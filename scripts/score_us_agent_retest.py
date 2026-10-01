"""Evaluator-only report checks against independent CSV references."""
import re
import json


def audit_query_actions(case, response_records, feedback_records):
    """Check explicit query attempts, including ones blocked by the program.

    Search detours are not errors. Unresolved candidates remain unknown rather
    than being scored correct from the eventual public report.
    """
    candidates = {}
    errors, unknown = [], []
    for record in feedback_records:
        for item in record.get("tools", []):
            if item.get("name") != "search_products":
                continue
            try:
                content = json.loads(item["content"])
            except (ValueError, TypeError, KeyError):
                unknown.append("search_feedback_unreadable")
                continue
            for candidate in content.get("candidates", []):
                if isinstance(candidate, dict) and isinstance(candidate.get("id"), str):
                    candidates[candidate["id"]] = candidate.get("code")
    attempted = 0
    for record in response_records:
        for call in record.get("tool_calls", []):
            if call.get("name") != "query_trade":
                continue
            attempted += 1
            args = call.get("arguments", {})
            if not isinstance(args, dict):
                errors.append("malformed_query")
                continue
            code = candidates.get(args.get("candidate_id"))
            if code is None:
                unknown.append("unresolved_candidate")
            elif code != case.get("expected_product"):
                errors.append("wrong_product_attempt")
            expected_flow = case.get("flow")
            if expected_flow and (args.get("flow") not in ("import", "export", "both") or
                                  expected_flow != "both" and args.get("flow") != expected_flow):
                errors.append("wrong_flow_attempt")
            if "partner" in case and args.get("partner") != case["partner"]:
                if case["partner"] == "all" and args.get("partner") == "china":
                    unknown.append("supplemental_china_requires_final_audit")
                else:
                    errors.append("wrong_partner_attempt")
            period = args.get("period", {})
            if not isinstance(period, dict):
                errors.append("malformed_period")
                continue
            if "start" in case:
                start, end = case["start"], case["end"]
                count = (int(end[:4]) - int(start[:4])) * 12 + int(end[5:]) - int(start[5:]) + 1
                if not (period.get("type") == "absolute" and period.get("start") == start and period.get("end") == end or
                        period.get("type") == "latest_contiguous" and type(period.get("count")) is int and period["count"] == count):
                    errors.append("wrong_fixed_period_attempt")
    return {"query_attempts": attempted, "errors": errors, "unknown": unknown,
            "query_actions_correct": not errors and not unknown if attempted else None,
            "full_model_decision_score": "not_evaluated_finish_and_boundary_review_required"}


def consecutive(months):
    numbers = [int(month[:4]) * 12 + int(month[5:]) for month in months]
    return bool(numbers) and all(right == left + 1 for left, right in zip(numbers, numbers[1:]))


def verification_result(errors, unverified=(), **extra):
    state = "failed" if errors else "unverified_reference" if unverified else "verified"
    return {"passed": state == "verified", "verification_status": state,
            "errors": errors, "unverified": list(unverified), **extra}


