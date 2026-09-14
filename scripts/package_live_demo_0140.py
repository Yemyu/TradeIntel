#!/usr/bin/env python3
"""Package the completed 0140 live-development result for local review.

The package is deliberately a small, read-only presentation bundle. It
copies reports and audit summaries, not API configuration or the full frozen
runtime directory. The source run must already be completed and accepted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys


DEFAULT_RUN = Path("tmp/live-development-0140-policy")
DEFAULT_OUTPUT = Path("docs/experiments/phase-0140-live/reproducible-package")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _summary(ledger: dict) -> dict:
    questions = ledger.get("questions")
    if not isinstance(questions, list):
        raise ValueError("ledger questions are missing")
    statuses = {row.get("status") for row in questions if isinstance(row, dict)}
    if ledger.get("status") != "completed" or statuses != {"accepted"}:
        raise ValueError("source run is not completed with all questions accepted")
    return {
        "version": "live-demo-package-0141",
        "source_run_status": ledger.get("status"),
        "question_ids": ledger.get("question_ids"),
        "question_statuses": [{"id": row.get("id"), "status": row.get("status"),
                               "stages": row.get("stages")} for row in questions],
        "reported_tokens": ledger.get("reported_tokens"),
        "token_budget": ledger.get("token_budget"),
        "external_calls": ledger.get("external_calls"),
        "automatic_retry": ledger.get("automatic_retry"),
        "run_mode": ledger.get("run_mode"),
        "reviewer_type": ledger.get("reviewer_type"),
        "frozen_snapshot_sha256": ledger.get("frozen_snapshot_sha256"),
        "terminal_reason": ledger.get("terminal_reason"),
        "terminal_at_utc": ledger.get("terminal_at_utc"),
        "semantic_accuracy_measured": False,
        "causal_effect_estimated": False,
        "training_or_fine_tuning": False,
    }


def package(run_dir: Path, output: Path) -> dict:
    run_dir = run_dir.resolve()
    output = output.resolve()
    if output.exists():
        raise ValueError(f"output already exists: {output}")
    ledger_path = run_dir / "ledger.json"
    if not ledger_path.is_file():
        raise ValueError("completed run ledger is missing")
    ledger = _read_json(ledger_path)
    summary = _summary(ledger)

    # Files selected for review are generated artifacts with no provider key.
    # Full tmp runs and standalone captures stay outside. Selected control-B
    # JSON summaries may themselves contain nested request_capture records.
    # This is not a complete runtime or a blanket privacy certification.
    selected = [
        (run_dir / "SYN-POLICY-01/delivery/report.zh-CN.md", Path("policy-report.zh-CN.md")),
        (run_dir / "SYN-COMBINED-01/delivery/report.zh-CN.md", Path("combined-report.zh-CN.md")),
        (run_dir / "SYN-POLICY-01/fact-review-summary.json", Path("policy-fact-review-summary.json")),
        (run_dir / "SYN-COMBINED-01/fact-review-summary.json", Path("combined-fact-review-summary.json")),
        (run_dir / "SYN-COMBINED-01/baseline.json", Path("combined-trade-baseline.json")),
        (run_dir / "SYN-COMBINED-01/scope-comparison.json", Path("combined-scope-comparison.json")),
        (run_dir / "SYN-COMBINED-01/delivery-inspection.json", Path("combined-delivery-inspection.json")),
        (run_dir / "SYN-POLICY-01/delivery-inspection.json", Path("policy-delivery-inspection.json")),
        (run_dir / "SYN-COMBINED-01/policy-pair-contract.json", Path("combined-policy-pair-contract.json")),
        (run_dir / "SYN-POLICY-01/policy-pair-contract.json", Path("policy-pair-contract.json")),
        (run_dir / "controls/SYN-COMBINED-01-control-a.json", Path("combined-control-a.json")),
        (run_dir / "controls/SYN-COMBINED-01-control-b.json", Path("combined-control-b.json")),
        (run_dir / "controls/SYN-POLICY-01-control-b.json", Path("policy-control-b.json")),
    ]
    missing = [src for src, _ in selected if not src.is_file()]
    if missing:
        raise ValueError("selected audit artifacts are missing: " + ", ".join(map(str, missing)))

    output.mkdir(parents=True)
    copied = []
    for source, relative in selected:
        destination = output / relative
        shutil.copyfile(source, destination)
        copied.append({"path": relative.as_posix(), "sha256": _sha256(destination),
                       "size": destination.stat().st_size})
    (output / "run-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    copied.append({"path": "run-summary.json", "sha256": _sha256(output / "run-summary.json"),
                   "size": (output / "run-summary.json").stat().st_size})
    manifest = {
        "version": "live-demo-package-0141",
        "source_run": (run_dir.relative_to(Path(__file__).resolve().parents[1]).as_posix()
                       if run_dir.is_relative_to(Path(__file__).resolve().parents[1])
                       else "[external local run]"),
        "files": copied,
        "excluded": ["api keys", "provider configuration", "full frozen snapshot",
                     "standalone raw HTTP capture files", "host review packets"],
        "audit_note": "仅展示和只读复核，非完整复现环境。control-b摘要仍可能嵌套request_capture；不保证排除所有HTTP记录，外发前需单独审查。完整审计仍在source_run。",
    }
    (output / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "packaged", "output": str(output), "file_count": len(copied),
            "manifest_sha256": _sha256(output / "MANIFEST.json")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(package(args.run_dir, args.output), ensure_ascii=False, indent=2))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "package_failed", "error_type": type(exc).__name__},
                         ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
