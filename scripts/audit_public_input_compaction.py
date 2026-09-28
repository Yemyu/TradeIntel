"""Inspect saved diagnostic inputs offline; never call a model or alter a package."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from tradeintel_ai.evidence_transport import pack, unpack
from tradeintel_ai.public_input_view import build_view, decode_view, restore_view, _project_original
from scripts.prepare_public_eval_diagnostic import estimate_input_tokens


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def audit(folder):
    response = json.loads((folder / "response.json").read_text())
    messages = json.loads((folder / "messages.json").read_text())
    payload = json.loads(messages[1]["content"])
    view = payload["view"]
    evidence = response["evidence"]
    original_ids = {item["id"] for item in evidence["observations"]}
    decoded = decode_view(view)
    wire_rows = view["evidence"]["observations"]["rows"]
    wire_ids = {item["id"] for item in decoded["evidence"]["observations"]}
    packet = build_view(response["report"], response["policy_context"])
    # A private backup roundtrip is not proof that the wire retained meaning.
    altered = deepcopy(packet)
    altered["view"]["evidence"]["metrics"]["levels"]["rows"][0][4][0] = -999
    altered["sidecar"]["view_sha256"] = digest(altered["view"])
    try:
        detached_view_accepted = restore_view(altered) == {
            "report": response["report"], "policy_context": response["policy_context"]}
    except ValueError:
        detached_view_accepted = False
    complete = {"request": response["request"], "evidence": evidence,
                "policy_context": response["policy_context"],
                "watchlist": response["report"]["watchlist"]}
    packed = pack(complete)
    assert unpack(packed) == complete
    return {
        "question": folder.name,
        "messages_file_sha256": hashlib.sha256((folder / "messages.json").read_bytes()).hexdigest(),
        "original_observations": len(original_ids),
        "wire_citable_observations": len(wire_ids),
        "unavailable_observations": sorted(original_ids - wire_ids),
        "original_metrics": len(evidence["metrics"]),
        "wire_metrics": len(decoded["evidence"]["metrics"]),
        "metric_tables": {key: len(value.get("rows") or [])
                          for key, value in view["evidence"]["metrics"].items()
                          if isinstance(value, dict) and "rows" in value},
        "wire_observations_have_metric_links": all(len(item[4]) > 0 for item in wire_rows),
        "wire_decode_matches_business_projection": decoded == _project_original(
            response["report"], response["policy_context"]),
        "private_backup_accepts_rehashed_different_view": detached_view_accepted,
        "watchlist_ids": [item["watch_id"] for item in view["watchlist"]],
        "current_input_estimate": estimate_input_tokens(messages)["tokens"],
        "complete_exact_pack_estimate_excluding_system": estimate_input_tokens([
            {"content": json.dumps(packed, ensure_ascii=False, separators=(",", ":"))}])["tokens"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {"status": "review_findings_not_model_scores", "api_calls": 0,
              "questions": [audit(args.package / f"q{i}") for i in range(1, 5)]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    for item in result["questions"]:
        print(item["question"], "observations", item["wire_citable_observations"], "/",
              item["original_observations"], "metrics", item["wire_metrics"], "/",
              item["original_metrics"], "links", item["wire_observations_have_metric_links"],
              "backup_not_wire_proof", item["private_backup_accepts_rehashed_different_view"],
              "full_pack_estimate", item["complete_exact_pack_estimate_excluding_system"])


if __name__ == "__main__":
    main()
