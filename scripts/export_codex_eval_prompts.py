"""Export fixed prompts for an independent, manual Codex evaluation session.

This only copies hash-verified candidate messages into a user-facing packet.
It never contacts a model, reads credentials, or records scores.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_public_brief_eval import (  # noqa: E402
    DEFAULT_MATRIX,
    DEFAULT_PACKAGE,
    MANUAL_SESSION_CHANNEL,
    QUESTION_IDS,
    preflight,
)
from src.tradeintel_ai.public_eval_protocols import QUESTION_PROTOCOLS  # noqa: E402


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def export_prompt_pack(*, provider_id: str, output: Path,
                       package_path: Path = DEFAULT_PACKAGE,
                       matrix_path: Path = DEFAULT_MATRIX) -> dict[str, object]:
    plan = preflight(matrix_path=matrix_path, package_path=package_path,
                     provider_id=provider_id)
    provider = plan["provider"]
    if provider["channel"] != MANUAL_SESSION_CHANNEL:
        raise ValueError("该导出包仅供 Codex 手动会话；API配置请走正式API流程")
    output = Path(output)
    if output.exists():
        raise ValueError("导出目录已存在；不覆盖已有测试材料")

    package = Path(package_path).resolve()
    manifest_bytes = (package / "MANIFEST.json").read_bytes()
    source_manifest = json.loads(manifest_bytes)
    prompt_dir = output / "questions"
    prompt_dir.mkdir(parents=True)
    rows: list[dict[str, object]] = []

    for question_id in QUESTION_IDS:
        relative = f"requests/{question_id}/messages.json"
        request_bytes = (package / relative).read_bytes()
        request_sha = _sha_bytes(request_bytes)
        if source_manifest.get("files_sha256", {}).get(relative) != request_sha:
            raise ValueError(f"题目输入摘要不一致：{question_id}")
        messages = json.loads(request_bytes)
        if (not isinstance(messages, list) or len(messages) != 2
                or messages[0].get("role") != "system"
                or messages[1].get("role") != "user"
                or not isinstance(messages[0].get("content"), str)
                or not isinstance(messages[1].get("content"), str)):
            raise ValueError(f"题目消息格式不符：{question_id}")

        snapshot_path = package / "host_artifacts" / question_id / "snapshot.json"
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        expected = QUESTION_PROTOCOLS[question_id]
        if (snapshot.get("mode") != expected["mode"]
                or snapshot.get("protocol") != expected["protocol"]
                or snapshot.get("messages") != messages):
            raise ValueError(f"题目协议或快照绑定不符：{question_id}")

        # A chat UI cannot set a true system role. Keep the instructions and
        # user payload verbatim, clearly separated, and mark this as a
        # Codex-session channel rather than API-equivalent transport.
        prompt = (
            "【系统要求】\n" + messages[0]["content"].rstrip()
            + "\n\n【本题问题与材料】\n" + messages[1]["content"].rstrip() + "\n"
        )
        filename = f"{question_id}.txt"
        prompt_path = prompt_dir / filename
        prompt_path.write_text(prompt, encoding="utf-8")
        prompt_sha = _sha_bytes(prompt.encode("utf-8"))
        rows.append({"question_id": question_id,
                     "mode": expected["mode"],
                     "protocol": expected["protocol"],
                     "source_request_sha256": request_sha,
                     "prompt_sha256": prompt_sha,
                     "prompt_file": f"questions/{filename}"})

    instructions = (
        "# 独立 Codex 四题测试包\n\n"
        f"测试配置：{provider['label']}（`{provider['model_id']}`，"
        f"reasoning effort `{provider['reasoning_effort']}`）。\n\n"
        "## 使用方法\n\n"
        "1. 先核对模型菜单显示的完整版本与本包一致；如果显示为其他版本（例如GPT-6），"
        "先暂停并更新登记，不要把不同版本的结果混记。\n"
        "2. 对每道题都新开一个空白会话，并在会话设置里选上面的准确模型与推理档位。"
        "四题不能放在同一会话里，避免前题答案影响后题。\n"
        "3. 打开 `questions/q1.txt` 到 `q4.txt`，每次只复制一份文件的全部内容，"
        "粘贴后直接发送。不要添加提示、评分标准或项目背景。\n"
        "4. 保存模型完整原答、对应的题号、模型菜单显示名称与推理档位；不要让模型自评。"
        "将四份原答交回项目审阅后再计算通过率。\n"
        "5. 这是手动 Codex 会话，不等同 API 请求；不要把会话消耗估成 API token 或费用。\n\n"
        "本包没有答案、评分参考或其他模型的回答。预检调用数为0；导出不调用模型。\n"
    )
    (output / "README.zh-CN.md").write_text(instructions, encoding="utf-8")
    export_manifest = {
        "schema_version": "codex-manual-eval-prompts-v1",
        "provider": {key: provider.get(key) for key in
                     ("id", "label", "channel", "model_id", "reasoning_effort")},
        "experiment_id": plan["experiment_id"],
        "candidate_schema": plan["candidate_schema"],
        "scoring_version": plan["scoring_version"],
        "package_manifest_sha256": _sha_bytes(manifest_bytes),
        "api_calls": 0,
        "questions": rows,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (output / "manifest.json").write_text(
        json.dumps(export_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return {"status": "exported", "output": str(output.resolve()),
            "provider": export_manifest["provider"],
            "question_count": len(rows), "api_calls": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-id", required=True)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        output = args.output or ROOT / "tmp/public-brief-eval-v2/manual-codex-packets" / args.provider_id
        result = export_prompt_pack(provider_id=args.provider_id, output=output,
                                    package_path=args.package, matrix_path=args.matrix)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
