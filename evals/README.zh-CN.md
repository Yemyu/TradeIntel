# 最终模型评估题集

这里有三套职责不同的文件：

- `questions.jsonl` 与 `gold_answers.json`：旧60题，只用于工具契约开发回归；
- `final_questions.jsonl`：模型会接触到的40道最终候选题，只含问题；
- `final_gold.json`：评估者使用的标准事实、来源与拒答要求，运行器不会加载；
- `final_manifest.json`：冻结题目、运行代码和证据文件的 SHA-256，防止看到结果后静默改题或改程序。

40题按10种任务模板分组，每个模板4题。它们测试组合查询、连续与非连续月份计算、质量和因果边界、文件溯源、错误报告纠正以及超范围指令。它们由同一项目维护者设计，属于同领域项目验收题，不能宣传成第三方盲测或完全独立的新领域测试。

运行器默认只做离线预检，不需要模型配置，也不会消耗额度：

```bash
.venv/bin/python scripts/run_live_evaluation.py
```

正式运行前先用旧题做3题冒烟。只有显式加入 `--execute` 才会调用模型：

```bash
.venv/bin/python scripts/run_live_evaluation.py \
  --questions evals/questions.jsonl \
  --allow-development-set --smoke --limit 3 --repeats 1 \
  --execute
```

正式批次固定为40题、三组、三轮，共360份回答，最多720次模型请求。每次请求和每份回答都会立即追加到 `tmp/ai-live-runs/*.jsonl`，整批汇总写入同名 `.json`；关闭终端时，已经完成的记录仍会保留。旧开发题即使复制改名也不能被标成正式题。

```bash
.venv/bin/python scripts/run_live_evaluation.py --execute
```

生成复核表后，逐项填写事实、引用、任务完成、适当拒答、越界因果和证据伪造。AI可以辅助初评，但必须登记为 `ai_assisted`，不能称作独立人工审核：

```bash
.venv/bin/python scripts/review_live_evaluation.py \
  tmp/ai-live-runs/运行文件.json \
  --output tmp/ai-live-runs/复核表.json

.venv/bin/python scripts/review_live_evaluation.py \
  tmp/ai-live-runs/运行文件.json \
  --review tmp/ai-live-runs/复核表.json \
  --output tmp/ai-live-runs/评分报告.json
```

详细边界与分母见 `docs/decisions/0009-live-evaluation-protocol.zh-CN.md`。当前只完成离线设计与冻结；没有运行正式模型批次，也没有真实模型成绩。
