# 2026-09-23 政策Q3提示格式修复 r1

后续状态：内容核查已完成，单题开发验收1/1；原答接入待审阅报告预览。详见[逐项审阅](20260923-POLICY-Q3-SHAPE-R1-REVIEW.zh-CN.md)。下文“尚待完成”记录调用刚结束时的状态，现已由该审阅覆盖。

## 结果

- 执行档：用户确认GPT-6 Luna Max。
- 仅修改`src/tradeintel_ai/public_policy_explanation.py`两处提示文字：明确`policy_explanations`是三项JSON数组、topic必须逐字使用三个英文枚举，并说明数字限制针对text/rationale正文。
- 解析器、v2数据合同、证据、题目、评分门槛均未修改；旧正式Q3结果0/1未改。
- 新增回归从真实提示抽取JSON示例，验证示例字段与原解析器一致；填入合成占位内容后解析器仍只给`manual_review_required`。对象形状、中文topic、未填source占位符均继续被拒绝。
- 定向测试：`tests.test_public_policy_explanation`、`tests.test_public_policy_eval_runner`、`tests.test_public_explanation_flow`、`tests.test_session_explanation_flow`，共38项，全部通过。

## 新候选材料

- 候选包：`tmp/public-brief-eval-v1/policy-q3-candidate-20260923-shape-r1`
- 包状态：`candidate_only_not_frozen`
- 协议：`public-policy-explanation-prototype-v2`（未升级）
- 输入估算：15,857 / 16,000；UTF-8大小32,164字节。估算余量143 tokens，不应再加提示内容。
- `user`消息与r5完全一致，SHA256：`389a5228a1478380bcfab7797f7d9213365f399c79f900cc5668f2b2f7d15621`。
- 新system提示SHA256：`38011acae6802074b376bd43f8b8342d7779e3e062503eeb03da57e807c743ae`，与方案中的精确修改一致。
- MANIFEST SHA256：`511ae11d32ab6179d31ddecc2fd23670cafe6aceaf6d6f4a6f566f39dbbe8677`。
- candidate冻结：`tmp/public-brief-eval-v1/policy-freezes-20260923/flash-high-policy-q3-shape-r1-candidate.json`，状态`candidate_not_formal`；冻结摘要：`092ed53494bc4b017b5c399d59b8fe6ee89b5dcb4def2b805c613af9953ab9ec`。以指定high_v2矩阵独立复核通过。

## 单次真实调用结果

- 正式冻结：`tmp/public-brief-eval-v1/policy-freezes-20260923/flash-high-policy-q3-shape-r1-formal.json`，状态`ready_for_formal`，摘要`bde36902c1c62227c45845f7766d8ba59f7804091ee751c2a3d370cb1e724a55`。
- 调用：DeepSeek-V4.1-Flash（请求及响应 API 名均为 `deepseek-flash`），thinking enabled / high；1次请求、1份回答、无重试；耗时33.166秒。官方依据和与旧 `deepseek-v4-pro` 别名的差异见[模型记录](../../MODEL_SELECTION.zh-CN.md)。
- 供应商用量：prompt 11,563 tokens，completion 6,856 tokens（其中reasoning 6,105），total 18,419；人民币费用未知。
- 原始响应SHA256：`22bd9b48cb506e36c6d65251b44e0618e19ccf61bff9afdb22f7d3d147942a6b`；文件：`tmp/public-brief-eval-v1/policy-q3-shape-r1-real-20260923/q3/raw-response.txt`。
- 机器验收：finish_reason=`stop`；v2原解析器直接接受三项policy解释、五项贸易解释、三项watchlist；v3输出预算全门通过（completion 6,856/8,192；说明正文846/2,000字符；3,311/65,536字节）。状态为`awaiting_semantic_review`，不是内容通过或可发布。
- 请求与冻结的user证据未变；没有参考答案、旧回答或评分材料进入提示。旧r5的0/1失败仍保留且不与本次合并。

## 尚待完成

需逐条核查模型陈述是否得到其引用的政策原文或贸易观察支持，并标出无支持、超出范围、混淆附加税与综合税则、因果/价格过度推断等问题。该审阅是非盲、AI辅助判断，不替代领域专家；建议下一阶段使用GPT-6 Astra Medium，因为结构测试无法判断语义蕴含。审阅通过后也只可报告“已见开发题的一次提示格式试验通过”，不能推断普遍可靠性或修改旧成绩。

API密钥未写入项目文件或结果文档；本轮未提交、未推送。用户可在本次调用后撤销/轮换该密钥。

## 范围与工作区

未安装依赖；未修改旧冻结、旧回答或历史分数；未提交、未推送。原工作区已有大量未提交/未跟踪内容，均保留不动。除本记录外，已更新方案状态、`docs/handoff/STATUS.zh-CN.md`顶部及`docs/PROJECT_CONTEXT_REFERENCE.zh-CN.md`当前恢复点。
