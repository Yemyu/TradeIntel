# 统一四题评测接线与离线验收（2026-09-23）

## 结论

新统一四题评测包已完成离线接线与验收，可以作为后续同配置模型比较的固定材料。**这不是模型质量结果：本阶段没有模型 API 调用，没有独立 Codex 会话作答，也没有新的模型正确率。**离线替身答复只验证系统管线，不算模型得分。

## 固定材料

- 题包：`tmp/public-brief-eval-v2/unified-service-20260923-v2/`
- 实验：`public-brief-unified-v2`
- 候选题包版本：`public-service-candidate-v2`
- 评分附件：`evals/public_brief_v1/SCORING_UNIFIED_V2.zh-CN.md`
- Q1、Q2、Q4 使用贸易解释协议；Q3 使用政策解释协议。Q3 的旧单题开发成绩不并入新四题组。
- 输入估算：Q1 15,914；Q2 12,699；Q3 15,857；Q4 15,914 tokens，均低于16,000硬门。Q1和Q4余量较窄；估算值不等于供应商实际计费量。

## 本阶段改动与防错边界

- 执行器根据题包绑定的协议选择对应解析器；评分汇总按实验、题包、评分协议和渠道分组，并校验原答、输入快照及哈希。历史独立Q3结果不会混入新四题成绩。
- 统一正文预算把贸易解释、政策解释和观察理由一起计入2,000字符门；Q3超限时阻止整题通过，不允许政策正文绕过原有门槛。
- Codex 对话候选与 API 候选分开：Codex Luna/Sol 可完成离线材料预检，但必须在独立新会话手动作答；API 执行器不会把对话冒充 API 调用。Codex 会话候选不能生成 API 冻结。
- 修复逐题运行记录中实验编号的读取位置；旧题包、冻结、历史分数和原答均未改写。

## 验收

- 定向 Python 回归：86项通过，包含统一四题、单题旧兼容路径、正文预算、冻结与拒绝边界、截止时间及汇总隔离；另有3项手动题包导出测试通过，合计89项。
- 六个矩阵候选（Codex Luna Max、Codex Sol High、GLM-4.6V、GLM-4.5-Air、DeepSeek Flash、DeepSeek Pro）离线预检全部通过。DeepSeek登记为 enabled/high；GLM只提供enabled思考开关，不设高低强度。每个预检均报告 `api_calls=0`；预检只证明材料与配置登记可读，不证明网络连通或回答质量。
- Codex独立会话题包已生成：`tmp/public-brief-eval-v2/manual-codex-packets/codex-luna-highest/` 和 `tmp/public-brief-eval-v2/manual-codex-packets/codex-sol-high/`。每包含四个核对过摘要的完整题目文本、使用说明和输入摘要；没有答案或参考评分。包内登记型号是GPT-5.6，开测前需核对模型菜单完整版本；不同版本不可混记。手动会话必须每题开新会话，且不与API成绩合并。
- 执行终端没有设置 `TRADEINTEL_GLM_API_KEY` 或 `TRADEINTEL_DEEPSEEK_API_KEY`；本轮未尝试读取聊天中的密钥，也未发API请求。
- `py_compile` 通过；无真实 API 请求、无提交推送。

## 尚未完成

1. Codex Luna Max 与 Sol High：各自在干净独立的新会话按相同问题作答，手动保存原答并按统一审阅规则计分；当前主对话有项目历史，不能当独立测试结果。题目文件和步骤见上述两个包内的 `README.zh-CN.md`。
2. GLM 与 DeepSeek：每个配置仍须核实密钥、接口端实际模型名及思考参数；DeepSeek按enabled/high请求，GLM按enabled请求。冻结后由用户确认再发出真实请求；每题一次，按停止规则审阅，不自动重试。
3. 每个模型的回答质量按确切模型、推理设置、渠道、题包版本分别报告Q/R；只有原答完整经过事实、范围、回应度和解释价值审阅才可计为通过。整条产品流程另记D/N。
4. 模型比较完成后再进入前端阶段。

## 重现命令（均不调用 API）

```bash
PYTHONPATH=src:. .venv/bin/python -B -m unittest \
  tests.test_public_brief_eval_runner \
  tests.test_unified_public_four_question_eval \
  tests.test_public_eval_budget_v3 \
  tests.test_output_budget \
  tests.test_public_eval_controls \
  tests.test_public_eval_release \
  tests.test_public_eval_deadline \
  tests.test_public_eval_scoring \
  tests.test_public_policy_eval_runner \
  tests.test_public_policy_explanation -q

PYTHONPATH=src:. .venv/bin/python -B scripts/run_public_brief_eval.py \
  --provider-id glm-46v
```

Codex 手动候选可将 `--provider-id` 改为 `codex-luna-highest` 或 `codex-sol-high` 做题包预检。正式 API 运行必须另外具备可复核的冻结文件和明确授权；当前阶段未放行调用。
