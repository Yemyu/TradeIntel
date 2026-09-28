# 公告字段建议：R2 首次真实调用

日期：2026-09-26。仅调用一次 DeepSeek API；没有候选启用、MySQL 写入、提交或推送。

## 执行与结果

- 新增独立执行器 `scripts/run_policy_extraction_pilot_once.py`。默认仅离线预检；真实调用需双显式参数。它复核官方正文、请求及代码摘要，逐字节校验已定 HTTP 请求体，先落盘 `provider_call_started`，再发唯一请求；保留完整原始响应，异常和未知结果不自动重试。R2/D2/H1/H2 顺序门与本地费用估算门已接入。
- R2 最终请求体 23,866 字节、SHA256 `e59b09a216f9e04e67ed0f57304d105d85b1c5ea0d6b635817bf20e9ec920e09`。实际发送 `deepseek-flash`、thinking enabled、reasoning high、`max_tokens=4096`、JSON output；没有增加 temperature。服务返回的 model 是 `deepseek-flash`。
- 首次响应 `finish_reason=length`；`content` 长度 0。用量：输入 4,705 tokens，输出 4,096 tokens，其中 reasoning 4,096 tokens。即输出额度全用于推理，没有最终 JSON；**无可评分字段、无模型准确率结论**。
- 原始响应 SHA256 `9f7b3e477c458d8288eaad5ba8cb481f999913a7d4b312941c1bd40703df67f7`，保存在 `.local/experiments/policy-extraction-v1/r2.response.json`；账本为 `r2.json`，状态 `invalid_answer`。原始模型思考仅在受保护本地文件，公开报告不复述。按事先登记的峰时单价估算本次约 **$0.0063267**；以服务商实际账单为准。
- 运行后离线复查账本仍为 `invalid_answer`；D2 前置门要求 R2 有合同有效且语义复核通过的首答，因此本轮不调用 D2/H1/H2，不重发 R2。

## 判断与后续设计边界

这是**输出预算/推理模式组合不适配**的证据，不是政策抽取正确或错误的证据，也不能据此给 DeepSeek Flash 的语义能力打分。不能把 `max_tokens` 原样增加后覆盖同一 R2 账本：首答已消耗一次机会且本版协议明定每题一次。若继续研究，应先另立有版本号的小规模实验，明确选“关闭 thinking 以保留 JSON 输出”还是“提高输出上限但保持 thinking”，重新估算价格和停止门，保留这次失败作为原始结果；不能看结果后偷偷改验收题或把开发题冒充盲测。

## 验证

离线 `unittest` 12 项通过，包含失败先记账、异常不重试、截断原答存档、合同原有边界。未跑全仓；没有生成或启用任何政策候选。
