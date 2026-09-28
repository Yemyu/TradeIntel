# Workbuddy执行输入清单

更新时间：2026-09-15。整理模型：Luna最高。状态：可开始离线实施；Workbuddy尚未启动。

## 1. 先读什么

按这个顺序读取，不要从旧聊天猜目标：

1. `docs/handoff/README.zh-CN.md`
2. `docs/handoff/ASTRA_EXECUTION_DESIGN_20260915.zh-CN.md`
3. `docs/handoff/STATUS.zh-CN.md`
4. 本文件
5. `docs/PROJECT_CONTEXT_REFERENCE.zh-CN.md`
6. `docs/handoff/COURSE_CODE_REVIEW.zh-CN.md`
7. `docs/handoff/COURSE_ADOPTION_MATRIX.zh-CN.md`

旧的 `MASTER_PLAN.zh-CN.md` 和 `WORKBUDDY_PROMPT.zh-CN.md` 只在完成上述阅读后作为历史背景；冲突时以新 Astra 方案为准。

## 2. 当前项目和基线

项目目录：`/Users/ye/dev/projects/TradeIntel`。

目标是一个贸易政策研究助手：官方政策/问题 → 政策条款与商品范围 → 真实贸易统计 → 确定性计算 → 有引用的中文解释 → 人工审阅/导出；以后能接入新公告、保存追问、检测资料更新。

必须保留：

- 现有 MySQL、贸易数据、政策原文、版本快照和确定性计算；
- HTS8/政策条件/版本绑定；
- 证据校验、审阅和导出门槛；
- 原始课程目录：`/Users/ye/Downloads/rag_agent_xdclass/`、`/Users/ye/Downloads/cloud_agent/`。

本次基线工作区有约76项已有修改/未跟踪文件。先运行并记录 `git status --short`，不得重置、清理、覆盖或擅自提交推送。不要把 fixture 结果写成真实模型成绩。

关键已有数据与代码：

- 主案例版本：`data/processed/policy_exposure/versions/91c2ed45f937392ea4473cd156ca05d3c7566e333ff9d50be90f5cbeccba4e1b/`
- 主政策/贸易报告：`data/processed/policy_exposure/`
- 证据与报告代码：`src/tradeintel_ai/evidence_linked_brief.py`、`brief_fact_catalog.py`、`business_evidence_view.py`
- 政策检索：`src/tradeintel_ai/policy_retrieval.py`
- 当前网页入口：`src/tradeintel_ai/web_app.py`、`web/`
- 离线脚本和测试：`scripts/prepare_brief_v3_offline.py`、`tests/test_evidence_linked_brief.py`、`tests/test_v3_repairs.py`、`tests/test_business_evidence_view.py`

现状不是“项目已完成”：旧G2两次开发回答因分母/范围越界已停止；v3是未采纳离线原型；本轮复现了畸形 `observation_id` 会触发 TypeError。已见输入无损压缩估算为31341→12245，但不是供应商 usage。

## 3. 课程参考副本

已复制48个源码文件到：

`vendor/course-reference/`

说明和每个文件SHA-256见：

`vendor/course-reference/README.zh-CN.md`

三类参考：

- RAG Agent：BM25/混合检索、文档/聊天/检索页面、分块与会话交互；
- CloudAgent：固定工具参数、路由和工作流状态；
- DeepResearch：有界阶段图、补查节点、状态与RAG接口。

这些文件只作阅读参考，不得直接加入运行时 import，也不得替换 TradeIntel 的数据库、政策范围和证据合同。不得复制 `.env`、密钥、node_modules、缓存、数据库、Docker编排或课程 mock 数据。Downloads 原目录不动。

吸纳方式必须在阶段日志逐项写清：独立重写、参考后改造、或仅阅读。不能把“复制文件”当作功能已接入。

## 4. 执行顺序

### E1：证据与解释准备

先做离线代码和 fixture：

