"""Reproduce E2 contract findings offline; does not modify product state."""
from copy import deepcopy
import json

from tradeintel_ai.announcement_extraction_pilot import (
    adapt_suggestion, make_disabled_store, prepare_request,
)
from tradeintel_ai.policy_candidates import REQUIRED_FIELDS


def probe(name, text, field_name, value, quotes):
    store = make_disabled_store("audit", "audit", text,
                                url="https://example.invalid/fixture", source_sha256="fixture")
    version = store["documents"][0]["doc_version"]
    fields = [{"field": key, "status": "unknown", "value": None,
               "reason": "合成诊断材料未提供", "evidence": []} for key in REQUIRED_FIELDS]
    field = next(item for item in fields if item["field"] == field_name)
    field.update(status="known", value=value, reason=None,
                 evidence=[{"quote": quote} for quote in quotes])
    try:
        adapt_suggestion({"doc_version": version, "fields": fields}, store, version)
        return {"probe": name, "result": "accepted"}
    except (ValueError, TypeError) as exc:
        return {"probe": name, "result": "rejected", "error": str(exc)}


def main():
    rate_quote = "Heading 9903.78.01: 50 percent additional duty on copper content."
    rule = {"kind": "conditional_rates_v1", "rules": [
        {"reporting_heading": "99037801", "rate_percent": 0, "basis": "copper content"}]}
    cases = [
        probe("zero_rate_matches_fifty", rate_quote, "rates", rule, [rate_quote]),
        probe("dictionary_in_effective_date", "Effective August 1, 2025.",
              "effective_date", {"not": "a date"}, ["Effective August 1, 2025."]),
        probe("hts10_prefix_claimed_as_whole_hts8", "Only HTS 2804.61.00.10 applies.",
              "hts_codes", [{"code": "28046100", "precision": "whole_hts8"}],
              ["Only HTS 2804.61.00.10 applies."]),
        probe("unrelated_digits_joined_into_code", "parts 28 batch 04 size 61 revision 00",
              "hts_codes", [{"code": "28046100", "precision": "whole_hts8"}],
              ["parts 28 batch 04 size 61 revision 00"]),
        probe("valid_wrapped_quote_rejected", "The rate is based on\ncopper content value.",
              "rate_meaning", "copper content value",
              ["The rate is based on\ncopper content value."]),
    ]
    decimal_rule = deepcopy(rule)
    decimal_rule["rules"][0]["rate_percent"] = 50.0
    cases.append(probe("equivalent_50_decimal_rejected", rate_quote, "rates",
                       decimal_rule, [rate_quote]))
    store = make_disabled_store("audit", "audit", "Original saved source.",
                                url="https://example.invalid/fixture", source_sha256="fixture")
    version = store["documents"][0]["doc_version"]
    store["documents"][0]["sections"][0]["text"] = "Changed without a new version."
    try:
        prepare_request(store, version)
        cases.append({"probe": "changed_source_with_old_digest", "result": "accepted"})
    except ValueError as exc:
        cases.append({"probe": "changed_source_with_old_digest", "result": "rejected", "error": str(exc)})
    print(json.dumps({"schema": "policy-extraction-e2-diagnostic-v1",
                      "model_calls": 0, "probes": cases}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
