# 已保存真实回答的离线重放报告

首次真实调用因返回分组格式被旧解析器拒绝；此页使用同一真实响应经新增格式兼容处理后离线重放，0次新增API。不是再次成功调用，也不改写首次失败成绩。原始运行：`tmp/policy-conditions-v1-first-20260914/P01/`；离线重放：`tmp/policy-conditions-v1-offline-replay-20260914/`。转换仅展开分组，记录中未触发换行转换。助手核查主要条件有据；生效表述仍需谨慎理解为2025-01-01 00:01或之后，不是每天00:01重新判断。

---

# 贸易政策研究初稿（待审阅）

问题：请结合2026年2月的28046100美国消费进口数据写综合简报：列出全部来源金额、中国金额和份额，并解释存档2024年12月31日CBP通知对原产中国该商品的具体成分限定、额外税率和生效条件，提供原文依据。

数据版本：`91c2ed45f937392ea4473cd156ca05d3c7566e333ff9d50be90f5cbeccba4e1b`。

## 贸易规模（程序计算）

统计期：2026-02；美国消费进口；单位：美元。排序字段：none。

| HTS8 | 中国金额 | 全部来源金额 | 中国占该项进口 |
|---|---:|---:|---:|
| 28046100 | 100,452 | 7,578,049 | 1.33% |

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
| 28046100 | cbp63577329:p9 |

登记商品中文描述（程序读取，仍需与原文核对）：含硅量不低于 99.99% 的硅

所问编码 28046100 的原文所在行 [cbp63577329:p9](https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ca1cf1)：

> (1) 2804.61.00 (Silicon containing by weight not less than 99.99 percent of silicon)

这是定位摘录，不包含所有上文条件；完整段落见下方核查区。

## 条件填写状态

字段与原文摘录检查不等于语义核验通过。

## AI解释与逐项原文核查

以下解释由模型生成，尚未完成语义审阅。原文由程序从本次检索记录展示，不由模型改写。

### 主张 1

28046100｜商品限定：按重量计含硅量不低于99.99%的硅

对应原文：

[cbp63577329:p9](https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ca1cf1)

公告日期：2024-12-31；抓取时间：2026-09-14T05:07:27.670234+00:00。

> For certain polysilicon and wafer products of China classified in the following 8-digit subheadings below, importers shall submit heading 9903.91.05 to pay the additional 50 percent rate of duty:
> (1) 2804.61.00 (Silicon containing by weight not less than 99.99 percent of silicon)
> (2) 3818.00.00 (Chemical elements doped for use in electronics, in the form of discs, wafers etc., chemical compounds doped for electronic use).

### 主张 2

28046100｜额外税率：需申报税目9903.91.05以缴纳50%的额外税率

对应原文：

[cbp63577329:p9](https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ca1cf1)

公告日期：2024-12-31；抓取时间：2026-09-14T05:07:27.670234+00:00。

> For certain polysilicon and wafer products of China classified in the following 8-digit subheadings below, importers shall submit heading 9903.91.05 to pay the additional 50 percent rate of duty:
> (1) 2804.61.00 (Silicon containing by weight not less than 99.99 percent of silicon)
> (2) 3818.00.00 (Chemical elements doped for use in electronics, in the form of discs, wafers etc., chemical compounds doped for electronic use).

### 主张 3

28046100｜生效条件：于2025年1月1日美东标准时间00:01起生效，适用于当日或之后供消费入境或从仓库提取供消费的货物

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