def check_report(case, report, reference, *, flow=None, require_latest=True):
    errors, unverified = [], []
    scope = report.get("scope", {})
    expected_flow = flow or case["flow"]
    expected_partner = "CHINA" if case["partner"] == "china" else (
        "ALL_DESTINATIONS" if expected_flow == "export" else "ALL_ORIGINS")
    for key, expected in (("reporter", "US"), ("product_code", case["expected_product"]),
                          ("flow", expected_flow), ("partner", expected_partner)):
        if scope.get(key) != expected:
            errors.append("scope:" + key)
    rows = report.get("series")
    if not isinstance(rows, list) or not rows:
        return verification_result(errors + ["missing_series"])
    months = [row.get("month") if isinstance(row, dict) else None for row in rows]
    if any(not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}", month) or
           not 1 <= int(month[5:]) <= 12 for month in months):
        return verification_result(errors + ["invalid_month"])
    if not consecutive(months):
        errors.append("non_contiguous_or_duplicate_months")
    if scope.get("start_month") != months[0] or scope.get("end_month") != months[-1]:
        errors.append("scope_series_window")
    if require_latest and months[-1] != "2026-07":
        errors.append("wrong_latest_month")
    if "start" in case and (months[0] != case["start"] or months[-1] != case["end"]):
        errors.append("wrong_fixed_window")
    if case.get("period_rule") == "recent_with_previous_month" and len(months) < 2:
        errors.append("missing_comparison_month")
    values, available = [], []
    for row, month in zip(rows, months):
        if row.get("value_usd") is not None and type(row.get("value_usd")) is not int:
            errors.append("monthly_value_type:" + month)
        if row.get("status") not in {"observed", "not_observed", "no_record", "not_processed"}:
            errors.append("invalid_observation_status:" + month)
        elif (row.get("status") == "observed") != (row.get("value_usd") is not None):
            errors.append("internal_observation_status:" + month)
        try:
            gold = reference["months"][month][expected_flow]["values"][case["expected_product"]][case["partner"]]
        except KeyError:
            registered = reference.get("registered_months", {}).get(expected_flow)
            if registered is not None and month not in registered:
                errors.append("unregistered_report_month:" + month)
            else:
                unverified.append("reference_unavailable:" + month)
            values.append(None)
            available.append(False)
            continue
        expected = gold["value_usd"]
        values.append(expected)
        available.append(True)
        actual = row.get("value_usd")
        if actual != expected or (actual is not None and type(actual) is not int):
            errors.append("monthly_value:" + month)
        if (row.get("status") == "observed") != (expected is not None):
            errors.append("observation_status:" + month)
    complete = all(value is not None for value in values)
    change = values[-1] - values[-2] if len(values) > 1 and values[-1] is not None and values[-2] is not None else None
    expected_summary = {"latest_month": months[-1],
        "previous_month": months[-2] if len(months) > 1 else None}
    if available[-1]:
        expected_summary["latest_value_usd"] = values[-1]
    if len(months) == 1 or all(available[-2:]):
        expected_summary["month_change_usd"] = change
    if all(available):
        expected_summary.update(period_total_usd=sum(values) if complete else None, complete_window=complete)
    summary = report.get("summary", {})
    displayed = [row.get("value_usd") for row in rows]
    if all(v is None or type(v) is int for v in displayed):
        observed = all(v is not None for v in displayed)
        internal = {"latest_value_usd": displayed[-1],
            "month_change_usd": displayed[-1] - displayed[-2] if len(displayed) > 1 and all(v is not None for v in displayed[-2:]) else None,
            "period_total_usd": sum(displayed) if observed else None, "complete_window": observed}
        for key, expected in internal.items():
            if key not in summary or summary[key] != expected or type(summary[key]) is not type(expected):
                errors.append("internal_summary:" + key)
    for key, expected in expected_summary.items():
        actual = summary.get(key)
        if key not in summary or actual != expected or (expected is not None and type(actual) is not type(expected)):
            errors.append("summary:" + key)
    return verification_result(errors, unverified,
        boundary="Numeric/scope check only; not full product, citation, policy or model decision score")


def count_results(results, planned=12):
    """Keep unrun/zero-response turns outside the model denominator."""
    if len({row["case_id"] for row in results}) != len(results):
        raise ValueError("Duplicate case result")
    executed = [row for row in results if row.get("executed") is True]
    responses = [row for row in executed if row.get("origin") == "api" and type(row.get("responses")) is int and row["responses"] > 0]
    scored = [row for row in responses if type(row.get("raw_decision_correct")) is bool]
    return {"planned": planned, "executed": len(executed),
        "batch_status": "complete" if len(executed) == planned else "partial",
        "model_denominator": len(responses),
        "model_scored": len(scored), "model_pending": len(responses) - len(scored),
        "model_correct_rate": (sum(row["raw_decision_correct"] for row in scored) / len(responses)
                               if responses and len(scored) == len(responses) else None),
        "model_raw_correct": sum(row.get("raw_decision_correct") is True for row in responses),
        "program_zero_response": sum(row.get("responses") == 0 and row.get("origin") == "program_precheck" for row in executed),
        "normal_complete": sum(row.get("kind") == "normal" and row.get("product_result") == "complete" for row in executed),
        "boundary_safe": sum(row.get("kind") == "boundary" and row.get("product_result") == "complete" for row in executed),
        "release_gate": "not_evaluated_requires_full_audit"}


