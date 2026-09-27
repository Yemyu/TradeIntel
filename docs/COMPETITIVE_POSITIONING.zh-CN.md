# TradeIntel 与相邻项目的区别

更新时间：2026-09-22

## 一句话

很多 Claude 项目或开源项目是“让模型去找资料并解释”；TradeIntel 的核心做法是“先由程序锁定范围、版本和数字，再让模型解释已经核验过的事实”。

这不是说 TradeIntel 的模型更强，也不是说它覆盖的数据更多。它的差异在于事实责任的分工。

## 对比

| 类型 | 主要解决什么 | 通常由谁决定事实 | TradeIntel 的区别 |
|---|---|---|---|
| Claude Projects / 普通 Claude RAG | 在上传的文件中检索相关段落并回答 | 模型根据检索结果组织答案 | 不把金额、分母、月份和商品范围交给模型猜；这些由发布版本和确定性查询产生 |
| Claude Code customs skill | HTS 分类、海关法律、裁定和合规草稿 | 技能规则 + 模型 + 外部资料 | TradeIntel 不做通用海关法律顾问，而是做政策与贸易统计的可复算简报 |
| Claude 插件/商业贸易平台 | 广泛的关税线、裁定、合规和落地成本 | 平台数据库和模型 | TradeIntel 数据范围较窄，但每次报告绑定政策版本、数据版本、商品范围和来源 |
| 普通 RAG / Agent demo | 展示检索、工具调用、对话和流程编排 | 模型和工具调用结果 | TradeIntel 把提案、确认、证据、审阅、导出设计成一条受控链，而不是单纯展示 Agent 流程 |

## 特别是 Claude 做的项目

这里要区分两种情况：

1. **用 Claude Projects 做的项目**。Claude 的项目知识库可以在资料变多时自动启用 RAG，模型搜索相关文件后回答。它很适合快速做“企业资料问答”，但通常没有贸易统计中的严格分母、版本冻结和查询确认。
2. **用 Claude Code 生成的项目**。它可以很快搭出前端、RAG、MCP 和 Agent 工作流。代码能否运行不等于研究结论可靠；如果没有独立参考答案和失败门，仍然可能把错误数字写进报告。

已有例子说明了这个差别：

- [customs-trade-law](https://github.com/onurkafk/customs-trade-law) 是 Claude Code 的美国海关/贸易法技能，定位是生成需要律师或报关师复核的草稿。
- [Rosetta Claude 插件](https://github.com/Colab8/rosetta-plugin) 面向广泛海关智能，连接商业数据源，覆盖分类、关税和合规。
- [Global Trade Alert 的 Claude 接入](https://globaltradealert.org/blog/gta-evidence-in-your-ai-assistant) 可以从其数据库检索干预记录并返回来源引用。
- [manifest-rag](https://github.com/arvindcr4/manifest-rag) 是更接近研究型工程的开源例子，强调混合检索、cite-or-refuse 和评测集。

这些项目并不与 TradeIntel 完全竞争：它们有的资料更多、有的法律范围更广、有的产品体验更成熟。TradeIntel 当前的定位更窄，但把以下链条作为产品本身：

```text
自然语言问题
  → 服务端范围提案
  → 用户确认商品和时间范围
  → 固定政策/数据版本
  → 程序计算金额、占比和比较
  → 模型解释事实，不改写数字
  → 人工审阅与导出
```

## 诚实的结论

TradeIntel 目前不是“所有方面都比 Claude 项目好”：

- Claude 项目通常更快、更通用，检索的资料范围也可能更大；
- TradeIntel 目前数据范围较窄，浏览器完整链和正式模型评测还没有收口；
- TradeIntel 真正能写进申请材料的点，是对“模型可能说错”做了工程化限制，并把失败、版本和证据保留下来。

因此，公开介绍时不要写“我们做了一个更强的 Claude”。更准确的说法是：**我们把通用模型放在一个可追溯的贸易数据研究流程里，让它负责解释而不是负责凭空决定事实。**
