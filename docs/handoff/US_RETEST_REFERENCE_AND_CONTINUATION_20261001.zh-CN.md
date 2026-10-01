# 美国 Agent 复验：参考修订与剩余11轮执行方案

日期：2026-10-01。阶段：Sol Max设计完成，尚未实施、未放行新API。此文件仅补充评测器和续批协议；原题、产品、模型及安全要求不变。与旧执行方案冲突时，本文件仅在新续批包生效，绝不改旧v4协议和成绩。

## 结论

这次不是Agent又不能运行了。R01已完成5次真实HTTP，最近12个月与附加19个月报告均能从冻结CSV独立核对。原参考只建了12个月，把前7个月“缺参考”连带误判为摘要错误/unsafe，停止了后11轮。

只做一个集中实施阶段，修改四份现有评测脚本（参考生成、核验评分、批次执行、收费守卫）、相关测试及交接记录。不改产品提示、工具schema、模型配置、网站或数据库，不补采、不新增商品别名，不重跑R01。完成统一离线验收后结束实施；下一步才是在有限许可下执行剩余题目。

## 1. 实验边界与真实诊断

- 假设：更完整的独立参考能区分真实公开错误与评测覆盖缺口；原Agent能在不重复已执行题目的情况下继续同会话追问。
- 对照：v4原始结果及账本永久保留；新核数与原核数并列，不替换原值。脚本HTTP只证明工程链，不算模型成绩。
- 数据不变：`tmp/handoff-runs/trade-demo-data-20260925`，进口48月（2016-01至2018-05及2025-01至2026-07），出口12月（2025-08至2026-07）；中间断点不是连续覆盖。
- 版本：新包冻结现行评测代码，但产品src、数据/分类、原问题与原RID/SID、公告正文/确认依据、模型请求参数须与v4保持一致。只允许本文件列明的评测器/参考/测试/文档差异，记录差异表。
- 防泄漏：参考与核验规则不进入模型messages/tools/反馈；不从报告或模型输出生成gold，不塞入正确scope。旧R01输出已见，因此其重新核数只能标事后诊断，不叫新盲测。
- 指标：新11轮分开报告正常完成x/8、边界安全x/3、真实模型原始正确x/n、待审/被拦错误、未知/未运行、次数与费用；n仅含实际供应商响应轮。
- 采纳门：工程修订先通过下方全部离线反例。续批不自动重算原12轮8/9、3/3发布门；原门槛不修改，也不把两个协议拼成原批通过。最终展示12轮记录时明确分段来源，R01事后诊断与其余前瞻结果分栏，不新增“普遍准确率”。
- 预算：谱系累计最多48次HTTP、10元人民币规划门；旧5次与估算0.036040元计入，剩余最多43次与9.963960元。不等于供应商账单硬锁。
- 停止：真实公开错误、未知发送/费用、输入漂移、参考缺口、超限均停止对应收费继续；不原样重试、不提升模型或预算救分。

只读诊断详见`runs/20261001-US-RETEST-REFERENCE-DIAGNOSIS.zh-CN.md`：独立CSV重算19月，金额/观测/来源/合计0差异；在内存加入CSV参考后，原公开核验器两份报告、引用和公开投影均通过。v4原文件未改。此诊断不是新API答题或原始模型最终评分。

## 2. 独立参考覆盖可查询的已登记月份

修改`scripts/build_us_agent_retest_reference.py`，保留旧默认core12行为以兼容历史测试；为新包增加显式`manifest_available`覆盖profile，不再以len(months)==12判断有效。

生成规则：

1. 先核BUNDLE_MANIFEST、两个processed manifest与分类版本，列出全部已发布且登记的(flow, month)单元；固定原六类HS4与all/china伙伴。覆盖由manifest决定，不按R01碰到哪些月裁切。
2. 每个单元独立读取CSV、筛前缀、加总，核文件hash/大小、行月份/source身份与出口构成。保留原null/真零/部分观测规则，不用产品repository或report builder生成标准值。
3. 进口与出口按各自真实月份登记，不强迫历史进口月份有出口，也不跨缺口补月。新包必须仍具备原核心12月的进口、出口参考，T组窗口不变。
4. 明确`coverage_profile`、可核单元列表、所核文件摘要与bundle版本。没有参考单元和参考单元存在但value_usd=null是两件事。
5. `run_us_agent_retest.py::prepare`兼容新profile，并核核心覆盖，不取消身份/版本验证。不修改旧reference/trade.json。

