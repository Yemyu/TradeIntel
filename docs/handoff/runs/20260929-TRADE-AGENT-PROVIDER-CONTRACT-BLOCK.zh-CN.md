# 贸易 Agent 首题：DeepSeek 高推理工具回合协议阻断

> **后续状态：** 此处记录的是修复前的阻断，现已完成[独立适配层与离线验收](20260929-TRADE-AGENT-THINKING-REPLAY-OFFLINE.zh-CN.md)。未发真实模型请求，真实兼容性仍未证实。

日期：2026-09-29。状态：**真实调用暂停，0 次新模型请求**。本记录修正此前[离线预检](20260929-TRADE-AGENT-PILOT-PREFLIGHT.zh-CN.md)的适用范围；此前的测试结果保留，但不再视为真实调用放行依据。

## 发现和证据

DeepSeek 官方[Thinking Mode 文档](https://api-docs.deepseek.com/guides/thinking_mode/)规定：在启用推理并使用工具时，后续请求必须带回模型返回的 `reasoning_content`；缺失可能收到 HTTP 400。此轮阻断核心是缺失推理回传。后续核查发现官方示例没有附加 `tool_choice`，且其[集成说明](https://api-docs.deepseek.com/quick_start/agent_integrations/oh_my_pi/)警告该可选参数可能被推理模式拒绝；新适配层因此省略它，不再沿用旧笔记对 `auto` 的乐观判断。官方[模型与价格](https://api-docs.deepseek.com/quick_start/pricing/)目前将 `deepseek-flash` 对应为 DeepSeek-V4.1-Flash；价格会变化，实际收费前还须重新核对。

现有 `src/tradeintel_ai/model_adapter.py` 解析模型回答时没有保存 `reasoning_content`，封装后续 assistant 工具消息时也未送回；`src/tradeintel_ai/trade_agent.py` 只续接 `content` 与 `tool_calls`。此前三轮工具测试的假服务未返回 `reasoning_content`，故不能证明真实 DeepSeek 高推理多轮兼容。第一轮真实请求可能产生费用，第二轮才因协议缺口失败。

## 已做的安全处理与验证

- `scripts/run_trade_agent_pilot.py` 设显式关闭门 `THINKING_TOOL_REPLAY_VERIFIED = False`；当前离线/真实入口均会返回受控错误，不能通过命令行开关绕过该门。
- 相关首题脚本单测 2/2 通过；手动离线入口也确认返回受控暂停提示，未发请求。
- 没有创建首题真实调用账本；没有修改历史模型成绩、旧公告账本、原始数据或服务商凭证。

## 下一阶段最小修复与验收

由 GPT-6 Sol High 处理局部接口判断：接收 DeepSeek 返回的非空 `reasoning_content`，在**仅内存**的工具回合中原样传递，在下一次请求的对应 assistant 消息中回传；不输出到用户对话、页面、通用日志或持久账本。构造会检查回传字段的假 HTTP 服务，要求至少三轮工具交互全过，并有缺字段即失败、非推理模型路径不受影响的反例。通过后才移除首题关闭门、重新跑离线预检；仍需用户单独授权一次收费调用，不能把离线通过写成真实模型事实准确率。
