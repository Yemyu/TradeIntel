# v4参考覆盖缺口：只读事后诊断

日期：2026-10-01；0新API，未改产品或旧输入/结果，未提交推送。本记录不是新批次成绩。

## 实际运行的诊断

从冻结数据包的进口manifest与CSV独立筛选HS4=1201、全部来源、observed=1，核BUNDLE登记hash/大小、行月份/来源与19个月公开报告的金额、观测/匹配细码计数及来源。未调用repository.query或报告生成器获取标准答案。

- 检查窗口2025-01至2026-07，共19月；逐月/来源/观测计数差异0。
- CSV期间合计609,574,018美元，与存档附加报告一致。
- 最新值46,041,287美元、较前月变化13,163,460美元，与CSV一致。
- 再独立aggregate前7月CSV，仅在内存扩展原参考，运行原`check_public_turn`：两份报告均passed、errors=[]，public_safety=verified_program_output。旧reference、R01结果均未写回。

该核验还覆盖原程序已实现的存档哈希读回、finish当前轮绑定、数据版本、逐月来源与公开投影；不代表原始模型工具决策已最终审阅，不代表政策理解或全产品通过。

## 关键留证摘要

| 文件（均在us-agent-retest-20261001-v4下） | SHA256 |
| --- | --- |
| results/batch/R01.json | 5c32befee0b09ffef1e03094f64fa692679959541fcc232e5374ad3d16124afc |
| runtime/.local/trade-reports/7837b89c5b7f4e27b7b9b68532e7ee4c.json | a78621627bb8e9d4b07b589711d4482b406e51e07a89f6f8368f850850fddde6 |
| results/evidence/R01/session-readback.json | 637be60776f5735803462aaab920114b8a4b55cee52b3e1439c46ef72a072355 |
| reference/trade.json | fe9320799bf0ac4b1d54af9c5f9013b765c085d110aa9c307667f5511d0b5173 |

## 原始决策不能混同

coverage反馈只给进口earliest=2016-01/latest=2026-07/count=48，不列缺口。模型先查最近12月成功，再尝试2024-08至2025-07得到缺月拒绝，最后查最近连续24月得到实际19月报告，并finish两份正确报告。不能单凭earliest/latest称模型明知缺月；也不能把最后正确报告当作全部原始决策正确。原评分保持pending。

## 处理方案

读取`../US_RETEST_REFERENCE_AND_CONTINUATION_20261001.zh-CN.md`。新参考按全部已登记(flow,month)生成，缺参考与真实错误分开；新11轮续批以原R01会话为上下文锚点，不重问R01、不改旧unsafe字段，不自动把分段结果写成原12轮验收通过。

本步结果：已验证19月报告无上述数值/来源差异，停批根因在独立参考覆盖。
下一步：实施参考修订与一次性续批入口，统一离线验收。
下一步模型：GPT-6 Luna Max；原因：最小方案已确定；切换：请切换后确认。
