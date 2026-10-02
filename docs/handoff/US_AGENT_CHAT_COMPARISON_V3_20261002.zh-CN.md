# 修复后 GPT 对话对照交接

2026-10-02。用户要求给 GPT 模型另开对话的交接话术，并追加 Sol Low；允许 Luna Max、Sol Low、Sol Medium 各一组。这里只准备交接，不自动创建或发送另一个会话，不运行外部 API。此前用户同意本批 DeepSeek 10元人民币规划门，正式 permit 尚未创建，不能把 GPT 对照许可当供应商发送许可。

## 三个位置

- GPT-6 Luna Max：`tmp/handoff-runs/us-agent-chat-compare-20261002-v3/luna/`
- GPT-6.1 Sol Low：`tmp/handoff-runs/us-agent-chat-compare-20261002-v3/sol-low/`
- GPT-6.1 Sol Medium：`tmp/handoff-runs/us-agent-chat-compare-20261002-v3/sol-medium/`

目录存在且有正式记录时拒绝覆盖，不换目录偷偷重跑。型号/档位用用户实际确认；未确认记 pending_user_confirmation，不从提示词或自我介绍猜测。若用户改用其他型号，保存实际配置而非预定标签。

## 可读输入与不可读内容

只读用户问题：`docs/handoff/US_AGENT_CHAT_QUESTIONS_20261001.json`。十二轮/七会话，today 固定2026-10-01，真实运行时间另记。商品数据只读：`tmp/handoff-runs/trade-demo-data-20260925/`。

唯一初始化政策：`tmp/handoff-runs/us-agent-final-regression-20261002-v3b/runtime/.local/announcement-docs/us_301_review2025_tungsten_solar.json`，可复制这一份已确认文档到自己 runtime 同位置。不要复制该包其他文件、参考、报告、会话、审批模板或答案。

生成结束前禁止读取 scenarios.json（金标）、MODEL_SELECTION、旧测试报告/评分、另一模型答案、final-regression 包 reference/results 或其他旧模型产物。这份交接不提供预期编码或结论。允许读取生产 SYSTEM_PROMPT、TOOL_SCHEMAS 和工具接口。不得联网搜索、读密钥/API设置或外部调用。

## 执行

用当前 Codex 对话模型提供决策，真实 `TradeResearchAgent.turn` 执行工具、会话和报告。复用 ModelResponse/ModelToolCall，桥接器只在自己目录内：complete 原样保存生产 messages/tools 请求，等待当前会话写入一次响应，再返回生产接口。响应形状 `{"text":"...","tool_calls":[{"call_id":"...","name":"...","arguments":{...}}]}`。不得用脚本预填正式决策、手工生成报告、直接查 CSV 代替 Agent，或改写 system/工具合同。

旧 bridge.py/run_agent.py 只能作为接口代码参考，若需要复用由主会话另提供源码副本；不读旧运行目录找答案，不直接运行旧路径/旧硬编码政策。无法接好实际桥接时记录未完成并停，不能自由聊天替代真实 Agent 流程。

每请求保留一个原始答案，不修改已有答案或参数。前置未 completed，依赖题记 not_run_prerequisite；每 session 独立，追问按原顺序继承。R06 若程序零模型响应，注明 program_precheck，不计模型内容成绩。

上限：每用户轮6次 complete/12工具；每组48对话决策、120分钟。8192输出token无法精确测量就记录无法证明，不造 usage。文件等待不是API90秒超时，不宣称与API传输协议完全相同。smoke只能标离线固定假响应，正式运行必须全新IDs/空会话；不得把 smoke 答案并入成绩。

首题前记录代码、解释器、问题、数据 manifest、政策 SHA 与生产工具合同v3；完成后逐项核对一致。完整工具反馈 audit_callback、公开会话与报告存档保存。使用项目 .venv，PYTHONPATH=src:.；不改 src/scripts/tests/evals/docs 或原数据、冻结，不安装依赖、不提交推送。

## 交回

保存 bridge源码、manifest.json、requests/、responses/、tool-feedback/、runtime/、逐题result与REPORT.zh-CN.md，注明实际型号/推理、channel=codex_chat_diagnostic、api_calls=0、开始结束时间、失败/中断/跳过和每次决策证据。不会调用外部API并不意味着Codex额度消耗为零。

全部答案封存前不评分或读金标；结束后只检查落盘/摘要/结构，不自评准确率，不读参考修答案。主会话统一核数与决策审阅。

交回只报 completed/澄清/失败/跳过数量与manifest、REPORT绝对路径；当前模型可靠确认不齐则注明。中断后保留原文件，不自动另跑第二组。

本步结果：交接规范已准备，尚未运行GPT新组。
下一步：用户在三个新对话分别粘贴交接话术并确认实际模型；主会话执行已授权的单组DeepSeek真实API测试。
下一步模型：GPT-6 Luna Max（主会话执行）；原因：规则与验收已固定；切换：当前档位待确认，三个测试对话由用户分别选择。
