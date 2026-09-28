"""One explicitly authorized retry; preserve the original freeze and attempt."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_public_brief_eval as runner
from src.tradeintel_ai.public_eval_ledger import latest_for_run, resolve_unknown


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-run", required=True)
    parser.add_argument("--provider-id", required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authorize-retry", action="store_true")
    args = parser.parse_args()
    if not args.authorize_retry:
        raise ValueError("需要本次明确授权")
    previous = latest_for_run(ROOT, args.previous_run)
    if not previous or previous["event"] != "unknown_outcome":
        raise ValueError("原运行不是可人工处理的unknown_outcome")
    provider = runner.preflight(provider_id=args.provider_id)["provider"]
    freeze = json.loads(args.freeze.read_text())
    runner.verify_freeze(freeze=freeze, provider=provider, package_path=runner.DEFAULT_PACKAGE)
    expected = runner.make_base_key(freeze["package_manifest_sha256"],
        runner.canonical_sha({"provider_id": provider["id"], "execution_channel": "real_api"}),
        previous["question_id"])
    if previous["base_key"] != expected or args.output.exists():
        raise ValueError("原运行身份不符或输出目录已存在")
    key = getpass.getpass("API key (hidden): ").strip()
    if not key:
        raise ValueError("密钥为空")
    os.environ[provider["secret_env"]] = key
    nonce = uuid.uuid4().hex
    resolve_unknown(ROOT, run_id=args.previous_run, resolution="resolved_retry_authorized",
                    decided_by="user", note="用户提供新凭据并明确要求重试；保留旧失败记录。")
    original_claim = runner.claim_ledger
    def authorized_claim(root, *, base_key, metadata):
        if base_key != expected:
            raise ValueError("授权仅适用于原题原配置")
        return original_claim(root, base_key=base_key, metadata=metadata, retry_nonce=nonce)
    # Supply the ledger's existing nonce parameter without changing frozen code.
    runner.claim_ledger = authorized_claim
    try:
        result = runner.run(provider=provider, package_path=runner.DEFAULT_PACKAGE,
            output=args.output, execute=True, authorize_real_call=True,
            question_ids=(previous["question_id"],), freeze_path=args.freeze)
        print(json.dumps({"status": result["status"], "api_calls": result["api_calls"]}))
    finally:
        runner.claim_ledger = original_claim
        os.environ.pop(provider["secret_env"], None)


if __name__ == "__main__":
    main()
