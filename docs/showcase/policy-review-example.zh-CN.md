# 政策报告原文核查示例（历史回答重排，不是新模型成绩）

此页复用R02已保存的真实GLM回答和检索证据，没有再次调用模型，没有修改原回答。第三项仍保留原来的时间歧义，供观察如何核查：原文12:01 a.m.对应00:01，而不是含糊的“上午12:01”。当前入口会拦截此种表达；此页不是当前入口通过报告。

来源运行：`tmp/business-repair-v1-first-20260914/R02/`。

## AI解释与逐项原文核查

以下解释由模型生成，尚未完成语义审阅。原文由程序从本次检索记录展示，不由模型改写。

### 主张 1

原产中国的38180000商品适用50%的额外关税。

对应原文：

[cbp63577329:p9](https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ca1cf1)

公告日期：2024-12-31；抓取时间：2026-09-14T05:07:27.670234+00:00。

> For certain polysilicon and wafer products of China classified in the following 8-digit subheadings below, importers shall submit heading 9903.91.05 to pay the additional 50 percent rate of duty:
> (1) 2804.61.00 (Silicon containing by weight not less than 99.99 percent of silicon)
> (2) 3818.00.00 (Chemical elements doped for use in electronics, in the form of discs, wafers etc., chemical compounds doped for electronic use).

### 主张 2

关税上调于2025年1月1日生效。

对应原文：

[cbp63577329:p8](https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ca1cf1)

公告日期：2024-12-31；抓取时间：2026-09-14T05:07:27.670234+00:00。

> The tariff increases take effect on January 1, 2025, with respect to goods entered for consumption, or withdrawn from warehouse for consumption, on or after 12:01 a.m. eastern standard time. See 89 FR 101682.

程序时刻提示：原文 `12:01 a.m.` → `00:01`（24小时制）；未转换时区、未推断日期或适用条件。

### 主张 3

生效时间针对东部标准时间上午12:01或之后供消费入境或从仓库提取供消费的货物。

对应原文：

[cbp63577329:p8](https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ca1cf1)

公告日期：2024-12-31；抓取时间：2026-09-14T05:07:27.670234+00:00。

> The tariff increases take effect on January 1, 2025, with respect to goods entered for consumption, or withdrawn from warehouse for consumption, on or after 12:01 a.m. eastern standard time. See 89 FR 101682.

程序时刻提示：原文 `12:01 a.m.` → `00:01`（24小时制）；未转换时区、未推断日期或适用条件。

## 人工核查清单（尚未勾选）

- 商品编码、商品限定和原产地是否同时匹配？
- 写的是额外税率还是综合税率？例外或排除条件有没有遗漏？
- 日期、24小时制时刻、原文时区是否一致？
- 生效判断是入境、供消费入境，还是从仓库提取供消费？不能混用。
- 引用是否支持整句话，而不仅仅提到了相同商品？

## 证据范围与未知

检索截止日：2026-09-14。这不是现行税则核验日期。

HTML段落序号不是PDF页码；当前网页的抓取副本不证明历史时点即可获得该版本。

仅解释存档政策，不确认现行综合税率；本报告未计算贸易损失、政策因果效应或未来走势。

- 仅登记CBP执行通知正文；不是现行综合税则。
- 段落索引是本地HTML提取序号，不是PDF页码；检索命中仍需核对具体主张。
- 抓取版本来自当前网页，出版日期筛选不等于历史发布版本回测。

检索到但本次主张未引用的段落：cbp63577329:p12。未引用不代表不适用，需检查遗漏条件。
