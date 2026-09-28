# 2026-09-22 Luna：范围提案与确认链

## 目标

把自然问题的第一步从“浏览器自己拼一份完整 request”改为服务端提出并保存范围，确认时只接受服务端提案编号；追问沿用同一版本边界。

## 完成

- `src/tradeintel_ai/scope_proposal.py`
  - 读取已启用政策、登记商品卡片和已发布数据版本。
  - 生成 `analysis-request-v1`、请求摘要、查询计划预览；提案阶段不查询贸易证据。
  - 追问只能继承政策/数据版本和既有比较设置；商品只能保持或缩小，窗口变化必须来自服务端追问解析。
- `src/tradeintel_ai/session_store.py`
  - 会话新增 `scope_proposals`。
  - `save_scope_proposal` / `load_scope_proposal` 在文件锁和 revision 检查下保存并重新校验完整提案。
- `src/tradeintel_ai/web_app.py`
  - `/api/session/proposal` 要求会话 ID，服务端从当前会话派生父请求。
  - 新增 `/api/session/confirm-proposal`；客户端不再提交可编辑的完整请求。
  - v1 追问变化自动生成并保存子提案，含澄清时不自动确认。
- `web/session-research.html`
  - 首问改为提案→确认→证据；刷新可恢复最近提案。
  - 多期证据和 `temporal-report-v1` 的草稿/导出字段已接线。

## 离线验收记录

未调用模型/API。静态编译与 `git diff --check` 通过；一次手工接口烟测验证：

1. 新会话提出“最近可用登记商品……”得到 `proposal-*`，`query_executed=false`；
2. 仅提交 `proposal-*` 后绑定活动发布版本；
3. 追问“那上月呢？”得到新的子提案，窗口由服务端改为 `2026-01`—`2026-06`，再确认成功；
4. 用 request digest 冒充 proposal id 被拒绝。

没有运行测试套件，没有修改旧冻结记录，也没有提交或推送。

## 下一步

继续准备四题独立参考和冻结候选包；之后才做有限模型验收。不要把本轮离线烟测写成模型正确率。
