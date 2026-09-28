# 公告抽取：结构化传输路线（2026-09-27）

## v6 单次真实验证：已接通服务商，但原始工具参数不是合法 JSON

在 v6 profile 完成人工复核、预检通过后，按冻结的 DeepSeek `deepseek-flash` / beta chat-tools 参数只发出 **1 次**真实请求：

- profile：`tmp/policy-extraction-schema-20260927/r2-strict-tool-v6/`；请求体 26,272 字节，输入估算 9,845 tokens；命名工具调用、thinking 关闭、禁止并行和自动重试；
- 服务商返回了恰好一个 `submit_policy_fields` 工具调用，响应 usage 为 prompt 5,490、completion 2,860、total 8,350 tokens，`finish_reason=tool_calls`；因此 endpoint 和工具路由确实接通；
- 但工具参数字符串在本地严格 JSON 解析时失败（解析位置约为参数第 2,938 个字符，账本统一记录为 `tool arguments must be valid JSON without duplicate keys`）。本次没有进入字段归一化、HTS 证据补全、语义评分、候选启用或数据库写入；状态 `invalid_answer`，`api_calls=1`，原始响应已保存，哈希为 `34d9b4e787fc6815a96e9610e2e5ba1e5bd7ce6cdd2628bca47bc274a3ecdbeb`；
- 原始响应有上述 usage，但旧执行器先解析工具参数、后登记 usage，因此本次 `ledger.json` 的 usage/费用估计为空。保留账本原样，未来执行器应在保存原答后先登记服务商 usage，再尝试字段校验；不凭旧价格编造实际费用；
- 这是一次**输出格式失败**，不是“模型已经把政策读错”的语义成绩，也不应把它计入正确率。按停止规则不重试、不修改旧账本、不把无效参数修补后冒充模型原答。

这次结果说明：继续堆叠字段提示并不能保证供应商返回合法 JSON；在没有新的、可验证的传输假设前，不再继续真实公告抽取调用。现阶段公告自动抽取仍不是产品发布依赖，人工确认导入路径保持为主路径。

## 这一步做了什么

上一轮五次 DeepSeek 试跑已经停止，原因是模型返回形状不稳定，不能进入语义评分。此次没有继续调用模型，而是先做一条与旧试验隔离的结构化传输路线：

- 新增 `src/tradeintel_ai/announcement_extraction_schema.py`；
- 函数名固定为 `submit_policy_fields`；
- 参数形状固定为 `doc_version + fields`，每个字段包含状态、值、理由和逐字引文；
- 为兼容 DeepSeek beta strict tool calling，`value` 使用显式的 `present/data` 包装，避免把 `null` 交给 strict schema；
- 工具调用解析要求恰好一个指定函数，拒绝混合文本、错函数、多次调用、重复 JSON 键和错误结束原因；
- 归一化后仍交给原有 `adapt_suggestion`，结果只能是 `review_only`，不会写入启用候选，也不会绕过人工确认；
- 新路线使用独立的 28,000 字节请求体门，旧 R2 的 24,000 字节包和旧账本完全不变。

## 第一次真实 capability probe 的结果

旧的结构化传输包（strict-tool-v2）随后按冻结参数做过**一次**真实 DeepSeek capability probe：

- endpoint：`https://api.deepseek.com/beta/chat/completions`；模型：`deepseek-flash`；thinking 关闭；命名工具调用；不重试；
- 服务商返回 HTTP 400，账本状态为 `provider_http_error`，`api_calls=1`；没有进入字段解析、语义评分、候选启用或数据库写入；
- 这不是“模型把公告读错”，而是请求在服务商层被拒绝。具体是哪一项 schema 约束触发 400，当前账本没有保存原始错误正文，因此不能武断归因；旧账本不重试、不覆盖。

这与 DeepSeek 官方 strict tool calling 的边界一致：strict schema 只接受有限 JSON Schema 类型，并要求嵌套对象的字段全部 required、`additionalProperties=false`；不符合时接口可能直接返回 400。参见[Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)和[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)。

## 第二个独立验证包：接口接通，但合同仍拒绝答案

为验证一个更保守的 schema，已另建 `policy-extraction-schema-probe-v2`，不改旧 v1 账本。离线预检通过后，按冻结规则只发出了一次真实请求：

- profile：`tmp/policy-extraction-schema-20260927/r2-strict-tool-v4/`；将开放式 `data:{}` 改成 `data:string`，模型把 JSON 作为字符串传回，再由本地严格解析；
- 请求体 `23,641` 字节，输入估算 `9,845` tokens；profile、body hash、endpoint、模型和参数均已读回核对；
- 服务商接受了请求并返回 `finish_reason=tool_calls`、恰好一个 `submit_policy_fields` 调用和 13 个字段；响应原文已保存（12,344 字节），所以 endpoint/schema 的**传输层**已经接通；
- 但 `title`、`publication_date`、`effective_date`、`origin`、`rate_meaning` 五个已知文本字段把 `data` 填成了普通文本（例如 `2025-12-29`），而当前合同要求 `data` 必须是可再解析的 JSON 字符串（例如 `\"2025-12-29\"`）。本地适配器因此以 `known field data is not valid JSON text` 拒绝，账本为 `invalid_answer`、`api_calls=1`；没有生成草稿、语义评分、候选启用或数据库写入；
- 这不是 HTTP 失败，也不是字段事实已经判错，而是模型输出与传输合同不一致。该 probe 已封存，不能原题重试或把它计入准确率；本地 fake 正向链路仍只能到 `review_only`，不会自动启用政策；
- 冻结标记：`.local/experiments/policy-extraction-schema-probe-v2/frozen-model.json`；预算上限 `$0.05`，只允许一次调用，失败停止，不做语义分数。

