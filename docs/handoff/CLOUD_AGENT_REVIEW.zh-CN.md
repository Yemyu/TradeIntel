# CloudAgent / DeepResearch 补充审查

2026-09-15，Astra静态审查；未运行服务、SQL、测试脚本或API。用户要求检查Downloads的其他课程项目，不启动交接。

## 必须保留的项目事实

用户已经安装MySQL。TradeIntel现有MySQL和贸易数据继续保留，不重复安装、不迁移成课程的业务库、不执行课程初始化SQL。先前“不用装MySQL”仅指不用额外照教程安装一套，不是取消现有MySQL。课程改造资料已由用户提供，后续专注技术复用，不重复索要无关资料。

## 找到的两个项目

- `/Users/ye/Downloads/cloud_agent/cloud_agent`：云客服。
- `/Users/ye/Downloads/cloud_agent/deep_research`：深度研究流程。

与原RAG工作台一起，三个参考方向互补；不等于要把三套后端合并运行。

### CloudAgent：适合参考受控数据库工具与路由

`agent/core/workflow/graph_manager.py`确实组装了Orchestrator、Product、Billing、Promotion、Recommendation、FinOps。多数分支为路由到一个专用Agent后结束；成本优化分支是Billing接FinOps。不是每次所有Agent共同讨论。

`agent/mcp_servers/cloud_platform_server.py`包含参数化MySQL订单/实例/监控查询。这种“模型选工具、代码写固定查询”的结构值得借鉴，映射为我们已有的贸易指标工具；不导入云订单表、不让模型任意写SQL、不要求为了工具封装引入MCP进程。现有受控查询若已满足要求，只补缺口。

当前实现缺口：

- orchestrator提示提到deep_research_agent，但实际图和返回分支没有它；选型路由规则也有冲突。不能只修改提示词就声称新增路由可用。
- `build_graph()`直接compile，没有checkpoint参数；应用另存对话记忆，不等于中间业务任务可断点恢复。
- `app/service/chat_service.py`先等待完整答案，再每5字符发送一次：是分段显示，不是模型生成过程中实时输出。
- `app/infra/cache.py`缓存按问句/用户等检索，未绑定我们的政策、月份、数据版本。贸易报告不能照搬语义相近就复用旧答案的逻辑。
- `UserIdInjector`在取不到身份时继续调用；不能当作已经完整验证的身份安全机制。
- `agent/database/init_mock_data.sql`含TRUNCATE课程表；不执行到用户现有库。测试目录含外部数据库/模型演示脚本，不能直接当离线测试批量运行。

### DeepResearch：与研究助手的流程最接近

`app/mult_agents/graph.py`存在意图、规划、网络搜索、本地RAG、证据整理、分析、补查、报告节点，且接收checkpointer。有补查循环与轮数终止条件；这是可借鉴的流程设计，不是量化质量证明。

`nodes.py`已有检索轨迹、证据池、来源ID、报告参考列表。`tools.py`含博查搜索与本地知识库工具。联网记录主要来自搜索返回的summary，不能当作已经下载并核验的官方政策全文。对我们的新政策流程，仍须获取官方正文、日期与商品字段，经过候选确认再发布。

需要替换的处理：

- `_validate_and_fix_citations`对匹配格式的非法引用直接移除，但保留原断言；我们必须标为待修或拒绝，不能删除引用后当成功报告。
- JSON解析失败可走fallback；后定义的`_fallback_analysis`默认为无需继续研究、空findings。不得让“解析失败”表现为“证据足够完成”。
- source_id存在性检查不等于原文支持结论；仍保留TradeShock的事实、分母、商品、版本约束。
- 搜索失败返回空列表，需要区分服务失败与确实没有资料；其日志打印密钥前缀的行为不复用。

## 方案增补

优先级按模块而非项目名：RAG工作台的交互；CloudAgent的固定数据库工具接口；DeepResearch的研究流程/来源轨迹。保留TradeShock现有MySQL、数据计算、版本/审阅/导出。不要复制云营销、海报、返佣、实例运维等业务。

最终主流程：聊天识别需求 → 政策检索/必要时发现官方新公告 → 确认商品与时间 → 受控工具查现有贸易数据 → 程序计算 → AI解释 → 验证与人工审阅 → 导出。补查有次数、费用与时间边界；失败明确显示，不靠更多角色掩盖。

下一执行包（尚未启动）：Luna最高先做离线接口/fixture验证，不装三整套服务。沿用COURSE_CODE_REVIEW中的边界测试，新增路由枚举、缓存跨版本不得命中、非法引用不能静默消失、解析失败不得标完成。接入方案需要重构原有核心契约或恢复状态时回Astra。S1/S2原质量门槛不取消，也不重跑旧G2。
