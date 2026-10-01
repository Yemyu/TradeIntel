# 贸易 Agent：DeepSeek 高推理工具回传离线验收

日期：2026-09-29。状态：**协议离线验收通过，真实模型未调用**。承接[调用前阻断](20260929-TRADE-AGENT-PROVIDER-CONTRACT-BLOCK.zh-CN.md)；不修改历史旧案的成绩、冻结摘要和一次性账本。

## 修改范围

- 新增 `src/tradeintel_ai/trade_agent_deepseek.py`：只在 DeepSeek 且 `thinking=enabled` 时使用独立工具适配层；从服务商回答取回 `reasoning_content`，下一轮携同一 assistant 工具消息原样回传；允许官方合同中的可空值，缺字段或类型错误则受控停止。使用历史通用适配器的发送、错误清理及工具解析，但不修改历史冻结的 `agent.py`、`model_adapter.py`。
- `trade_agent.py` 只在当轮内存消息附带该字段及原始 `content`（包括 `null`）；会话存档、公开报告和工具摘要均不接收推理内容。模型结果的对象表示也隐藏推理字段。
- 产品网页的贸易 Agent 路径和独立首题入口都选用同一个新适配层；非推理/其他厂商仍走旧路径。首题入口的源码版本快照纳入新文件。
- DeepSeek 官方[思考模式示例](https://api-docs.deepseek.com/guides/thinking_mode/)未附加可选 `tool_choice`，而[集成说明](https://api-docs.deepseek.com/quick_start/agent_integrations/oh_my_pi/)警告思考模式可能拒绝该参数；新适配层不发送它，保留 `tools` 及其默认自动选择。旧通用适配器行为不变。

## 验收

- 假 HTTP 模拟 DeepSeek 连续三轮工具调用，每轮验证之前所有 assistant 的 `reasoning_content` 与 `content` 均被完整回传；刻意缺字段时只产生一次响应并停止，不会继续产生第二次收费请求；显式 `null` 与字段缺失分开处理。
- 私有账本、公开会话结果都不含测试推理标记或测试密钥；产品模型选择对 DeepSeek 推理、DeepSeek 非推理和其他端点分别核对。
- 相关 Python **42/42** 通过，包括原通用适配器、贸易 Agent、网页接口及报告追问测试；`git diff --check` 通过。未重跑全仓历史冻结实验和浏览器视觉验收。
- 本机首题**离线**预检重新得到 `offline_ready`；实际首轮请求 **4,167 字节**，六个工具，DeepSeek Flash/high，数据/分类版本与事前参考一致，快照 `9d0a60baf358bc2bdd87cb837332dded9c66ab190b42279a98b991340a5b3ddd`，首题真实账本不存在。没有发送 HTTP 模型请求。

## 仍待验证

假服务只验证请求结构与本地流程，不能代表 DeepSeek 真实端点一定接受参数或模型会选对商品、月份和数字。下一步先只读复核当天官方价格、账户可用状态和快照；然后必须等用户明确授权**首题一次收费尝试**才运行。若真实请求返回 4xx、未知结果或严重事实错误，按事前五题方案立即停下，不重发首题刷成绩。
