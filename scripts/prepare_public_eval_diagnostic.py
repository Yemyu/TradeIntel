"""Build production inputs for the four scenarios; never call a provider.

These are diagnostic artifacts, not a frozen test or an end-to-end success.
The ranges are built explicitly until the natural-language proposal route is
verified. Missing policy context and oversized requests block formal testing.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from tradeintel_ai.analysis_request import default_window
from tradeintel_ai.exposure_version_store import ExposureVersionStore
from tradeintel_ai.policy_cases import CASES
from tradeintel_ai.session_brief import build_temporal_session_brief
from tradeintel_ai.session_explanation import build_public_snapshot

VERSION = "91c2ed45f937392ea4473cd156ca05d3c7566e333ff9d50be90f5cbeccba4e1b"
POLICY = "us_301_review2025_tungsten_solar"
PRODUCTS = ["28046100", "38180000", "81019400", "81019910", "81019980"]
INPUT_HARD_TOKENS = 16000
INPUT_TARGET_TOKENS = 8000
QUESTIONS = [
    "最近这几类商品的贸易有什么值得关注的？我不懂这些，帮我讲明白。",
    "那这类商品呢？跟之前比变化明显吗？比去年怎么样？",
    "这项关税调整到底改了什么？结合现在能看到的数据，哪些变化值得继续关注？",
    "照这个情况，接下来相关产品是不是会涨价？我还应该关注什么消息？",
]


def estimate_input_tokens(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Use the repository's deliberately conservative planning heuristic."""
    text = "\n".join(str(item.get("content", "")) for item in messages)
    ascii_chars = sum(ord(char) < 128 for char in text)
    estimate = math.ceil(1.25 * (ascii_chars / 3 + (len(text) - ascii_chars) * 2 + 128))
    return {"tokens": estimate,
            "method": "ceil(1.25*(ASCII/3 + nonASCII*2 + 128))",
            "target": INPUT_TARGET_TOKENS, "hard": INPUT_HARD_TOKENS,
            "characters": len(text), "utf8_bytes": len(text.encode("utf-8"))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    # Never overwrite an earlier diagnostic or frozen request package.
    args.output.mkdir(parents=True, exist_ok=False)
    release = ExposureVersionStore(root, root / CASES[POLICY].versions).load_snapshot(VERSION)
    rows = []
    for index, question in enumerate(QUESTIONS, 1):
        products = ["38180000"] if index == 2 else PRODUCTS
        request = {
            "schema_version": "analysis-request-v1", "original_question": question,
            "policy_id": POLICY, "policy_binding": None, "products": products,
            "window": default_window(release, products=products),
            "comparisons": ["series", "mom", "yoy", "origins"],
            "data_version": VERSION, "policy_view": "archived_event",
            "policy_verified_at": None, "requested_as_of": None,
        }
        response = build_temporal_session_brief(root, request, data_version=VERSION)
        snapshot = build_public_snapshot(response, question=question)
        folder = args.output / f"q{index}"
        folder.mkdir()
        artifacts = {"request.json": request, "snapshot.json": snapshot,
                     "response.json": response, "messages.json": snapshot["messages"]}
        hashes = {}
        for name, value in artifacts.items():
            raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
            (folder / name).write_bytes(raw)
            hashes[name] = hashlib.sha256(raw).hexdigest()
        wire = json.dumps(snapshot["messages"], ensure_ascii=False, separators=(",", ":"))
        input_estimate = estimate_input_tokens(snapshot["messages"])
        rows.append({"question_id": f"q{index}", "window": request["window"],
                     "message_characters": len(wire), "message_utf8_bytes": len(wire.encode()),
                     "input_estimate": input_estimate,
                     "within_hard_gate": input_estimate["tokens"] <= INPUT_HARD_TOKENS,
                     "policy_sources": len(snapshot["policy_context"].get("sources", [])),
                     "hashes": hashes})
    result = {"status": "diagnostic_only_not_frozen", "api_calls": 0,
              "blockers": ["natural_language_proposal_not_verified",
                           "fixed_followup_summary_not_connected",
                           "independent_references_not_frozen",
                           "provider_token_budget_not_verified"], "questions": rows}
    (args.output / "diagnostic.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
