# 新公告贸易统计报告：实施与 R2 页面验收

日期：2026-09-26  
状态：核心实现完成；真实公告全新导入的组合浏览器验收另列下一步。  
模型/API：0 次模型调用。  
数据库：0 次 MySQL 写入。  
Git：未提交、未推送；没有清理或覆盖既有工作区更改。

## 做成了什么

把已经启用并人工确认的公告与通用美国进口数据接到现有网页报告，不再只显示旧的固定政策案例：

- 新增服务端“准备范围”和“生成报告”入口。服务器从已启用公告读取已经确认的商品和来源国；页面提交的金额、观测状态和政策字段不作为可信输入。
- 报告默认使用最新可用月往前12个月，用户确认商品和月份后才查询。生成过程中重新核对公告候选摘要、数据版本和商品目录版本；报告保存为带摘要的独立记录，刷新时读取原快照。
- 报告展示月度已观测金额图、最近月逐商品金额、HTS10目录应有/匹配/有来源国观测数量、缺失编码、公告条件和来源链接。缺失细码不补零；有观测的金额不冒称完整政策金额；只有前后月编码集合与名称一致且覆盖完整时才显示单品变化。
- 新报告使用 `announcement-statistics-report-v1` 与 `explanation_protocol=none`。其模型解释接口在读供应商设置和发出请求之前拒绝，不能把它误路由到旧政策解释/A3合同。
- 首次浏览器检查发现政策正文把完整法条挤在主报告、数据来源链接连成一行，页首还显示了无关的旧模型连接状态。现将编码/税率、完整条件/例外/修订和逐月数据来源放入可展开区；展开后来源逐条排列；报告顶部说明这是一份无需模型的统计报告；英文视图也不再露出内部中文原因字段。

## R2 实际数据结果

使用 `astra-semantic-review-2` 中已修正、已人工确认的 R2 候选，以及隔离临时目录中的已发布数据快照。没有用早期 `migration-run-7` 候选覆盖旧记录。

- 查询期：2025-08 至 2026-07；18 个已确认的完整 HTS8 商品范围。
- 2026-07 中国来源美国消费进口的**已观测金额合计**：71,062,824 美元。
- 该月官方目录对应69条HTS10，已发布数据匹配68条，中国来源有观测67条；18项HTS8范围中16项细码完整。
- 这不是完整政策敞口、逐笔税额或政策造成的贸易变化。缺失值未补零；条件不满足时不计算18项总环比。
- 2025-08至2026-07逐月金额与前次独立 CSV 求和核对一致；图中保留缺失/不完整标识。

通过本机临时 HTTP 服务完成 prepare→report→持久化→`report-state` 恢复，并在独立浏览器页打开该报告。确认页面保留全部12个月、显示16/18完整状态、显示正确的2026-07已观测金额；刷新后从保存记录恢复；中英文切换有效；没有可用的模型解释按钮。API 冒烟中，模型 provider stub 调用计数为0。此处使用的是已经确认的 R2 记录，并非本轮重新从空白页面导入公告。

## 验证

- Python 定向回归：36 项通过，命令：
  `PYTHONPATH=src:. .venv/bin/python -m unittest tests.test_announcement_trade_bridge tests.test_k3_announcement_flow tests.test_trade_explanation tests.test_trade_explanation_http tests.test_trade_query_flow`
- Node 页面回归：`tests/trade_explanation_ui.test.cjs` 11 项通过；`tests/announcement_import_ui.test.cjs` 2 项通过。
- `announcement_statistics_report.py`、`trade_report_store.py`、`web_app.py` 编译检查通过；`live.js` 语法检查和 `git diff --check` 通过。
- 没有运行全仓测试，不能据此称全仓全部通过。

## 改动范围

- 服务：`src/tradeintel_ai/announcement_statistics_report.py`、`trade_report_store.py`、`trade_explanation.py`、`web_app.py`
- 页面：`web/announcement-import.html`、`web/design-preview/live.js`、`web/design-preview/style.css`
- 回归：`tests/trade_explanation_ui.test.cjs`
- 计划与恢复点：本文件、`ANNOUNCEMENT_STATISTICS_REPORT_DESIGN_20260926.zh-CN.md`、`STATUS.zh-CN.md`、`docs/PROJECT_CONTEXT_REFERENCE.zh-CN.md`、`PROJECT_PLAN.md`

## 尚未做

1. 没有在同一个隔离流程里从官方原文重新导入、填写引文、人工确认并启用后再生成 R2 报告；报告页本身用已确认 R2 快照通过浏览器验收，人工导入页之前用合成公告通过单独验收。
2. 没有 AI 自动发现/抓取/解析新公告，也没有在未见官方公告上测 AI 字段候选。
3. 没有调用 GPT、GLM、DeepSeek 或其他模型；没有开始 F1—F4 追问正式横评。
4. 没有运行全仓测试、独立打印到 PDF 的实机验收、新环境安装或公网部署验收。

## 下一步

若继续这条新公告路线，在隔离临时目录用一份真实官方公告走完“导入原文→核对逐字引文→人工确认并启用→确认范围→生成报告→刷新恢复”，不写用户真实公告记录、不调用模型/API。完成后再单独决定是否值得为 AI 公告字段候选建立未见材料评测。
