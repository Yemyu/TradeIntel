# 公告抽取模型试跑：服务与请求预检

日期：2026-09-26。此记录为离线预检，真实API调用0次。

## 当前可用配置

项目的本地产品配置已设为 DeepSeek `deepseek-flash`、`reasoning_effort=high`，此前的短连接状态为 connected（2026-09-26 01:29 UTC）。短连接仅证明当时“Reply with OK”请求通了，不代表公告抽取质量或本轮调用已开始。本轮不改产品配置，不读取或复制密钥到实验材料。

DeepSeek 官方当前接口列出 `deepseek-flash`、`deepseek-v4-pro` 两个名称；官方模型表把 `deepseek-flash` 对应到 DeepSeek-V4.1-Flash。Chat Completions 支持 thinking enabled、`reasoning_effort=high`、JSON Output 和 `max_tokens`；本文据此选 Flash/high 作为唯一试跑候选，不把 Flash 的后端名误写成独立“4.1 API 型号”。[模型与价格](https://api-docs.deepseek.com/quick_start/pricing/)、[Chat Completions参数](https://api-docs.deepseek.com/api/create-chat-completion/)、[思考模式与档位](https://api-docs.deepseek.com/guides/thinking_mode/)。

## 最终请求体离线测量

请求固定为：`model=deepseek-flash`、`thinking.type=enabled`、`reasoning_effort=high`、`max_tokens=4096`、`response_format.type=json_object`、`stream=false`；不额外传 temperature。发送正文由已验证包的 `request.json` 生成，provider HTTP 请求体实际字节为：

| 案例 | 请求体字节 | SHA256 |
|---|---:|---|
| R2 | 23,866 | `e59b09a216f9e04e67ed0f57304d105d85b1c5ea0d6b635817bf20e9ec920e09` |
| D2 | 9,585 | `c127004767322ceb85603ade8e6df521edfd432b0891822e0273a626a3ebee04` |
| H1 | 11,007 | `068162a3c1b20c17632b3ed943ac036d1bdf278baae5889f333b12198d7a587a` |
| H2 | 7,690 | `3e7f3dfd2566a00867b02a4a09a930c443c39863e499cd1b69679b8970734ddd` |

四份都低于24,000字节硬门。R2仅余134字节，所以不能加任何额外消息字段；改模型名或发送参数后须重新计算，不做截断。

## 费用门提案与执行顺序

官方页面目前按峰时价格列 Flash 输入未命中 `$0.30/百万tokens`、输出 `$1.20/百万tokens`；非高峰价格减半。按每次输入最多24,000 tokens、输出最多4,096 tokens作预算估算，每次约 `$0.01212`，最多4次约 `$0.04846`。这是按当前公开峰时单价和token上限推算的保守估值，不等于实际账单，也不是供应商侧硬封顶。计划把整轮本地放行上限设为 `$0.10`；以用量账单为准，任何用量未知的响应后停止后续调用。[DeepSeek价格](https://api-docs.deepseek.com/quick_start/pricing/)。

按设计最多执行 R2→D2 两道开发题；两题均通过门槛后才可继续 H1→H2。每题一次，不自动重试；中断或用量未知会占用该题名额并停止。正式报告仅记录模型原答和字段分数，手工评分不能盖掉原答。H1/H2已参加方案设计，结果只能写“两个固定案例内部验收”，不能写盲测或总体准确率。

下一实现阶段需新增独立执行器：只从本地受保护配置取密钥，验证已冻结包和最终请求字节，先原子写入“已开始”账本，再调用；响应正文先保存，再作合同与评分准备。连接错误、超时、空响应均不重发，不能输出密钥、请求认证头或服务端错误原文。完成执行器及离线拒绝路径后，才开始R2单题。
