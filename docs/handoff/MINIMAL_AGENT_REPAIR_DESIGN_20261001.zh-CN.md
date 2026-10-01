# Agent 最小修复方案

状态：2026-10-01，已按本方案实施并离线验收。现行相关74项、Node52项全部通过；0 新 API，原始答案/数据/冻结不改，未提交推送。见[执行记录](runs/20261001-MINIMAL-AGENT-REPAIR-OFFLINE.zh-CN.md)。下方为原固定设计，旧协议四项运行成功预期被新v3守卫拒绝的情况如实留在执行记录，不称全仓绿色。

## 要解决什么

让已有数据的问题少被不必要的澄清和重复检索卡住，同时保留真正的商品歧义、证据冲突和数据缺失拒绝门。不是重做 Agent，不添加国家、数据库、前端架构、多智能体或新的模型横评。

依据：[三组对话核验](runs/20261001-CHAT-COMPARISON-REVIEW.zh-CN.md)、[DeepSeek v5 原始结果](runs/20261001-US-RETEST-V5-LIVE.zh-CN.md)。20 份 GPT 程序报告及 5 份 DeepSeek 发布报告的核数检查已通过，不重复改这些答案。GPT-6.1 Sol Medium 本轮完成 9 道正常题，说明主链能够工作；它有旧摘要暴露，不据此断言模型强度与成功率的因果关系。

只读复现得到四处具体问题：

| 问题 | 已验证事实 | 修法 |
|---|---|---|
| 中文目录匹配 | “天然橡胶”“可可豆”找到正确 HS4 却标 related；对应英文可查。“钨及其制品”的单字钨被分词丢掉。“葡萄酒”召回酒渣而遗漏 2204 | 共用已审中英别名，区分整商品组与精准代码命中 |
| 英文误升准确结果 | 现 startswith 将 tungsten 矿砂/制品、wine 葡萄酒/酒渣同时升为 exact | 删除无条件前缀升格；保留相关结果发现，不自动取数 |
| 双方向接口 | 已返回 both:1201，再分别请求 import/export 被拒，需要多搜两次 | 仅允许本轮合法 both:HS4/HS6 向单方向投影，逐月重验 |
| 政策重复检索 | 同 citation 的原文、位置、完整依赖相同，仅 score/matched_codes 随查询变化，却被整包比较当作冲突 | 证据身份比较只排除两个检索元数据字段，其他内容仍严格比较 |

另有真实模型错误：P01 用页面 source_id 而不是版本绑定 citation_id 收尾；R05 想用七月代替日历九月；T03 多查未经请求的全部伙伴。不能把这些统称程序错误，也不能通过放行错误参数刷完成率。

## A. 商品匹配与双方向查询

主要文件：`src/tradeintel_ai/trade_classification_catalog.py`、`src/tradeintel_ai/trade_agent_tools.py`；工具说明在 `trade_agent.py` 同步。共用别名/边界函数放在现有目录模块，不另建一套目录或让三个调用处各写一份映射。

### 固定匹配合同

1. 搜索排序、match_type、原问题 product_anchors 使用同一已审规则。别名只解释官方分类，不映射到金额、参考答案或题号；每次仍查实际目录、版本和期间。
2. 新增已审 heading 别名：1801 可可豆/cocoa beans；2204 葡萄酒/wine；4001 天然橡胶/natural rubber；8101 钨及其制品/钨制品/tungsten articles。加入 2611 钨矿砂/tungsten ores 和 2307 葡萄酒渣/wine lees 作为形态排除对照，依据当前官方完整 heading 核对后使用。英文词边界和最长复合名称优先，不能按任意包含词升格。
3. `match_type` 固定为三类：既有 `exact_product`（明确代码、完整官方目录名及原来已审的直接名称）、新增 `heading_family`（本次已审的日常名称对应整 HS4 组）、`related_candidate`（发现候选，不可自动取数）。未知类别拒绝，不依赖“不是 related 就允许”的隐式逻辑。
4. heading_family 返回 `scope_note`、`scope_note_en` 和官方完整名称。一般“天然橡胶趋势”可默认查看 4001 整组，但须说明包含其他天然胶；8101 须说明组内含废碎料。这是默认统计口径，不是该细分商品的精确金额。
5. 用户明确排除其他胶、钨废料，或询问天然橡胶轮胎/化学衍生物等加工品时，禁止用上述 HS4 总额代替；可继续找实际可支持的更细目录，否则澄清。原问题限制优先于模型改写后的搜索词。
6. 裸“钨/tungsten”“橡胶/rubber”仍是真歧义，不能自动选择矿砂、制品或天然胶；“wine lees/葡萄酒渣”不能被 wine 截成 2204。豆油/豆粕与大豆、玉米淀粉与玉米、茶与提取物、棉花多 heading、手机与 8517 宽组的既有保护保留。
7. 移除英文 startswith 自动升 exact。未审英文前缀仍可作 related 发现。明确代码/完整名称与别名匹配继续由实际目录验证，不为一个新别名放宽全部机器抽取的中文片段。