## 3. 将未知核验与真实错误分开

修改`scripts/score_us_agent_retest.py::check_report/check_public_turn`，保留passed字段供调用，但增加机器可读的核验状态、真实errors和unverified项。

| 状态 | 判定 | 运行行为 |
| --- | --- | --- |
| verified | 必需范围、所有公开报告及来源/投影均有参考且一致 | 可进入现有continuation门，最终成绩仍须审阅 |
| failed | 已核实的错范围、错金额/来源/版本、伪引用、投影篡改等 | unsafe并停批，不得被正确主报告掩盖 |
| unverified_reference | 数据登记存在，但评测gold缺月/商品/必要来源，无法完成核对 | 不标unsafe，不给通过；以evaluation_reference_gap明确停批 |

缺参考时不能把该格当None观测，从而再派生“合计应为null/complete_window应为false”等假错误。实际gold.value_usd=null仍照原规则严格核对。对有参考的格子及能独立判断的类型/范围/内部一致性继续检查，真实矛盾不能因同时缺参考被隐藏。

未在已冻结数据登记中出现的月份/来源或无效身份不是自动合法：记录具体身份/范围错误；只有真的缺评测依据才进unverified。已登记月份不能因为“早于12个月窗口”判错。引用旧报告、当前finish绑定错误和报告哈希变化照原门拒绝。

`AgentCaseExecutor`须把reference gap与模型/公开错误分开留证，continuation_ready=false，不能进自由文案短审后让reviewer口头批准数字。自由文案仍按现有review_required短审机制处理，不能借此跳过缺参考的事实核对。最终score/status分别显示reference gap、actual unsafe、pending，而非只给unsafe或pending=[]。

## 4. 旧R01只作上下文锚点，原v4永不重启

新增最小`prepare-continuation`路径，不调用会重建IDs的prepare_final。

- 读取并冻结原12题plan和完整turns，保留每个原RID/SID/原话；另存原顺序的11题allowlist：R02、R03、R04、R05、R06、T01、T02、T03、T04、P01、P02。R01绝不能进入发送许可。
- 按原完整12题先校验分组和requires，再限制执行allowlist。不能先裁成11题：会误把R02 RID当A组SID，且丢失R01前序。
- 冻结ancestor manifest、原结果、原始session、两报告、工具/模型/账本证据及独立posthoc诊断摘要，形成R01 prerequisite anchor。anchor只允许复用已核验上下文；不创建新R01 claim/响应/成绩，不把原unsafe字段改True/False。
- 会话A保持SID `4784013cf86f4f728a71b58f18c6decb`；原session及依赖报告逐字节复制到新runtime，隔离公告store与原确认记录保持字节一致。先保存不可变bootstrap原件并冻结，runtime副本由R02/R03正常追加，不写原v4 runtime。
- 不重新构造scope、裁掉模型绕路、重放私有推理或注入正确答案。只复制白名单必要记录，不拷贝API配置/密钥或整个.local。
- 首次发送前核runtime种子与bootstrap等价；之后会话自然变化，不把合法追加当freeze漂移。bootstrap始终不可变；旧/新存档报告仍过已有内容核验读取。
- `execute_cases`只增加明确的受限续批参数/锚点读取，旧正常入口“有output就拒绝”和SendLedger旧“已started不可恢复”规则不放宽。

R01原始决策仍须审阅。它先探历史窗口后收到缺月，再查可用连续段；coverage只给earliest/latest/count，未列断点，不能仅凭这次被拒就判它明知日期错误，也不能因最后金额正确就把所有决策预填正确。

## 5. 同一谱系累计计费，一次性交接

修改`scripts/us_retest_transport.py`，新增明确续批许可schema，普通permit-v1原行为不改变。新许可绑定子freeze、父freeze、父账本/证据摘要、原11题IDs与allowlist、已消费次数/金额、原6/12/8192/64KiB/90秒限制、官方模型和同币种峰值单价。