1. 在所有集合/membership/set 操作前校验 `observation_id`、`policy_refs.source_id`、`hts8` 类型，畸形值返回受控错误，不抛 TypeError。
2. 补齐重复ID、零分母、并列榜首、单商品100%、零来源、错国家、错HTS、错版本、未知例外、引用缺失等反例。
3. 让完整A3程序报告和输入包含：全部观察、逐商品政策条件/例外、税率含义、事件时间/原产地、来源和局限；不能只显示关键字。
4. 新增可读紧凑业务视图及sidecar（可沿用已有 `build_view/restore` 作为基准）：`restore(view, sidecar)==原业务payload`，且关键法律条件能直接读到；ID缩写只作用于ID字段。
5. 新增fake模式实验执行器和manifest：目标估算≤8000、硬门16000、输出≤2000、超时90秒；超硬门不得删法律条件，manifest必须能识别中断目录。
6. 保留v2/v3 contract_version，不把v3未采纳输出冒充旧版本。
7. 只运行针对性离线测试，不调用模型、不要重跑旧G2，不改变旧账本/冻结输入。

E1完成后写 `docs/handoff/runs/<时间>-E1.md`，更新STATUS，并在 `RETURN_TO_ASTRA.zh-CN.md` 填R1所需事实。R1前可并行做E2/E3的离线工作。

### E2：新政策和政策RAG

- 设计官方文档版本、原URL、抓取时间、SHA、解析版本、段落/页码/偏移和publication_time；
- 候选字段必须带 known/unknown/conflict、精确quote/location、candidate_digest，人工确认绑定摘要；
- 区分 code_precision、policy_scope_match、trade_coverage；含“ex”不能冒充整个HTS8金额；
- 检索先按政策/版本/日期/status/enabled过滤，再BM25/精确HTS，再补共同生效/原产地/例外条款；不允许500字符截断导致条件消失；
- 12题开发检索集达到方案中的门槛后再报告；开发题不是盲测；
- 向量库只有在BM25发生可复现语义漏项且满足新对照门槛时，才返回Astra决定。

### E3：会话、恢复和受控更新

- 持久保存session、messages、current_request、政策/数据版本、digest、revision、run_ids；
- 追问换商品/月必须重新验证范围；“上月”无已确认基准时先澄清；使用“最近已发布数据”而不是冒称实时；
- 任务状态区分等待确认、证据就绪、生成中、已保存、待审阅、已导出、失败和未知结果；
- request_id+版本+模型+prompt摘要去重，未知结果不自动重复收费；
- 刷新页面恢复已保存回答，更新失败保留旧活动版本；
- 可先用普通轮询，不要伪造模型逐字流式；
- 复用现有 ExposureVersionStore，不新建冲突发布指针。

### E4：真实有限验收（必须先回 Astra）

在R1/R2冻结模型、预算、正式题目和新公告原文前，不得运行。旧G2剩余槽禁用。真实调用、内容审阅、模型切换和最终采纳由Astra决定。

## 5. 不能做的事

- 不做/恢复自研因果匹配；
- 不为“像课程”而部署Postgres、Redis、Milvus、Neo4j或课程Docker；
- 不把通用RAG问答或云客服业务覆盖到贸易研究链；
- 不使用聊天中出现过的API key，不读取任何课程 `.env`；
- 不删除旧实验、下载原件、数据快照或用户已有修改；
- 不用测试数字宣传AI准确率，不制造完成百分比；
- 不提交、推送或公开仓库，除非用户另行明确要求。

## 6. 返回 Astra 的条件

普通代码实现不需要回来。遇到以下任一情况，保存原始证据并停止对应支路：

- 必须删除政策条件/来源才能满足输入预算；
- 发现数据、分母、税率、HTS范围或版本污染；
- 真实模型严重错误、伪造引用、未知调用状态；
- 需要改模型、实验题目/预算、数据库或核心合同；
- 课程代码要求整体替换现有链路；
- 新公告原文或参考答案尚未冻结却要求盲测。

返回时只交：决策问题、输入/结果路径、原答和usage、已尝试及影响范围、最多两个建议；等待审阅期间继续独立离线任务。


