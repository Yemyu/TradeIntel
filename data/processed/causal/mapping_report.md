# HTS10 → HS6_2017 映射报告

状态：`mapping_built_with_conservative_ambiguity_flags`

本次生成 76,691 条年度 HTS10 映射记录。2016 年跨 HS 版本变化使用 WCO Table II；WCO 标有 `ex` 或一对多关系时，只有同一个 Census HTS10 在 2016/2017 年度文件中同时存在、完整描述和计量单位精确一致、两年历史有效且原六位前缀属于 WCO 明示候选，才标记为 `census_exact_hts10_continuity`；其余仍留空。2017–2019 年优先使用 Census 年度 concordance；对历史文件确认当年有效、但不在年度快照中的代码，只有在其六位前缀已存在于 2017 锚点时才标记为 `history_only_same_hs6_prefix`。新出现的六位 HS6 仍保持空映射。

映射状态计数：

```text
{
  "census_exact_hts10_continuity": 753,
  "history_only_same_hs6_prefix": 386,
  "no_target_hs6": 1,
  "same_hs6_prefix": 74862,
  "wco_exact_single": 10,
  "wco_partial_or_ambiguous": 679
}
```

历史有效性计数：

```text
{
  "not_in_historical_file": 22,
  "not_valid_in_year": 30,
  "valid": 76639
}
```

这张表只是商品代码层输入，不代表控制组已经通过金额覆盖、匹配平衡和政策前趋势门槛。完整候选面板仍需读取所有原始月份贸易数据，并在 Sol 审查后才可生成。
