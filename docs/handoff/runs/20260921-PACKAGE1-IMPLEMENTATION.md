# 包1实现记录（2026-09-21）

状态：进行中，尚未宣布通过。

本轮按总体设计修复包1的实际断点：

- `/api/session/task/generate` 保存完整 `catalog` 和生成问题，后续解释不再依赖测试直接注入 response；
- explanation snapshot 绑定 `session_id/task_id`，统一 `path`/`path_sha256`，保留旧 `snapshot_path` 只作兼容别名；不同内容不会覆盖已有快照；
- 客户端解释提交拒绝自报 `channel=api`，只允许开发注入的 `chat_simulation`/`stub`；真实 API 仍需未来服务端 provider adapter；
- explanation submit 路径先原子保存原始回答，再解析；坏 JSON/字段错误保留原答并写入 failed；
- session explanation 保存增加版本计数、身份校验和原回答历史，避免旧页面副本覆盖新结果；重复 prepare 不会抹掉已有解释审阅；
- 修正 finding/followup 审阅索引按各自类型计数，已接受的 followup 不会在渲染时丢失。
- 将会话解释的逐项审阅字段校验集中到 `interpretation_review_store.validate_session_review`；旧 legacy/v2 文件审阅仍走原有 `submit` 语义，不伪造旧 packet。
- 审阅结果现在显式记录 `session-explanation-review-v1`、`review_revision` 和 `base_review_digest`；同一原答的后续审阅追加到 `review_history`，新原答会开启新的审阅链，避免覆盖旧决定。
- 新增只读 `/api/session/draft?session_id=...&task_id=...`，在确定性 A3 生成后即可下载程序草稿；它不附带未审阅 AI 内容，最终 `/api/session/export` 仍保留原有确认与复核门。
- 现有会话页仅增加一个轻量草稿链接，不改变页面布局或引入新的前端框架；最终导出链接仍只在 `exportable` 状态显示。
- `docs/USAGE.zh-CN.md` 已补充草稿接口、最终导出门和审阅历史说明。
- `reviewed → exportable` 以及直接请求 `exportable` 现在都会先经过当前报告的内容绑定门，避免审阅修订后留下“状态已可导出但实际导出被拒”的假完成状态。
- 同一任务已有 `raw_sha256` 后拒绝再次提交第二份回答；重试必须创建新任务，避免覆盖原答、失败记录或审阅历史。
- 草稿链接增加空节点兼容保护，旧页面或最小化 DOM fixture 不会因缺少新链接而中断原有状态渲染。

验证：`.venv/bin/python -m compileall` 对本轮涉及的四个 Python 模块通过；`git diff --check` 通过。根据当前执行约束，本轮未运行测试套件、未调用模型 API、未安装依赖、未提交推送。

尚未完成：真实 HTTP/handler 链从确认→evidence→generate→prepare→stub→review→export 的行为验收（包括草稿、重复回答、审阅修订和失败后导出边界）；现有网页仍主要展示 A3 程序稿，尚未接入新解释交互；旧 legacy/v2 文件 packet 与会话解释的入口仍保持隔离，尚未做统一 HTTP 分派。

下一步继续包1：补统一审阅协议分派、完成真实入口验收和报告导出边界，然后才开始包2多期确定性分析。若出现需要改变审阅数据格式或状态机的冲突，返回Astra重新裁定。