### 固定方向合同

- 返回 `supported_flows`：单向候选仅其本方向；合法 both:HS4/HS6 可 both/import/export。
- `query_trade` 只能使用本轮 `self.candidates` 中的真实候选。both → import/export 时，内部构造所请求方向 canonical ID，仍调用原 `ClassificationCatalog.validate_choice`，逐月检查存在性、目录版本、官方描述稳定性。
- scope 的 `selected_product_id` 保存实际查询方向 ID，`source_candidate_id` 保存目录真实返回 ID；不得冒称已经做过单向目录搜索。
- 单向 → 另一方向/both、伪 ID、跨轮/过期候选仍拒绝。不修改 `validate_choice` 的严格方向合同。
- 用户问 both 的 finish 仍需同商品、同期间、同伙伴的两方向；只给进口或两方向不同期间继续拒绝。进口消费额与出口 FAS 不相减称净贸易额。

### 范围说明必须真实到达读者

将 heading 的说明存入现有 `scope.coverage_note`，新增可选 `coverage_note_en`；query 反馈也返回该说明。保留原出口短期间提示，不能被商品说明覆盖。原 `build_reader_view` 已复制 scope，复用这条传递链。

`web/design-preview/report-view.js` 现仅在出口且多月时显示 coverage_note，英语还固定解释成“不足12月”。仅修这一条件：商品范围说明进口/出口、单月/多月均显示，英语用保存的英文说明；旧报告无英文说明时保留原短期间提示回退。放在商品/图表附近与来源详情中，不重做页面样式、导航或案例数据。双方向子报告同样保留说明。

## B. 政策证据稳定合并

主要文件：`src/tradeintel_ai/trade_agent_tools.py`。不改 PolicySearch 的排名、切段、法律依赖生成或公告状态。

增加窄的证据身份比较函数：从比较副本的 `hit` 中只去掉 `score`、`matched_codes`；完整保留 citation_id、doc/policy/version、正文、URL/page/offset、来源身份，以及外层完整 required_context、条件/例外/缺失依赖。不得按“正文一样”就合并依赖不同的证据，也不得忽略将来新增的其他字段。

- 同 citation 稳定内容相同：接受本次结果；账本保留首次 canonical bundle，查询反馈仍显示本次真实 score/matched_codes。保留各次检索 diagnostics，同次重复引用只存一个证据单元。
- 同 citation 稳定内容不同：仍受控报冲突。两版本同 section_id 因 citation 不同而并存，不重写旧引用。
- 原 12k 单 bundle、20k proposed、25k 返回上限及完整依赖守卫不变；不靠删条件、截断原文或提高上限达到成功。

必须使用实际政策存档离线复现这两对查询：

1. P01：`钨 加税 关税` → `9903.91.11 tungsten additional duty 301`。同 p12 para1 的 score 为 1.81108351 → null，matched_codes 为 null → [99039111]；其余内容相等。
2. R04：`大豆 美国 进口 出口 关税 政策 soybean` → `soybean 大豆 农产品 中国 关税 出口限制`。同 p12 para1 的 score 为 1.17516867 → 2.35033733；其余内容相等。

## C. 收尾合同说清楚，不让程序替模型猜引用

主要文件：`src/tradeintel_ai/trade_agent.py`，必要时复用 tools 的返回字段。将工具协议登记为 `trade-agent-tools-v3`，只对新运行使用；旧协议和冻结记录不刷新。

