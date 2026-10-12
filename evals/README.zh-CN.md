# 评测材料

[English](README.md) | **简体中文**

[项目介绍](../README.zh-CN.md) · [模型测试结果](../docs/MODEL_SELECTION.zh-CN.md) · [工程测试](../docs/TESTING.zh-CN.md)

本目录提供结构化测试题、评分要求、参考答案和版本清单。题目或参考文件的存在不表示对应模型已经通过测试；当前公开成绩及其限制见模型测试结果页。

## 当前模型测试

[us_agent_retest_v1/scenarios.json](us_agent_retest_v1/scenarios.json)包含12个美国贸易场景：商品查找、进出口追问、换商品、政策检索，以及缺月份、伙伴不支持和税率证据不足等边界题。文件保留原设计版本；实际执行方式、完成率和报告核数见[测试结果与评分方法](../docs/MODEL_SELECTION.zh-CN.md)。

GPT组通过Codex聊天作答，DeepSeek与GLM通过应用API执行。GPT成绩不确认应用的GPT API兼容性。部分对话包含此前测试上下文，不能视为独立盲测；评分使用AI辅助核验，报告金额另与数据文件核对。

## 其他题目与评分资源

- `questions.jsonl`、`gold_answers.json`：早期工具契约开发题和事实参考。
- `final_questions.jsonl`、`final_gold.json`、`final_manifest.json`：40题候选集、评估者参考与原冻结版本信息。
- `trade_model_v4/`：固定报告解读题、程序生成的报告基线及评分JSON，用于模块回归测试。
- 其他JSON、JSONL和CSV：各模块的开发题、验收输入、参考或版本信息；用途与状态以文件中的说明为准。

这些材料由项目维护者设计，不是第三方独立基准。模型只能接收题目及授权工具提供的证据，评估者专用答案和预期字段不能进入模型请求或反馈。AI参与初评时应标记为`ai_assisted`，不能称为独立人工审核。

历史运行的会话、原始输出及部分冻结证据保存在本地，未随公开源码完整提供。版本清单可能引用这些原始路径和摘要，用于核对历史版本；仅克隆仓库不能复现全部历史实验。
