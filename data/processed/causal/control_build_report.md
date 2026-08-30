# 控制组构建报告：等待完整贸易面板

> 状态：`mapping_built_trade_panel_pending`

官方政策暴露表、List 1 排除时间线和跨年 HTS10 → `HS6_2017` 映射已经完成。映射对 WCO `ex`、一对多和歧义关系保留标记，不强行猜测。

下一道硬门槛是重建所有原产国的 48 个月贸易面板。当前面板是 List 1-only，只能支撑已完成的描述性分析，不能直接充当控制组。面板完成后还必须通过金额覆盖、污染排除、匹配平衡和政策前趋势检查，才允许运行事件研究。

机器可读详情见 `control_build_report.json`；映射来源见 `mapping_source_manifest.json`。
