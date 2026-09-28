# 核心收口：Astra代码核查与Luna执行方案

> 2026-09-21展示复核：以下“已完成”不作验收结论；generate未保存catalog，真实会话解释入口仍断开，现有新测试绕过生成入口。公开模拟提交及独立审阅实现也未按本方案边界完成。待集中修复再验收。

状态：核心集成已实施，2026-09-21。服从 PRODUCT_CLOSEOUT_20260921.zh-CN.md；本阶段不改前端、不调用真实API、不做四题评测、不提交推送。

## 核查结论

| 环节 | 本轮直接证据 | 判断 |
|---|---|---|
| 会话→证据→报告 | web_app.py 的 session/task/generate 只构建 program-report-a3 | 数据程序稿已接线，最新AI解释未接入 |
| 最新解释协议 | bounded_explanation.messages/parse；provider_executor E合同独立运行 | 有输入、解析、实验记录，不等于产品完成 |
| AI审阅 | interpretation_review_store._packet_snapshot 仅支持legacy/v2文件集合 | 不能把E输出硬塞成v2，需显式协议分派 |
| 导出 | web_app._program_draft_gate 拒绝非A3内容 | 正确保留安全边界，不能简单放开kind白名单 |
| 事实保存 | 两个session brief builder创建catalog后仅返回摘要和A3 | 需要保存实际catalog以绑定后续解释，而不只存哈希 |
| 公告与恢复 | 本轮71项相关测试通过，见下方命令 | 当前离线回归有证据；不宣称所有网络更新或全仓通过 |

核心缺口已收口为一条：确定性会话报告与E解释现在共用会话任务、事实目录、版本绑定、解析和审阅导出。不要新建另一套Agent、生成框架或实验账本。新公告解析保留人工确认；不把任意新公告自动理解作为V1门槛。

## 实施顺序：一个集成包，不逐项另开实验

### 一、固定生成输入并连接现有解释协议

- 修改 session_brief.py、announcement_report.py：返回已校验的完整 catalog（内部字段），A3文本和原返回字段保持兼容；不要改变计算公式、catalog语义或历史冻结文件。
- 在 evidence_ready 阶段持久化不可变生成快照：request_snapshot、policy_binding、data_version、catalog、A3、由 bounded_explanation.messages 构造的实际 messages、协议版本及各摘要。磁盘写入完成才宣告就绪。路径由服务端按session/task派生，不接受用户任意文件路径。
- 再生成时验证快照摘要及其与任务/已查看证据的一致性，不读取“最新活动版”替换确认版。显式停用或撤销公告时阻止新生成并要求重新确认；仍保留历史报告。
- 保留原A3生成方式；新增显式解释生成服务，默认关闭真实调用。复用session_store的锁内 generation_started 领取许可及 model_adapter 的响应类型。请求身份纳入实际模型配置、协议和messages摘要，不接受浏览器自报摘要当权威。
- 开发用注入的provider替身返回原始文本；聊天模拟可从固定请求读入一次原始回答，走相同完成处理函数。标记channel=chat_simulation或stub，usage未知不是零。仅开发CLI/测试可注入，不做公开任意原答上传接口或手工模式页面。
- 真实provider后续沿用现有适配器并显式配置/授权；本包验证关闭时不会创建网络客户端。不要调用run_experiment绕开冻结，也不要复活stopped实验。正式实验执行器保持独立的实验审计用途。
- 原始响应先原子落盘，再parse；坏JSON/合同失败保存原答并failed；语义flags进入待修，不自动批准。started而无原答的重启保持unknown_outcome且不重复调用；已保存原答的恢复仅重新校验，不再调用模型。异常记录不得含密钥。

### 二、扩展现有审阅服务，再接报告导出

- 在 interpretation_review_store 中显式增加E协议分派，尽可能复用已有审阅记录与修订机制，不改legacy/v2审阅语义。不要伪造v2 evidence-bundle文件以求兼容。
- E审阅packet绑定session/task/run身份、原答hash、实际messages、catalog、A3、政策/数据版本；重算parse结果，不能信任客户端传入approved或canonical answer。
- 可审阅条目为每个解释slot及后续研究问题（missing_evidence和question作为一个配对条目）。每条必须给accept/reject/needs_revision和原因；facts_checked另行确认。flags对应条目必须明确处置，不能静默绕过。
- 采纳条件：事实确认、所有条目有决定、无needs_revision、至少一项解释slot被接受。reject项不出现在报告正文，审计记录保留。自动结构校验不等于语义正确；操作人是本地自报身份，不冒称鉴权。
- 输出固定A3事实部分＋仅被接受的AI解释＋被接受的研究问题＋来源/范围/数据截至月/人工审阅说明。AI文字按不可信纯文本转义，不允许HTML或伪造链接注入。
- 使用新的response kind明确区分AI报告。普通transition端点不得替AI写A3确认；AI导出必须通过对应审阅服务重验全部内容hash和审阅版本。不要移除_program_draft_gate；按kind显式分派。
- 最终报告文本hash也绑定确认；修改原答/catalog/绑定版本/报告文本均使旧审阅失效。审阅、导出读取一致快照；并发修订用已有版本冲突机制拒绝旧副本。

### 三、收口证据与使用说明

- 增加自包含集成fixture，临时目录初始化两条路径：已登记主案例、新公告已确认子集；不得依赖tmp下已存在的实验目录。不自动下载数据/调用API。
- 至少验证：①正确结构模拟→待审→逐项接受→导出→重启读回；②缺证不生成；③数字禁令/坏JSON/额外slot拒绝；④跨任务/跨catalog原答拒绝；⑤改原答或版本后审阅失效；⑥并发生成仅一次provider调用；⑦中断不重复调用；⑧全部reject或待修不导出AI稿；⑨部分reject只导出接受内容；⑩普通A3确认不能批准AI；⑪新公告完整范围缺口阻断、显式已覆盖子集可用；⑫异常原答含HTML时导出不执行。
- 真数据开发冒烟沿用现有主案例和R2材料，临时根目录，不改活动发布指针。只验证工程链，合成回答不记模型正确率。不碰最终四题。
- 更新 docs/USAGE.zh-CN.md：核实唯一启动命令、现有入口与真实能力、API暂不启用和模拟仅开发、支持范围、失败恢复。前端改版留到用户给网站之后。
- 跑相关测试并记录运行/跳过/失败数。全量失败需与本次基线对比，不能把历史47项直接套用到当前仓库；不改旧冻结哈希刷绿。

## 完成与升级边界

交付：一个可从确定性证据到模拟解释、持久审阅及导出的核心链；不称已完成真实模型验收或全自动最新政策监控。验收通过后停止扩张，交Astra审查差异与失败边界，再等用户网站做前端。

Luna可按以上方案实施。若需要改变E合同、经济指标定义、政策覆盖口径、版本存储/审阅历史格式的破坏性迁移，或发现并发跨存储无法保持绑定，保存安全进度并返回Astra，不自行重设计。原有失败方向不重跑。

## 本轮验证

以下命令实际运行：71项通过，0失败/错误；仅本轮所列模块，不是全仓验收，0真实API。

```bash
PYTHONPATH=src:. .venv/bin/python -m unittest tests.test_bounded_explanation tests.test_bounded_executor tests.test_j1_j4_integration tests.test_s1_policy_binding tests.test_s2_trade_coverage tests.test_k3_announcement_flow tests.test_k4_announcement_parser tests.test_e3_sessions
```

下一阶段模型建议：Luna最高；任务是执行已锁定的核心集成方案。完成后Astra中复核，不先启动模型排行。
