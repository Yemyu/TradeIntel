# FR2026-19516：独立调用入口方案

日期：2026-09-28。状态：**方案已定，尚未实现或调用模型**。本方案承接[答前参考](../../evals/announcement_reading_v2/unseen-20260928-screen/2026-19516/reference.zh-CN.md)与[执行器检查](runs/20260928-UNSEEN-READING-RUNNER-PREFLIGHT.zh-CN.md)。目标是让这份公告最多发一次受控请求，并保住旧R2案例的冻结证据和账本。

## 采用的做法

新增 `scripts/freeze_announcement_reading_unseen.py` 和 `scripts/run_announcement_reading_unseen_once.py`。旧的 `freeze_announcement_reading_dev.py`、`run_announcement_reading_dev_once.py` **保持字节不变**：R2冻结清单锁了这两个文件的摘要，直接将它们参数化会使旧包失去可复验性。新脚本可复用现有离线包验证、三字段解析及与案例无关的加锁/原子写/总时限工具；这些被调用的代码也写进新清单摘要。不要调用旧脚本中绑定R2的 `_body`、`verify_frozen`、`_paths`、`_package`、`_interpret` 或 `run_once`。

新案唯一身份固定为 `fr-2026-19516-reading-unseen-v1`；冻结输出在 `evals/announcement_reading_v2/frozen/fr-2026-19516-unseen-v1/`，私有账本目录在 `.local/experiments/announcement-reading-v2/fr-2026-19516-unseen-v1/`。账本、锁、原答、技术审阅各用该案例独立文件名，不能以命令行覆盖成R2目录。旧R2的 `needs_human_review` 记录不改、不重发。

## 冻结器要做的事

1. 首先核对现有 `REFERENCE_MANIFEST.json` 的**既定** SHA-256 `25c2fb7e123128956bfd1e7e0ce8e41496abd294e012cd43bfaca23f27af4895`，再逐个核其中13个文件摘要；不能读取被改后的参考并重新生成一个“正确”清单来放行。锁定的 `request_sha256` 是 `0ebde1623741467e34ef7cc7f2c9ce06046a4a9f0459e719129c3e58f57e8a39`，`doc_version` 是 `docver-4856274e93216a5e`，原文摘要是 `8ca8e250cec45f44dafb77b28d4e243db5439072221878ead7b85f645e5c06e0`。
2. 调用现有 `prepare_announcement_reading_offline.verify`，确认仅1份禁用文档、1个来源、54个锚点、完整原文无损重建以及请求27,615/28,000字节。复制离线 `source-store.json`、`request.json`、`anchor-map.json` 和离线 `MANIFEST.json` 到**新**冻结目录；来源PDF、下载原件、阅读文本、参考文件和参考清单可保留原处并按摘要校验，避免多份手改副本。冻结目录已存在时一律拒绝覆盖。
3. 实际 POST 体只由验证过的 `request.json` 中两条 system/user 消息及本案例确定的服务商参数生成；只允许预定键集合，并逐字节保存 `provider-body.json` 与摘要。参考文本、13项事实表、旧R2答案不能进入任何消息。现有28,000字节是阅读消息门；POST体另设并核对独立大小门，不能把前者当后者。
4. 新冻结清单记录案例身份、材料/参考/代码逐文件摘要、实际消息与POST体摘要、型号/端点/推理与输出上限、总时限、费用预留和 `api_calls=0`。冻结时把新脚本、三字段解析器、离线准备脚本、政策文档存储器、以及实际复用的锁/原子写模块纳入代码摘要。`git_head` 只作线索：该案例材料目前未跟踪，验收依赖逐文件摘要，不能只比对HEAD。
5. 服务候选仍是此前讨论的 DeepSeek Flash/high，但**本案配置尚未冻结**。正式冻结POST体前须核准请求型号与响应型号别名、端点、完整参数、当天官方价格、输入/输出预留及本案计划预算。旧R2的 `$0.03` 不能未经核对直接继承；计划预算也不是账户硬扣费上限。密钥只从现有本机私有配置读取，不写入包。

## 单次执行器要做的事

- 默认命令只做本地预检，显示冻结包身份、摘要、已记录尝试状态和安全的模型配置信息，不建立账本、不发HTTP。
- 真实路径须同时给 `--live`、`--authorize-one-call`、当日价格确认日期，并在发请求前重新核清单、请求体和本机模型配置。模型配置不符即拒绝。
- 在案例独立锁内，先用只限当前用户读取的账本持久记录 `provider_call_started`，才可发唯一一次请求。同案若账本、原答或审阅文件任一已存在，拒绝第二次发送；进程中断或超时保持结果未知，不自动重试。一次性状态不可通过删除文件“复位”。
- 保存完整原始响应及安全元数据；只有 `finish_reason=stop`、非空正文、可核对用量、正确响应型号和现有 `parse_reading_answer` 技术合同通过，才写 `needs_human_review`。该状态**不是13项事实通过**。任何错误保留可核查状态，不写政策候选、不启用、不写MySQL。

## 完成标准与最小验证

实现前先核已锁摘要，拒绝被改的材料或参考；生成后逐字节比较实际待发送体与冻结文件，确认只有这份公告的两条消息。用假服务核对：源文、参考清单、系统提示或请求体分别变更时都在HTTP前拒绝；旧R2冻结包仍可读；两个案例账本互不占用；并发只发1次；400/超时/空正文/截断/错版本/错锚点不自动重试；合法假答案只到 `needs_human_review`。保留原始结果，不用假答案给13项打分。

离线实现及验收完成后，再冻结真实型号、参数、当日费用和一次调用许可。调用之后按[答前参考](../../evals/announcement_reading_v2/unseen-20260928-screen/2026-19516/reference.zh-CN.md)审13项及答案所有主张；真人省事仍需另外测量。失败的同一公告不可改提示后重报“未见通过”。

本步结果：完成方案；决定新增案例专用入口，旧R2脚本及账本保持可复验。
下一步：按此方案实现两个新入口与独立冻结校验，并用假服务核对边界。
下一步模型：GPT-6 Sol High；原因：方案已定，但冻结清单、请求体和账本的接口衔接仍需局部判断；切换：请切换后确认。
