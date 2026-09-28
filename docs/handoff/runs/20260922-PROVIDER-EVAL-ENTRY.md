# 2026-09-22 公共四题模型评测入口

> 当前状态：冻结、持久去重、逐题执行和语义审阅门已经离线实现；真实命令仍会因为没有 `ready_for_formal` 冻结而拒绝。DeepSeek身份已有此前成功记录，正式思考参数尚未冻结。当前规格见 `../ASTRA_PUBLIC_RUNNER_REVIEW_20260922.zh-CN.md`。

## 本轮完成

- 新增 `evals/public_brief_v1/provider_matrix.json`，登记两种 Codex 会话配置和四个 API 候选。矩阵不保存密钥，也不把历史 GLM-4.7 结果冒充本轮 GLM-4.6V/Air 成绩。
- 新增 `scripts/run_public_brief_eval.py`。它只读取 `candidate-service-20260922-v1` 的四份 `messages.json`；参考答案和主机报告不进入送模消息。
- 默认命令是离线预检，核对题包状态、每个文件摘要、题目顺序和输入估算；本轮预检为 0 次 API。
- 真正请求必须同时带 `--execute --authorize-real-call --freeze <ready_for_formal文件>`，并通过专用环境变量提供密钥；每次命令只发送一道题，下一题需先记录上一题的语义审阅。无自动重试；原答及usage先保存在本地，程序只做结构解析，语义评分仍由隐藏模型名后的人工/复核流程完成。
- 输出也有独立硬门：优先使用供应商返回的 `completion_tokens`，缺失时用项目保守估算；超过两千 token 或六十四 KiB 直接阻断并保留原答，不自动重试。

## 运行方式

先做不联网预检：

```bash
PYTHONPATH=src:. .venv/bin/python scripts/run_public_brief_eval.py \
  --provider-id glm-46v
```

离线控制测试（不会调用API）：

```bash
PYTHONPATH=src:. .venv/bin/python -m unittest \
  tests.test_public_eval_controls tests.test_public_brief_eval_runner
```

真实运行必须逐题，不能一次传q1,q2：

```bash
PYTHONPATH=src:. .venv/bin/python scripts/run_public_brief_eval.py \
  --provider-id glm-46v --questions q1
```

真实 API 运行（只有在模型 ID、端点、思考参数和密钥已单独确认后才执行）：

```bash
TRADEINTEL_GLM_API_KEY='只在当前终端临时设置' \
PYTHONPATH=src:. .venv/bin/python scripts/run_public_brief_eval.py \
  --provider-id glm-46v --questions q1 \
  --freeze .local/experiments/public-brief-v1/glm-46v.freeze.json \
  --output tmp/public-brief-eval-v1/results/glm-46v-20260922 \
  --execute --authorize-real-call
```

命令行和日志不会记录密钥。不要把密钥粘进 `provider_matrix.json`、提交记录或聊天。DeepSeek 的 model ID 和 endpoint 已按成功探测记录恢复；正式思考档位和总预算仍需冻结，在此之前执行器会拒绝它，而不是猜参数。

完成一题后，先查看 `results/.../q1/raw-response.txt` 与确定性程序报告，再记录语义审阅；这一步不会修改原答：

```bash
PYTHONPATH=src:. .venv/bin/python scripts/review_public_brief_answer.py \
  --run-dir tmp/public-brief-eval-v1/results/glm-46v-20260922 \
  --run-id pub-... --reviewer 'human' --verdict pass \
  --ledger-root .
```

## 当前未完成

1. Luna/Sol 需要在独立干净会话逐题运行，不能把本长对话示例计入成绩。
2. GLM-4.6V/Air 需要确认平台实际返回的 model ID 和思考字段是否接受当前冻结参数。
3. DeepSeek Flash/Pro 需要补确切 model ID、兼容端点和思考设置。
4. 真实回答完成后，按 `evals/public_brief_v1/SCORING.zh-CN.md` 隐去模型名评分；四题结构通过也不能直接称为长期准确率。

本记录不宣称正式题包已经冻结、不修改旧实验账本；截至本次更新 API 调用仍为0。正式回答产生后，用 `scripts/review_public_brief_answer.py` 记录人工/AI辅助审阅，不能只凭结构解析算通过。
