# 政策Q3格式修复与一次开发复测方案

状态：两处提示修改和38项定向测试通过；新提示下调用1次，原始响应通过结构、预算及AI辅助非盲内容核查，单题开发验收1/1。原答提交与待审阅报告预览已贯通，用户尚未批准发布。旧r5的0/1结果未改。详见runs/20260923-POLICY-Q3-SHAPE-R1-REVIEW.zh-CN.md。
设计档：用户已确认GPT-6 Astra High。执行档：GPT-6 Luna Max；结果审查档：GPT-6 Astra High。

## 1. 目标与已知事实

目标：让模型直接按照程序原本要求的格式作答，随后检查内容是否可用。交付一个小范围修复、一份新候选包及至多一次真实Q3结果。

基准原答：`tmp/public-brief-eval-v1/policy-q3-real-20260923/q3/raw-response.txt`；SHA256为`116cf2370dba22e63389d44cd0a0e63a87585413b49ec47c48ef320114b78639`。原答是合法JSON，`policy_explanations`为以change/applicability/limits三个英文键索引的对象，各对象中的topic值为中文标题。解析器要求三项数组及英文topic枚举，故原成绩0/1不变。

代码确认：政策提示没有显式写数组类型、没有结构样例，也未充分说明topic必须逐字使用英文枚举。普通贸易提示已有格式样例，但政策messages重建了system消息，没有继承这个样例。提示与解析要求传达不完整是已确认缺陷；它是不是本次模型失败的唯一原因尚未验证。

旧原答在内存转换形状后解析通过，仅说明其余被检查字段及预算可接受。来源ID合法不代表引用支持陈述，更不能据此判内容正确。

## 2. 设计决定

采用一次最小的提示格式澄清；解析器、来源绑定、语义要求和导出审阅门保持原标准。

