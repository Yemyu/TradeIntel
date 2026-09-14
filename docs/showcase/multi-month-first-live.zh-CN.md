# 首次真实多月简报（保留原结果）

GLM-4.7真实调用生成，未事后修改正文。助手审阅：四个月金额、份额和任务路由正确；政策部分有范围遗漏（未解释81019980的其他未列名制品限定），且额外涉及未询问的硅片条款，所以整题未完全通过。后续代码新增了商品中文登记名与原文定位行，但没有用新代码重跑本题；此页仍是原始结果。

记录：`tmp/business-series-v1-first-20260914/S01/`。详见 [阶段审阅](../experiments/business-series-v1.zh-CN.md)。

---

# 贸易政策研究初稿（待审阅）

问题：请做多月综合简报：列出2026-01至2026-04的81019980逐月美国消费进口全部来源金额、中国原产金额和份额，同时解释存档的2024年12月31日CBP通知中的商品范围、额外税率及生效条件，并附原文。

数据版本：`91c2ed45f937392ea4473cd156ca05d3c7566e333ff9d50be90f5cbeccba4e1b`。

## 逐月贸易规模（程序计算）

统计期：2026-01 至 2026-04；美国消费进口；名义美元，未季节调整。

| 月份 | HTS8 | 中国金额 | 全部来源金额 | 中国占该项进口 |
|---|---|---:|---:|---:|
| 2026-01 | 81019980 | 1,232,234 | 3,254,426 | 37.86% |
| 2026-02 | 81019980 | 1,068,898 | 2,321,608 | 46.04% |
| 2026-03 | 81019980 | 1,527,001 | 3,935,770 | 38.80% |
| 2026-04 | 81019980 | 984,639 | 2,807,454 | 35.07% |

## 跨期比较的依据与限制

逐月列示不自动计算首末变化；不代表编码定义已连续核查。


月度名义金额变化可能包含价格、数量、季节与其他因素；没有数量或价格证据，不能把它写成需求变化或政策效果。
本表不是走势预测；中国份额不是中国出口对美依赖率；贸易规模不是实际税基或损失。

## 数据出处

```json
[
  {
    "kind": "local_evidence_file",
    "path": "data/processed/policy/section301_review2025_event.csv",
    "sha256": "fac5b4e637ee83e7529584d3332e6289afabb5d2d08a35fafd86d4a09844be52",
    "url": "https://www.federalregister.gov/documents/2024/12/16/2024-29462/notice-of-modification-chinas-acts-policies-and-practices-related-to-technology-transfer"
  },
  {
    "kind": "local_evidence_file",
    "path": "data/processed/policy/section301_review2025_products.csv",
    "sha256": "623e9abd3b170f324b3d557aceab28d5505e4784dae5dbed6b179b06ecd9a6f6",
    "url": "https://www.federalregister.gov/documents/2024/12/16/2024-29462/notice-of-modification-chinas-acts-policies-and-practices-related-to-technology-transfer"
  },
  {
    "kind": "local_evidence_file",
    "path": "data/processed/policy_exposure/manifest.json",
    "sha256": "4288baedc40dac3e2498cd275397d0135b13e11fb1bf9ff4d70606237a5cb02d"
  },
  {
    "kind": "local_evidence_file",
    "path": "data/processed/policy_exposure/policy_metadata_corrections.json",
    "sha256": "bd55927eaf16e1aa04abac9b4d0f1c71acc9a2449b491cbaa89f063a4d1cdce0"
  },
  {
    "kind": "local_evidence_file",
    "path": "data/processed/policy_exposure/monthly/us_301_review2025_tungsten_solar_2026_01.csv",
    "sha256": "32d8295cbf68c8ee4e7d9297461b62f37b2db0cbafcb48b6f74c2ebfedd871f6"
  },
  {
    "kind": "official_census_archive",
    "month": "2026-01",
    "url": "https://www.census.gov/trade/downloads/2026/Merch/im_m/IMDB2601.ZIP",
    "file_name": "IMDB2601.ZIP",
    "sha256": "f45ba6917e0aa4269146053927b3a764b796ae3f80c4d3ea6881fac863feeac4"
  },
  {
    "kind": "local_evidence_file",
    "path": "data/processed/policy_exposure/monthly/us_301_review2025_tungsten_solar_2026_02.csv",
    "sha256": "4dfb20d23775147f1333ce68adf82c61cd90e354b0d4a5b8c59bf78c83d236d9"
  },
  {
    "kind": "official_census_archive",
    "month": "2026-02",
    "url": "https://www.census.gov/trade/downloads/2026/Merch/im_m/IMDB2602.ZIP",
    "file_name": "IMDB2602.ZIP",
    "sha256": "1c43d47e7c34003be8dd24ecbe9ee81d3761c6ab7bd6d5a36ac81db8fad97f4e"
  },
  {
    "kind": "local_evidence_file",
    "path": "data/processed/policy_exposure/monthly/us_301_review2025_tungsten_solar_2026_03.csv",
    "sha256": "fac6f03f4993ba7fbf9f7f5ac2319c7656bcfdee82fa50cc2a4b531e0ec69880"
  },
  {
    "kind": "official_census_archive",
    "month": "2026-03",
    "url": "https://www.census.gov/trade/downloads/2026/Merch/im_m/IMDB2603.ZIP",
    "file_name": "IMDB2603.ZIP",
    "sha256": "a263062b3b95ba083475393663c71adbab2ae973311b69ffd5570011f040a92e"
  },
  {
    "kind": "local_evidence_file",
    "path": "data/processed/policy_exposure/monthly/us_301_review2025_tungsten_solar_2026_04.csv",
    "sha256": "e5a4de130c2331c7e87d13f1a2fefa3cf03f01a2869c4fe37e284b0cade1e613"
  },
  {
    "kind": "official_census_archive",
    "month": "2026-04",
    "url": "https://www.census.gov/trade/downloads/2026/Merch/im_m/IMDB2604.ZIP",
    "file_name": "IMDB2604.ZIP",
    "sha256": "7f2075efb381a5229e8ffc7e1e8a797ca886af5841a84f09cbb4250091b566fe"
  },
  {
    "kind": "local_evidence_file",
    "path": "data/processed/policy_exposure/policy_corpus.json",
    "sha256": "11f9f52730fd358eb3616bae6bbe838b386581f80d8ff68cd00e8da5b41f003b"
  }
]
```