- 工具说明及 SYSTEM_PROMPT 明确 heading_family 的整组范围、both 单向投影规则，减少不必要的重复目录检索。
- `finish.source_ids` 字段名保留兼容，但必须填写本轮命中的 `citation_id`（含版本和段落），不是页面 `source_id`。在说明中明确区分两者；不得自动把页面 ID 映射成任意段落、接受旧轮引用或强行放行。
- 在 ID 校验错误的反馈中，给出受控 `error_code=invalid_finish_reference`、本轮实际 `available_report_ids`/`available_policy_citation_ids` 和一句使用说明；只列当前 tools 中已有 ID，沿用最多 12 项及原长度门。畸形类型、空报告、伪造或错误版本仍拒绝。范围/月/伙伴失败不要伪装成引用错误。
- 成功查数后如仍无政策证据，只能保留真实 no_evidence/partial/incomplete 状态和限制，不能编造完整政策解释；既有政策核验标准不降低。不得自动 finish、自动重试 API、手填报告或加大 6 轮/12 工具/8192 输出限制。
- 日历上月不改为数据末月，未知不补零，未经请求的伙伴补查不替换主范围。提示词提醒不是这些守卫的替代。

## 一次实施、一次离线验收

执行顺序 A → B → C，随后统一收口；不每个 helper 单独交接。固定环境 `.venv/bin/python`，`PYTHONPATH=src:.`，Node 使用项目现有测试。实施前记录涉及源码的 SHA/工作区状态；不要安装全局依赖或改系统设置。

### 正向与拒绝验收

| 组 | 必须通过 |
|---|---|
| 商品 | 中英可可豆、葡萄酒、天然橡胶同 heading/同 match_type，准确已审组排前；钨制品 8101、矿砂 2611、酒渣 2307 分开；真歧义继续澄清 |
| 范围 | 明确排除/加工品不能借 HS4 总额通过；中英 scope_note 经反馈→保存→重读→reader→单月进口/多月出口显示，旧短期间提示不丢 |
| 方向 | both 受控投影与独立单向查询金额/月份/版本一致；未搜索/伪ID/跨轮/single→opposite/both、缺月/缺码/描述漂移/版本变化拒绝；双方向 finish 不完整仍拒绝 |
| 政策 | 上述两对实际查询修前失败、修后成功，check_policy_bundles 通过；只变 score/命中码可去重；正文、身份、版本、位置、完整依赖、例外状态或缺失依赖任一变化继续拒绝 |
| 收尾 | 页面 source_id 首次拒绝并返回本轮 citation 提示，脚本模型第二次用真实 citation 可完成；伪 ID/旧轮 ID/错范围仍拒绝，不能仅改为“没报错” |
| 边界 | 九月未接入不得用七月替代；巴西不得换全部伙伴；中国金额未知不得补零；额外报告不得接管用户主范围；完整法律条款/例外及预算门原样有效 |

新增集中测试 `tests/test_trade_agent_catalog_contract.py` 和 `tests/test_trade_agent_policy_merge_contract.py`；finish/reader 部分优先扩现有测试。运行现 mainline、boundaries、language、request、policy_evidence、report_view、supplemental、classification 与相关 Node reader/UI 套件；具体命令按已有文件/锁文件确认，不编造文件名。正式报告和公开投影继续用现 `check_saved_report`/`check_public_turn` 核数。

可用保存的失败路径编写脚本模型驱动真实 Agent 和真实只读数据，验证不多搜两轮、不过度澄清、政策再次检索可收尾；修后的真实反馈必须由程序新产生，不能把旧反馈当修复后的工具输出。这是已见回归，不是再次运行 DeepSeek/GPT、不是盲测，也不能报告“模型准确率提升至100%”。

## 不可改变的约束与停止点

- v4/v5 原始答案、许可、成绩、CSV参考、freeze 和全部聊天组产物只读。v5 已结束不可重启，不拿旧收费许可启动改后新实验。
- 现有源文件多为用户未提交内容，保留所有无关修改。局部回归与全仓既有失败区分，不改旧冻结哈希刷绿；旧记录保留，不删数据/证据。
- 只有上述窄修复及必要范围说明接线。发现需新增数据、改变法律依赖规则、重做 taxonomy 或扩大架构才可满足验收时，保存进度，暂停，交 GPT-6 Sol Max 定新的最小判断；不要自行扩大。
- 离线门通过后，本次实现目标结束。是否再做有限模型验证另交用户决定；若做，只建立新代码/数据/政策哈希绑定的新包，分列已见回归与未用于修改的新场景，先定评分、预算和停止条件，不把旧失败改分。

实施交回：修改摘要、实际测试命令/数量/结果、未跑项目、旧证据摘要不变证明、零 API 声明；更新 STATUS 与本文件实施状态。无需另造安装包、交付目录或模型清单。

本步结果：A—C已实现，真实数据/公告与范围说明离线验收通过；未新增模型实测成绩。
下一步：无，本轮最小修复目标已完成；是否新真实验证另决。
下一步模型：无需；原因：当前目标已完成；切换：无需。
