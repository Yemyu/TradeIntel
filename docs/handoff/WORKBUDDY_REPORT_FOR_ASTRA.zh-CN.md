# Workbuddy 阶段汇报（待Astra恢复后一并审阅）

建立：2026-09-16。背景：Astra侧额度暂缺，本阶段执行不逐项返回；按[执行方案K1—K5](WORKBUDDY_EXECUTION_PLAN_20260916.zh-CN.md)累积证据，Astra恢复后一次性汇报。期间RETURN_TO_ASTRA冻结不更新。

## 汇报口径（先读）

- 全部工作离线，0次真实模型/网络API调用。
- stub计数、开发检索集、页面fixture均为工程验收，不是盲测准确率，不是AI质量通过。
- 真实开发B/C运行、正式题、R2公告迁移均未执行——见下方"待Astra决定"。

## 执行进度

（每包完成后由执行方追加：新增能力、怎么用、验收证据路径、未完成项）

- **K1 三个边界修复：完成（2026-09-16 15:15）**
  - 公告导入路径安全：policy_id白名单+拒绝`..`/分隔符+resolve包含校验+可重入文件锁（并发导入不丢文档）。反例：`../evil`、`/abs/path`、`a/b`、`a\b`、空、65字符、`case..2026` 全拒绝；双线程并发两公告均在。
  - A3导出确认全绑定：`_program_draft_gate` 校验 report_sha256/data_version/catalog_sha256/response_kind 四项；仅改元数据也失效；AI内容即使有确认记录也指向逐项审阅。
  - evidence两种顺序：先开始再确认与先确认再开始均服务端校验摘要+绑定版本；未确认/换请求未重确认/版本被改均拒绝。
  - 补合法session版本不符路由测试（响应J验收对J2测试的批评）。
  - 证据：`tests/test_k1_boundaries.py` 22项；`runs/20260916-1515-K1.md`；全量1097项中47项与基线一致零新增回归。
- **K2 实际provider执行器+持久账本：完成（2026-09-19交接日志）**
  - 新增实际调用执行器（`provider_executor.py`+CLI）：14槽独立事件账本（append-only，旧G2不动）；实际messages验证+重新计量（>16000→blocked_budget不耗槽）；调用前先落盘started；**原答先落盘再解析**（测试spy断言顺序）；重复请求拒绝且不二次调用；超时→unknown_outcome不自动重试（人工resolved_*决定）；B/C同view仅输出合同不同（`VIEW_SYSTEM_PROMPT_FREE`）；usage原样记录（stub标记保留）；输出>2000→blocked_output_budget。
  - 真实调用双门：冻结标记`.local/experiments/frozen-model.json`+`--authorize-real-call`缺一即拒绝——本阶段标记不存在，真实路径实测拒绝。
  - 证据：`tests/test_k2_provider_executor.py` 7项；CLI演练`tmp/handoff-runs/20260916-k-package/`（真实开发包B/C stub，completed）；`runs/20260919-1935-K2-K3PARTIAL.md`。
- **K3 新公告路径第二段：完成（2026-09-19）**
  - 严格绑定目标 `doc_version`：只允许 disabled 公告提交/启用；跨公告引文、正文改动后的旧引文、缺字段、无 reason 的 unknown、重复启用均受控拒绝。
  - 启用后保存 candidate+confirmation 元数据；新增只读 `/api/announcements/coverage`，无受信任贸易查询时保持 `trade_coverage=not_checked`；新增 `/announcement-import` 页面并从首页可达。
  - 证据：`tests/test_k3_announcement_flow.py` 6项、`tests/test_k3_web_routes.py` 2项、`tests/announcement_import_ui.test.cjs` 1项；合成公告机制验收，**不是 R2 真实迁移验证**。
- **K4 受控更新解析贯通：完成（2026-09-19）**
  - 新增 `src/tradeintel_ai/announcement_parser.py`，纯离线正则/逐字引文抽取；抽不出就 unknown，不猜；过滤 9903.91.05/11 Chapter 99 申报标题。
  - 本地真实 CBP p8/p9/p12 文本验收：2025-01-01 生效；50% 对应 28046100/38180000；25% 对应 81019400/81019910/81019980；链式 parser→K3 submit→enable 全通，贸易覆盖仍 `not_checked`。
  - 证据：`tests/test_k4_announcement_parser.py` 4项（含 hash-verified fetch→save→reload→parse 链）。
- **K5 使用说明与汇报收口：完成（2026-09-19）**
  - 新增 `docs/USAGE.zh-CN.md`，说明本地启动、四个页面入口、13字段确认、覆盖/重绑定和失败边界；首页加入新公告入口。
  - 全量 discover 实测 1096 项：3 failures + 48 errors，均为既有冻结/环境问题（44 冻结守卫、3 既有失败、4 个 SciPy ABI 导入错误）；K3/K4 新增测试和页面 fixture 全部通过，未把全量结果包装成全绿。

## 待Astra决定（本阶段累积，不自行裁决）

1. 模型/端点/参数及供应商约束冻结（J包验收中Astra原定职责）；冻结标记文件 `.local/experiments/frozen-model.json` 待冻结后由Astra/用户创建。
2. 开发实验与正式四题的防泄漏规则（月份选择、输入/参考接触记录要求）。
3. R2官方公告原文与逐字段参考（新公告迁移真实验证的前提）。
4. K2执行器验收通过后，是否放行有限开发B/C真实运行（≤各1次）。
5. （如有）执行中遇到的需要架构/合同级裁决的事项。

## 已就绪可复核的材料（承接J包，保持不变）

- 紧凑协议离线链：`tmp/handoff-runs/20260916-r1-fix/real-dev-package/` → `real-dev-fake-run/`（13792含C合同；短ID适配→原catalog校验）。
- J1—J4：`tests/test_j1_j4_integration.py`（16项）、`runs/20260916-0155-J1-J4.md`。
- 基线：全量1075项中47项历史失败（44冻结+3已知）与交接前诊断一致。
