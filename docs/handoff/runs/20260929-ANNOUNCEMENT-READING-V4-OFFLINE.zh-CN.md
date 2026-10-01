# 公告阅读 v4：离线合同与只读页面

日期：2026-09-29。范围只包括独立 v4 合同、离线包、合成假回答和页面只读适配；没有新真实模型调用，也没有第三份未见公告。

## 改了什么

- `src/tradeintel_ai/announcement_reading_v4.py`：完整保存原文生成编号段落；要求模型只返回十个固定检查点的 `status/claims/note`。模型不再生成 `claim_id` 或双向关联，程序按固定顺序编号并映射到原有三栏。提示与解析器均明确状态规则、来源身份和长度门；`addressed` 允许非空备注，`incomplete` 使整份笔记不就绪。仅核结构与引用位置，不证明法律含义。
- `scripts/prepare_announcement_reading_v4_offline.py`：生成离线请求、来源锚点和最后写入的摘要清单；核验时重建请求与已保存公告比对。清单显式标记未构造真实 POST、0 次 API。
- `scripts/run_announcement_reading_v4_fake.py`：保存假回答、经过同一 v4 解析器的只读结果和摘要；无服务商客户端。
- `web/announcement-import.html`：识别 v4 标准化结果，沿用三栏和原文定位；旧 v2/v3 分支仍可读。页面不自动写13字段、不提交、不启用候选。
- `tests/test_announcement_reading_v4.py` 与页面测试：54 段合成公告、不同措施/国家/日期、可带备注的已回答、partial/conflict/not_stated/not_applicable/incomplete、十键缺失/多余、身份错误、锚点错误/重复、重复 JSON 键、超限、包篡改及只读页面反例。

## 验收

- `PYTHONPATH=src:. .venv/bin/python -m unittest tests.test_announcement_reading_v3 tests.test_announcement_reading_v4 tests.test_announcement_reading_v3_source tests.test_announcement_reading_v3_reference tests.test_announcement_reading_v3_once -q`：28/28 通过。
- `node --test tests/announcement_import_ui.test.cjs`：10/10 通过。
- 用两份**已见**官方保存材料只读测 v4 完整消息：FR2026-19516 为 29,135/32,000 字节，FR2026-19517 为 7,897/32,000 字节。不构造真实 POST，也不宣称语义通过。
- `git diff --check`：通过。未跑项目全量测试；本轮未调用模型 API、未访问 MySQL、未提交推送。

## 保持不变与停止门

v2/v3 冻结源码、正式请求、原答、一次性账本和两案 `invalid_response/answer_contract` 结论不变。合成案例与假回答仅证明机制，不是模型准确率或真人省时。没有新来源和答前事实参考、真实 POST 预算/一次性账本、模型与当日价格及单案许可之前，不发第三次付费请求；同两案不重跑来刷通过。

本步结果：v4 离线合同、反例、假回答和页面只读适配完成；相关 Python 28/28、Node 10/10，通过离线门但没有模型语义成绩。
下一步：先只读核对产品主线待办，再决定下一交付是否继续公告试验。
下一步模型：GPT-6 Sol Max；原因：下一步是两条产品路线的优先级与验收取舍，方案尚未确定；切换：请切换后确认。
