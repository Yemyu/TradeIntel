# Astra S1/S2复核与R2设计收口

执行日期：2026-09-20。模型建议Astra中；本轮是语义/架构复核与必要修复。

交付：`docs/diagnostics/ASTRA_S2_REVIEW_R2_PLAN_20260920.zh-CN.md`，包含复核证据、逐字段真实公告参考、L1—L3修改目标和验收门。

已修：`announcement_report.py`不再忽略税率含义或丢掉小数，保留未能归类的确认值；报告重验候选与覆盖内容/身份；活动及历史数据都通过`release_root`验证副本。`brief_fact_catalog.py`展示未映射税率原值/含义。两个新增测试验证篡改拒绝和税率语义/小数。

最终验证：S1/S2/K/J/provider共94项通过，evidence_linked_brief另10项通过，Node页面4项通过，git diff --check通过。未重跑全量，沿用历史全量问题记录但不称全绿。

联网读取官方材料并下载GovInfo原始HTML；真实模型API=0。首次解析13字段全unknown，结果已保存在tmp/r2-20260920/parser-first-result.json，解析器未为此公告调参。不能称R2通过。

长上下文已去除重复的历史“最新状态”，完整旧文存入`docs/PROJECT_CONTEXT_SNAPSHOT_20260920_BEFORE_R2_REVIEW.zh-CN.md`；STATUS/PROJECT_PLAN同步当前入口。没有删除历史数据、ZIP或实验，没有提交推送。

下一阶段：Luna最高按L1—L3执行；如政策层次或范围无法按已锁定合同表达，返回Astra。执行者不要重新复查全部旧阶段或增建框架；集中完成页面、覆盖版本/子集及同一真实公告迁移。验收后Astra才冻结S3模型实验。
