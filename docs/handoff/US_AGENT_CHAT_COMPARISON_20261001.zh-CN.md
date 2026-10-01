# 同题对话渠道诊断：两个独立会话

目标：在产品代码、数据、工具合同不变的情况下，用当前Codex对话模型替代API模型，观察其能否完成同一批真实Agent任务。不是让模型看现成报告回答问题，也不是修复项目。两会话独立生成，主会话随后统一核验。实际模型与档位由用户最后确认；运行时无法核实时记录pending_user_confirmation，不能靠自我介绍猜测。

## 隔离位置

- 会话一：`tmp/handoff-runs/us-agent-chat-compare-20261001/luna/`
- 会话二：`tmp/handoff-runs/us-agent-chat-compare-20261001/sol/`
- 只读数据：`tmp/handoff-runs/trade-demo-data-20260925/`
- 唯一题目输入：`docs/handoff/US_AGENT_CHAT_QUESTIONS_20261001.json`
- 唯一初始化政策来源：`tmp/handoff-runs/us-agent-retest-20261001-v5/bootstrap/runtime/.local/announcement-docs/us_301_review2025_tungsten_solar.json`

允许复制这一个已登记政策文档到各自runtime对应位置；不得复制DeepSeek会话、报告、答案、人工/AI评分或原始反馈。会话A从R01新建，其他会话同样独立；这是完整12轮对话诊断，不是v5剩余11轮续批，不能直接横排成相同API协议准确率。

生成结束前不得读：scenarios.json（含金标）、v4/v5 results/reference、各模型旧成绩、实测总结、另一会话答案。只读问题JSON、生产SYSTEM_PROMPT/TOOL_SCHEMAS和实现接口。不得联网搜索，不加载任何API配置/密钥，不调用外部API，不把本机CLI/Codex发起另一模型调用。只用当前对话里的模型作决策。

## 执行方式：真实程序执行工具，对话模型提供决策

复用`src/tradeintel_ai/trade_agent.py`的TradeResearchAgent与`agent.py`的ModelResponse/ModelToolCall。只在自己的结果目录写最小文件队列桥接器：ChatModel.complete将生产messages与tools原样保存为请求，等待当前Codex会话保存一次响应，再返回ModelResponse；后台驱动实际agent.turn。桥接器不预填决策、不注入候选/正确税号/答案，不修改system，不人工代替生产工具。保留实际audit_callback反馈、read_public_session与报告落盘。

每次收到请求：仅根据该请求messages/tools作一次决策，原样保存`{"text":"...","tool_calls":[{"call_id":"...","name":"...","arguments":{...}}]}`；随后让真实Agent执行反馈。每个请求只能一个原始答案，不润色、不改参、不重写已有文件，不提前读取下一题答案。不得绕过query/finish安全门；不能手动写报告替代Agent。若桥接器无法真实接入，记录未完成并停止，不退化成自由文本答案冒充完整Agent验收。

生产限制：today=2026-10-01，每题最多6次complete、12个工具；最多48次对话决策请求，响应长度不超过8192 token时无法精确计数须明确无法证明，不能编造API usage/费用。90秒API超时不适用于文件队列等待；记录渠道差异。2小时墙钟上限，不为慢升级，不重试模型答案。bridge smoke可用明确标记的固定假响应测试接口，不计正式成绩；正式答案只能由当前模型依据动态请求生成。

同session内按题序自然继承；新session从空状态开始。requires前置正常题未completed时，依赖题记not_run_prerequisite，不能手填前置结果解锁。R06若生产预检查0响应，保留程序来源，模型分母不计。问题、代码、数据与初始化政策SHA在首题前存manifest；运行后核对未改。禁止修改产品/src、评测脚本、题目、冻结、原始数据、别的结果，禁止安装全局依赖/提交/推送。用现有项目.venv与PYTHONPATH=src:.。

## 保存与交回

各自目录保存bridge源码、manifest.json、requests/、responses/、tool-feedback/、runtime/、逐题result.json和REPORT.zh-CN.md；关键文件保存SHA、开始结束时间。metadata写channel=codex_chat_diagnostic、api_calls=0，model/reasoning按可靠用户确认，否则pending；不得填虚构API响应计数/token/费用。保存公开输出与实际报告ID，失败和跳过原样保留。

全部答案封存前不跑评分器；封存后可检查结构/回放与文件摘要，但不要自评准确率或读金标修答案。交回主会话做统一独立数值/原始决策审阅，不能把模型自己写“通过”当验收。完成后只汇报执行/失败/跳过数量、manifest和REPORT路径及实际模型待确认项。

注意：当前模型同时拥有Codex工具和较大对话上下文，文件队列桥接也不等于供应商API传输。结果可用于定位“模型决策 vs 产品工具”的差异，但不宣称同协议盲测、API接入已验证或普遍正确率。
