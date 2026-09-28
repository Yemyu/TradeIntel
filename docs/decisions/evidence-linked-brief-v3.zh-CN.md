# 证据关联简报 v3：设计与低成本执行规范

> 当前以 `docs/handoff/MASTER_PLAN.zh-CN.md` 为后续执行依据：S1补齐未覆盖缺口并接紧凑业务视图；新的独立实验输入硬门16000，旧G28000保持不变。本页下方“A—D完成”属于上轮交付口径，尚未被Astra采纳。

状态：2026-09-15，Luna已按[集中修复清单](../diagnostics/v3-implementation-review-20260915.zh-CN.md)完成 A—D 离线修复，并新增反例测试；交付记录见[修复交付](../diagnostics/v3-repair-delivery-20260915.zh-CN.md)。Astra尚未完成修复后复核，0新模型成绩，旧G2保持stop。下文是目标规范与复核边界，不代表AI质量已通过。

## 1. 目标、依据与取舍

继续完成贸易政策研究助手。此阶段让用户读到口径明确的数据事实，并得到AI基于事实和存档条款的阅读重点。保留单月T1任务与现有两案例，之后再建设T2新政策接入。

已核对源码：evidence_bundle.py已有金额、分母ID、月份、商品、版本和来源；research_brief_v2.py的提示已禁止改写数字，但输出仍只有自由explanation，render_pending直接展示它。review检查ID和少数词语，无法证明语义正确。business_workflow.py及interpretation_review_store.py直接绑定v2契约。旧失败因此不是“忘了写一句禁止改写数字”。

可证实的故障：GLM成功读取数值，却在文字中把美国从所有来源进口表述成全球进口。仅一个C样本，不能确定是模型能力、英文world字段歧义或提示负担各自贡献多少。本轮设计减少自由改述事实的空间，仍需真实结果验证。

取舍：先做并行离线原型，复用已有证据包；不修改v2默认业务入口、审阅历史或冻结源码。通过后再接入页面，避免在质量未知时改完整链。

## 2. 用户会看到什么

程序事实示例（已见开发数据，非模型结果）：2026年7月，美国对38180000商品的消费进口中，中国原产金额为8,385,427美元，占美国该商品全部来源进口金额的4.7061%；占本次五税号中国原产进口合计金额的81.7958%。两个百分比必须分开显示分母说明。

AI段落引用上述事实卡和政策条款，说明哪些证据回答“金额规模”，哪些回答“进口来源构成”，以及商品统计范围与存档政策限定是否存在已知/未知关系。没有足够证据就说明对应问题尚不能判断；不强制每条都制造政策结论或后续调查。

AI可做的工作：按用户关注点选择相关证据、解释两个事实的关系、结合带出处的条款说明适用边界。事实卡由程序写，AI解释仍须语义审阅。若最终只是复述事实卡，AI增益判定不通过。

## 3. 离线原型接口（Luna按此实现）

新增src/tradeintel_ai/brief_fact_catalog.py：build_fact_catalog(bundle)和render_fact_catalog(catalog)。只读已验证的EvidenceBundle，不读密钥、不访问网络、不读reference.private.json。

catalog包含schema_version=brief-fact-catalog-v1、policy_id、data_version、request、evidence_sha256、facts、policy_refs、limitations。evidence_sha256绑定完整原始bundle的稳定JSON；catalog本身再计算摘要用于响应绑定。

每条fact至少包含id、kind、metric_ids、observation_ids、period、reporter=USA、flow=consumption_import、product_scope、origin_scope、numerator_id、denominator_id、source_refs、text。沿用完整metric ID；新增文本ID从metric/observation ID确定性生成，不按排序序号重新编号。源ID、政策/版本/商品必须一致；缺字段/不一致直接报错。

各指标的中文标签必须显式区分：

| 原字段类型 | 事实文本含义 |
|---|---|
| world_import_usd | 美国该商品从所有原产地的消费进口金额 |
| china_import_usd | 美国该商品的中国原产消费进口金额 |
| china_share_of_product_percent | 中国原产金额占美国该商品所有来源消费进口金额 |
| product_share_of_scope_china_percent | 该商品中国原产金额占本次所选商品中国原产合计金额 |
| product_share_of_scope_world_percent | 该商品所有来源金额占本次所选商品所有来源合计金额 |
| scope_world_import_usd / scope_china_import_usd | 本次商品范围内美国所有来源/中国原产消费进口合计金额 |

不能把内部world字段裸露成“全球进口额”。程序读取现有数值，Decimal格式化：金额精确到输入美元整数、比例保留最多4位小数；不让AI转换单位。零分母为未知；单商品范围内构成比例可能100%，明确“本次仅选一项”，不能暗示市场份额100%。并列榜首保留全部，金额/占比榜首相同时说明相同，不造差异。来源缺失不可伪造。

政策资料直接复用已投影的policy_facts：保留税号、原文、日期/适用事件/存档身份、未知条件与例外。policy_refs需绑定source_id与本次requested_products中相关税号；共享段落提及其他税号不能扩展请求范围。只做引用有效性检查，不能判法律适用。

新增src/tradeintel_ai/evidence_linked_brief.py：messages(question,catalog)、validate(answer,catalog)、render_pending(answer,catalog)。复用现有严格JSON解析器，不修改它。

响应JSON固定：

```json
{
  "schema_version": "evidence-linked-brief-v3",
  "catalog_sha256": "给定摘要",
  "findings": [{
    "observation_id": "给定观察ID",
    "fact_ids": ["给定事实ID"],
    "policy_refs": [{"source_id": "给定原文ID", "hts8": "本次商品"}],
    "interpretation": "中文解释",
    "limitation_ids": ["给定局限ID"]
  }],
  "followups": []
}
```

