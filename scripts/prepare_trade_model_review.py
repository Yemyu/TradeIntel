"""Create a one-time anonymous content-review packet from frozen v3 API answers.

The public packet has no model or provider names. Its mapping is kept in
.local; do not give that file to a reviewer before scores are locked.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import secrets

from scripts.freeze_trade_model_eval import verify_frozen
from scripts.run_trade_model_eval import CASE_IDS, CANDIDATE, FROZEN, ROOT, _read
from scripts.run_trade_v3_canary import _atomic


ANSWERED_MODELS = ("deepseek-flash-high", "deepseek-v4-pro-high")
PACKET_DIR = ROOT / "tmp/trade-model-eval-v3/review-packet-20260924"
MAPPING = ROOT / ".local/trade-model-eval-v3/review-packet-map.json"


def build(*, root: Path = ROOT, candidate: Path = CANDIDATE,
          frozen: Path = FROZEN, packet_dir: Path = PACKET_DIR,
          mapping_path: Path = MAPPING) -> dict:
    verify_frozen(root, candidate, frozen)
    if packet_dir.exists() or mapping_path.exists():
        raise ValueError("匿名审阅包或映射已存在；不得覆盖")
    reviews = []
    mapping = {}
    randomizer = secrets.SystemRandom()
    for case_id in CASE_IDS:
        options = []
        for model_id in ANSWERED_MODELS:
            folder = root / ".local/trade-model-eval-v3" / model_id
            record = _read(folder / f"{case_id}.json")
            if record is None:
                continue
            if record.get("status") != "needs_review" or record.get("contract_pass") is not True:
                raise ValueError(f"{case_id} 的原答状态不适合匿名审阅")
            raw_path = folder / f"{case_id}.raw.txt"
            if raw_path.is_symlink() or not raw_path.is_file():
                raise ValueError("原答文件缺失或不安全")
            raw = raw_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != record.get("raw_sha256"):
                raise ValueError("原答与持久账本摘要不符")
            answer = json.loads(raw)
            options.append((model_id, answer, record["raw_sha256"]))
        randomizer.shuffle(options)
        labelled = []
        for index, (model_id, answer, digest) in enumerate(options):
            label = f"{case_id.upper()}-{chr(65 + index)}"
            labelled.append({"label": label, "answer": answer})
            mapping[label] = {"model_id": model_id, "raw_sha256": digest}
        reviews.append({
            "case_id": case_id.upper(),
            "question": json.loads((frozen / f"host_artifacts/{case_id}/report.json").read_text(encoding="utf-8"))["question"],
            "program_report": json.loads((frozen / f"host_artifacts/{case_id}/report.json").read_text(encoding="utf-8")),
            "recomputed_reference": json.loads((frozen / f"references/{case_id}.json").read_text(encoding="utf-8")),
            "anonymous_answers": labelled,
        })
    packet = {
        "schema_version": "trade-v3-anonymous-content-review-v1",
        "source_frozen_manifest_sha256": hashlib.sha256((frozen / "MANIFEST.json").read_bytes()).hexdigest(),
        "instructions": [
            "只依据本包的用户问题、程序报告、逐月参考和匿名原答评阅；不要查看模型映射或既有评论。",
            "分别填写 factual_fidelity、answers_the_question、helpfulness_and_readability 和理由；格式合同已由程序独立检验。",
            "模型只补充解释，金额与图表由程序报告提供；不要因为解释没有复述已显示的数字而直接扣分。",
            "注意最近月环比与整个观察窗口首尾变化不是一回事；政策因果不能仅凭金额走势判定。",
            "没有回答的配置不在匿名原答中；不猜模型，也不把无答案算作内容错误。",
        ],
        "cases": reviews,
    }
    packet_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    _atomic(packet_dir / "packet.json", packet)
    packet_digest = hashlib.sha256((packet_dir / "packet.json").read_bytes()).hexdigest()
    _atomic(mapping_path, {"schema_version": "trade-v3-review-map-v1",
                           "packet_sha256": packet_digest, "labels": mapping})
    return {"packet": str(packet_dir / "packet.json"), "packet_sha256": packet_digest,
            "case_count": len(reviews), "answer_count": len(mapping),
            "mapping_private": str(mapping_path)}


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False))
