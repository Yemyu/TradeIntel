# 课程代码吸纳与重复项清单

日期：2026-09-15。原始目录只读保留：`/Users/ye/Downloads/rag_agent_xdclass/`、`/Users/ye/Downloads/cloud_agent/`。本项目目前只加入自己的边界适配代码，没有把课程目录复制进Git。

## 现在已经吸纳的内容

| 本项目位置 | 来源思路 | 作用 | 状态 |
|---|---|---|---|
| `src/tradeintel_ai/course_adapters.py` | RAG source卡片、CloudAgent固定工具参数、DeepResearch证据状态 | 将课程事件转成带政策/版本/证据约束的TradeIntel对象 | 已加入，离线测试通过 |
| `scripts/check_course_adapter_offline.py` | 三个项目的输入输出边界 | 不连API、不启服务就验证拒绝边界 | 已加入，7项通过 |
| `tests/test_course_adapter_offline.py` | 课程组件适配fixture | 防止任意SQL、跨版本缓存、空证据成功，并检查页面状态标记 | 已加入，5项通过 |

这里的“吸纳”是把通用做法用TradeIntel自己的代码重写，不是把云客服业务代码原封不动粘进来。

## 发现重复，但暂不删除

| 原有TradeIntel模块 | 看起来和课程重复的部分 | 为什么继续保留 |
|---|---|---|
| `policy_retrieval.py` | BM25/政策检索 | 它知道历史政策页、发布日期和当前项目的范围拒答；课程检索不知道HTS8和政策版本 |
| `analysis_planner.py`、`intent_*` | 任务规划、确认、能力复核 | 它们有用户确认和“不支持不执行”规则，课程planner的fallback不能替代 |
| `evidence_*`、`research_brief_v2.py` | 证据、引用、报告合同 | 这是项目的核心正确性边界，课程来源卡片只能作为输入适配 |
| `business_workflow.py`、`tools.py` | 工具调用、报告生成 | 已绑定TradeIntel的MySQL/贸易指标和审阅状态，不能换成云客服工具 |
| `web_app.py`、`web/` | 聊天/报告网页 | 已有贸易研究页面和审阅入口，课程前端只能借鉴视觉/交互，暂不覆盖 |

因此当前没有直接砍掉任何原有文件。等新入口在真实fixture上通过，再逐个把确认过的旧重复函数标为deprecated；如果新实现没有超过旧实现，就不替换。

## 明确不复制

- CloudAgent的云产品、账单、促销、返佣、FinOps及mock表。
- DeepResearch的通用网络搜索、Bocha摘要直接证据、空fallback成功和静默删除非法引用。
- RAG Agent的通用chunk聊天链路、课程自己的数据库表、OCR云服务配置和前端整套依赖。
- 三个项目各自的Docker编排和服务启动脚本；TradeIntel只按自己的数据链需要使用已有MySQL。

## 下一步替换规则

1. 先让新适配层承接一个固定的聊天/报告fixture。
2. 旧模块和新模块同时跑同一输入，比较：政策/版本是否一致、证据是否完整、报告状态是否一致。
3. 只有新模块不降低任何已有检查、并明确改善交互或流程，才替换旧入口。
4. 替换完成后再归档旧实现，不物理删除历史实验。

## 当前验收证据

- 结构化入口和自然语言 v2 已在本地 fixture 页面完成点击验收：确认前不读数据，确认后才执行，并显示固定贸易工具与数据版本。
- 审阅页已验证空表单拒绝、逐条决定保存、修订历史保留；存在“需要修改”时，审阅稿导出返回 HTTP 409。
- 详细记录见 `docs/handoff/runs/20260915-1958-course-adapter-browser.md`、`20260915-2002-natural-v2-browser.md` 和 `20260915-2016-review-export-browser.md`。
- 以上是接口/交互与门槛验收，不是真实模型质量、课程整体运行或生产部署验收。