findings 1—3条、观察ID唯一；interpretation 1—300字符。fact_ids必须非空且无重复，至少一条绑定所引观察，其他只能为同请求内支持该解释的事实；policy_refs和limitation_ids允许空，不强制凑政策关联。followups 0—2条，字段复用v2的observation_ids/missing_evidence/question及长度规则。明确拒绝额外字段、类型错误、跨版本/跨商品无效引用。

focus覆盖要求沿用v2：china_amount只强制amount_leader，china_share只强制share_leader；contrast按已有观察覆盖两者及rank_contrast；单商品为single_product_profile。不要把可选观察变成额外硬门槛。

展示：按fact_ids在程序端展开完整事实句，再展示模型interpretation；政策原文与未知可展开查看。AI不能提供事实text、金额、比率或链接覆盖字段。解释要求通过引用谈关系，避免重述数量。检测到额外数值表述可标needs_revision供审阅；不能靠数字/关键词黑名单证明语义通过，也不能误把合法否定句自动判严重错误。无论是否有flag均approved=false、semantic_approval=false。

保存raw-response、parsed-response、catalog及摘要，渲染只使用同一份catalog。原答不自动润色、修复或删句再计通过；示例修改单列。事实合法但解释非法时只展示“待修改”，不得静默移除坏解释宣布任务完成。

## 4. Luna实施边界与交付

可新增文件：上述两个模块、tests/test_brief_fact_catalog.py、tests/test_evidence_linked_brief.py、scripts/prepare_brief_v3_offline.py、必要的脱敏fixture及中文学习说明。

脚本默认只离线：载入明确指定的bundle/问题，输出catalog、消息、程序A3事实报告、预算估算、文件摘要及测试摘要。输入/输出路径必须显式；已有输出拒绝覆盖。没有--live功能、provider依赖或密钥读取。开发只使用已见七月材料及合成反例；不要提前读四个正式题的独立参考或模型输出。

不得修改冻结manifest记录的文件，也不把v3塞进v2 schema或修改旧账本。测试和原型新增文件可直接放当前工作区，保留其他改动。不安装系统依赖，不自动提交推送。

必须验证的行为：

1. 两种分母对应正确，全文明确美国/消费进口/月份/范围。
2. 零分母、零中国金额、单商品100%均表达正确。
3. 并列及同一榜首保留正确关系。
4. 跨案例、跨版本、缺来源、未知ID被拒绝。
5. 无关商品政策引用被拒绝；共享条款不扩商品范围。
6. JSON重复键/额外字段/类型/重复观察/缺必要观察被拒绝或明确覆盖不完整。
7. 恶意模型事实覆盖字段被拒绝；HTML/Markdown危险链接不可直接注入可信事实展示。
8. 摘要变化不能复用旧响应；raw原答保持不变。
9. 数值格式错误与语义待审分开；合法“不证明依赖”不能自动判已证明依赖。
10. 离线准备可在无密钥、无网络下运行，旧冻结文件摘要保持一致。

只跑上述新增模块相关测试及必要的解析器兼容测试，不重跑全仓历史实验。交付一套已见案例离线样例、反例结果、A3基准、messages及输入预算估算。明确样例响应是fixture，不是GLM成绩。

## 5. Astra复核与后续真实验收设计

Luna交付后Astra检查实际差异：事实含义是否正确、有没有把AI功能全部变成模板、引用选择能否增加帮助、消息预算、冻结保护及留出资料隔离。通过前不接生产页面、不发模型请求。

若采纳原型，再建立独立新实验记录，引用旧G2失败作为历史；旧剩余10槽不可当自动获准的新预算。新实验预算建议上限10请求（开发B3/C3各1，四题B3/C3各1共8），无重试、首次严重错误停。具体模型ID/可用性/输入估算上限和账本须在调用前冻结；默认保持GLM-4.7以减少变量，不在同轮换模型。此处是后续建议预算，本阶段只批准离线实现。

假设：完整事实句和引用型输出能减少统计口径改写，同时保留具体解释增益。

基准：A3为程序完整事实卡/确定性观察/政策原文；B3自由回答与C3引用型回答使用同一事实卡和原文、相同模型参数。A3比旧A更完整，不能用仅新增事实文案宣称AI获胜。旧C仅为故障对照，不能拿跨提示旧B作公平对照。

防泄漏：七月旧开发题已见，任何新成功都只算开发。四个原正式任务保持留出，不能查参考调prompt；参考答案只由离线评分持有。两政策此前已用于开发，称已知政策任务迁移，不称新政策盲测。先冻结新消息/参考/评分规则，再调用。

采纳：四题完整、零严重政策/数字/分母/范围错误、至少三题原文无需重写可用、至少三题较A3有具体受支持解释增益。数字抄对、只引用ID、免责声明、完整事实句本身不算AI增益。两个整体contrast须解释关注点差别，单商品不能硬凑对比。引用完整仅是工程检查。

开发失败：记录原答及机制，停止本轮并报告。不能追加提示/换月份刷过。只是没有AI增益也应明确未达产品目标，而非编分数。UI真实生成的C请求须预先纳入同一总预算；具体接入和网页槽在原型采纳时确定。

## 6. 下一步模型与项目记忆

Luna最高已按A—D完成集中修复；主案例完整政策资料进入消息后保守估算约31k，超过8000门槛，离线manifest标记`blocked_budget`，没有截断或擅自提额。下一阶段使用Astra中做反例复核、业务视图/预算决策及实验采纳判断；复核前不接生产页面、不调用新模型，旧G2剩余槽保持停止。

本次Astra仅设计并更新文档，0新API；T2及资源更新仍是后续产品目标，自研因果保持取消。v3设计不是质量提升成绩。
