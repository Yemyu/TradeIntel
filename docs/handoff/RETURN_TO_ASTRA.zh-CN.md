# 返回Astra的固定审阅单

> 最新审阅：ASTRA_J_ACCEPTANCE_20260916.zh-CN.md。J包16项独立验证通过，进入真实实验准备；旧J1—J3待修叙述已过时。下一Astra任务为模型/实验协议冻结，下一执行方任务为真实provider执行器的离线验收及三项页面边界。真实调用暂未放行。

> 最新裁定见ASTRA_R1_RECHECK_20260916.zh-CN.md：认可紧凑协议离线闭环及13792预算；下一包执行J1—J4，之后返回实际生成领取/版本固定/正文保存/审阅边界证据。真实调用模型与正式题尚未冻结。以下旧审查说明与F1—F9提交保留历史，不覆盖本次裁定。

> Astra已审：见[审查与集中修复单](ASTRA_R1_REVIEW_20260915.zh-CN.md)。预算13299本身接受，R1因准备/响应闭环及核心边界缺口暂未通过。下一返回请附F1—F9完成证据、完整C请求计量、真实开发包prepare→fake及两条页面fixture记录。R2由Astra准备官方原文/参考，用户无需提供金标。下面是原提交，保留追溯。

> 最新裁定见ASTRA_R1_RECHECK_20260916.zh-CN.md：认可紧凑协议离线闭环及13792预算；下一包执行J1—J4，之后返回实际生成领取/版本固定/正文保存/审阅边界证据。真实调用模型与正式题尚未冻结。以下旧审查说明与F1—F9提交保留历史，不覆盖本次裁定。

## J集成包复核请求（2026-09-16 01:55，J1—J4完成）

J1—J4已集中实施完毕，全程离线，0次API调用。复核材料：

- **J1 生成许可**：`tests/test_j1_j4_integration.py::test_provider_stub_called_exactly_once`（4线程并发领取，provider stub计数=1）；两份旧副本仅一份领取成功；exportable后旧副本申请→TaskStateConflict。transition_task 状态检查移入锁内、以磁盘stored任务为准，旧副本不被信任。
- **J2 版本绑定**：确认时服务器解析登记活动版本并绑定session；证据/报告/导出按绑定版本构建（非活动版本走其发布副本）；`test_report_stays_on_confirmed_version_after_active_moves`（活动版切换后报告仍为确认版本且catalog一致）；客户端版本期望不匹配拒绝（服务器实测）；空/未知版本拒绝。构建后核验实际版本与catalog，不一致→任务失败+要求重新确认。
- **J3 候选正文与跳转守卫**：`test_save_then_read_back_is_byte_identical`（原文字节+元数据原子保存，重读hash完全一致；content_saved标记不冒称已保存）；hash不匹配拒绝；`OfficialRedirectHandler` 直接测跨主机/降级/超跳均在下一跳前拒绝（handler层实测，非假final_url stub）；真实final_url取自response对象。
- **J4 审阅隔离与公告导入**：transition白名单（客户端仅reviewed/exportable，实测内部状态被拒）；program_draft_confirmation 记录report_sha256/版本/操作者（实测落盘）；导出门校验当前报告hash，报告变化即失效；AI内容导出直接拒绝、必须走逐项审阅服务；`/api/announcements/import` 以disabled候选登记（幂等），第二路径其余步骤单列待做。
- **浏览器实测**（端口8899，真实数据）：全链路（确认前无执行→证据→A3→审阅→可导出→导出返回A3全文）+四个拒绝门（内部状态×2、版本不匹配）+确认记录落盘（operator=local-user）。
- **回归**：新增 `tests/test_j1_j4_integration.py` 16项；全量1075项中47项失败/错误与基线（44冻结+3已知）完全一致，零新增回归；Node 3项页面测试通过。
- **边界**：12+2题检索集与页面均为开发验收，非盲测；新公告路径仅完成导入登记一步；真实调用执行器的原答持久化与预算验收待模型冻结后按审查单执行。

## R1修复包复核请求（2026-09-16 01:05，F1—F9完成）

F1—F9已集中实施完毕并附页面接线，全程0次API调用，未改旧冻结记录。复核材料：

