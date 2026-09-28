# Astra二次复核：紧凑协议离线链通过，真实调用尚未放行

日期：2026-09-16。此前F1—F9已有实质修复。本次区分协议离线链验收、页面验收和真实实验授权，避免全部重做。

## 通过的部分

对 `tmp/handoff-runs/20260916-r1-fix/real-dev-package/` 执行现有包验证，核对必需文件哈希；重新计量messages为13792；restore(view,sidecar)==business_payload(catalog)；从view生成短ID回答、adapt_answer转换、原catalog校验得到manual_review_required。认可这一离线协议链，预算在16000以内，不再追求8000。

本轮独立运行tests.test_f1_f2_closed_loop、tests.test_f3_f8_fixes、tests.test_f9_source_registry共44项，通过。全量1059/47历史失败一致是执行方报告，本轮未重新运行或独立确认全量差异。浏览器路径是执行方记录，本轮审查其后端实现，未重复宣称浏览器实测。

这些不构成真实AI效果采纳。R1中模型/参数/正式题冻结仍未完成，无新API调用。

## 下一包：四项集成收口，保留已通过部分

### J1 生成许可必须在锁内检查最新任务状态（真实调用前阻断）

直接复现：同一evidence_ready任务载入两份session；第一份transition_task到generation_started；第二份旧session也transition到generation_started，仍被接受。原因：合法性检查发生在锁外的旧task上，锁内读到stored后直接覆盖，不检查stored状态。start_task去重测试不能覆盖生成领取。

实现：在锁内读取stored，针对stored验证from/to与revision；只有一次可领取generation_started。未知结果处理也重新检查磁盘状态。冲突返回in_progress或受控状态冲突，不能再次许可调用。

验收：两旧副本、线程并发生成申请只允许一次；完成/失败状态不可被旧副本退回started；provider stub计数只能1。

### J2 会话证据与报告绑定同一版本（页面接模型前阻断）

session_brief.build_session_brief每次pin当前活动版本；web_app的task/evidence和task/generate各构建一次，没有传任务证据版本或复用证据目录。两步之间更新活动版，会生成不同于用户已确认/查看证据的报告。会话请求端点还接受客户端提供版本值，未由服务端核对。

实现：确认后由服务器解析登记版本，保存明确版本及catalog/请求摘要；证据阶段保存完整可信产物引用；生成阶段复用该产物或按固定版本重建并验证摘要。客户端版本仅为期望值，必须核对；不允许空版本暗指不断变化的活动版。

验收：证据后切换活动版，报告继续旧版或要求重新确认；报告、面板、任务、导出版本一致；未知版本拒绝。

### J3 候选原文保存及真实HTTP守卫尚未完成（新政策抓取前阻断）

save_candidate在临时目录直接调用得到NameError: tempfile未导入；即使补导入，函数未保存content，只写了摘要，fetch_source也只返回元信息，原文字节没有完整保存链。

default_transport把redirect_request赋到OpenerDirector上，不会替换urllib的HTTPRedirectHandler；默认跳转处理仍生效，visited也不能可靠表示真实最终URL。当前注入transport的测试没有覆盖这一真实实现。

实现：原文字节与元数据原子持久保存，核验content hash相同后发布候选记录；返回路径可供解析。通过真正HTTPRedirectHandler子类处理跳转并核对实际最终URL，每跳按官方来源登记策略校验、限定次数/大小/时间。不要连接真实模型即可验证。来源URL内容身份在实际抓取时核对，不因HTTPS就认定内容匹配。

验收：保存→重读字节及hash完全一致；元数据不冒称已保存正文；模拟HTTP handler层的跨主机/降级/过多跳转在发出下一跳前拒绝。不能只用返回假final_url的stub。

### J4 页面边界与审阅身份说明（产品验收项）

新增session/task/transition允许客户端直接请求reviewed/exportable；export只看该状态和有无markdown，没有调用既有细粒度审阅记录。当前可以作为A3程序稿的简化确认，但不能声称沿用原AI审阅合同，更不能未来直接接AI。

实现：明确程序稿确认与AI解释审阅两种类型。A3确认记录报告摘要/版本/操作者/决定，报告变化失效；AI生成内容导出仍必须过已有逐项审阅服务，不接受仅客户端state跳转。普通客户端不得任意设置内部生成/证据状态。

新页面仍硬编码只接受主案例，更新检查页不是“新公告导入→候选抽取→确认→数据覆盖→报告”第二条用户路径。当前可验收“主案例程序稿+检查页”，新公告路径单列待做；继续按原E2/E3方案接policy_candidates/search与上传/URL导入，不将第二条检查路径作为新公告路径完成证明。

## 后续顺序

Workbuddy按J1—J4做一个集成包，原通过的44项仅按改动范围回归。保存provider stub计数、活动版切换反例、原文重读、A3/AI导出门差异和网页实际行为；结果写runs与RETURN_TO_ASTRA。

Astra随后集中冻结真实开发实验的模型/端点/参数和题目；无需因新公告路径未结束阻止已独立就绪的解释开发实验，但须J1/J2及实际调用执行器的预算/原答持久化验收完成。R2用于新公告迁移验收，原文和参考由Astra选择准备，用户不承担标注。

本轮仅审查/方案和记录更新，没有改生产源码，没有API调用，没有提交推送。
