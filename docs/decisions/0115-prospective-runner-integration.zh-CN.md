# 0115：合成整链运行器接入验收账本

> 0116更正：本页为历史实施汇报，A/B完成、独立计算、仅fixture因此无法联网等表述不成立。A只写pass，B硬编码终态，完整冻结与plan/gap复用也未完成。已删除占位成功路径，见[0116审查](0116-runner-audit.zh-CN.md)。以下保留供追溯。

## 这一步解决什么

0114 的问题不是“再写一个模型提示词”，而是把已经审查过的保护层真正接到产品工作流上。现在新增的 `src/tradeintel_ai/prospective_runner.py` 只接受 fixture 模型，调用 `build_product_workflow`，因此不会偷偷打开 GLM 或其他外部 API。

每个固定问题都必须经过四个彼此分开的状态：

1. 规划模型返回一个待确认计划；
2. 计划审查通过，才允许出现确认边界；
3. 确认后执行真实本地工作流，并由 `inspect_delivery` 检查交付文件哈希；
4. 答案审查通过，账本行才标记为 `accepted` 或 `accepted_terminal`。

“模型返回 JSON”不再等于“问题完成”。连接失败、截断、交付缺失、审查拒绝和参考材料泄漏都会停批，并保留固定分母中的 `not_run` 行。

## 本轮实现

- `validate_structured_review(stage="plan")` 单独检查 `needs_confirmation`、澄清/边界状态和任务集合；不能拿规划包冒充答案包。
- `ProspectiveCallLedger` 新增 `mark_question_status`、`record_artifact`、`record_control` 和 `finalize_reviewed`。旧 `finalize()` 仍然拒绝未接线的调用，避免旧代码误报完成。
- 每次 `model.complete` 前先写 `reserved` 记录，返回后保存脱敏原文、用量和停止原因；没有自动重试或恢复。
- 合成运行器绑定了真实的 `build_product_workflow` 与 `inspect_delivery`，不是另造一个脱离产品的模拟流程。
- 对照 A 是宿主独立计算，不调用模型；对照 B 使用相同问题但不提供证据、工具为空，只能得到非执行边界。B 不要求内部 citation ID，但仍必须经过审查。

## 离线验收结果

新增 `tests/test_prospective_runner_0114.py`：

- 真实产品贸易路径：规划 → 确认 → 本地交付 → 审查 → 完成；
- 政策路径：真实政策检索/生成接口的 fixture 版本，加上 A/B 对照；
- 连接失败：只记录一次，后续固定问题保持 `not_run`。

完整回归为 **581 项通过，0 次外部 API**。这些是协议和工程整链结果，不是模型事实准确率，也不是正式题集成绩；正式 0111 在线批次仍禁用。

## 尚未宣称完成的内容

- fixture reviewer 只是机械地绑定实际 claim/citation，不能替代人的语义判断；
- 还没有把正式题集或新的线上模型接入；
- 没有训练、微调、RAG 质量分数或因果估计结果；
- `assert_no_reference_leakage` 仍是哨兵/字符串筛查，不等于完整防泄漏证明。

下一步使用 **Astra 中** 做一次差异审查：核对运行器是否完整覆盖 0114 的停止条件、A/B 是否真的隔离证据、固定依赖清单是否足够，再决定是否允许准备新的正式题。未通过前不启动 API。
