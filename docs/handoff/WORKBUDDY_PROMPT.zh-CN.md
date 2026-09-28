# 可直接复制给Workbuddy

请接手本机项目 `/Users/ye/dev/projects/TradeIntel`，按已经完成的 Astra 设计连续执行，不要重新规划目标，也不要从旧聊天恢复任务。

## 先读固定入口

依次完整阅读：

1. `docs/handoff/README.zh-CN.md`
2. `docs/handoff/ASTRA_EXECUTION_DESIGN_20260915.zh-CN.md`
3. `docs/handoff/STATUS.zh-CN.md`
4. `docs/handoff/WORKBUDDY_INPUTS.zh-CN.md`
5. `docs/PROJECT_CONTEXT_REFERENCE.zh-CN.md`
6. `docs/handoff/COURSE_CODE_REVIEW.zh-CN.md`
7. `docs/handoff/COURSE_ADOPTION_MATRIX.zh-CN.md`

新 Astra 方案优先于旧 `MASTER_PLAN.zh-CN.md`、旧S1提示词和历史聊天。读取后先记录 `git status --short`，保留当前约76项已有修改，不重置、不清理、不覆盖、不擅自提交或推送。

## 产品目标

TradeIntel 是贸易政策研究助手，不是通用聊天机器人：

官方政策或研究问题 → 条款和商品范围 → 真实贸易数据 → 确定性计算 → 有引用的中文解释 → 人工审阅/导出；后续支持新公告、追问、会话恢复和受控更新。

现有 MySQL、数据快照、HTS8/政策条件/版本绑定、证据合同、审阅和导出必须保留。自研因果匹配已取消，不要恢复。不要用课程 mock 数据替换真实数据，也不要把“fixture通过”写成真实模型成绩。

## 课程源码怎么用

`vendor/course-reference/README.zh-CN.md` 是已选48个源码文件的索引和哈希。它们只供参考：

- RAG Agent：参考 BM25/混合检索、文档/聊天/检索界面；
- CloudAgent：参考固定工具参数、路由和状态；
- DeepResearch：参考有界阶段图、补查和状态保存。

不要把这些文件直接加入运行时 import，不复制 `.env`、密钥、node_modules、缓存、数据库、Docker或课程 mock。原始 Downloads 目录保持不变。阶段日志逐项记录“独立重写／参考改造／仅阅读”。

## 执行要求

先连续完成 E1，之后在等待审阅时继续 E2、E3 的离线工作；不要每改一个文件就停下来汇报。

### E1

- 修复证据校验：所有 set/membership 前先校验 observation_id、source_id、HTS8 类型；畸形输入返回受控错误。
- 补齐零分母、并列、单品100%、零来源、错国家、错HTS、错版本、未知例外、引用缺失和重复ID反例。
- 让完整A3程序报告和业务输入含全部观察、逐商品政策条件/例外、税率含义、时间/原产地、来源和局限。
- 实现可读紧凑业务视图及sidecar，保证 `restore(view, sidecar)==原业务payload`，ID缩写不能改写政策原文。
- 加入fake实验执行器和manifest：目标估算≤8000、硬门16000、输出≤2000、超时90秒；超过硬门不能删法律条件。
- 保留v2/v3 contract_version；不要修改旧G2输入、账本或冻结实验。
- 本包只做离线代码和测试，不调用外部模型、不启动课程服务、不部署Docker。

### E2

实现当前政策文档版本、候选字段引文、coverage分层和政策检索闭环。过滤顺序必须是政策/版本/日期/status/enabled → 精确HTS/BM25 → 补齐共同条款/例外。不能让停用、旧版本、500字符截断内容进入报告。先用现有BM25；向量升级必须有可复现漏项和新对照，先返回Astra决定。

### E3

实现本地单用户会话/任务持久化、追问和恢复、证据面板、审阅/导出状态、受控版本更新。request_id+版本+模型+prompt摘要去重；未知结果不自动重复收费；更新失败保留旧活动版。轮询可以，不能伪造逐字模型流式。

### E4

不要自行启动真实模型实验。只有 R1/R2 冻结了模型、预算、正式题目和新公告原文后，才由 Astra 给出明确许可。旧G2剩余槽禁用。

## 文件记录和停点

每个大包结束或中断前：

- 更新 `docs/handoff/STATUS.zh-CN.md`；
- 追加 `docs/handoff/runs/<YYYYMMDD-HHMM>-E1|E2|E3|E4.md`；
- 大产物放 `tmp/handoff-runs/<唯一run-id>/`；
- 写清实际修改、验收命令、结果、API次数/usage、未完成项和下一步。

遇到以下情况停止对应支路并更新 `docs/handoff/RETURN_TO_ASTRA.zh-CN.md`：需要删证据才能过预算；数据/分母/税率/HTS/版本污染；真实模型严重错误或未知调用状态；需要改模型、预算、数据库或核心合同；新公告尚未冻结却要求盲测。普通代码问题自行修复，等待 Astra 时继续无API离线工作。

最后用中文给出一段用户能看懂的总结：这次新增了什么、怎么使用、哪些还未完成；不要只报告测试数量。