- 数据格式仍为`public-policy-explanation-prototype-v2`，预算仍为v3。此次只修改提示表达，没有修改程序接受的数据结构，不制造v3数据格式迁移。
- 提示修订标签为`policy-json-shape-r1`，通过新目录、实际messages及代码摘要追踪；不新增服务接口或迁移历史快照。
- 不对模型原答自动进行对象转列表、中文topic转英文的修补。修补后的回答不能当作原始格式通过。
- 本轮不同时改写经济学措辞、不换模型或推理档、不改变证据和评分，避免把多个改动的结果混在一起。
- 仅开启普通JSON模式不足以约束本次错误：旧原答本来就是合法JSON。DeepSeek的[JSON Output文档](https://api-docs.deepseek.com/guides/json_mode/)描述的是合法JSON输出；其[Responses接口文档](https://api-docs.deepseek.com/api/create-response/)列出JSON Schema，且[兼容性说明](https://api-docs.deepseek.com/guides/responses_api/)列出text.format支持。文档核查日期2026-09-23；本项目尚未实测此能力。若明确格式后仍失败，下一次设计优先评估原生结构化输出适配，不继续逐词刷同题。当前Chat适配器不能据此声称已经支持Responses结构化输出。

## 3. 精确修改规格

允许修改：`src/tradeintel_ai/public_policy_explanation.py`中的messages提示、`tests/test_public_policy_explanation.py`中对应回归、必要的现有runner测试，以及本方案所指向的状态/结果文档。无需安装依赖。

在messages中将以下连续文字：

```text
schema_version和binding_sha256照抄输入。policy_explanations必须各有一项change、applicability、limits，每项仅有topic、source_ids、text；source_ids引用view.policy.sources.rows第一列的p编号，至少一项，不重复。
```

替换为：

```text
schema_version和binding_sha256照抄输入。policy_explanations必须是JSON数组，恰好三项；topic逐字使用change、applicability、limits各一次，不得翻译；每项仅含示例字段。结构示例：[{"topic":"change","source_ids":["<p-id>"],"text":"<text>"},{"topic":"applicability","source_ids":["<p-id>"],"text":"<text>"},{"topic":"limits","source_ids":["<p-id>"],"text":"<text>"}]。占位符须替换；source_ids从view.policy.sources.rows首列选择，至少一项，不重复。
```

同一system提示中将`文字不输出阿拉伯数字`替换为`text和rationale正文不输出阿拉伯数字`，明确禁数字规则作用于说明正文，ID和摘要字段照协议输出。除此以外保持system语义与user消息不变。

样例只有结构占位符，不含政策判断、商品名称、贸易变化方向或标准答案。不得把上次原答、审阅结论、reference.json或required_points复制进请求。

## 4. 已完成的只读设计验证

基于旧r5冻结messages在内存执行上述两处替换，未改运行代码或旧材料：

| 项目 | 基准 | 方案测算 |
|---|---:|---:|
| 输入token估算 | 15704 | 15857 |
| UTF-8字节 | 31887 | 32164 |
| 硬上限 | 16000 | 16000 |

估算剩余143，不能再随意追加模板。它是现有规划估算器结果，不是厂商实测token。user消息逐字保持不变。

- 基准messages文件SHA256：`c14a1503df46ae227701a33d4ee29e7c4f7a698885b54fc939d48a03e13ee44a`。
- 新system内容SHA256：`38011acae6802074b376bd43f8b8342d7779e3e062503eeb03da57e807c743ae`。
- 不变的user内容SHA256：`389a5228a1478380bcfab7797f7d9213365f399c79f900cc5668f2b2f7d15621`。

这些是实施时的对照值，不是对尚未修改代码的测试通过声明。

## 5. 执行顺序与离线验收

1. 先核对工作树及上面基准文件摘要，保留用户既有修改；用项目`.venv/bin/python`。只实施两处提示修改。
2. 增加最小合同回归：从实际messages提取示例并解析其JSON结构；给占位符填入合成fixture内容后必须通过原解析器并保持manual_review_required。另验对象形状、中文topic、未替换占位符仍受控拒绝。不要依赖只有本机tmp里才有的原答作为单元测试fixture，也不要放宽原解析器来刷绿。
3. 运行直接涉及的现有测试：`tests.test_public_policy_explanation`、`tests.test_public_policy_eval_runner`、`tests.test_public_explanation_flow`、`tests.test_session_explanation_flow`。仅新失败指向相关模块时扩大检查，记录实际数量。无需为纯提示修改重复整站浏览器或全量历史冻结套件。
4. 用现有准备器从`tmp/public-brief-eval-v1/service-v3-audited-20260922`生成新目录`tmp/public-brief-eval-v1/policy-q3-candidate-20260923-shape-r1`，禁止覆盖目录。核对question、user消息、response和reference与r5不变；system恰好上述两处变化；新估算等于15857且不超过16000。
5. 用现有runner生成`tmp/public-brief-eval-v1/policy-freezes-20260923/flash-high-policy-q3-shape-r1-candidate.json`，provider为`deepseek-flash-high-v2`，matrix为`evals/public_brief_v1/provider_matrix_high_v2.json`。在临时账本用stub验证准备→保存回答→解析→awaiting_semantic_review，API记0；可复用现有测试覆盖，无需重复另跑同等链路。
6. 将检查结果写入一份`docs/handoff/runs/20260923-POLICY-Q3-SHAPE-R1.md`。精确差异、预算和测试都符合本方案后，可按本方案制作独立formal冻结并复核hash；这是已设计的机械性放行，无需新增设计轮。任何不符合之处停在candidate状态，交设计档判断。

新formal建议路径：`tmp/public-brief-eval-v1/policy-freezes-20260923/flash-high-policy-q3-shape-r1-formal.json`。真实输出新目录：`tmp/public-brief-eval-v1/policy-q3-shape-r1-real-20260923`。旧停止账本和结果不更改；新包摘要用于区分新配置。

## 6. 单次真实实验与采纳规则

本次用户要求定方案，本阶段API调用为0。用户后续切换执行档并要求按本方案执行，即可涵盖已列明的离线工作和至多一次真实Q3调用；无需每个步骤重复请求许可。使用可用的本地凭证或受控会话注入，避免将密钥写进命令正文、源码、文档或结果；如果已撤销/不可用则报告真实缺项，不反复尝试旧密钥。

| 项目 | 锁定内容 |
|---|---|
| 假设 | 明确数组结构和英文枚举后，原始响应可直接满足现有解析器；内容质量仍需独立核对 |
| 对照 | 2026-09-23的r5原始Q3失败；不改分，不采用内存修补版作对照 |
| 数据/代码 | 同一自然Q3、数据版本`91c2ed45f937392ea4473cd156ca05d3c7566e333ff9d50be90f5cbeccba4e1b`、相同user证据；新冻结保存实际代码及messages摘要 |
| 模型/接口 | DeepSeek API `deepseek-flash`，thinking enabled，reasoning_effort high，原Chat接口和其余参数不变 |
| 防泄漏 | Q3已用于开发，明确记作已见开发题；仅澄清结构，不输入原答、标准答案或评审；不计盲测或通用正确率 |
| 资源 | 1次请求；输入估算≤16000；max_tokens=8192（包含推理）；正文≤2000字符；原答≤65536字节；总时长90秒；不另发连通性请求 |
| 费用记录 | 保存厂商usage及耗时；实际人民币费用未知，不用估算器伪造账单 |
| 格式门 | 正常完成、原始响应直接通过原解析器，三项政策主题完整，topic/引用/绑定正确 |
| 内容门 | 调整性质、范围和条件、未知限制有来源支持；具体贸易观察正确；附加税与完整税则不混淆；无未经支持的首次纳入、因果或价格结论 |
| 停止 | 任何接口错误、超时、未知结果、格式或预算失败都保存证据并结束；内容未通过也结束；不自动重试或换模型 |

语义审阅要求：逐项列“原句→来源/数据依据→判断”。实际若由模型审阅，应标注AI辅助、非盲审，不能称作独立人工专家核验。数值/日期由程序展示，不要求AI违反原提示复述数字；结合程序事实面板与AI说明判断完整性。对“纳入”等措辞按完整语境判断，不能仅凭一个词判严重错误，也不能忽略真实的首次纳入断言。

成功后用同一份原答验证会话submit→审阅候选→报告预览，0次追加API；未经用户真实确认不冒记human_approved或对外发布。成功结论仅为“新格式提示下，这一道开发题本次通过”，不是可靠性保证，也不证明提示改动是全部改善的唯一原因。temperature=0不构成确定性重复保证。

结果表分别列请求数、收到回答数、原始格式通过、预算、内容审阅、整题结果、tokens。单题开发记录不并入旧四题组。

## 7. 交接、停止和回退

GPT-6 Luna Max负责精确修改、回归、新包及固定一次调用，之后由GPT-6 Astra High审阅结果和采纳结论。出现预算差异、user消息变化、合同冲突或需要调整评分时停止扩大修改，保留产物并返回设计档。一般局部实现异常可交GPT-6 Sol High，不应直接扩大到架构重做。

若格式再次失败，结论是这一路径尚不能满足用途；下一设计再评估原生Schema适配及最小能力验证，不重复相同配置。若结构通过但内容失败，按具体证据定位事实解释问题，不继续把它当格式问题。

回退只撤销本执行包的两处提示及关联新增测试，逐项补丁恢复，不覆盖工作树其他修改。保存新旧原答、冻结和失败记录；旧快照只读追溯，新任务需重新准备，不能用新提示重算旧冻结并冒称原输入未变。用户未要求提交推送，本包不自动对外提交。

执行交接话术：

> 按docs/handoff/POLICY_Q3_FORMAT_PLAN_20260923.zh-CN.md执行policy-json-shape-r1：精确修两处提示，用原解析器验收，保存新包和单次Q3结果。当前模型应为GPT-6 Luna Max。所有门槛符合才执行一次已列明的请求，失败停止；发生方法冲突返回GPT-6 Astra High。完成后更新既有STATUS、长上下文和本包run记录，提供原答路径供审阅。