def check_saved_report(root, report_id, case, reference):
    """Use the existing content-bound reader, not raw unverified JSON."""
    from tradeintel_ai.trade_report_store import load_record
    saved = load_record(root, report_id)
    report = saved["report"]
    if case["flow"] == "both":
        if report.get("kind") != "trade-query-both-v1":
            return {"passed": False, "errors": ["missing_both_direction_report"]}
        checks = {flow: check_report(case, report.get(flow + "_report", {}), reference, flow=flow)
                  for flow in ("import", "export")}
        return {"passed": all(check["passed"] for check in checks.values()), "checks": checks,
                "saved_readback": True, "full_product_score": "not_evaluated"}
    check = check_report(case, report, reference)
    return {**check, "saved_readback": True, "full_product_score": "not_evaluated"}


def check_public_turn(root, current, case, reference, tool_records):
    """Verify every displayed report against its own scope, then primary coverage.

    Checks are not final model scoring. Free user-facing model prose stays
    review_required; wrong public facts stop the batch rather than hiding them.
    """
    from tradeintel_ai.trade_report_store import load_record, get_state
    from tradeintel_ai.trade_agent_report_view import build_reader_view
    from tradeintel_ai.trade_agent import _program_summary
    errors, unverified, checks, main_flows = [], [], [], set()
    query_ids, finish = set(), []
    for item in tool_records:
        content = json.loads(item["content"])
        if item["name"] == "query_trade" and content.get("status") not in ("error", "unavailable", "limited"):
            if content.get("report_id"):
                query_ids.add(content["report_id"])
        if item["name"] == "finish" and content.get("status") == "completed":
            finish.append(item)
    ids = current.get("report_ids", [])
    if current.get("status") != "completed" or not ids:
        return {"passed": False, "errors": [], "checks": [], "public_safety": "review_required"}
    if len(finish) != 1 or any(report_id not in query_ids for report_id in ids):
        errors.append("report_not_from_current_turn")
    if finish and (set(finish[0]["arguments"].get("report_ids", [])) != set(ids) or
                   set(finish[0]["arguments"].get("source_ids", [])) != set(current.get("policy_source_ids", []))):
        errors.append("finish_readback_mismatch")
    primary = current.get("primary_report_id")
    public_reports = []
    unrelated = False
    for report_id in dict.fromkeys(ids):
        saved = load_record(root, report_id)["report"]
        public_reports.append(get_state(root, report_id))
        parts = [saved["import_report"], saved["export_report"]] if saved["scope"]["flow"] == "both" else [saved]
        for part in parts:
            scope = part["scope"]
            partner = "china" if scope.get("partner") == "CHINA" else "all"
            own = {"expected_product": scope["product_code"], "flow": scope["flow"], "partner": partner,
                   "start": scope["start_month"], "end": scope["end_month"]}
            check = check_report(own, part, reference, require_latest=False)
            checks.append({"report_id": report_id, **check})
            errors.extend(check["errors"])
            unverified.extend(check.get("unverified", []))
            expected_metric = "import_value_consumption_usd" if scope["flow"] == "import" else "total_export_fas_usd"
            versions = scope.get("dataset_versions", {})
            if (scope.get("metric") != expected_metric or versions.get(scope["flow"]) != reference["dataset_versions"].get(scope["flow"])
                    or any(reference["dataset_versions"].get(key) != value for key, value in versions.items())
                    or scope.get("catalog_version") != reference["dataset_versions"].get("classification")):
                errors.append("metric_or_dataset_version")
            for row in part["series"]:
                try:
                    gold = reference["months"][row["month"]][scope["flow"]]
                    value = gold["values"][scope["product_code"]][partner]
                    if row.get("source_sha256") != gold["source_sha256"] or row.get("source_url") != gold["source_url"]:
                        errors.append("source_identity")
                    matched_key = "matched_hts10" if scope["flow"] == "import" else "matched_country_rows"
                    if row.get(matched_key) != value["matched_rows"] or scope["flow"] == "import" and row.get("observed_hts10") != value["observed_rows"]:
                        errors.append("row_coverage")
                    if row.get("classification_year") != int(row["month"][:4]):
                        errors.append("classification_year")
                except KeyError:
                    registered = reference.get("registered_months", {}).get(scope["flow"])
                    if registered is not None and row["month"] not in registered:
                        errors.append("unregistered_source_month")
                    else:
                        unverified.append("source_reference_missing:" + row["month"])
            expected_part = {**case, "flow": scope["flow"]}
            main_check = check_report(expected_part, part, reference)
            main = (scope["product_code"] == case["expected_product"] and partner == case["partner"] and
                    (case["flow"] == "both" or scope["flow"] == case["flow"]) and
                    not main_check["errors"])
            if main:
                main_flows.add(scope["flow"])
            if report_id == primary and not main:
                errors.append("wrong_primary_scope")
            if scope["product_code"] != case["expected_product"] or case["flow"] != "both" and scope["flow"] != case["flow"]:
                unrelated = True
    needed = {"import", "export"} if case["flow"] == "both" else {case["flow"]}
    if primary not in ids or not needed <= main_flows:
        errors.append("missing_primary_coverage")
    if current.get("message_kind") == "program_summary_v1":
        if current.get("reader_view") != build_reader_view(current["question"], public_reports, current.get("policy_evidence")) or current.get("message") != _program_summary(public_reports, len(set(current.get("policy_source_ids", [])))):
            errors.append("public_projection_mismatch")
    else:
        unrelated = True
    return verification_result(errors, unverified, checks=checks,
        public_safety="unsafe" if errors else "review_required" if unverified or unrelated else "verified_program_output")


