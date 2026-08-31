# 控制组构建报告：贸易面板已完成，等待资格审查

> 状态：`all_origin_panel_built_controls_pending`

官方政策暴露表、List 1 排除时间线、跨年 HTS10 → `HS6_2017` 映射，以及 all-origin 贸易面板已经完成。面板覆盖 2016-01 至 2019-12 的 48 个月，共 245,388 条 HS6×月份记录；全来源金额映射覆盖率为 95.78%，中国金额映射覆盖率为 98.02%。

这不等于“已经有了控制组”，更不等于“已经得到关税效应”。覆盖率是全样本汇总值；冻结协议要求对 **处理组、政策前期间** 单独核验金额覆盖和 HTS10 覆盖。随后还必须排除 List 2/3、Section 232/201 等污染商品，只用政策前特征匹配，检查平衡和前趋势。

因此暂不生成 `control_candidate_features.csv`、`matched_control_pairs.csv` 或 `causal_candidate_panel.csv`，也不运行事件研究。

机器可读详情见 `control_build_report.json`；面板来源和逐月哈希见 `causal_trade_panel_manifest.json`。
