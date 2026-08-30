# TradeShock AI 数据质量报告

- 总体状态：`pass_with_review`
- 政策事件：1 条
- 政策商品：818 条
- 贸易记录：1,600,952 条
- 月份：48 个月
- 原产国代码：230 个

## 规则结果

| 规则 | 维度 | 严重性 | 状态 | 说明 |
|---|---|---|---|---|
| POLICY-001 | 政策事件 | critical | pass | 政策事件的身份、日期、税率和来源有效。 |
| HTS-001 | 政策商品身份 | critical | pass | 政策商品数量符合预期，8 位 HTS 身份合法且唯一。 |
| HTS-002 | 官方修正 | critical | pass | 9033.00 的官方修正已经明确记录并且可以追溯。 |
| TIME-001 | 月份覆盖 | critical | pass | 贸易面板和来源清单覆盖声明的连续月份。 |
| KEY-001 | 贸易数据粒度 | critical | pass | 月份 × 原产国代码 × HTS10 业务键唯一。 |
| CODE-001 | 贸易商品代码 | critical | pass | 贸易 HTS10/HTS8 格式合法、前缀一致，并且属于政策范围。 |
| VALUE-001 | 贸易金额 | critical | pass | 贸易金额是非负整数，并且存在对应的明细记录。 |
| ORIGIN-001 | 原产国身份 | critical | pass | 每条贸易记录都有合法的 4 位 Census 原产国代码和名称。 |
| ORIGIN-002 | 原产国名称历史 | review | review | 稳定国家代码存在历史名称变化；分析必须按代码聚合。 |
| POLICY-ORIGIN-001 | 政策—原产国映射 | critical | pass | 政策目标国唯一映射到一个稳定的 Census 原产国代码。 |
| SOURCE-001 | 来源追溯 | critical | pass | 每个月只有一个合法来源指纹，并且与来源清单一致。 |
| COVERAGE-001 | 政策商品覆盖 | review | review | 没有贸易记录的政策 HTS8 需要复核，不能静默补零。 |
| DB-001 | CSV 与 MySQL 对账 | critical | pass | MySQL 的行数、金额总额和月份覆盖与 CSV 一致。 |

## 需要人工复核

- 未观察到贸易记录的政策 HTS8：86011000
- 存在历史名称变化的原产国代码：4794, 7950

## 数据采纳决定

- `aggregate_descriptive_analysis`：`allowed_with_coverage_disclosure`
- `origin_level_analysis`：`allowed_only_when_grouped_by_origin_code`
- `unobserved_hts8_product_analysis`：`blocked_pending_review`
- `causal_policy_claims`：`blocked_pending_exclusions_crosswalks_and_design_checks`

## 解释

`pass_with_review` 不是失败。它表示结构、主键、金额和来源检查通过，但仍有不能自动猜测的业务问题。分析可以按上面的采纳条件继续，相关限制必须进入后续报告和 AI 证据包。
