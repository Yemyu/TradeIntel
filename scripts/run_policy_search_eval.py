#!/usr/bin/env python3
"""Offline 12-question development evaluation for the current-corpus policy search.

Builds a document store from the registered (hash-verified) policy corpus and
adds the 2018 USTR notices as a superseded document version for cross-version
questions.  The development set follows the Astra allocation: 6 normal /
synonym questions, 2 common-qualifier questions, 2 cross-version questions and
2 no-evidence questions.  Gates: normal+qualifier at least 7 of 8 with zero
missed key conditions, zero version pollution, and no-evidence questions must
clearly report insufficiency instead of substituting hits.

This is a development acceptance harness, NOT a blind-test accuracy claim.
No model, network or provider access.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from tradeintel_ai.policy_retrieval import build_corpus as build_2018_corpus
from src.tradeintel_ai.policy_documents import build_document, build_document_store
from src.tradeintel_ai.policy_search import PolicySearch, set_required_dependencies

CURRENT_PUBLISHED = "2024-12-31"
OLD_PUBLISHED = {"initial_notice": "2018-06-20", "amendment_notice": "2018-08-16"}


def build_eval_store(root: Path) -> dict:
    corpus = json.loads((root / "data/processed/policy_exposure/policy_corpus.json").read_text())
    sources = [{"id": chunk["id"], "url": chunk["url"], "text": chunk["text"],
                "document_sha256": chunk["sha256"]}
               for chunk in corpus["chunks"]]
    current = build_document(
        {"policy_id": "us_301_review2025_tungsten_solar",
         "data_version": "91c2ed45f937392ea4473cd156ca05d3c7566e333ff9d50be90f5cbeccba4e1b",
         "sources": sources},
        doc_id="cbp63577329", publication_time=CURRENT_PUBLISHED, status="enabled")
    # Evidence-backed required-dependency mapping (review F6): locations were
    # verified against the registered sections; exceptions verified absent.
    set_required_dependencies(current, {
        "effective_date": {"status": "known",
                           "section_ids": ["cbp63577329:p8:para1"],
                           "evidence": "登记步骤核对：生效句在p8首段"},
        "origin": {"status": "known",
                   "section_ids": ["cbp63577329:p9:para1", "cbp63577329:p12:para1"],
                   "evidence": "登记步骤核对：两段均含 products of China"},
        "conditions": {"status": "known",
                       "section_ids": ["cbp63577329:p9:para2", "cbp63577329:p12:para2",
                                       "cbp63577329:p12:para3", "cbp63577329:p12:para4"],
                       "evidence": "登记步骤核对：各税号行内含纯度/用途限定"},
        "exceptions": {"status": "verified_absent",
                       "note": "已索引的p8/p9/p12全部段落均无例外条款；未知代表本公告未载明，不代表没有其他例外。",
                       "evidence": "登记步骤核对：全文扫描无 exclusion/except 字样"},
    })
    old = build_2018_corpus(root)
    documents = [current]
    for wanted in ("amendment_notice:p1:c1245", "initial_notice:p2:c0"):
        chunk = next(item for item in old["chunks"] if item["id"] == wanted)
        notice = "amendment_notice" if "amendment" in chunk["id"] else "initial_notice"
        documents.append(build_document(
            {"policy_id": "us_301_list1_2018", "data_version": "ustr-2018-notices",
             "sources": [{"id": chunk["id"], "url": chunk["url"], "text": chunk["text"],
                          "document_sha256": chunk["sha256"]}]},
            doc_id=f"ustr-2018-{notice}", publication_time=OLD_PUBLISHED[notice],
            status="superseded"))
    store = build_document_store(
        documents,
        policy_id=current["policy_id"], data_version=current["data_version"],
        limitations=["文档存储只包含已登记公告的正文段落，不是完整法规库。",
                     "publication_time 未知时，检索不得声称该文档在给定时间点已可得。",
                     "2018年公告属另一政策条目，跨政策检索被隔离，默认不返回。"])
    return store


DEV_SET = [
    # -- 6 normal / synonym questions ------------------------------------
    {"id": "q01", "type": "normal", "question": "2025年钨产品加征的额外关税税率是多少？",
     "required": ["8101.94.00", "25 percent rate of duty"], "forbidden": []},
    {"id": "q02", "type": "normal", "question": "多晶硅和硅片要加征多少关税？",
     "required": ["2804.61.00", "50 percent rate of duty"], "forbidden": []},
    {"id": "q03", "type": "normal", "question": "这次加征关税从什么时候开始生效？",
     "required": ["January 1, 2025"], "forbidden": []},
    {"id": "q04", "type": "normal", "question": "什么时间点入境的货物适用这次加征？",
     "required": ["12:01 a.m. eastern standard time"], "forbidden": []},
    {"id": "q05", "type": "normal", "question": "8101.99.80 钨制品的加征税率是多少？",
     "required": ["8101.99.80", "25 percent"], "forbidden": []},
    {"id": "q06", "type": "normal", "question": "这些关税适用于哪一原产地的产品？",
     "required": ["of China"], "forbidden": []},
    # -- 2 common-qualifier questions ------------------------------------
    {"id": "q07", "type": "qualifier", "question": "28046100 多晶硅的加征是否也适用于纯度不足99.99%的硅？",
     "required": ["2804.61.00", "not less than 99.99 percent"], "forbidden": []},
    {"id": "q08", "type": "qualifier", "question": "从仓库提取消费的钨棒81019910是否适用这次加征？",
     "required": ["8101.99.10", "withdrawn from warehouse for consumption"], "forbidden": []},
    # -- 2 cross-version questions ---------------------------------------
    {"id": "q09", "type": "cross_version", "policy_id": "us_301_list1_2018",
     "question": "2018年8月16日的公告对第一批301清单做了什么修订？",
     "kwargs": {"include_superseded": True},
     "required": ["301"], "forbidden": ["2804.61.00"],
     "forbidden_doc_version": "current"},
    {"id": "q10", "type": "cross_version",
     "question": "多晶硅产品在2024年年中是否已经被加征这次301关税？",
     "kwargs": {"as_of": "2024-06-30"},
     "expected_status": "no_evidence",
     "required": [], "forbidden": ["2804.61.00", "50 percent rate of duty"]},
    # -- 2 no-evidence questions ------------------------------------------
    {"id": "q11", "type": "no_evidence", "question": "这些产品的排除清单具体包含哪些企业？",
     "required": [], "forbidden": ["exclusion"],
     "expected_status": "no_evidence"},
    {"id": "q12", "type": "no_evidence", "question": "光伏组件8541.42.00的加征税率是多少？",
     "required": [], "forbidden": ["2804.61", "8101"],
     "expected_status": "no_evidence"},
    # -- extended set: review F5/F6 counter-examples (development only) ---
    {"id": "e01", "type": "extended", "question": "8101.94.00和2804.61.00的税率分别是多少？",
     "kwargs": {"top_k": 1},
     "required": ["8101.94.00", "2804.61.00", "25 percent", "50 percent"], "forbidden": [],
     "note": "两个税号top_k=1：精确命中不受top_k裁切，未覆盖税号必须显式报告"},
    {"id": "e02", "type": "extended",
     "question": "2018年8月的公告修订了什么？",
     "required": [], "forbidden": ["August 16, 2018"],
     "expected_status": "no_evidence",
     "note": "政策隔离：当前政策检索器不返回另一政策条目（2018）的内容"},
]


def evaluate(store: dict) -> dict:
    searchers: dict[str, PolicySearch] = {}

    def searcher_for(policy_id: str | None) -> PolicySearch:
        key = policy_id or store["policy_id"]
        if key not in searchers:
            searchers[key] = PolicySearch(store, policy_id=key)
        return searchers[key]

    current_versions = {document["doc_version"] for document in store["documents"]
                        if document["status"] == "enabled"}
    results = []
    for item in DEV_SET:
        kwargs = dict(item.get("kwargs", {}))
        outcome = searcher_for(item.get("policy_id")).search(item["question"], **kwargs)
        blob = "\n".join([hit["text"] for hit in outcome["hits"]]
                         + [ctx["text"] for ctx in outcome["required_context"] if ctx.get("text")])
        missing_required = [marker for marker in item["required"] if marker not in blob]
        pollution = [marker for marker in item["forbidden"] if marker in blob]
        wrong_version = (item.get("forbidden_doc_version") == "current"
                         and any(hit["doc_version"] in current_versions for hit in outcome["hits"]))
        uncovered = outcome.get("uncovered_codes") or []
        expected_status = item.get("expected_status", "candidate_evidence")
        passed = (outcome["status"] == expected_status
                  and not missing_required and not pollution and not wrong_version
                  and (item["type"] not in ("normal", "qualifier") or not uncovered))
        results.append({"id": item["id"], "type": item["type"], "question": item["question"],
                        "expected_status": expected_status, "actual_status": outcome["status"],
                        "missing_required": missing_required, "version_pollution": pollution,
                        "current_version_leak": wrong_version, "uncovered_codes": uncovered,
                        "hit_citations": [hit["citation_id"] for hit in outcome["hits"]],
                        "required_context_citations": [ctx["citation_id"] for ctx in outcome["required_context"]],
                        "passed": passed})
    normal_qualifier = [item for item in results if item["type"] in ("normal", "qualifier")]
    extended = [item for item in results if item["type"] == "extended"]
    summary = {
        "normal_qualifier_total": len(normal_qualifier),
        "normal_qualifier_passed": sum(1 for item in normal_qualifier if item["passed"]),
        "extended_total": len(extended),
        "extended_passed": sum(1 for item in extended if item["passed"]),
        "key_condition_misses": sum(len(item["missing_required"]) for item in results),
        "version_pollution_count": sum(len(item["version_pollution"]) for item in results)
                                   + sum(1 for item in results if item["current_version_leak"]),
        "no_evidence_clear": all(item["passed"] for item in results if item["type"] == "no_evidence"),
    }
    summary["gate_7_of_8"] = summary["normal_qualifier_passed"] >= 7
    summary["gate_zero_miss"] = summary["key_condition_misses"] == 0
    summary["gate_zero_pollution"] = summary["version_pollution_count"] == 0
    summary["gate_extended_all"] = not extended or summary["extended_passed"] == len(extended)
    summary["dev_acceptance"] = (summary["gate_7_of_8"] and summary["gate_zero_miss"]
                                 and summary["gate_zero_pollution"] and summary["no_evidence_clear"]
                                 and summary["gate_extended_all"])
    return {"summary": summary, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    store = build_eval_store(ROOT)
    report = evaluate(store)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    output = args.output or ROOT / "tmp/handoff-runs" / f"{stamp}-e2-policy-search-eval"
    output.mkdir(parents=True, exist_ok=True)
    (output / "eval-results.json").write_text(
        json.dumps({"schema_version": "policy-search-dev-eval-v1",
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "api_calls": 0,
                    "note": "开发验收集（6正常/2限定/2跨版本/2无证据）；不是盲测准确率。",
                    **report}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "eval-summary.zh-CN.md").write_text(
        "# 当前语料政策检索 12题开发集结果\n\n"
        f"- 正常+限定 8题通过：{report['summary']['normal_qualifier_passed']}/8（门槛≥7）\n"
        f"- 关键条件漏项：{report['summary']['key_condition_misses']}\n"
        f"- 版本污染：{report['summary']['version_pollution_count']}\n"
        f"- 无证据题明确不足：{report['summary']['no_evidence_clear']}\n"
        f"- 开发验收：{'通过' if report['summary']['dev_acceptance'] else '未通过'}\n"
        "- 边界：开发验收，不是盲测准确率；0次模型调用。\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    for item in report["results"]:
        marker = "PASS" if item["passed"] else "FAIL"
        print(f"[{marker}] {item['id']} ({item['type']}) -> {item['actual_status']}"
              + (f" missing={item['missing_required']}" if item["missing_required"] else "")
              + (f" pollution={item['version_pollution']}" if item["version_pollution"] else ""))
    print(f"output: {output}")
    return 0 if report["summary"]["dev_acceptance"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
