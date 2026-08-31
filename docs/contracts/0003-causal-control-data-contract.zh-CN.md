# 数据契约 0003：因果对照商品扩展

> 状态：资格层已执行；歧义金额门槛失败，停止在匹配之前
>
> 日期：2026-08-31

## 1. 目标

为 Section 301 List 1 建立一组在政策前可比、研究期内未被其他主要贸易措施直接处理的候选商品，从而决定事件研究是否具备最低可信条件。

这一步不是保证一定得到因果结果，而是建立一套会主动淘汰不合格对照组的流程。

## 2. 分析单位为什么改成 2017 版 HS6

当前政策按 2018 年 HTS8 定义，原始贸易记录按各月 HTS10 记录。HTS10 会随年份拆分、合并或改名，直接把字符串跨年连接会制造虚假的商品出现和消失。

主设计将每个月的 HTS10 映射到稳定的 `HS6_2017` 商品家族。Census 的历史 HS 文件作为主要映射来源，年度/月度商品 concordance 和 USITC HTS archive 用于核查有效代码和变更时间。

禁止使用商品描述的模糊文本相似度自动决定正式映射。名称相似只能帮助发现候选问题，不能进入最终分析键。

## 3. 时间窗口

| 阶段 | 月份 | 用途 |
|---|---|---|
| 干净政策前 | 2016-01 至 2018-05 | 选择对照、计算特征和检查趋势 |
| 公告/预期 | 2018-06 | 单独保留，防止提前进口污染 |
| 生效过渡 | 2018-07 | 月中生效，单独保留 |
| 主政策后 | 2018-08 至 2019-07 | 12 个完整月份 |
| 短窗口复核 | 2018-08 至 2018-12 | 降低后续事件累积影响 |

政策后的数据绝不能参与对照商品选择。

## 4. 处理组、对照组和混合组

### 处理组

政策前中国进口金额全部能够连接到原始 List 1 HTS8 的稳定 HS6 商品家族。主问题估计的是“被原始 List 1 列入”的意向处理效应（ITT），不是每个月都准确承受 25% 税率的机械效应。

实施澄清（在运行资格结果前冻结）：如果一个 HS6 的政策前中国进口全部来自 List 1，但同一 HS6 代码范围还覆盖 List 2、List 3、Section 232 或 Section 201，该家族仍会单独标记并退出主处理组。原因是结果变量按整个 HS6 汇总，不能把同一家族内另一项政策造成的变化冒充 List 1 效应。

### 对照组

稳定 HS6 商品家族在研究窗口内对以下行动的直接暴露必须为零：

- Section 301 List 1；
- 2018-08-23 生效的 List 2；
- 2018-09-24 生效的 List 3；
- 2018 年影响中国商品的 Section 232 钢铝措施；
- 2018-02-07 生效的 Section 201 洗衣机和光伏保障措施。

不纳入 List 4，因为主窗口在其 2019 年 9 月生效前结束。如果以后延长时间窗口，必须重新冻结污染清单。

### 混合组

同一稳定 HS6 内既有受处理又有未处理进口的家族不进入主二元事件研究。它们可以在以后连续暴露强度模型中使用，但不能为了扩大样本临时混入主结果。

## 5. 产品排除怎样处理

USTR 的第一轮 List 1 排除在 2018 年 12 月公布，而且排除追溯到 2018-07-06。部分排除只覆盖某个 HTS10 或具体商品描述，不能简单给整个 HTS8 打一个“未处理”标签。

本项目采用两层处理：

1. 主分析估计原始 List 1 列入的 ITT，处理身份不随排除改变；
2. 为每个稳定商品家族保存排除批次、公告日期、追溯日期、HTS10 和商品描述，复核时删除所有曾被排除的家族。

如果主结果与“删除曾排除家族”的方向相反，停止因果采纳。

## 6. 对照选择规则

候选商品首先必须在 29 个干净政策前月份中至少 24 个月有正的中国进口额。这个条件只使用政策前数据，不要求政策后继续有贸易，因为用政策后是否活跃筛样本会删除真实退出效应。

匹配使用政策前特征：

- 中国月均进口额的对数；
- 政策前趋势斜率；
- 月度波动；
- 中国占美国该商品全部原产地进口的份额；
- NAICS3 行业。

主匹配在相同 NAICS3 内为每个处理商品选择 3 个最近对照，允许重复使用对照。所有特征只能来自 2016-01 至 2018-05。

匹配后每项特征的绝对标准化均值差必须小于 0.10，并且至少 80% 的处理商品能得到两个合格对照。

## 7. 数据输出

执行阶段应生成：

- `hts_history_mapping.csv`：原始年月 HTS10 到 `HS6_2017` 的官方映射；
- `trade_action_exposure.csv`：每个代码受到哪些同期贸易行动影响；
- `list1_exclusion_timeline.csv`：List 1 排除时间线和适用范围；
- `control_eligibility.csv`：每个稳定 HS6 的处理/对照资格与排除原因；
- `policy_exposure_hs6.csv`：官方同期政策范围展开到统一 HS6 的审计表；
- `treated_mapping_exceptions.csv`：按政策前金额排序的映射异常明细；
- `control_candidate_features.csv`：只用政策前数据计算的候选特征；
- `matched_control_pairs.csv`：冻结的处理—对照配对和距离；
- `causal_candidate_panel.csv`：稳定 HS6 × 月份面板；
- `control_build_report.json/.md`：覆盖、平衡、污染和阻断结果。

原始 Census ZIP 仍按现有规则处理成功后删除，只保留 URL、哈希、取得时间和处理记录。

## 8. 验收门槛

- 官方映射覆盖至少 95% 的政策前处理组进口金额；
- 至少覆盖 90% 的处理组 HTS10；
- 金额口径的歧义映射不超过 1%；
- 至少 100 个纯处理 HS6、200 个纯对照 HS6；
- 所有候选控制均未直接暴露于冻结的污染行动；
- 每个输出业务键唯一，月份连续，金额可与原始聚合对账；
- 匹配平衡和覆盖达到第 6 节门槛；
- 所有选择规则不读取 2018-06 之后的结果。

任一核心门槛失败，状态设为 `blocked`，不能自动降低标准。

## 9. 官方来源

- Census 历史与年度进口代码：[International Trade Reference](https://www.census.gov/foreign-trade/reference/index.html)
- Census 月度商品 concordance：[Data Product Concordances](https://www.census.gov/foreign-trade/data/dataproducts/concordance)
- USITC 历史 HTS 版本：[HTS Archive](https://hts.usitc.gov/download/archive)
- USTR [List 1](https://www.ustr.gov/issue-areas/enforcement/section-301-investigations/section-301-china/34-billion-trade-action)、[List 2](https://ustr.gov/issue-areas/enforcement/section-301-investigations/section-301-china/16-billion-trade-action)、[List 3](https://ustr.gov/issue-areas/enforcement/section-301-investigations/section-301-china/200-billion-trade-action)
- USITC 2018 年其他贸易行动：[Section 232 and 301 Trade Actions](https://www.usitc.gov/research_and_analysis/trade_shifts_2018/special_topic.htm)

直接命令行请求 Census 历史 Excel 在 2026-08-31 返回 HTTP 403；随后已通过官方参考页支持的浏览器下载路径取得文件并核验 SHA-256，没有使用第三方镜像。资格层已严格只读政策前数据执行：6 道门槛通过 5 道，唯一失败项是歧义映射金额占比 1.0822% 高于 1.00% 上限，因此未生成匹配结果。
