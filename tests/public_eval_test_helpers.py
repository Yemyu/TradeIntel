"""Synthetic review decisions for ledger tests, never model quality evidence."""
from src.tradeintel_ai.public_eval_ledger import record_review as _record_review


def record_review(*args, **kwargs):
    verdict = kwargs["verdict"]
    kwargs.setdefault("checks", {
        name: {"passed": verdict == "pass" or name != "facts",
               "reason": "离线测试夹具，仅用于验证审阅控制，不是实际模型评分。"}
        for name in ("structure", "facts", "relevance", "usefulness")
    })
    return _record_review(*args, **kwargs)
