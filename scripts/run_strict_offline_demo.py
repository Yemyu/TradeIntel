#!/usr/bin/env python3
"""Run the registered TradeIntel workflow with a deterministic local model.

This is a zero-network demonstration of the strict acceptance wiring.  It is
not a model benchmark and must never be used as a substitute for a real
provider run.  Use a fresh output directory for every invocation.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.prospective_acceptance import digest
from tradeintel_ai.prospective_runner import default_cases, fixture_review, run_synthetic_batch


def _trade_plan() -> dict:
    return {
        "status": "plan", "policy_question": None, "policy_as_of": None,
        "trade": {
            "policy_id": "us_301_list1_2018", "operation": "read",
            "metric": "import_value_consumption_usd", "origin": "other_origins",
            "granularity": "policy_aggregate", "months": ["2018-09", "2018-10"],
            "hs6": None, "causal_effect": False,
        },
        "tasks": ["trade"],
        "evidence": {
            "trade.policy_id": "第一批关税", "trade.operation": "查询",
            "trade.metric": "美元消费进口额", "trade.origin": "其他原产地整体",
            "trade.granularity": "政策整体范围", "trade.months": "2018-09和2018-10",
            "trade.hs6": "政策整体范围", "trade.causal_effect": "只做描述性比较，不做因果分析",
            "trade.comparison": "2018-10相对于2018-09",
        },
        "missing": [], "comparison": {
            "kind": "endpoint", "reference_month": "2018-09", "current_month": "2018-10",
        },
        "policy_search_query": None,
        "request_units": [{
            "quote": "查询其他原产地整体2018-09和2018-10的美元消费进口额；比较2018-10相对于2018-09；只做描述性比较，不做因果分析；第一批关税，政策整体范围。",
            "kind": "request", "target": "trade",
        }],
    }


def _policy_plan() -> dict:
    return {
        "status": "plan",
        "policy_question": "第一批关税何时生效，额外税率是多少？",
        "policy_as_of": "2018-07-06",
        "trade": None,
        "tasks": ["policy"],
        "evidence": {
            "policy_question_quote": "第一批关税何时生效，额外税率是多少？",
            "policy_as_of_quote": "2018-07-06",
        },
        "missing": [],
        "comparison": None,
        "policy_search_query": "initial Section 301 List 1 effective date additional duty rate",
        "request_units": [
            {"quote": "第一批关税何时生效，额外税率是多少？", "kind": "request", "target": "policy"},
            {"quote": "政策资料截止日是2018-07-06。", "kind": "constraint", "target": "none"},
        ],
    }


def _clarification_plan() -> dict:
    return {
        "status": "clarify", "policy_question": None, "policy_as_of": None,
        "trade": None, "tasks": [], "evidence": {}, "missing": ["商品、月份和金额口径"],
        "comparison": None, "policy_search_query": None,
        "request_units": [{
            "quote": "我想分析关税影响，但没有说明商品、月份和金额口径。",
            "kind": "request", "target": "trade",
        }],
    }


class OfflineModel:
    """Deterministic model-shaped object; never opens a socket."""

    def __init__(self, stage: str, plan: dict | None = None) -> None:
        self.stage = stage
        self.plan = deepcopy(plan)
        self.config = SimpleNamespace(
            model="tradeintel-offline-fixture", base_url="fixture://offline",
            temperature=0.0, timeout_seconds=60.0, api_key="",
        )

    def effective_request_settings(self) -> dict:
        return {
            "model": self.config.model, "temperature": 0.0, "max_tokens": 768,
            "thinking": {"type": "disabled"}, "stream": False,
        }

    def complete(self, *, messages, tools):
        if self.stage == "planning":
            payload = self.plan
        elif self.stage == "policy_with_evidence":
            request = json.loads(messages[-1]["content"])
            evidence = request.get("evidence", [])
            citation = evidence[0]["id"] if evidence else ""
            payload = {"claims": [{
                "text": "第一批额外关税适用于2018年7月6日及之后进入消费的相关商品，额外税率为25%。",
                "citations": [citation],
            }]}
        else:
            payload = {"claims": []}
        return ModelResponse(
            text=json.dumps(payload, ensure_ascii=False),
            metadata={"finish_reason": "stop", "usage": {"total_tokens": 5}},
        )


def _fact_review(packet: dict) -> dict:
    """A deterministic wiring label, explicitly not a human semantic review."""

    main = packet["arm"] == "with_evidence"
    claims = packet["answer"]["claims"]
    facts = []
    for fact in packet["facts"]:
        row = {
            "id": fact["id"],
            "status": "supported" if main and claims else "missing",
            "reason": "offline fixture wiring label",
            "claim_indices": [0] if main and claims else [],
        }
        if main and claims:
            source_id = fact["evidence_ids"][0]
            row["source_id"] = source_id
            row["evidence_excerpt"] = packet["evidence"][source_id]["text"]
        facts.append(row)
    reviewed_claims = [
        {"index": index, "status": "supported", "reason": "offline fixture wiring label",
         "fact_ids": [fact["id"] for fact in packet["facts"]] if main else []}
        for index in range(len(claims))
    ]
    return {
        "case_id": packet["case_id"], "arm": packet["arm"],
        "packet_sha256": digest(packet), "reviewer": "offline-fixture-reviewer",
        "reviewed_at": "2026-09-13", "facts": facts, "claims": reviewed_claims,
        "citation_review": {"status": "pass" if main else "not_applicable",
                            "reason": "offline fixture wiring label"},
    }


def model_factory(stage: str, model_input) -> OfflineModel:
    plans = {
        "SYN-TRADE-01": _trade_plan(),
        "SYN-POLICY-01": _policy_plan(),
        "SYN-CLARIFY-01": _clarification_plan(),
    }
    return OfflineModel(stage, plans.get(model_input.id))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a zero-network strict TradeIntel demo.")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "docs/experiments/phase-0126-offline-demo/run",
                        help="fresh output directory")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.exists():
        parser.error(f"output already exists; choose a fresh directory: {output}")
    summary = run_synthetic_batch(
        output, cases=default_cases(), model_factory=model_factory,
        reviewer=fixture_review, fact_reviewer=_fact_review,
        strict_protocol=True, reviewer_id="offline-fixture-reviewer",
    )
    print(json.dumps({
        "status": summary["status"],
        "question_status_counts": summary["question_status_counts"],
        "call_count": summary["call_count"],
        "acceptance_ready": summary["acceptance_ready"],
        "semantic_accuracy_measured": summary["semantic_accuracy_measured"],
        "network_calls": 0,
        "warning": "synthetic fixture only; not model accuracy or human semantic review",
        "output": str(output),
    }, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
