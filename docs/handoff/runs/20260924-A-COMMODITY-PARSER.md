# A 包：商品和月份解析止错（2026-09-24）

## 目标

阻止系统忽略用户提到的第二种商品、把不连续月份压成一个月，或把没有年份的月份猜成默认窗口；保留表达明确的查询。

## 改动

- `src/tradeintel_ai/trade_query_flow.py`
  - 发现已识别商品与未识别并列范围时返回 `needs_product`，不再按唯一识别到的商品继续生成报告。
  - 商品组与其HTS细码同时出现时要求用户明确选择整组或细码。
  - 多个不连续月份要求澄清；没有年份的月份要求补年份。
  - 识别“2026年5月至7月”连续月份范围；“最近12个月”继续使用最近12个连续可查询月份。
- `web/design-preview/live.js`
  - 贸易商品查询返回 `needs_product` 时，只有用户明确提到政策/关税等内容才进入旧政策案例流程；普通贸易商品问题直接显示澄清提示。
- 对应 Python 与 Node 测试新增了上述错误和保留行为的覆盖。

## 验收

本地真实数据探测：

| 问题 | 结果 |
| --- | --- |
| 最近美国大豆和小麦出口有什么变化？ | `needs_product` |
| 最近美国大豆和咖啡出口有什么变化？ | `needs_product` |
| 2026年5月和7月美国大豆出口有什么变化？ | `needs_period` |
| 美国大豆出口7月有什么变化？ | `needs_period` |
| 美国大豆和1201900090进口有什么变化？ | `needs_product`，明确提示整组/细码范围不同 |
| 2026年5月至7月美国大豆出口有什么变化？ | `ready`，`2026-05` 至 `2026-07` |
| 最近12个月美国大豆出口有什么变化？ | `ready`，`2025-08` 至 `2026-07` |

测试命令与结果：

- `PYTHONPATH=src:. .venv/bin/python -m unittest tests.test_trade_query_flow tests.test_trade_export_integration tests.test_trade_explanation tests.test_trade_explanation_http`：27项通过。
- `node --test tests/trade_explanation_ui.test.cjs`：4项通过。

## 限制与下一步

本包只处理范围解析与安全澄清，没有扩大可识别商品名称。小麦、咖啡等仍需代码才能查询。未调用模型API、未下载目录、未提交或推送。下一步 B 包从已有 Census 月包生成进出口分开的官方候选目录，并接入候选确认页面；实施中如需新增未定边界，再重新评估模型档位。
