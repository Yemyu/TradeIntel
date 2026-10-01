# FR2026-19516：正式单次调用返回，但格式合同未通过

日期：2026-09-29。本记录接续[正式包离线验收](20260929-UNSEEN-READING-LIVE-PACK-OFFLINE.zh-CN.md)。**本案已发送且只发送一次真实请求；不得以“未通过”为由重试这份未见公告。**

## 事前固定条件与实际结果

- 固定请求：`deepseek-flash`（官方 DeepSeek V4.1 Flash）、thinking/high、JSON、`max_tokens=20000`、输入预留40000、180秒；最终请求体 SHA-256 `3b898bf79fe3efb82d8e0d042338ef61ea7830d1c3b3ffd2990f0101000acbaf`，清单 SHA-256 `5bb734beca1bb14423a651109f755c920233687306b0b212d41a2d22e1e5200e`。请求当天按[官方价格](https://api-docs.deepseek.com/quick_start/pricing/)复核峰时输入缓存未命中 $0.30/百万 token、输出 $1.20/百万 token，计划门 $0.04 不是账户硬上限。
- 运行结果：执行器返回 `invalid_response` / `answer_contract`、`retry_allowed=false`。一次性私有账本现为 `invalid_response`，默认预检同样读到该状态；没有第二次请求。HTTP 已返回正常模型响应，`provider_model=deepseek-flash`、`finish_reason=stop`，不是 400、超时或截断。
- 用量：输入 7,011 token（其中缓存命中 128）、输出 6,652 token（其中推理 5,741）。按**全部输入均未命中**和峰时价保守估算本次约 **$0.01009**；这不是实际账单。返回原始 JSON SHA-256 `66f2626718b677a02ae076e032696f550cc091d918c1682994b2e5fcba4887d4`，仅存本机 `.local/experiments/announcement-reading-v2/fr-2026-19516-unseen-v1/`，不入库、不在本文复制模型内容或密钥。正式审阅文件未生成。

## 可复现的格式故障

冻结提示要求对 `rate_meaning`、`conditions`、`exceptions` 列出可独立核对的要点和段落编号，但**没有告诉模型**解析器的两个数量门：`MAX_CLAIMS_PER_FIELD=6`、`MAX_ANCHORS_PER_CLAIM=3`（`src/tradeintel_ai/announcement_reading_suggestions.py`）。本次 `conditions` 给出 8 条要点，锚点数为 `[5,6,6,4,7,4,1,3]`；`exceptions` 5 条，锚点数为 `[5,3,3,4,3]`。所有段落编号均存在于保存的原文，正文 2,976 字节也低于 6,000 字节门。`rate_meaning` 为 `unknown`，没有要点。

只读诊断中，按原冻结规则调用 `_interpret(raw)` 报 `reading value or source positions are malformed`；仅在**该临时进程内**把两项数量上限调至 12 后，同一原答可解析为 `review_only`。没有修改产品代码、冻结包、原答、账本或正式评分。这个反事实检查只说明失败集中在未写进提示的数量上限，**不说明13项事实正确，也不把本次改判为通过**。需要分别审查：协议如何保持覆盖完整而限制输出，以及原答各项解释是否真的有原文支持；不能将结构失败直接归咎于模型质量。

## 结论与下一关口

FR2026-19516 已被本次模型调用消费，不能再作为“未见材料”重发。正式技术结论保持 `invalid_response`；13项事实覆盖、无据额外说法、真人补查/改写省时均**未评分或未测**。下一阶段先作离线方案诊断：保持本案原结果不动，决定对现有原答是否另列“事后语义诊断”（不得冒充正式成绩），并设计未来**新公告**的提示—解析器一致性及事前假服务验收。任何新公告和收费调用都须独立冻结、预算及许可。

本步结果：一次请求已完成并保存原答；格式合同未通过，重试门锁定，未得语义成绩。
下一步：离线核定协议修订和原答事后诊断的边界，形成下一份新公告试验的事前验收方案。
下一步模型：GPT-6 Sol Max；原因：下一步要比较“限制数量”与“保留全部独立事实”之间尚未确定的方案；切换：请切换后确认。