## 政策与统计连接

以下仅核对登记税号在本次原文中出现；商品限定和税则适用仍需逐项审阅。

| 统计HTS8 | 政策原文段落 |
|---|---|
| 81019980 | cbp63577329:p12 |

## AI解释与逐项原文核查

以下解释由模型生成，尚未完成语义审阅。原文由程序从本次检索记录展示，不由模型改写。

### 主张 1

关税上调适用于2025年1月1日或之后东部标准时间00:01起进入消费或从仓库提取供消费的货物。

对应原文：

[cbp63577329:p8](https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ca1cf1)

公告日期：2024-12-31；抓取时间：2026-09-14T05:07:27.670234+00:00。

> The tariff increases take effect on January 1, 2025, with respect to goods entered for consumption, or withdrawn from warehouse for consumption, on or after 12:01 a.m. eastern standard time. See 89 FR 101682.

程序时刻提示：原文 `12:01 a.m.` → `00:01`（24小时制）；未转换时区、未推断日期或适用条件。

### 主张 2

对于归类于2804.61.00和3818.00.00的中国产多晶硅和晶圆产品，进口商需提交9903.91.05标题以支付50%的额外关税。

对应原文：

[cbp63577329:p9](https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ca1cf1)

公告日期：2024-12-31；抓取时间：2026-09-14T05:07:27.670234+00:00。

> For certain polysilicon and wafer products of China classified in the following 8-digit subheadings below, importers shall submit heading 9903.91.05 to pay the additional 50 percent rate of duty:
> (1) 2804.61.00 (Silicon containing by weight not less than 99.99 percent of silicon)
> (2) 3818.00.00 (Chemical elements doped for use in electronics, in the form of discs, wafers etc., chemical compounds doped for electronic use).

### 主张 3

对于归类于8101.94.00、8101.99.10和8101.99.80的中国产钨产品，进口商需提交9903.91.11标题以支付25%的额外关税。

对应原文：

[cbp63577329:p12](https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ca1cf1)

公告日期：2024-12-31；抓取时间：2026-09-14T05:07:27.670234+00:00。

> For certain tungsten products of China classified in the following 8-digit subheadings below, importers shall submit heading 9903.91.11 to pay the additional 25 percent rate of duty:
> (1) 8101.94.00 (Tungsten, unwrought (including bars and rods obtained simply by sintering)
> (2) 8101.99.10 (Tungsten bars and rods (o/than those obtained simply by sintering), profiles, plates, sheets, strip and foil)
> (3) 8101.99.80 (Tungsten, articles nesoi).

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
