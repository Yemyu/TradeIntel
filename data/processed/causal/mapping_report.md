# HTS10 → HS6_2017 映射报告

状态：`mapping_built_with_conservative_ambiguity_flags`

本次生成 76,304 条年度 HTS10 映射记录。2016 年跨 HS 版本变化使用 WCO Table II；WCO 标有 `ex` 或一对多关系的记录保留候选代码但不强行填入单个 `HS6_2017`。2017–2019 年使用 2017 HS6 前缀，并由 Census 年度 concordance 验证代码和 NAICS。

映射状态计数：

```text
{
  "same_hs6_prefix": 74862,
  "wco_exact_single": 10,
  "wco_partial_or_ambiguous": 1432
}
```

历史有效性计数：

```text
{
  "not_in_historical_file": 22,
  "not_valid_in_year": 30,
  "valid": 76252
}
```

这张表只是商品代码层输入，不代表控制组已经通过金额覆盖、匹配平衡和政策前趋势门槛。完整候选面板仍需读取所有原始月份贸易数据，并在 Sol 审查后才可生成。