def check_policy_bundles(bundles, store):
    """Check saved quotations against registered versioned text and dependencies.

    This verifies citation integrity, not free-form model policy semantics.
    """
    from tradeintel_ai.policy_documents import validate_document_store
    from tradeintel_ai.policy_search import PolicySearch
    validate_document_store(store)
    errors = []
    seen = set()
    searcher = PolicySearch(store)
    for bundle in bundles:
        document = next((doc for doc in store["documents"] if doc["doc_version"] == bundle.get("doc_version")
                         and doc["doc_id"] == bundle.get("doc_id")), None)
        if document is None or document.get("status") != "enabled":
            errors.append("unregistered_or_disabled_version")
            continue
        hit = bundle.get("hit", {})
        section = next((part for part in document["sections"] if part["id"] == hit.get("section_id")), None)
        if section is None or hit.get("text") != section["text"] or hit.get("source_id") != section.get("source_id"):
            errors.append("hit_text_or_source_mismatch")
        else:
            seen.add(section["source_id"])
        required, missing = searcher._required_context(document)
        if missing:
            errors.append("unregistered_dependencies")
        actual = bundle.get("required_context", [])
        for clause in required:
            matching = [item for item in actual if item.get("dependency") == clause["dependency"]
                        and item.get("section_id") == clause["section_id"]]
            if len(matching) != 1 or any(matching[0].get(key) != clause.get(key)
                                         for key in ("text", "status", "citation_id", "note")):
                errors.append("dependency_missing_or_changed:" + clause["dependency"])
    if not bundles:
        errors.append("no_policy_bundles")
    if "cbp63577329:p12" not in seen:
        errors.append("missing_tungsten_hit")
    return {"passed": not errors, "errors": errors, "semantic_score": "not_evaluated"}
