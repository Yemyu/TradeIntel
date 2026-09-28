# 公告原文税率与报告月份适用性：安全边界接线

日期：2026-09-27。执行依据：[路线裁定](../UNSEEN_NOTICE_ROUTE_DECISION_20260927.zh-CN.md)。本轮只改公告统计报告的声明与页面显示，不建立现行税率引擎，不重做五份筛选。

## 已改

- `announcement_statistics_report.py` 给新报告固定写入 `rate_evidence_scope=source_document_only`、`current_applicability_status=not_verified`；只在人工确认的原文生效日是严格 `YYYY-MM-DD` 且所选贸易月份全部更早时，标 `before_recorded_effective_month`。日期未知、不合法或与报告末月重合时返回 `not_determined`，不猜后续修订。原来的商品、月份、金额、报告存储协议未改。
- `web/design-preview/live.js` 在实际报告标题与图表之间显示独立提示，说明税率只是原公告发布时写的，不代表图表月份或今天实际适用。即使读回旧存档、缺少新增状态字段，仍显示同样的保守提示；税率汇总及细码展开都改成“公告原文记载”。若已证实所选月份都早于原文生效月份，再补“更早贸易背景，不是政策实施后结果”。打印沿用该报告区域，没有将提示排除。中英文文本均有对应版本。
- `web/announcement-import.html` 把 `latest_available_month` 正确标为“所选区间内最近可用月份”，确认范围前提示原文税率与实际适用税率的区别。超过当前 262,144 字节请求门的完整原文在页面就拒绝，不截掉附件，也不登记候选。这里仍**不支持 PDF/网址抓取**。
- 旧测试中的 10% 原文与后续 15%/7.5% 文本反例不再能在页面被写成“现行 10%”；后端对显式要求 `rate_mode=current_applicable_rate` 的请求返回 400，不暗自把原文税率替代过去。

## 验收

- `.venv/bin/python -m unittest tests.test_announcement_trade_bridge tests.test_trade_data_root tests.test_web_app`：21/21 通过。合成公告覆盖严格日期、未知/非法日期、当前税率请求拒绝、新报告保存读回；金额不变。
- `node --test tests/trade_explanation_ui.test.cjs tests/announcement_import_ui.test.cjs`：17/17 通过。覆盖旧报告缺新增字段时的保守提示、中文/英文文字、打印提示未排除、超长公告不提交也不改原文。
- `PYTHONPATH=src:. .venv/bin/python scripts/run_r2_fresh_http_qa.py`：临时目录真实 HTTP 导入→13 字段确认→18 个商品、12 个月报告→重启读回通过。2026-07 已观测金额仍为 **71,062,824 美元**；报告摘要因新增状态和说明而变化，是预期结果，不是旧记录被改写。原报告文件未动。脚本增加了新状态断言。
- 本地隔离页面浏览器目视：报告上方可见税率时间范围提示，后面仍可见图表、原文内容及来源。随后重新启动同一 R2 隔离流程，**实际点击语言按钮**，标题、提示、金额、条款标签和来源全部切成英文；此前第一次浏览器点击没有反应，隔离静态页与第二次真实报告均可切换，未复现稳定产品故障，因此没有改语言脚本。`git diff --check` 与 JS 语法检查通过。未跑全仓测试。

## 仍不成立的声明

这次只是防止误读，不证明 2019 List 4 的现行税率、政策前后变化、新公告空白导入、全 PDF 接入或 AI 自动读政策。上一轮五份筛选成绩不变。0 次模型 API，0 次 MySQL 写入，未提交或推送；工作区其他既有修改保留。

## 下一步

按 [路线裁定](../UNSEEN_NOTICE_ROUTE_DECISION_20260927.zh-CN.md) 另预登记最多五份未参与当前开发的官方材料，逐份保留选择/排除理由；已见的 R2 和上一轮五份不能重新算留出。如果找不到符合当前合同且数据时间关系有用的材料，报告支持范围或数据时效不足，不改门槛刷通过。
