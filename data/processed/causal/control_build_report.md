# 控制组构建报告：资格层已执行

> 状态：`blocked_before_matching`

资格审查严格只使用 2016-01 至 2018-05 的政策前数据，没有看政策后涨跌来选样本。政策范围展开、处理组金额覆盖、HTS10 覆盖、样本数量均已实际计算。

| 冻结门槛 | 实际值 | 规则 | 结果 |
|---|---:|---:|---|
| `treated_pre_value_coverage` | 98.91% | minimum 95.00% | 通过 |
| `treated_hts10_code_coverage` | 97.93% | minimum 90.00% | 通过 |
| `ambiguous_value_share` | 1.08% | maximum 1.00% | 失败 |
| `pure_treated_hs6` | 309 | minimum 100 | 通过 |
| `clean_control_hs6` | 882 | minimum 200 | 通过 |
| `official_policy_scope_expansion` | 0 | maximum 0 | 通过 |

目前有 309 个处理候选和 882 个干净对照候选；但歧义映射金额占比为 1.0822%，高于事先冻结的 1.00% 上限。因此系统停在匹配之前，没有为了得到结果而放宽标准。

`treated_mapping_exceptions.csv` 已按政策前进口金额列出需要官方资料查证的年份 × HTS10。详细资格结果见 `control_eligibility_report.md`；在该门槛解决前不生成匹配对，也不运行事件研究。
