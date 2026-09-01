# Phase 10c 学习版：把真实模型接到已有工具上

> 当前状态：已完成一个可替换的 OpenAI-compatible HTTP 适配器和离线契约测试；尚未用真实 API key 运行模型评估。

## 这一阶段到底在学什么

前面的阶段已经把“工具能查什么、返回什么、什么时候必须拒绝因果结论”固定下来了。本阶段不重新设计数据分析，也不把模型变成数据库管理员，而是学习一个工程边界：

> 模型服务的请求格式可以变化，但项目内部的 `ChatModel` 接口和六个工具契约不变。

这层翻译程序叫 **model adapter（模型适配器）**。它像一个插头转换器：一边是项目统一的消息和工具调用，另一边是某个模型服务的 HTTP JSON 格式。

## 先理解几个词

### Provider 和 endpoint

Provider 是提供模型的服务商或本地推理程序。Endpoint 是程序发送请求的 URL。不同 provider 可能有不同域名、模型名和认证方式。

“OpenAI-compatible”只表示请求/响应采用一种常见的聊天与工具调用 JSON 形状，不表示项目只能使用 OpenAI，也不表示所有服务的行为完全一样。

### API key

API key 是访问远程模型的秘密凭证，类似密码。它不是代码，也不是数据。它只能放在当前电脑的环境变量或本地密钥管理器中，不能写进 `.py`、README、测试输出或 Git。

本项目使用带项目名前缀的变量，避免把个人机器上别的项目凭证误当成 TradeIntel 配置：

```bash
export TRADEINTEL_MODEL_BASE_URL="https://你的服务/v1"
export TRADEINTEL_MODEL_NAME="你的模型名"
export TRADEINTEL_MODEL_API_KEY="只在当前终端暂时存在的密钥"
```

如果服务运行在本机，也可以把 `BASE_URL` 改成本地地址；本地服务可能不需要 key。不要把上面的真实密钥复制给我或提交到 GitHub。

### Tool calling

模型不会直接执行 Python 函数。它先返回“我想调用 `get_policy_event`，参数是……”的结构化请求；`ToolCallingAgent` 验证并执行已登记工具，再把工具结果返回给模型。模型最后只负责组织语言。

因此要区分：

- 模型选择工具：有一定不确定性，需要评估；
- Python 工具的数字、日期边界、来源和因果状态：由确定性代码控制；
- 最终文字：仍要经过安全后卫，不能把 blocked 状态写成“关税导致”。

### 为什么暂时不用 SDK

SDK 可以减少几行 HTTP 代码，但会把“服务商格式”和项目逻辑混在一起。当前用 Python 标准库实现一个很薄的适配器，先看懂边界、请求、响应和错误；将来需要流式输出、重试或某家 SDK 时，可以只替换这一层。

## 代码怎样分工

| 代码 | 负责什么 | 明确不负责什么 |
| --- | --- | --- |
| `agent.py` | 有上限的模型—工具循环、安全后卫 | 不知道某家服务商的 HTTP 格式 |
| `model_adapter.py` | HTTP 请求、工具 schema 翻译、响应解析 | 不计算贸易数字、不改变因果权限 |
| `tools.py` | 固定查询、参数校验、来源和限制 | 不调用模型 |
| `repository.py` | 读取已经核验的 CSV/JSON 证据 | 不接受模型传入的任意 SQL |

## 怎样先离线学习和测试

不设置任何 API key 也可以运行：

```bash
source .venv/bin/activate
python -m unittest tests.test_tradeintel_ai_model_adapter -v
python scripts/run_tradeintel_ai.py --mock-agent "关税导致中国进口下降了吗？"
```

离线测试会检查：

1. 项目内部工具 schema 是否正确转换成 provider 需要的嵌套格式；
2. 工具调用参数是否能从 JSON 还原；
3. 无内容的工具调用响应是否能处理；
4. 非法 JSON、HTTP 错误是否会安全失败；
5. API key 不会出现在异常文本中；
6. system prompt 会提醒模型遵守证据和因果边界。

## 有 key 后怎样做一次真实冒烟测试

先在当前终端设置三个变量，再运行：

```bash
source .venv/bin/activate
export TRADEINTEL_MODEL_BASE_URL="https://你的服务/v1"
export TRADEINTEL_MODEL_NAME="你的模型名"
export TRADEINTEL_MODEL_API_KEY="你的密钥"
python scripts/run_tradeintel_ai.py --live-agent "2018 年 Section 301 List 1 后中国相关商品进口变化是多少？"
```

`--live-agent` 没有配置模型名时会立刻返回配置错误；请求失败时只显示 HTTP 状态或连接问题，不显示密钥和完整请求体。当前没有 API key 时，不应把 Mock 结果写成真实模型效果。

## 这一步的验收门槛

- **对照基线**：已有确定性路由和离线 Mock 模型；它们必须继续可运行。
- **防泄漏**：模型只收到六个已登记工具的 schema 和工具返回值；不读取隐藏答案、政策后结果匹配面板或 MySQL 凭证。
- **采纳门槛**：适配器离线契约测试通过；完整项目测试不回归；至少一次真实调用能返回合法文本或合法工具调用；因果越界断言仍为 0。
- **停止条件**：服务格式不兼容、请求失败或真实模型评估未达到既定指标时，保留 Mock/确定性模式，不继续堆 LangChain、RAG 或多 Agent。

60 道评估题的现有 100% 结果只是工具契约基线。接入真实模型后必须重新记录模型名称、日期、配置和每道题结果，才能讨论真实模型是否通过。

## 你需要真正掌握的判断

你不需要背 HTTP 语法。你需要能回答：

1. 为什么 key 不能放进 Git？因为仓库历史可能长期保留秘密，删除当前文件也不等于撤销历史泄漏。
2. 为什么工具 schema 不能让模型随意改？因为 schema 是模型可请求的权限清单，扩大它就等于扩大系统权限。
3. 为什么没有 key 仍然先做适配器？因为可以先验证协议、错误边界和安全规则，不把网络、费用和模型质量混入基础测试。
4. 为什么真实模型回答得很流畅仍可能不合格？因为流畅只代表语言质量；数字、来源、工具选择和因果边界必须单独评分。