## 离线复盘与 v2 合同草案

对已保存的 v2 响应做了离线拆解，发现还有两个独立问题：

- 请求构建时把原有字段语义提示整体替换成了短传输提示，所以 `hts_codes` 被模型返回成裸字符串数组，`rates` 也没有按原合同稳定表达；这属于提示内容丢失，不是数据库或报告问题；
- `origin` 的一条逐字引文在公告中出现两次，模型仍填 `occurrence=0`，本地证据定位正确拒绝了歧义引用。

因此没有继续放宽旧适配器，而是新增隔离合同模块 `src/tradeintel_ai/announcement_extraction_transport_v2.py`：保留完整的 13 字段语义规则，标量字段使用原始文本，数组/对象字段使用 JSON 文本，并明确重复引文必须使用 1-based occurrence。合成全 unknown 响应已能进入 `review_only`，原有人工确认门仍然有效。

新的离线请求 profile 已生成并读回核验：`tmp/policy-extraction-schema-20260927/r2-strict-tool-v6/`，请求体 `26,272` 字节，输入估算 `9,845` tokens，低于 28,000/16,000 门。随后 v6 已按冻结规则完成**唯一一次**真实调用并因工具参数非法 JSON 封存；v5 原答的离线复盘只用于验证兼容逻辑，没有把它改写成成功成绩；其中 `origin` 和 `rate_meaning` 仍有未指定 occurrence 的歧义引文，所以不能自动补成通过。

## 验收结果

离线测试：

```text
tests.test_announcement_extraction_schema
tests.test_announcement_extraction_pilot
tests.test_policy_extraction_pilot_runner
17 tests OK
```

另外已通过 Python 编译检查。离线 profile/fake 阶段没有调用 API；上方 v1 和 v2 capability probe 各自只调用一次，账本彼此隔离，旧实验记录没有被修改。

用现有四份离线包实测新请求体：R2 `24,974` 字节 / 输入估算 `9,845` tokens；D2 `10,693` / `4,030`；H1 `12,115` / `4,622`；H2 `8,798` / `3,284`。四份都低于新路线的 28,000 字节和 16,000 tokens 门；旧 R2 的 24,000 字节门仍保持不变。

## 仍然不能宣称的事情

函数 schema 只能减少“字段结构错位”，不能证明字段含义、税号范围、税率条件或引文真的支持结论；这些仍由 `adapt_suggestion` 和人工审阅负责。当前 28,000 字节门只是离线预算上限，不代表服务商已经接受该请求。

## 独立请求包与 fake 全链路

新增两个脚本：

- `scripts/prepare_policy_extraction_schema_request.py`：读取已核验的旧公告包，生成新的 `provider-body.json`、请求摘要和 manifest；v1 历史 profile 位于 `tmp/policy-extraction-schema-20260927/r2-strict-tool-v2/`，当前待授权的 v2 profile 位于 `tmp/policy-extraction-schema-20260927/r2-strict-tool-v4/`，均固定 DeepSeek beta chat-tools endpoint 并通过读回核验。
- `scripts/run_policy_extraction_schema_fake.py`：写入 started 记录，保存 fake 原始响应，再解析、归一化并进入 `adapt_suggestion`。`tmp/policy-extraction-schema-20260927/fake-valid-v2/` 最终状态为 `review_only`，API 调用数为 0。

同一 profile 还演练了五种异常：错误函数、多次调用、重复 JSON 键、截断响应均记录为 `invalid_answer`；超大响应记录为 `blocked_output_budget`。这些运行均保存了独立 ledger，且 API 调用数为 0。它证明了“结构化响应→本地校验→待审阅草稿”和“失败后停止”的本地链路已经连通；它仍然没有证明服务商会接受 strict tool calling。

## 下一步门槛

1. v6 已完成并封存，不再对同一 profile 重试。若要继续，只能先提出新的传输假设（例如改用普通 JSON 响应而非 strict tool arguments），另建版本、另定预算和停止规则，再做一次最小 capability probe。
2. 在新的传输路线得到可复现的合法 JSON 之前，公告自动抽取不进入发布门；人工导入和人工确认仍是当前可用路径。
3. 即使未来结构和字段都通过，也只能生成 `review_only` 草稿，不能自动启用公告或把模型结果写入生产数据库。
