# 首次真实综合简报：原始报告存档

以下是GLM-4.7两次请求生成的综合任务报告，原文保留，没有事后改写模型说明。助手审阅确认本题主要数字、税率、生效条件和引用一致；主张2的“未锻造”应规范为“未锻轧”，因此仍是需编辑复核的初稿，不作为报关依据。单个开发题不是独立准确率。

运行记录：`tmp/business-brief-v1-first-20260914/C01/`。评议见 [首次综合验证](../experiments/business-brief-v1.zh-CN.md)。

---

# 贸易政策研究初稿（待审阅）

问题：请做一份综合简报：解释存档的2024年12月31日CBP通知对原产中国的81019400商品规定的额外税率、商品限定和生效条件，并列出2026年4月该税号的美国消费进口全部来源金额、中国原产金额和中国份额。政策解释附原文依据，不必确认现行全部税率。

数据版本：`91c2ed45f937392ea4473cd156ca05d3c7566e333ff9d50be90f5cbeccba4e1b`。

## 贸易规模（程序计算）

统计期：2026-04；美国消费进口；单位：美元。排序字段：none。

| HTS8 | 中国金额 | 全部来源金额 | 中国占该项进口 |
|---|---:|---:|---:|
| 81019400 | 338,657 | 2,374,813 | 14.26% |

金额排序用于安排调查，不能直接当作风险、损失或政策效果排名。

来源：
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

此表统计政策登记税号的贸易规模，不是逐笔实际征税基数。中国份额的分母是美国该税号全部来源进口，不是中国对全球出口。
金额不能直接乘公告税率当成应缴税额；具体商品限定、豁免、入境条件及后续税则尚需核查。

## 政策与统计连接

以下仅核对登记税号在本次原文中出现；商品限定和税则适用仍需逐项审阅。

| 统计HTS8 | 政策原文段落 |
|---|---|
| 81019400 | cbp63577329:p12 |

## AI解释与逐项原文核查

以下解释由模型生成，尚未完成语义审阅。原文由程序从本次检索记录展示，不由模型改写。

### 主张 1

原产中国的81019400商品需缴纳额外25%的关税，进口商应提交税目9903.91.11。

对应原文：

[cbp63577329:p12](https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ca1cf1)

公告日期：2024-12-31；抓取时间：2026-09-14T05:07:27.670234+00:00。

> For certain tungsten products of China classified in the following 8-digit subheadings below, importers shall submit heading 9903.91.11 to pay the additional 25 percent rate of duty:
> (1) 8101.94.00 (Tungsten, unwrought (including bars and rods obtained simply by sintering)
> (2) 8101.99.10 (Tungsten bars and rods (o/than those obtained simply by sintering), profiles, plates, sheets, strip and foil)
> (3) 8101.99.80 (Tungsten, articles nesoi).

### 主张 2

该商品限定为未锻造钨（包括仅通过烧结获得的条和杆）。

对应原文：

[cbp63577329:p12](https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ca1cf1)

公告日期：2024-12-31；抓取时间：2026-09-14T05:07:27.670234+00:00。

> For certain tungsten products of China classified in the following 8-digit subheadings below, importers shall submit heading 9903.91.11 to pay the additional 25 percent rate of duty:
> (1) 8101.94.00 (Tungsten, unwrought (including bars and rods obtained simply by sintering)
> (2) 8101.99.10 (Tungsten bars and rods (o/than those obtained simply by sintering), profiles, plates, sheets, strip and foil)
> (3) 8101.99.80 (Tungsten, articles nesoi).

### 主张 3

关税上调适用于2025年1月1日美国东部标准时间00:01或之后供消费入境或从仓库提取供消费的货物。

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

检索到但本次主张未引用的段落：cbp63577329:p9。未引用不代表不适用，需检查遗漏条件。
