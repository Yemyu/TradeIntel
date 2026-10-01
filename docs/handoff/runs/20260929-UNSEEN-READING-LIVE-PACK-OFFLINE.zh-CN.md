# FR2026-19516 正式调用包：离线实现与验收

日期：2026-09-29。范围仅为[既定配置](../ANNOUNCEMENT_READING_UNSEEN_CALL_DECISION_20260929.zh-CN.md)的实现和假服务验证；**未发送真实模型请求**，也未给13项事实打分。

## 结果

- 新增 `scripts/freeze_announcement_reading_unseen_live.py`、`scripts/run_announcement_reading_unseen_live_once.py`、`tests/test_announcement_reading_unseen_live_once.py`。旧R2和新案离线候选两套脚本没有改动。
- 最终包单独放在 `evals/announcement_reading_v2/frozen/fr-2026-19516-unseen-live-v1/`，不能覆盖；保持原新案 `case_id` 和私有账本槽。实际 POST 体 **27,784 字节**、SHA-256 `3b898bf79fe3efb82d8e0d042338ef61ea7830d1c3b3ffd2990f0101000acbaf`；最终清单 SHA-256 `5bb734beca1bb14423a651109f755c920233687306b0b212d41a2d22e1e5200e`。
- 模型 `deepseek-flash`/thinking high/JSON、`max_tokens=20000`、输入预留40000、180秒。2026-09-29官方峰时缓存未命中价的请求前估算 `$0.036`，计划门 `$0.04`；计划数不是硬扣费上限，实际账单未知。
- 最终执行器发送前强制验证最终清单状态、所有文件及代码摘要、实际请求体和费用门；另须显式单次许可、当天价格确认及已配置的本地模型。使用**同一新案账本**，持久化初始账本文件和目录后才能 POST；未知结果、400、超时及合同失败不自动重试。原答只写私有目录，不写政策候选或MySQL。

## 离线验收

- 相关 `unittest` **44/44 通过**，其中最终包新增14项：候选包误放行、预算为空/超额、来源变化均在HTTP前拒绝；账本写入并同步后才触发假服务；4线程并发只发1次；400、超时、空正文、截断、错模型和错锚点保留记录且不能重发。
- 最终包 `--verify` 返回 `live_eligible_after_authorization`，默认执行器只读预检返回 `not_started`、`provider_calls_by_check=0`，本机配置识别为 DeepSeek Flash。这里的 eligible **只是技术状态，不代表用户已许可收费调用**。
- 新案离线候选仍 `verified_offline_candidate`、原清单 SHA `11221cda...`；旧R2仍 `verified_offline`、原清单 SHA `6abda160...`。旧R2私有账本、原答、审阅三份 SHA-256 在实现前后分别始终为 `216ccd5944ac97780f9f76d9647b4ac23423047fa5288d477e92f9352c3ffb6c`、`cc8acdfa60bb0e9e319619ff5200c809019c40230809080ef1c27a16ad51578a`、`6adf2db7691508261c85d15240ec7ef54739f1df9496b57f04bf5c487fd017af`。
- 本轮真实模型 API 0次、MySQL读写0次。此前项目进度已推到私有 GitHub 分支 `codex/local-release-candidate`（提交 `b639f2b`）；**本包是推送之后的新本地改动，尚未提交/推送**。购买课程原件、`.workbuddy` 与导出PDF未入库。

## 下一关口

发送当天重新核 [DeepSeek 官方价格](https://api-docs.deepseek.com/quick_start/pricing/) 与本机模型配置，确认账本仍 `not_started`、最终包仍可复验；需用户明确同意**本案最多一次、计划门 $0.04 的收费调用**，再由执行器发送。若任何门未过，停止，不以旧候选包或直接 HTTP 绕开。收到原答后按答前13项及所有额外断言审语义；技术合同通过不等于事实通过，真人省事仍 `not_measured`。

本步结果：正式包与14项新增假服务回归完成；旧包和账本不变，0次真实调用。
下一步：在明确单次许可后重核当日价格/状态，只发本案一次并保存原答待语义审阅。
下一步模型：GPT-6 Luna Max；原因：方案和验收门已固定，下一步只需按门执行一次试验并记录结果；切换：请切换后确认。
