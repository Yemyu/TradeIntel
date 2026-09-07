"""Continue unattempted slots only; preserve the frozen v1 runner and all failures."""
from __future__ import annotations

import argparse
from copy import deepcopy
import getpass
import json
import os
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_live_evaluation as live
from src.tradeintel_ai.model_adapter import OpenAICompatibleConfig, OpenAICompatibleModel, ModelAdapterError

DEFAULT_PARENT = ROOT / "tmp/ai-live-runs/20260906T151758594188Z.json"
AMENDMENT = ROOT / "docs/decisions/0010-collection-continuation.zh-CN.md"


def schedule(questions, repeats, seed):
    rng = random.Random(seed)
    for repeat in range(1, repeats + 1):
        order = list(questions)
        rng.shuffle(order)
        for q in order:
            arms = ["direct", "agent"]
            rng.shuffle(arms)
            for arm in arms + ["direct_evidence"]:
                yield repeat, q, arm


def prepare(parent_path):
    parent = json.loads(Path(parent_path).read_text(encoding="utf-8"))
    manifest = live.validate_manifest(live.DEFAULT_MANIFEST, live.DEFAULT_FINAL_QUESTIONS)
    questions, _ = live.load_question_set(live.DEFAULT_FINAL_QUESTIONS)
    if (parent.get("manifest") != manifest or parent.get("repeats") != 3
            or parent.get("seed") != 301 or parent.get("planned_answers") != 360
            or parent.get("question_sha256") != live.digest(live.DEFAULT_FINAL_QUESTIONS)
            or set(parent.get("systems", [])) != set(live.ARMS)):
        raise ValueError("旧批次与冻结配置不一致，停止续跑")
    slots = list(schedule(questions, 3, 301))
    known = {q["id"]: q for q in questions}
    recorded = {}
    for row in parent["questions"]:
        q = known.get(row["id"])
        if q is None or any(row.get(k) != v for k, v in q.items()):
            raise ValueError("旧批次题目与冻结题集不一致")
        for arm, result in row["systems"].items():
            key = (row["repeat"], row["id"], arm)
            if key in recorded:
                raise ValueError("旧批次含重复记录")
            recorded[key] = result
    expected = [(r, q["id"], a) for r, q, a in slots]
    if set(recorded) != set(expected[:len(recorded)]):
        raise ValueError("只允许从已记录的连续前缀续跑，不能选择性补题")
    if not isinstance(parent.get("request_count"), int) or not 0 <= parent["request_count"] <= 800:
        raise ValueError("旧批次请求计数无效")
    return parent, slots, recorded


