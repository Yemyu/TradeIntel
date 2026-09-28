# Workbuddy 执行方案 K1—K5（无Astra期间，2026-09-16）

设计：GLM-5.3（2026-09-16）。执行：GLM-5.3-Flash（下一会话按本文件逐包执行）。
性质：Astra侧额度暂缺，本阶段**不返回Astra、不更新RETURN_TO_ASTRA**；所有证据累积到汇报文档，Astra恢复后一次性汇报。本文依据：[Astra执行设计](ASTRA_EXECUTION_DESIGN_20260915.zh-CN.md)、[J包验收](ASTRA_J_ACCEPTANCE_20260916.zh-CN.md)、[项目计划](../../PROJECT_PLAN.md)。

## 0. 背景与当前状态（交接起点）

- 已通过：紧凑协议离线链（真实开发包13792含C合同，prepare→fake→短ID适配→原catalog校验）；F1—F9修复；J1—J4集成（生成许可锁内校验、版本绑定、候选正文保存+真跳转守卫、A3程序稿确认与AI审阅分型）。Astra已验收认可（见J包验收文件），并指出**三个待修边界**与**下一大阶段执行方任务=实际provider执行器+持久账本**。
- 未完成：三个边界修复；实际provider执行器（fake不能当真实调用执行器）；新公告导入路径第二段（候选确认→启用→覆盖→报告重绑定）；受控更新解析贯通；使用说明。
- Astra原定职责（模型/端点/参数冻结、正式题防泄漏规则、R2公告材料）**本阶段无人履行**：执行方不得自行替代这些裁决，遇到需要裁决的事项记入汇报文档"待Astra决定"节。

## 1. 铁律（每包执行前重读）

1. **0次真实模型/网络API调用**。真实调用需同时满足：用户明确指令+冻结标记文件存在——本阶段两者皆无，执行器默认拒绝真实调用（见K2设计）。
2. 不改旧冻结记录/旧G2账本/冻结哈希；不重跑已过测试冒充新进展；47项历史失败（44冻结+3已知）不得"修复"。
3. 12+2题检索集、页面、stub结果均为开发验收，**不得宣称盲测准确率或AI质量通过**。
4. 每大包完成→更新STATUS+runs日志+给用户一段中文说明（新增能做什么/怎么用/哪些未完成），不只报测试数。
5. 不提交不推送（等用户指令）；git基线 main @ a87554c，约百项工作区修改全部保留。
6. 期间**不写RETURN_TO_ASTRA**；改写 `docs/handoff/WORKBUDDY_REPORT_FOR_ASTRA.zh-CN.md`（累积汇报，含"待Astra决定"清单）。
7. 运行命令统一 `PYTHONPATH=src:. .venv/bin/python ...`；会话/实验运行数据在 `.local/`（gitignored）。

## 2. K1 三个边界修复（Astra验收明确要求，连接AI页面前完成）

### K1a 公告导入路径安全

