# 官方政策来源取得报告

生成时间（UTC）：2026-08-30T17:40:18+00:00

## 已取得的来源

本阶段取得或核验了 17/17 个 USTR/GovInfo 官方政策文件。每份文件的 URL、SHA-256、取得状态和本地临时路径都记录在 `source_manifest.json`；`data/raw/policy/` 按仓库规则被 Git 忽略，不把大 PDF 提交到仓库。

解析结果：

- Section 301 List 1：818 个已核验 HTS8（复用上一阶段的官方修正结果）；
- Section 301 List 2：279 个 HTS8；生效日 2018-08-23；
- Section 301 List 3：5,745 个 HTS8（5,734 个主代码 + 11 个特殊代码）；生效日 2018-09-24；
- Section 232/201：保留官方范围规则或官方代码集合，但标记为需要 HTS 历史展开，不能直接当作完整 HS6 暴露表；
- List 1 排除：保存 2018-12 至 2019-12 的官方批次时间线；排除追溯生效日记录为 2018-07-06，文字描述没有擅自转换成“整条 HTS8 未处理”。

## 尚未完成的边界

Census 历史 HS 和年度/月度 concordance 仍未取得：2026-08-31 对官方静态入口的受控请求返回 HTTP 403。因而本阶段没有生成 `hts_history_mapping.csv`、`control_candidate_features.csv`、`matched_control_pairs.csv` 或 `causal_candidate_panel.csv`，也没有把现有 List 1-only 面板伪装成对照数据。

下一阶段需要在 Sol 高模型审查下选择可复核的 Census 官方支持入口，完成跨年 HTS10 → HS6_2017 映射后，才允许进入候选控制组和事件研究。
