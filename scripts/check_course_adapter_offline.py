"""离线校验证据、固定贸易查询和研究状态契约。

使用标准库和固定样例，核对证据字段、查询参数、缓存范围与研究状态。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 允许从仓库根目录直接执行 `python scripts/...`，不需要安装本项目。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.tradeintel_ai.course_adapters import (
    AdapterContractError,
    adapt_course_db_tool,
    adapt_course_source,
    cache_scope,
    validate_research_state,
)


def main() -> int:
    source = adapt_course_source({
        "source_id": "POL-1", "policy_id": "us_301_review2025_tungsten_solar",
        "data_version": "trade-v1", "quote": "full condition", "location": "page 3",
    })
    query = adapt_course_db_tool({
        "policy_id": source.policy_id, "data_version": source.data_version,
        "month": "2026-07", "hts8": ["28046100"],
    })
    assert cache_scope(policy_id=query.policy_id, data_version=query.data_version, month=query.month, question="New policy")[-1] == "new policy"
    validate_research_state({"source_index": [{"source_id": source.source_id}], "parse_failed": False})
    negative_cases = [
        lambda: adapt_course_db_tool({"sql": "SELECT * FROM trade"}),
        lambda: validate_research_state({"source_index": []}),
        lambda: validate_research_state({"source_index": [{"source_id": "S1"}], "parse_failed": True}),
    ]
    for check in negative_cases:
        try:
            check()
        except AdapterContractError:
            continue
        raise AssertionError("unsafe course adapter case was accepted")
    print("course adapter offline checks: 7 passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
