# 新公告页面真实浏览器验收

使用独立的临时服务根目录和后台 IAB 页面，未触碰用户活动浏览器，也未调用模型。

## 结果

- 登记 synthetic official notice 为 `disabled` 候选，页面明确显示不会进入检索。
- 生成13字段模板成功；逐字段填写两项 known 原文引文，其余字段带 unknown 原因，候选校验通过。
- 启用后显示 `rebind_required`，覆盖状态保持 `not_checked`。
- 覆盖核对因临时根目录无贸易明细，保留缺失商品并隐藏研究助手链接；页面提示不会补零。

## 期间修复

发现页面 `onTemplate` 使用 `bodyFor()` 发送空 `fields` 数组，服务端将其识别成候选提交而拒绝模板请求。已改为只发送 `policy_id` 与 `doc_version`；Node 页面测试增加断言，防止再次把空字段当作提交。

## 验证

- `node --test tests/announcement_import_ui.test.cjs tests/session_flow_ui.test.cjs`：3项通过。
- 相关 Python：18项通过。
- `git diff --check`：通过。

本次是页面和边界验收，不是新公告的正式数据迁移，也不代表模型评测成绩。正式四题仍未调用模型。