- **真实开发包贯通**：`tmp/handoff-runs/20260916-r1-fix/real-dev-package/`（prepare成功）→ `real-dev-fake-run/`（fake短ID回答经 adapt_answer →原catalog校验通过，status=fake_response_validated）。实际待发送请求（含完整C输出schema）估算**13792**≤16000；raw v3为31424仅诊断不复现命令在manifest.command。
- **反例结果**：`tests/test_f1_f2_closed_loop.py`（13：缺文件/改问题/改sidecar/空hash清单/中断包/输出超限/错别名/跨包别名/目录摘要错误/原文不动）；`tests/test_f3_f8_fixes.py`（26：版本变更/两版并存/旧引用/篡改拒绝/跨政策隔离/停用+opt-in/独立例外段/500字符后限定/undetermined依赖/两税号top_k=1/同政策两版/同秒会话/并发保存/重复点击/追问不直写/多月保留/换商品排除旧税号/mark_failed人工路径/重试绑定原请求）；`tests/test_f9_source_registry.py`（5：大小上限/未登记来源/候选不激活）。E2原12题+2扩展题开发验收通过（非盲测）：`tmp/handoff-runs/20260916-0015-e2-policy-search-eval/`。
- **两条页面fixture路径**（真实浏览器已贯通，本地服务端口8899）：`/session-research`（提问→确认前无执行→确认范围→真实数据证据面板（五税号实际金额/占比）→A3生成→待审阅→审阅通过→已可导出→导出端点返回A3全文；页面刷新恢复会话与状态；追问“上月”→候选请求→确认后写入）与 `/update-check`（最近检查时间随每次检查更新且与版本created_at分离、无变化不造版本）。快照/截图：`tmp/handoff-runs/20260916-r1-fix/session-fixture-snapshot.txt`、`update-check-fixture.png`。
- **回归与基线差异**：全量1059项（基线1013+新增46），47项失败/错误与 `docs/diagnostics/astra-xhigh-20260915.json` 完全一致（44冻结哈希守卫+3已知），零新增回归；Node页面测试3项+课程适配检查7项通过。
- **边界**：页面为单用户本地fixture；真实抓取默认关闭（无源时仅记录检查）；修订候选的实际激活需真实数据管线接入后验证；不称盲测、不报AI准确率。

## 历史提交（E1阶段R1事实，存档）

状态：2026-09-15 Workbuddy已完成E1离线阶段，本单为R1（E1证据包/模型与实验冻结）所需事实；R2（新公告原文/参考冻结）仍待用户提供公告后另行冻结，可与R1合并处理。等待R1期间E2（政策文档/候选/coverage/检索+12题开发集通过）与E3（会话/任务/受控更新）离线阶段也已完成（见STATUS与runs记录）。E1—E3全为离线工作，0次API调用；本单不是已通过证明。

## 执行者填写（R1）

- 阶段 / 需要决定的一句话：E1离线完成（反例/完整A3/紧凑业务视图/fake执行器）；请冻结新实验的模型、端点、参数、预算与正式四题月份，并裁定真实主案例业务视图请求估算13299（硬门16000内、目标8000未达）是否接受或需给出进一步压缩边界。
- 实际模型 / 环境 / git基线与已有修改：执行模型为Workbuddy内置GLM-5.3-Flash（非实验模型）；项目.venv Python 3.12.13；git `main @ a87554c`，约76项已有修改全部保留，本轮新增E1文件后仍未提交未推送。
- 修改文件和阶段日志路径：`src/tradeintel_ai/evidence_linked_brief.py`、`src/tradeintel_ai/brief_fact_catalog.py`、`src/tradeintel_ai/brief_business_view.py`(新)、`scripts/run_fake_experiment.py`(新)、`scripts/measure_e1_budgets.py`(新)、`tests/test_e1_hardening.py`(新)；日志 `docs/handoff/runs/20260915-2237-E1.md`。
- 原始输入/版本/目录摘要及产物路径：主案例 `us_301_review2025_tungsten_solar` 活动版本 `91c2ed45f937…e1b`；测量产物 `tmp/handoff-runs/20260915-2224-e1-budget-measurement/`（measurement.json / business-view.json / business-view-sidecar.json / program-report-A3.zh-CN.md / catalog.json）。
- 预期结果 / 实际结果 / 最小复现命令：预期E1方案第5节反例全部受控；实际104项相关测试OK、真实主案例 restore==payload 验证通过、v3原始31424→业务视图13299估算；复现 `PYTHONPATH=src:. .venv/bin/python -m unittest tests.test_e1_hardening …` 与 `PYTHONPATH=src:. .venv/bin/python scripts/measure_e1_budgets.py`。
- 已通过的验收与未通过项：通过=上述104项+Node DOM+7项课程适配检查；未通过/未达=8000估算目标（13299，剩余为事实句/条款原文/来源正文，删法律条件或语义摘要被禁止）；全量978项中47项失败/错误与交接前诊断记录完全一致（历史冻结实验哈希守卫44项+已知3项），非本轮引入。
- 是否影响法律限定、数字/分母、版本、留出资料：未删除或改写任何法律条件、数字、分母、版本绑定；正式四题未选定，未接触留出资料；fake回答仅合同验证非模型成绩。
- 实际API次数、usage、未完成请求状态：0次调用，无usage，无未完成请求；旧G2账本未触碰。
- 已尝试的修复与结果（不要重复失败方向）：畸形输入TypeError已修复；视图压缩三轮（机器字段/等价关系/ID缩写/条款与原因去重/字段引用冗余/pf.sources子集别名）31424→13299；继续压缩只能删法律文本或做语义摘要，均被禁止，故停在13299交裁定。
- 建议方案 / 替代方案 / 代价：建议①接受13299作为E1估算事实并按方案第8节冻结模型/预算/正式四题（代价：无）；替代②要求进一步压缩，则需明确允许牺牲哪类内容（代价：法律条件风险）或允许改变输出协议（需新对照协议）。
- 等待期间可继续的独立事项：E2政策检索闭环与12题开发集（离线）、E3会话持久化/任务状态/受控更新均已完成；剩余离线项为E3页面接线（证据面板/查看预览/审阅导出与存储对接）及浏览器回归。

附：原答无（本轮无模型输出）；不复制密钥或大文件，全部路径如上。
