"""Internal v2.1 acceptance: 24 questions, two repeats. Offline by default; --execute asks for a hidden GLM key."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_live_evaluation as live
from src.tradeintel_ai.evidence_v21 import EvidenceAgentV21 as EvidenceAgentV2, EvidenceRegistryV21 as EvidenceRegistryV2, report_v21 as build_report
from src.tradeintel_ai.model_adapter import ModelAdapterError, OpenAICompatibleConfig, OpenAICompatibleModel

QUESTIONS = ROOT / "evals/acceptance_v21_questions.jsonl"
REFERENCE = ROOT / "evals/acceptance_v21_reference.json"
MANIFEST = ROOT / "evals/acceptance_v21_manifest.json"
BASE = "https://open.bigmodel.cn/api/paas/v4"
MODEL = "glm-4.5-air"


def load_questions(path=QUESTIONS):
    questions = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(questions) != 24 or len({q["id"] for q in questions}) != 24:
        raise ValueError("试验固定24道不同问题")
    if any(set(q) != {"id", "question"} or any(not isinstance(v,str) or not v.strip() for v in q.values()) for q in questions):
        raise ValueError("模型题目只能包含非空id和question")
    return questions


def structural_checks(result, reference):
    """Necessary checks only. Never label these as semantic task accuracy."""
    facts, sources = result.get("facts", []), result.get("sources", {})
    checks = []
    for label, value, path in reference["facts"]:
        matches = [f for f in facts if f["label"] == label and f["value"] == value]
        supported = any(any(sources.get(sid, {}).get("path", "").endswith(path)
                            for sid in fact["source_ids"]) for fact in matches)
        checks.append({"label":label,"value_and_source_present":supported})
    scope = set()
    invalid_scope = False
    for tool in result.get("tool_results", []):
        if tool.get("status") == "ok" and tool["tool_name"] == "get_trade_series":
            d = tool["data"]
            invalid_scope |= d.get("hs6") is not None or d.get("policy_id") != "us_301_list1_2018"
            scope.update((d["origin"], row["month"]) for row in d["series"])
    required_tools = {name for name, _ in reference["calls"]}
    return {"expected_fact_checks":checks,
            "queried_trade_scope_matches":not invalid_scope and scope == {tuple(p) for p in reference["trade_scope"]},
            "required_model_selected_tools_present":required_tools <= set(result.get("model_selected_tools", [])),
            "all_facts_bound_to_sources":bool(facts) and all(f["source_ids"] and all(s in sources for s in f["source_ids"]) for f in facts),
            "required_explanations_present":all(any(f["label"] == label for f in facts) for label in reference.get("explanation_labels", [])),
            "no_failed_tool_requests":not result.get("failed_tool_requests"),
            "manual_semantic_review":None, "manual_focus":reference.get("manual_focus", "Check scope, units, omissions, and whether the visible report answers the whole question."),
            "task_completed":None}


def reference_result(reference):
    registry = EvidenceRegistryV2()
    outputs = [registry.call(name,args) for name,args in reference["calls"]]
    if any(x["status"] != "ok" for x in outputs):
        raise ValueError("人工预设工具路线失败")
    if "get_causal_readiness" not in {name for name,_ in reference["calls"]}:
        outputs.append(registry.call("get_causal_readiness"))
    report = build_report(outputs)
    return {"facts":report.facts,"sources":report.sources,"response":report.render(),
            "tool_results":outputs, "model_selected_tools":[name for name,_ in reference["calls"]],
            "route_origin":"developer_reference_not_model", "model_prose_published":False}


def preflight():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for path, expected in manifest["files"].items():
        if live.digest(ROOT/path) != expected:
            raise ValueError(f"试验冻结文件已变化：{path}")
    questions = load_questions()
    references = json.loads(REFERENCE.read_text(encoding="utf-8"))
    if set(references) - {"purpose"} != {q["id"] for q in questions}:
        raise ValueError("问题和参考不对应")
    baselines = {q["id"]:reference_result(references[q["id"]]) for q in questions}
    for q in questions:
        checks = structural_checks(baselines[q["id"]], references[q["id"]])
        if (not all(f["value_and_source_present"] for f in checks["expected_fact_checks"])
                or not checks["queried_trade_scope_matches"] or not checks["required_explanations_present"]):
            raise ValueError("参考路线与独立数值检查不一致")
    return questions, references, baselines, manifest


def run(*, execute=False, output=None, config=None):
    questions, references, baselines, manifest = preflight()
    summary = {"status":"preflight_passed", "mode":"internal_acceptance_v21", "questions":24, "repeats":2, "planned_answers":48,
               "maximum_api_requests":192,"model":MODEL,"model_adopted":False,"semantic_accuracy":None}
    if not execute:
        return summary
    if config is None:
        raise ValueError("缺少模型配置")
    if (config.base_url != BASE or config.model != MODEL or config.timeout_seconds != 60
            or config.temperature != 0):
        raise ValueError("配置与本次试验不一致")
    key = config.api_key
    if not key or not key.isascii() or any(c.isspace() for c in key):
        raise ValueError("请只输入原始Key，不包含空白或非ASCII字符")
    output = Path(output or ROOT / "tmp/ai-acceptance-v21" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+".json"))
    journal_path = output.with_suffix(".jsonl")
    if output == journal_path or output.exists() or journal_path.exists():
        raise ValueError("不能覆盖已有运行记录")
    report = {**summary, "status":"running","question_count":24,"questions":[],"started_at_utc":live.utcnow(),
              "manifest":manifest,"manifest_sha256":live.digest(MANIFEST),"output":str(output),
              "api_requests":0,"manual_scoring_status":"not_run", "references":baselines}
    model = OpenAICompatibleModel(config, system_prompt=live.AGENT_PROMPT)
    output.parent.mkdir(parents=True, exist_ok=True)
    def serialise(value):
        return json.dumps(value, ensure_ascii=False, allow_nan=False).replace(key, "[REDACTED]")
    with output.open("x", encoding="utf-8") as out, journal_path.open("x", encoding="utf-8") as journal:
        def append(value):
            journal.write(serialise(value)+"\n")
            journal.flush()
            os.fsync(journal.fileno())
        recorder = live.Recorder(append, 192)
        append({"event":"run_started", "manifest_sha256":report["manifest_sha256"], "configuration":{"model":MODEL,"base_url":BASE,"temperature":0,"timeout_seconds":60}})
        ordered = [{**q, "repeat":repeat} for repeat in (1,2) for q in questions]
        random.Random(908).shuffle(ordered)
        try:
            for i,q in enumerate(ordered,1):
                print(f"开始 {i}/48：{q['id']} 第{q['repeat']}轮（单次请求等待上限约60秒）",flush=True)
                wrapped = live.RecordedModel(model,recorder,{"id":q["id"],"arm":"v21_agent","repeat":q["repeat"]})
                interrupted = False
                try:
                    result = EvidenceAgentV2(wrapped).answer(q["question"])
                except KeyboardInterrupt:
                    interrupted = True
                    result = {"status":"error","error":"interrupted_in_flight"}
                except Exception as exc:
                    result = {"status":"error","error":str(exc) if isinstance(exc,ModelAdapterError) else type(exc).__name__}
                last = wrapped.trace[-1].get("response",{}) if wrapped.trace else {}
                complete = result.get("status") == "needs_review" and last.get("metadata",{}).get("finish_reason") == "stop"
                checks = structural_checks(result,references[q["id"]])
                item = {**q,"result":result,"trace":wrapped.trace,"generation_complete":complete,"structural_checks":checks}
                report["questions"].append(item)
                append({"event":"answer_recorded","item":item})
                print(f"已记录 {i}/48；{'报告生成完成' if complete else '失败或未完整结束，已保留'}；累计请求 {recorder.count}/192",flush=True)
                if interrupted:
                    raise KeyboardInterrupt
                errors = [str(t.get("error","")) for t in wrapped.trace]
                if any(any(f"HTTP {code}" in e for code in (400,401,402,403,404,429)) for e in errors):
                    recorder.stop_reason = "configuration_or_quota_error"
                if recorder.stop_reason:
                    raise live.RunStopped(recorder.stop_reason)
            report["status"] = "collected_not_scored"
        except KeyboardInterrupt:
            report["status"] = "interrupted"
        except Exception as exc:
            report.update(status="stopped",stop_reason=recorder.stop_reason or type(exc).__name__)
        finally:
            report.update(finished_at_utc=live.utcnow(),api_requests=recorder.count)
            append({"event":"run_finished","status":report["status"]})
            out.write(serialise(report)+"\n")
            out.flush()
            os.fsync(out.fileno())
    return {"status":report["status"],"recorded":len(report["questions"]),"api_requests":recorder.count,
            "output":str(output),"model_adopted":False,"semantic_accuracy":None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute",action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(run(),ensure_ascii=False),flush=True)
        if not args.execute:
            return 0
        key = os.environ.get("TRADEINTEL_MODEL_API_KEY")
        if not key:
            if not sys.stdin.isatty():
                raise ValueError("请在交互终端输入Key")
            key = getpass.getpass("请粘贴GLM API Key并回车（输入不显示）：")
        result = run(execute=True, config=OpenAICompatibleConfig(BASE,MODEL,key.strip(),60,0))
        print(json.dumps(result,ensure_ascii=False),flush=True)
        return 0 if result["status"] == "collected_not_scored" else 1
    except (ValueError,OSError,KeyError,ModelAdapterError):
        print("配置或冻结文件检查失败；没有显示密钥。请告知我。")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
