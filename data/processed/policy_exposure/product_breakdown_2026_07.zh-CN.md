# 贸易暴露分项表（程序生成，非 AI 回答）

报告截止日：2026-09-14；统计期：2026-07。不是实时数据，也不是严格历史发布版本回测。

政策标识：`us_301_review2025_tungsten_solar`；范围：登记政策整体税号范围。

## 可核查事实

- 美国全部来源消费进口额：193,774,871 美元。
- 中国原产消费进口额：10,251,657 美元。
- 中国占上述进口额：5.29%；分母不包含美国本土生产。

## 能帮助判断什么

确定登记范围当月进口规模与中国来源占比，为分商品、分来源调查提供起点；不是中国出口对美依赖率，也不是损失或因果效果。

## 程序预设的后续调查建议

1. 按登记税号分别查询：中国份额是否被合计金额掩盖？需各税号同月金额；不能由总体份额推断每个商品。
2. 查询其他原产地分布：进口集中在哪些来源？需分国别金额；原产地统计本身不能识别转运。

## 分商品：合计份额不能代替单项判断

| HTS8 | 全来源进口额（美元） | 中国原产（美元） | 中国占该项进口 | 该项占范围总进口 |
|---|---:|---:|---:|---:|
| 28046100 | 6,457,801 | 25,928 | 0.40% | 3.33% |
| 38180000 | 178,183,620 | 8,385,427 | 4.71% | 91.95% |
| 81019400 | 3,077,376 | 139,999 | 4.55% | 1.59% |
| 81019910 | 2,592,286 | 742,146 | 28.63% | 1.34% |
| 81019980 | 3,463,788 | 958,157 | 27.66% | 1.79% |

中国占比的分母是该税号进口额；最后一列的分母是整个查询范围进口额。它们不是同一个指标。
合计份额是按进口金额加权的结果，大金额商品会主导合计值；这里不据份额高低直接认定风险或替代能力。

## 政策原文候选证据

- 来源：https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ca1cf1；出版日：2024-12-31；本地段落：9

> For certain polysilicon and wafer products of China classified in the following 8-digit subheadings below, importers shall submit heading 9903.91.05 to pay the additional 50 percent rate of duty:
> (1) 2804.61.00 (Silicon containing by weight not less than 99.99 percent of silicon)
> (2) 3818.00.00 (Chemical elements doped for use in electronics, in the form of discs, wafers etc., chemical compounds doped for electronic use).

- 来源：https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ca1cf1；出版日：2024-12-31；本地段落：8

> The tariff increases take effect on January 1, 2025, with respect to goods entered for consumption, or withdrawn from warehouse for consumption, on or after 12:01 a.m. eastern standard time. See 89 FR 101682.

- 来源：https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ca1cf1；出版日：2024-12-31；本地段落：12

> For certain tungsten products of China classified in the following 8-digit subheadings below, importers shall submit heading 9903.91.11 to pay the additional 25 percent rate of duty:
> (1) 8101.94.00 (Tungsten, unwrought (including bars and rods obtained simply by sintering)
> (2) 8101.99.10 (Tungsten bars and rods (o/than those obtained simply by sintering), profiles, plates, sheets, strip and foil)
> (3) 8101.99.80 (Tungsten, articles nesoi).


日期区分：USTR 公告 2024-12-11；Federal Register 出版 2024-12-16；CBP 指引 2024-12-31；该次安排生效 2025-01-01。
日期依据：https://ustr.gov/about-us/policy-offices/press-office/press-releases/2024/december/ustr-increases-tariffs-under-section-301-tungsten-products-wafers-and-polysilicon-concluding；https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ca1cf1
81019910 的棒材范围排除仅经烧结得到的棒材；登记描述修订不改变本表按税号计算的金额。

## 证据不足，不能下结论

这些金额不能证明国内自给、产能填补缺口、没有供应短缺、第三国转运或政策效果。跨期编码连续性未审阅，不据本表推断趋势。

## 来源

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
    "path": "data/processed/policy_exposure/monthly/us_301_review2025_tungsten_solar_2026_07.csv",
    "sha256": "e283032c3bcae946cc30a45766bfd8ea53bd1a1151307b9724427a44dfd3789f"
  },
  {
    "kind": "official_census_archive",
    "month": "2026-07",
    "url": "https://www.census.gov/trade/downloads/2026/Merch/im_m/IMDB2607.ZIP",
    "file_name": "IMDB2607.ZIP",
    "sha256": "55274118bcdbf4e2e6585322069d795d3f24d1b29ef8256d73c4058c2acf6997"
  },
  {
    "kind": "local_evidence_file",
    "path": "data/processed/policy_exposure/policy_corpus.json",
    "sha256": "11f9f52730fd358eb3616bae6bbe838b386581f80d8ff68cd00e8da5b41f003b"
  }
]
```

说明：本表未调用 AI，调查方向为程序预设；事实、边界文字和引用由程序生成。结构通过不等于独立研究质量验证。