def collect(parent_path, *, execute=False, output=None, config=None, pause=time.sleep):
    parent, slots, recorded = prepare(parent_path)
    pending = [(r, q, a) for r, q, a in slots if (r, q["id"], a) not in recorded]
    plan = {"status": "preflight_passed", "retained": len(recorded), "remaining": len(pending),
            "planned_answers": 360, "scoring_status": "not_run"}
    if not execute or not pending:
        return plan
    original = parent["configuration"]
    config = config or OpenAICompatibleConfig.from_env()
    endpoint = live._safe_endpoint(config.base_url)
    if (config.model != original["requested_model"] or config.temperature != original["temperature"]
            or config.timeout_seconds != original["timeout_seconds"]
            or live.hashlib.sha256(endpoint.encode()).hexdigest() != original["endpoint_sha256"]):
        raise ValueError("续跑的模型、地址、温度或超时与原批次不一致")
    if config.api_key and (not config.api_key.isascii() or any(c.isspace() for c in config.api_key)):
        raise ValueError("Key格式不正确，请只复制原始Key；内容不会显示")
    models = {a: OpenAICompatibleModel(config, system_prompt=p) for a, p in (
        ("agent", live.AGENT_PROMPT), ("direct", live.DIRECT_SYSTEM_PROMPT),
        ("direct_evidence", live.EVIDENCE_SYSTEM_PROMPT))}
    output = Path(output or live.DEFAULT_OUTPUT_DIR / (live.datetime.now(live.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-continued.json"))
    journal_path = output.with_suffix(".jsonl")
    if output == journal_path or output.exists() or journal_path.exists():
        raise ValueError("输出已存在；不能覆盖旧记录")
    report = deepcopy(parent)
    report.update(status="running", stop_reason=None, scoring_status="not_run", model_adopted=False,
                  metrics=None, output=str(output), journal=str(journal_path))
    report["continuation"] = {"parent": str(Path(parent_path).resolve()), "parent_sha256": live.digest(parent_path),
        "retained_slots": len(recorded), "started_at_utc": live.utcnow(),
        "amendment_sha256": live.digest(AMENDMENT), "collector_sha256": live.digest(__file__),
        "policy": "unattempted_slots_only; no_answer_retries; at_most_two_30s_cooldowns"}
    rows = {(x["repeat"], x["id"]): x for x in report["questions"]}
    output.parent.mkdir(parents=True, exist_ok=True)
    def serialise(value):
        text = json.dumps(value, ensure_ascii=False, allow_nan=False)
        return text.replace(config.api_key, "[REDACTED]") if config.api_key else text
    with output.open("x", encoding="utf-8") as out, journal_path.open("x", encoding="utf-8") as journal:
        def append(value):
            journal.write(serialise(value) + "\n")
            journal.flush()
            os.fsync(journal.fileno())
        recorder = live.Recorder(append, 800)
        recorder.count = parent["request_count"]
        cooldowns = 0
        done = len(recorded)
        append({"event": "continuation_started", "report": report})
        try:
            for repeat, q, arm in pending:
                key = (repeat, q["id"])
                if key not in rows:
                    rows[key] = {**q, "repeat": repeat, "systems": {}}
                    report["questions"].append(rows[key])
                row = rows[key]
                identity = {"id": q["id"], "repeat": repeat, "arm": arm}
                print(f"已记录 {done}/360；正在运行第{repeat}轮 {q['id']} {arm}（单次等待上限约60秒）", flush=True)
                wrapped = live.RecordedModel(models[arm], recorder, identity)
                context = live.replay_context(row["systems"].get("agent", {}).get("trace", []))
                start = time.perf_counter()
                interrupted = False
                try:
                    result = (live.ToolCallingAgent(wrapped).answer(q["question"]) if arm == "agent"
                              else live.run_direct(wrapped, q["question"], evidence_context=context if arm == "direct_evidence" else None))
                except KeyboardInterrupt:
                    interrupted = True
                    result = {"status": "error", "error": "interrupted_in_flight"}
                except live.RunStopped as exc:
                    result = {"status": "error", "error": str(exc)}
                except ModelAdapterError as exc:
                    result = {"status": "error", "error": str(exc)}
                result.update(trace=wrapped.trace, elapsed_ms=round((time.perf_counter()-start)*1000, 2))
                if arm == "direct_evidence":
                    result.update(evidence_context=context, interpretation="conditional_replay_of_agent_evidence")
                last = wrapped.trace[-1].get("response", {}) if wrapped.trace else {}
                reason = last.get("metadata", {}).get("finish_reason")
                result["generation_complete"] = (bool(result.get("response", "").strip()) and
                    result.get("status") in {"ok", "needs_review"} and reason in (None, "stop"))
                row["systems"][arm] = result
                append({"event": "answer_recorded", "identity": identity, "result": result})
                done += 1
                print(f"已记录 {done}/360；本项{'回答完成' if result['generation_complete'] else '失败已保留'}", flush=True)
                if interrupted:
                    raise KeyboardInterrupt
                errors = [t.get("error", "") for t in wrapped.trace]
                if any(any(f"HTTP {code}" in e for code in (400, 401, 402, 403, 404, 429)) for e in errors):
                    recorder.stop_reason = "configuration_or_quota_error"
                    raise live.RunStopped(recorder.stop_reason)
                if recorder.stop_reason:
                    if recorder.stop_reason != "three_consecutive_request_errors" or cooldowns >= 2:
                        raise live.RunStopped(recorder.stop_reason)
                    cooldowns += 1
                    append({"event": "cooldown", "seconds": 30, "number": cooldowns})
                    print("连续连接失败，等待30秒后继续下一项；失败记录保留。", flush=True)
                    pause(30)
                    recorder.stop_reason = None
                    recorder.consecutive_errors = 0
            report["status"] = "collected_not_scored"
        except KeyboardInterrupt:
            report["status"] = "interrupted"
        except Exception as exc:
            report["status"] = "stopped"
            report["stop_reason"] = recorder.stop_reason or type(exc).__name__
        finally:
            report.update(finished_at_utc=live.utcnow(), request_count=recorder.count)
            append({"event": "run_finished", "status": report["status"]})
            out.write(serialise(report) + "\n")
            out.flush()
            os.fsync(out.fileno())
    return {"status": report["status"], "recorded": sum(len(r["systems"]) for r in report["questions"]),
            "output": str(output), "stop_reason": report.get("stop_reason"), "scoring_status": "not_run"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, default=DEFAULT_PARENT)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(collect(args.parent), ensure_ascii=False), flush=True)
        config = None
        if args.execute:
            parent, _, _ = prepare(args.parent)
            c = parent["configuration"]
            base = "https://open.bigmodel.cn/api/paas/v4"
            # Only restore the endpoint previously verified in this project's GLM run.
            if live.hashlib.sha256(base.encode()).hexdigest() != c["endpoint_sha256"]:
                raise ValueError("原地址不是已确认GLM接口，需要检查配置")
            key = os.environ.get("TRADEINTEL_MODEL_API_KEY")
            if not key:
                if not sys.stdin.isatty():
                    raise ValueError("请在交互终端运行，以便隐藏输入Key")
                key = getpass.getpass("请粘贴 GLM API Key 并回车（输入不显示）：")
            if not key.strip():
                raise ValueError("Key不能为空")
            config = OpenAICompatibleConfig(base, c["requested_model"], key.strip(), c["timeout_seconds"], c["temperature"])
            result = collect(args.parent, execute=True, config=config)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            return 0 if result["status"] in {"preflight_passed", "collected_not_scored"} else 1
        return 0
    except (ValueError, OSError, KeyError, ModelAdapterError):
        print("配置或输入文件校验失败；未显示密钥。请保留终端提示并告知我。", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
