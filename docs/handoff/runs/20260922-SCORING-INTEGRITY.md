# 2026-09-22 评分真实性修复

## 已实施

- 汇总重新计算raw-response.txt摘要，核对唯一started、待审阅事件、题号、provider、冻结摘要、请求摘要、参数、渠道、实际输出目录及validation产物。
- 空interpretations不再进入待语义审阅状态，返回needs_revision；缺失finish_reason不能当作正常结束。
- 离线注入明确标offline_injected，api_calls=0；与真实API的去重身份区分。
- 汇总按模型配置、冻结和渠道分行。待审阅显示通过数/收到数，但不提前发布百分比。
- record_review重读原答和验证产物，拒绝空答案或摘要不符；审阅CLI按run-id查找唯一对应记录。

新增反例覆盖原答在审阅前/后被改动、缺少账本、空答案、模拟API次数和未审阅百分比。测试中的示例解释只用于协议测试，不是模型回答，也不代表语义质量评测。

验证：`PYTHONPATH=src:. .venv/bin/python -m unittest tests.test_public_eval_scoring tests.test_public_eval_controls tests.test_public_brief_eval_runner tests.test_public_explanation_flow tests.test_session_explanation_flow`，30项通过。`git diff --check`通过。未运行全量套件。

## 未完成／不得冒称

正式四题仍未调用。不宣称执行器完全验收：思考与正文预算分离、冻结到发送的完整绑定、四项语义评分逐项记录仍待集中完成。现有部分测试依赖本地候选题包，不等同干净克隆可复现的独立测试集。

不把旧全量测试的失败一概称作历史失败；本轮只报告实际运行的定向测试结果。未动旧冻结记录、未提交、未推送。
