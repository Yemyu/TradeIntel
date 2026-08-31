# 控制组构建报告：资格层已执行

> 状态：`eligibility_gates_passed_matching_pending`

资格审查严格只使用 2016-01 至 2018-05 的政策前数据，没有看政策后涨跌来选样本。政策范围展开、处理组金额覆盖、HTS10 覆盖、样本数量均已实际计算。

| 冻结门槛 | 实际值 | 规则 | 结果 |
|---|---:|---:|---|
| `treated_pre_value_coverage` | 99.98% | minimum 95.00% | 通过 |
| `treated_hts10_code_coverage` | 99.86% | minimum 90.00% | 通过 |
| `ambiguous_value_share` | 0.01% | maximum 1.00% | 通过 |
| `pure_treated_hs6` | 315 | minimum 100 | 通过 |
| `clean_control_hs6` | 893 | minimum 200 | 通过 |
| `official_policy_scope_expansion` | 0 | maximum 0 | 通过 |

全部资格门槛已经通过：目前有 315 个处理候选和 893 个干净对照候选；歧义映射金额占比降至 0.0109%。现在允许进入政策前特征与匹配阶段，但这仍然不是因果结果；匹配平衡和前趋势通过前不运行或发布事件研究。

`treated_mapping_exceptions.csv` 已按政策前进口金额列出仍需查证的年份 × HTS10。详细资格结果见 `control_eligibility_report.md`；剩余异常继续保留供审计，不影响本轮资格采纳。下一步生成政策前特征并执行冻结匹配。
