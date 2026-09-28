# 统一四题评测：首轮 GLM / DeepSeek API 结果

> 评分分工复核已完成，见[追加复核裁定](20260923-UNIFIED-SCORING-ADJUDICATION.zh-CN.md)和[模型对照表](20260923-MODEL-COMPARISON-TABLE.zh-CN.md)。本文件保留首轮原始状态，不覆盖原答、账本或冻结结果。

日期：2026-09-23。题包：`public-brief-unified-v2`，固定材料为 `tmp/public-brief-eval-v2/unified-service-20260923-v2/`。本轮只执行冻结允许的配置；没有重试，没有调用 GLM-4.5-Air 或 Qwen。用户提供的凭据没有写入代码、配置文件或日志。

## 结果概览

| 配置 | 实际请求/返回标识 | 已调用 | 收到回答 | 当前结论 |
|---|---|---:|---:|---|
| GLM-4.6V（thinking enabled；接口不提供 high/low 档） | `glm-4.6v` / `glm-4.6v` | Q1 一次 | 1 | 无效响应：原答在解释正文中写入数字税号和日期，生产解析明确拒绝，整题结构不通过。记录里的 `body_unavailable` 是解析失败后无法计算正文字数的次级显示，不是实际超长或接口丢答。触发停止门，Q2—Q4 未运行。 |
| DeepSeek Flash（thinking enabled，requested high） | 请求/返回 `deepseek-flash` / `deepseek-flash` | Q1—Q3 各一次 | 3 | Q1、Q2 结构与正文预算通过；非盲 AI 辅助初审两题记为 minor error，但部分扣分理由与冻结提示词禁止输出数字/日期的规则冲突，最终内容结论待统一裁定。Q3 到达 8192 completion-token 上限并以 `finish_reason=length` 截断，整题不能通过；Q4 按停止规则未运行。底层版本无法仅凭 API 返回别名确认。 |
| DeepSeek Pro（requested `deepseek-v4-pro`，thinking enabled，requested high） | 请求 `deepseek-v4-pro`；90 秒内没有可记录的返回模型 | Q1 一次 | 0 | `unknown_outcome`：本地 90 秒截止，服务端是否完成及是否计费未知。按规则不重试，Q2—Q4 未运行。不能把未知结果记成答错或接口成功。 |

## 用量与分数口径

- 共发出 **5 次真实 API 请求**：GLM 1 次、DeepSeek Flash 3 次、DeepSeek Pro 1 次；没有自动重试。
- 四个已收到响应的请求合计 **63,323 tokens**（GLM 12,780；Flash Q1 17,479、Q2 13,312、Q3 19,752）。Pro 的 token 用量未知；这里不推算货币费用。
- 当前没有可诚实报告的“模型正确率”。Flash Q1/Q2 的初审口径须先裁定；GLM Q1 违反格式合同；Flash Q3 截断；Pro Q1 无已保存答案。结构/预算失败和接口未知均单列，不伪装成语义判断。复核细节见[首轮结果审计](20260923-UNIFIED-FIRST-RESULTS-AUDIT.zh-CN.md)。
- DeepSeek API 返回的只是别名 `deepseek-flash`；Pro 没有返回型号。不得把请求名直接当作已证实的底层版本，也不得与旧版本或聊天渠道合并。

## 与已经完成的 GPT 答案关系

GPT-5.6 Luna + max 与 GPT-5.6 Sol + high 的四题原答确实已经存在于 `tmp/public-brief-eval-v1/manual-runs-20260922/`；不再向用户索要或要求重发。它们来自 **v1 题包/旧协议**。该批次另有旧版语义审阅记录（Luna 严格整题 0/4；Sol 3/4 通过、1题需补充），可作为历史开发证据，但**不能拼入本次 v2 统一四题横评**：新 v2 的 Q3 已换成独立政策解释协议，且其他问题也绑定新题包摘要。v2 的 Codex Luna/Sol 干净会话包在 `tmp/public-brief-eval-v2/manual-codex-packets/`，目前尚无 v2 原答。

## 下一步边界

1. GLM Q1 的格式拒绝原因已查明；保留旧冻结和原始运行记录，不重跑同题。
2. 先统一裁定模型解释与程序报告的评分分工，再对 Flash Q1/Q2 追加可追溯的最终审阅；不能把有冲突的非盲初审直接当成最终成绩。
3. DeepSeek Flash 和 Pro 本轮已触发停止门；不重试、不续题。若未来要修改响应合同或重开配置，必须建立新版本/新冻结、记录新假设并先获明确授权。
4. v2 GPT 对话结果仍需由各自干净会话取得；v1 的已有答案与分数保留为历史，不作废，也不混算。

原始响应、冻结文件、usage 与解析结果保留在 `tmp/public-brief-eval-v2/formal-runs-20260923/`。本记录不包含密钥。