- 问题：`_handle_announcement_import` 的 policy_id 直接拼本地路径，可被 `../`、绝对路径、分隔符注入。
- 改 `src/tradeintel_ai/web_app.py`：
  - 新增 `_announcement_store_path(root, policy_id)`：policy_id 必须匹配 `^[A-Za-z0-9_.-]{1,64}$` 且不得含 `/`、`\`、`..`；resolve 后必须仍在 `announcement-docs/` 内，否则 WebRequestError。
  - 导入读改写加锁（`fcntl` 文件锁 `<policy_id>.lock`，参考 session_store 的可重入锁实现），避免并发导入丢文档。
- 验收（新增测试，临时目录反例）：`../evil`、`/abs/path`、`a/b`、空、超长均拒绝；合法ID两次并发导入不丢文档（两线程各导入一个不同公告→两个都在）。

### K1b A3导出确认校验扩展

- 问题：导出门只比较 report_sha256；确认记录里已有 data_version/catalog_sha256，未实际校验；response kind 也未比较。
- 改 web_app：
  - 确认记录新增 `response_kind` 字段（来自 task.response.kind）。
  - 提取共用函数 `_program_draft_gate(task) -> None | str`：校验 kind==program-report-a3（否则AI门拒绝）；最新 program_draft_confirmation 的 report_sha256==sha256(markdown) **且** data_version==response.data_version **且** catalog_sha256==response.catalog_sha256 **且** response_kind==response.kind；任一不符→"程序稿确认缺失或报告已变化"。
  - 导出端点改用该函数。
- 验收：直接路由级测试（构造task后调 `_program_draft_gate`）：改正文→失效；只改 data_version/catalog/kind 元数据（正文不动）→也失效；全匹配→通过。

### K1c evidence端点两种顺序

- 问题：task/evidence 只接受 awaiting_confirmation，但 start_task 在请求已确认时产生 received——"先确认再开始"走不通。
- 改 web_app task/evidence：接受 `state in {received, awaiting_confirmation}`，且同时校验：
  - `request_digest(task.request_snapshot) == task.request_digest`（任务自身一致）
  - `session.request_digest == task.request_digest`（会话已确认同请求）
  - `session.data_version == task.data_version`（版本未被重新确认替换）
  - 任一不符→"请先确认范围"拒绝。**未确认不得放行**。
- 验收：顺序A（start未确认→确认→evidence通过）；顺序B（确认→start→evidence通过）；确认后换请求未重确认→拒绝；确认后版本变化→拒绝。

### K1d 补合法session的版本不符路由测试

- Astra指出J2的"客户端版本不符"用例缺session_id，可能在版本检查前就失败。补：先 create_session，再带合法 session_id + 错误 data_version 调 `/api/session/request` 处理函数，断言到达版本检查并拒绝（错误消息含"期望与服务器登记版本不一致"）。

**K1测试文件**：`tests/test_k1_boundaries.py`（预计12—16项）。完成后跑受影响回归（test_j1_j4_integration、session相关、node测试）。

## 3. K2 实际provider执行器与持久账本（下一大阶段核心，离线构建+stub验收）

Astra原话："依据Astra冻结协议实现实际provider执行器和持久账本（fake执行器不能当真实调用执行器）。必须实际待发送messages验证、重新计预算、必需artifact固定集合、原答先落盘再解析、未知请求不重试、B/C同view、usage原样记录、无网络provider stub验证。不可复活旧G2账本。"

### 新文件

- `src/tradeintel_ai/provider_executor.py`（库）+ `scripts/run_provider_experiment.py`（CLI）。
- 账本：`.local/experiments/provider-ledger.json`（append-only，schema `provider-ledger-v1`）：每条={run_id, at, contract(B|C), model, endpoint, request_digest, input_messages_sha256, budget{input_est, output_gate, timeout}, status(started/completed/blocked_budget/unknown_outcome/failed), usage(原样), output_dir, slots_used, remaining_slots}。总槽上限14（开发B/C各1+正式四题B/C各1+规划≤2+新公告抽取≤2），账本启动时初始化 remaining。
- 冻结标记：`.local/experiments/frozen-model.json`（{model, endpoint, params, frozen_by, frozen_at}）。**本阶段不存在**——真实调用路径因此自动拒绝。

### 执行器流程（CLI：--package --contract B|C --output [--provider-stub ...]）

1. 包验证（复用 `run_fake_experiment._verify_package`：必需文件+哈希+ready状态）。
2. **实际待发送messages验证**：重新读 messages.json 计算其 sha256 记账；C合同=包内messages原样；B合同=新函数 `view_request_free(view)`（同view同证据，仅系统提示换成自由中文回答合同，无JSON格式要求）——B/C同view仅输出合同不同。B消息同样估算预算。
3. **重新计预算**（不信任manifest数字）：估算>16000→blocked_budget（账本记blocked，不耗槽）。
4. 账本去重：同 request_digest+contract+model 已有 completed/started 记录→拒绝重复运行（防泄漏防重复收费）；槽位不足→拒绝。
5. **先落盘started**：run目录写 run-manifest.json（status=started, started_at, input hashes, api_calls=0）+ 账本 append started 条目。
6. 调用：`--provider-stub` 注入（计数/模拟超时/模拟错误/模拟超长输出）；无stub且无冻结标记→拒绝："模型未冻结，真实调用未授权"。有冻结标记+`--authorize-real-call` 才走 model_adapter 真实调用（本阶段不可达）。
7. **原答先落盘再解析**：stub/model返回→raw-response.json 原样写入（先）→再 parse（C：adapt_answer→parse_response→render_pending；B：原样+人工审阅占位）。测试用 monkeypatch 在 parse 回调中断言 raw 文件已存在。
8. 超时/网络异常→status=unknown_outcome（**不自动重试**），需人工 resolve（复用 session_store.resolve_unknown_outcome 语义或独立 resolve 子命令）。
9. usage 原样记录（stub 提供假 usage 也原样存并标注 stub）。
10. 输出>2000估算→blocked_output_budget。run-manifest 最后写完成态。

### 验收（`tests/test_k2_provider_executor.py`，全stub无网络）

- stub调用计数=1；同请求重复运行被账本拒绝；超时stub→unknown_outcome且不再调用；blocked_budget不耗槽；B/C同view（两合同run的view哈希一致、仅messages不同）；raw先于parse落盘；usage原样；无冻结标记时真实路径拒绝；账本append-only且remaining递减正确；旧G2账本未动。
- 用真实开发包 `tmp/handoff-runs/20260916-r1-fix/real-dev-package/` 做一次stub贯通演练，产物存 `tmp/handoff-runs/20260916-k-package/`。

## 4. K3 新公告导入路径第二段（候选确认→启用→覆盖→报告重绑定）

### 后端

- `src/tradeintel_ai/announcement_flow.py`：
  - `candidate_template(store, doc_version)`：从启用的公告文档生成13字段候选模板（全部 unknown+reason 占位；known 字段由人工/后续模型填写）。
  - `submit_candidates(store, fields)`：复用 `policy_candidates.build_candidates`（逐字引文校验、digest）。
  - `confirm_and_enable(root, policy_id, doc_version, candidate)`：`confirm_candidate` 通过后，`set_document_status(disabled→enabled)`；启用门槛=13字段全部显式状态（unknown须reason，conflict须已解决）；文档或字段变化→确认失效需重来。
  - `coverage_report(candidate, trade_evidence)`：复用 `build_coverage`；无贸易查询→not_checked。
  - 报告重绑定：启用后向会话层返回 `rebind_required`（旧确认范围基于旧政策，需重新确认）。
- web_app 新端点：`/api/announcements/candidates`（GET模板/POST提交）、`/api/announcements/enable`（POST确认+启用，带digest）、`/api/announcements/coverage`（GET）。
- 页面 `web/announcement-import.html`（第三条用户路径）：导入→逐字段确认表单（引文粘贴+quote校验反馈）→启用→覆盖显示→提示重新确认研究范围。

### 验收（`tests/test_k3_announcement_flow.py` + node页面测试）

- 导入的disabled公告→模板生成→人工提交13字段（含2条逐字引文）→confirm通过→enabled；quote不匹配拒绝；缺字段/无reason的unknown拒绝启用；启用后文档被改→确认失效；启用产生 rebind_required；覆盖无贸易查询=not_checked。
- **边界**：用合成测试公告验证机制；明确标注"非R2真实迁移验证"（R2材料等Astra）。

## 5. K4 受控更新解析贯通（fetch→parse→staging）

- `src/tradeintel_ai/announcement_parser.py`：CBP公告文本→段落document（复用 policy_documents.build_document）+ 确定性字段抽取（生效日期/税率/税号行，正则+逐字引文生成候选 known 字段；抽不出的留 unknown）。用现有 p8/p9/p12 真实文本做fixture。
- 打通：`fetch_source`(真实transport仅显式操作员)→`save_candidate`→`load_candidate_content`→parser→announcement-docs→K3确认链→（贸易数据侧）构造snapshot payload→`run_update_cycle` dry-run/staging（已有）。
- 验收：真实CBP文本fixture解析出正确的生效日/两税率/五税号+引文；解析失败的行留unknown不猜测；整链离线测试（注入内容，无网络）。

## 6. K5 使用说明与汇报包

- `docs/USAGE.zh-CN.md`：本地启动、两条用户路径操作步骤、更新检查页、边界说明（什么不是实时/不是AI质量通过）。
- `docs/handoff/WORKBUDDY_REPORT_FOR_ASTRA.zh-CN.md`（本阶段开始建立，每包追加）：
  - 各包证据索引（测试、产物路径、页面行为）；
  - **待Astra决定清单**：模型/端点/参数冻结、正式四题防泄漏规则、R2公告材料、是否放行有限开发B/C真实运行；
  - 汇报口径：离线就绪≠已运行；stub计数≠模型成绩。

## 7. 执行顺序与停止点

K1（半天内）→ K2（核心，优先）→ K3 → K4 → K5。K3/K4可互换；K5每包同步追加。每包完成=STATUS+runs+用户中文说明+全量回归对比基线（47项历史失败须一致）。异常停止点：需要Astra裁决的事项、破坏性操作、真实调用请求——记入汇报文档待决清单并继续其他独立包。

## 8. 当前边界重申

本阶段交付后仍是：0真实API调用；模型/题目未冻结；新公告路径为机制验证非R2迁移验证；产品为单用户本地；不提交不推送。K2执行器就绪后，真实开发B/C运行仍等Astra恢复冻结或用户显式授权。
