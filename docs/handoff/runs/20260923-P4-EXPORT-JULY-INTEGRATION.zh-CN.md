# P4 首月出口数据与工作台验收（2026-09-23）

## 为什么做这一轮

用户问“最近美国大豆贸易有什么变化”，旧页面只能用固定的钨/光伏案例或进口数据回答；美国**出口**没有独立来源。此轮只处理一个真实出口月，先确认统计口径和完整数据链路，不把单月演示说成长期趋势，也不调用模型 API。

## 输入与核对

- 原始来源：美国人口普查局 [2026-07 商品出口月包](https://www.census.gov/trade/downloads/2026/Merch/ex_m/EXDB2607.ZIP)；本地 `data/raw/trade-export/EXDB2607.ZIP`，120,709,344 字节，SHA-256 `cf102c8f01f0f286ba8b364e39dcf2a187b7dd5b97532425b4e07b23a63c871d`。下载后 ZIP CRC 完整检查通过，原包保留、不入 Git。
- 按 Census [固定宽度布局](https://www.census.gov/foreign-trade/reference/products/layouts/exdb.html)读取 `EXP_DETL.TXT` 的当月金额（不取累计金额），分辨国产出口 `df=1` 与再出口 `df=2`；`COUNTRY.TXT` 唯一确认中国目的国码为 `5700`。
- 全包 1,202,671 条明细、17,494 条商品汇总。所有商品及国产/再出口分项对 `EXP_COMM.TXT` 的美元金额核对，差异 **0**；另有 733,608 条原始零值明细，存在记录的零与没有记录分别处理。
- 发布后 337,316 条商品×目的国汇总行；加工文件 SHA-256 `88e6b869a984d88707d0313c9ac6e677abf96fe160259933a2dd85488540ecc3`。出口目录版本 `3c449c885cac7c70e0638184e4d1e2ca87def2acc73daf6985581ef854914658`。全部商品保留，名称识别目前只开放已核实的大豆、玉米及用户给出的合规编码。

## 本轮实测结果

- 美国大豆 HS4 `1201` 的 2026-07 **总出口额**（FAS）为 889,379,312 美元＝国产出口 889,360,720＋再出口 18,592；向中国为 141,197,240 美元。美国玉米 HS4 `1005` 同月全部目的地总出口额为 1,637,235,741 美元。
- `/api/trade/prepare` 对“最近美国大豆出口有什么变化”返回出口方向、2026-07 至 2026-07、已确认的 Schedule B 来源；`/api/trade/report` 从出口加工文件给出上面的金额，环比字段为 `null`；浏览器实际显示“只有一个月，不能判断出口走势”。
- “最近美国大豆贸易有什么变化”先要求选进口、出口或两者；选两者时分别查询同一月的美国消费进口额 46,041,287 美元与总出口额 889,379,312 美元，不相减称贸易差额。旧钨政策案例依旧是另一条路径。
- 合成反例验证：目的国不同、无记录不同于数值0、同一原包重复发布不改版本、清单指向被改过的文件会拒绝查询、HTTP 入口与底层金额一致。

## 执行与验证

核验入口：`PYTHONPATH=src:. .venv/bin/python scripts/audit_census_export_month.py data/raw/trade-export/EXDB2607.ZIP --year 2026 --month 7`。

发布入口：`PYTHONPATH=src:. .venv/bin/python scripts/publish_census_export_month.py data/raw/trade-export/EXDB2607.ZIP --year 2026 --month 7`。同源二次发布所得摘要一致，不覆盖旧加工文件。

定向测试：`PYTHONPATH=src:. .venv/bin/python -m unittest tests.test_trade_export_integration tests.test_trade_query_flow tests.test_trade_data_repository tests.test_census_export_audit tests.test_product_scope tests.test_product_model_config tests.test_web_app -q`，36 项通过。`node --check web/design-preview/live.js`、`node --check web/design-preview/app.js` 和 `git diff --check` 通过。独立本地浏览器真实执行“提问→确认→出口报告”以及“模糊大豆贸易→方向澄清→两方向并列报告”，页面和服务金额一致。没有跑历史全量测试，因为其中冻结哈希守卫已有既存失败；本轮不改旧冻结或刷绿。

## 尚未完成与下一门

出口只有一月，距离默认最近 12 个月还差 2025-08 至 2026-06 共 11 月。按同一来源、上限、CRC、全商品对账及独立文件版本逐月处理；一个月失败不得跳过缺口继续画整年趋势。网页上保存的旧报告包含已确认版本，但当前服务只查询活动清单，跨发布版本重新计算尚未实现。MySQL 出口副本及 SQL/文件一致性未验。通用商品报告只有程序计算，`ai_status=not_run`；不把它算作完整 AI 问答验收。没有 API 调用、未提交或推送 Git。
