# 2026-09-22：页面入口分流与重复任务保护

## 完成内容

- 普通多期主案例：首问走 `/api/session/proposal`，确认后才启动任务和确定性证据查询。
- 新公告入口：使用 URL 中的公告身份进入服务器 `policy_binding` 确认路径，不再把公告请求送入主案例范围提案器。
- 新会话创建时清除旧页面内存中的待确认提案。
- 相同问题已有活动/已完成任务时，页面不重复创建任务；相同问题已有待确认提案时提示先确认或更换问题。
- 保留公告的所选 HTS8 列表和服务器绑定信息，确认前不执行贸易查询。

## 验证

通过：

- `tests/session_flow_ui.test.cjs`：主案例确认门、重复点击、刷新恢复、导出链接；公告绑定和所选商品；
- `tests/announcement_import_ui.test.cjs`：公告导入→提交→启用→覆盖核对入口；
- `git diff --check`。

这些是 DOM/接口夹具验收，不是实际浏览器点击证据。真实浏览器链仍需验证公告入口、主案例入口、追问和刷新恢复。

## 服务链烟测

在临时复制的数据目录上按生产端点顺序完成了一次无模型调用烟测：

`Q1 提案 → 确认 → task/start → evidence → generate → explanation/prepare → Q2 追问提案 → 确认 → evidence → generate → explanation/prepare`

结果：Q1、Q2 均返回 `ready_for_provider`；Q2 选择 `38180000`，窗口为 `2026-02` 至 `2026-07`，上下文为 `public-request-context-v1`，父任务为 `task-1`，包含 8 条程序事实摘要。该结果证明服务函数链已贯通，不替代真实浏览器验收，也不产生模型质量成绩。
