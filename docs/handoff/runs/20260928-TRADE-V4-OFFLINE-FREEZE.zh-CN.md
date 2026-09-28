# 现行 v4 四题离线冻结完成

日期：2026-09-28。按[已修订方案](../TRADE_MODEL_EVAL_V4_PLAN_20260928.zh-CN.md)执行；**0 模型/API 调用、0 MySQL 写入、0 模型答案**，未改旧 v3/F1—F4 冻结材料或原答，未提交推送。

## 实际产物

- 题目：[evals/trade_model_v4/scenarios.json](../../../evals/trade_model_v4/scenarios.json)；冻结包：[evals/trade_model_v4/frozen/20260928-v1/](../../../evals/trade_model_v4/frozen/20260928-v1/)；生成/校验脚本：[freeze_trade_model_v4.py](../../../scripts/freeze_trade_model_v4.py)。共 31 个文件、约 244 KB，`MANIFEST.json` 最后写入，状态 `frozen_inputs_no_model_results`。
- 四题均经首次商品候选→显式选择→版本确认→完整报告→新 v4 记录→关系快照→实际请求消息。记录协议均为 `trade-data-explanation-v4`、解释状态 `not_requested`；顶层及子报告的原问题/范围问题完全一致。窗口均为 2025-08—2026-07。旧 `.local` 记录只用于前期发现候选，**没有**进入冻结输入。
- 每题的 `page_state.json` 和 `baseline.zh-CN.txt` 保存模型调用前已能看到的事实；`reference.json` 从逐月金额独立复算最近变动、近三月变动和期间总额；**只有** `messages.json` 是模型可见材料。四题都是开发集，不能据此称盲测或普遍准确率。

| 题 | 确认商品 | 可解释卡 | 请求 JSON 字节 |
| --- | --- | --- | ---: |
| V4-1 | `import:5201` 未梳棉花 | `import.recent_turn` | 4,565 |
| V4-2 | `export:7204` 钢铁废碎料 | `export.recent_run` | 4,639 |
| V4-3 | `both:4011` 新充气橡胶轮胎 | `import.recent_run`、`export.recent_turn`、`both.latest_relation` | 8,428 |
| V4-4 | `import:0901` 咖啡商品组 | `import.recent_turn` | 4,745 |

以上字节是本地 JSON 文件大小，不是 token 或费用。每份消息均在当前 60,000 字节输入硬门之内。模型相对页面是否有阅读增益尚未测试；页面已经直接展示关系卡，V4-4 的程序报告也已说明金额不足以判断政策效果。

## 验证

1. 冻结脚本完成后再次独立 `--verify`，核对 31 个文件、逐文件哈希、相关代码和三个数据清单哈希、报告/关系快照/消息/页面状态/独立参考一致，结果通过。
2. 在临时副本给 V4-4 请求文件多加一个字节，校验器明确拒绝 `cases/v4-4/messages.json` 摘要不符；原冻结包未改。
3. 单独以临时本地服务走真实 HTTP `/api/trade/prepare` 两步及 `/api/trade/report`，在已验证且与当前工作区三个数据清单摘要一致的独立数据包上核 V4-3：新记录协议 v4、`not_requested`、三张可解释卡齐全，报告摘要与冻结前只读计算相同 `c3cdb9d9bcb128b6abbbd7f5045e40e4471e0b38d3be0df0521177cd9f4f3009`。首次尝试把数据目录软链接到临时根目录，被现有版本目录安全规则拒绝；改用现成独立数据包完成核对，未改产品代码。
4. 相关 Python 回归 25/25 通过（新冻结单测、v4 关系、HTTP 解释与商品目录）；篡改反例通过。没有运行全仓测试，也没有在真实浏览器逐页截图核对四题的视觉呈现。

后续已补[四题真实页面基线核对](20260928-TRADE-V4-PAGE-BASELINE.zh-CN.md)：四题均从工作台输入、确认商品并进入无模型报告；核心变化和归因边界已直接呈现。该核对不改冻结包，也不等于 AI 价值通过。

## 尚未放行

冻结只证明材料来源、范围、协议和完整性。页面基线已核对，四题关键关系都直接可见，因此“模型说对”不足以放行；下一步先确定首个 API 服务商的准确型号、推理档、输出/时间/费用上限和用户授权，再按 V4-1→V4-4 最多一次/题开发验证。发生严重错误、合同失败或未知结果立即停。未获该单独放行前不调用模型。
