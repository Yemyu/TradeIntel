# 报告追问开发题：价值闸门核对

日期：2026-09-26。范围：只读核对旧小麦开发答和原报告，核实待用模型的公开接口资料；不改四题冻结包，不调用模型 API。

## 旧小麦回答与报告对照

读者追问：“最新一个月回升了，那今年以来是不是一路上涨？”原报告为美国小麦及混合麦出口、2025-08 至 2026-07。模型回答“不是一路上涨”，引用 2026-02→03 减少 17,759,081 美元、2026-05→06 减少 37,229,071 美元。两处均与保存的报告逐月金额和事实目录相符；2026-06→07 增加 49,597,132 美元，也与报告摘要相符。

这条回答**事实正确、切题**，但独立增益仍未证实：原报告网页已经显示逐月柱图和金额，并在“最近出现转向”卡中写明六月下降、七月回升。回答挑出了两次下降并给出直接结论，可能节省读图时间，却没有提供图表之外的比较、机制或判断依据。本轮是已见材料的 AI 内部开发审阅，暂记“与原报告差不多”；**不是独立盲审，更不是模型正确率**。

按预先写好的门槛，当前不能据此放行 F1—F4 正式模型横评或追问页面入口。`evals/trade_followup_v1/frozen/20260926-v1/` 继续只作固定材料；`MODEL_MATRIX_TEMPLATE.json` 保持未冻结。旧未知结果、空正文和这条开发答都不重发、不改分。

下一次最小验证应先决定一个具体、原报告没有直接呈现的追问收益，并用**新的开发材料**验证，而不是在已封存的 F1—F4 上改提示刷分。一个候选是同年最新月相对峰值的差距：本报告 2026-07 为 453,063,847 美元，比 2026-04 的 504,192,091 美元低 51,128,244 美元；程序须先核对同年、连续观测及统计口径，再提供可引用事实。即使补出这条比较，仍须让未见答案的读者对照原报告评价是否真正更容易理解；不预设“补卡=AI 有价值”。若仍无增益，停止这条 AI 追问实验，现有确定性报告照常交付。

## 待用型号的只读资料核对（不是运行许可）

- OpenAI 官方列出 `gpt-6-luna` 与 `gpt-6-sol`，API 推理档均含 `high` 和 `max`；有推理的工具调用建议使用 Responses API。Codex 对话答卷与产品 API 答卷必须分开标记，不能互充。来源：[Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)、[Sol](https://developers.openai.com/api/docs/models/gpt-6-sol)、[模型指导](https://developers.openai.com/api/docs/guides/latest-model)。
- DeepSeek 官方 Chat API 当前列出 `deepseek-flash` 与 `deepseek-v4-pro`，`reasoning_effort` 支持 `none/low/high/max`。请求别名和服务端实际模型身份应分别记录，不能只凭回显推定底层快照。来源：[Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)。
- 智谱文档列出 `glm-5.3-flash`，该型号的思考配置允许 `low/high/max`；`glm-4.6v` 的思考示例不等于本项目已接通可控 high 档。当前产品设置代码只列 `glm-4.7`、`glm-4.6v`、`glm-4.5-air`，且非 DeepSeek 仅接受 `default`，不能把官方支持或旧连接测试写成产品已可选 GLM high。来源：[GLM-5.3-Flash](https://docs.z.ai/guides/vlm/glm-5.3-flash)、[Chat API](https://docs.z.ai/api-reference/llm/chat-completion)、[GLM-4.6V](https://docs.z.ai/guides/vlm/glm-4.6v)。

本阶段重新运行封存包只读复核：4 题、29 个文件摘要及重算均通过，状态仍为 `frozen_materials_execution_not_authorized`、正式模型调用数为 0。只改状态文档，未运行测试套件；未发模型 API 请求，未接 MySQL，未改冻结包或本地密钥，未提交推送。