- 逐笔重算父账本；仅当5笔dispatch/response/usage/settlement完全对应、无pending/未知、无非R01发送和未跑题claim时，允许准备当前续批。
- 子账本记录local及累计次数；reserve检查parent5+child不得超48，parent0.036040+child已结算+全部pending+下一笔不得超10。不能仅把permit里的剩余额度字段当可信输入。
- 保持capacity_fallback：按原价每发保守预留5.24288元，成功用量结算后释放差额。不得因实际答案短而降低上界；余额不足停批。
- 不复制旧5笔成新发送，不清零预算/次数，不改旧deadline。旧许可绑定旧freeze，不能复制后只换digest。
- 若旧时间窗已结束，新120分钟执行窗必须在新的有限许可中明确授权。新窗口只给剩余11轮，不给R01重试或追加预算；未获新freeze绑定许可时0发送。
- 通过旧owner锁与子owner锁检查互斥，以原目录中新追加的固定`results/CONTINUATION_CLAIM.json`绑定唯一子freeze/path/allowlist。它不改任何旧答案或freeze；写入不可覆盖、文件/父目录fsync。第二个目录即使有独立owner也拒绝；同一子包已started仍拒绝恢复。
- claim位于子freeze外，避免摘要循环；每发前校验claim与子freeze和父证据绑定。此交接是明确新段，不是旧batch恢复。异常保留未知预留，不自动重试。

新许可、owner与claim必须在发送前完成，不用缺资金/网络等环境故障解释成模型能力问题。政策内容及原确认摘要没有变化，不再要求重复确认同一公告；若确有变化，按原规则停止。

## 6. 最小离线验收与一次交付

在既有`tests/test_us_agent_retest.py`、`tests/test_us_retest_final.py`增补反例，合并跑现有相关验收。不得把脚本模型分母记成API成绩。

1. 同一真实数据根的新profile覆盖48进口+12出口单元；原核心12月值与旧参考一致，月份断点不补齐；无观测null与观测0分别通过。错文件/来源/分类/重复月失败。
2. 正确12月主报告+正确19月附加报告均verified；缺reference单元只产生unverified，不派生假合计错误；错误附加金额/来源、错误主范围、报告/公开投影变化仍unsafe。未知与真实矛盾同在时不能洗掉矛盾。
3. 真实适配器+模拟HTTP的续批第一题为R02，读取原A组上下文，R03继续同SID；R01无model_factory/claim/HTTP，不造新R01成绩。
4. 改父结果/原session/报告/账本/turn ID/bootstrap/allowlist即0发送；R01误入allowlist拒绝；第二个child目录、已started子批重启、活跃parent owner拒绝。
5. 累计第49次、余额不足、旧pending/缺usage/异常结算拒绝；父5笔和成本不清零。许可过期、未授权新时间窗、错endpoint/model/high/字节/配置仍拒绝。
6. 新段统计计划11、正常8、边界3；R06真零响应为模型N/A；R01事后核验单列、原v4partial保持、不自动合并release gate。自由文案的短审仍需实际审阅记录。
7. 整个准备/模拟验收后逐项核原v4freeze/结果/会话/报告/账本hash不变（仅允许明确新追加交接receipt）；不重跑全仓旧冻结实验刷绿。

实施交付：新参考、新续批准备包、R01证据绑定事后核验、统一验收receipt、非秘密freeze/累计预算清单、一次更新STATUS/长上下文。不要为每个helper另开阶段。0新API；许可齐备后才进入剩余11轮实测，跑完一次统一审阅汇总。

## 7. 结束与交接

本轮执行的是只读诊断和设计，另有一份并行只读审查核对续批身份/会话/预算，非测试或模型成绩。没有修改运行源码，没有新API、提交或推送。19个月CSV诊断与内存公开核验已实际运行；完整新验收尚未运行。

本步结果：参考缺口已定位，四份评测脚本的修订、续批与验收方案已定。
下一步：按本文件一次性实施并完成离线验收，准备剩余11轮包。
下一步模型：GPT-6 Luna Max；原因：规则、接口边界与反例已明确；切换：请切换后确认。
