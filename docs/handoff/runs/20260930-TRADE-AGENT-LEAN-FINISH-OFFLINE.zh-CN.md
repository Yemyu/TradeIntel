# 大豆别名与完成工具：离线实施结果

2026-09-30，按 [已定方案](../TRADE_AGENT_AFTER_THIRD_DECISION_20260930.zh-CN.md)实施。

- `soybean`、`soybeans`、`soya bean`、`soya beans` 整词原料别名在 import/export/both 中使用官方目录的 `soybeans` 搜索，只将 `1201` 标为准确商品；原搜索返回的加工商品仍作为相关项保留。豆油1507、豆粕2304的英文和中文查询保持独立，不能代查原料大豆。
- 完成协议标记 `trade-agent-tools-v2`，供应商 finish schema 只要求 `report_ids` 与 `source_ids`。后端仍接收原有三字段调用并核其类型和长度，旧 explanation 不进入公开完成摘要。公开摘要、图表、旧记录和多报告主范围机制保持。
- 新增补充题入口 `scripts/run_trade_agent_supplemental_pilot.py`，默认离线；豆油与缺上月数据各有独立快照及一次性账本，真实路径须显式调用门。预检只读核参考和目录，不创建正式会话或报告。

验收：新针对性测试6/6，相关Python合计 **42/42**；假HTTP两字段finish确实完成豆油报告，实际首条请求哈希与预检一致；模拟模型把上月改为最新可用月仍被挡住，重复／超时不重试、快照变化发送前拒绝；原三字段回归继续通过。`git diff --check`通过。本阶段0次真实模型API，0次MySQL写入，未提交／推送，未重打ZIP。

当前实际预检：

| case | 状态 | 请求字节 | 完整快照SHA-256 | 正式账本 |
| --- | --- | --- | --- | --- |
| soybean-oil | offline_ready | 4208 | fe07f4a7011c90394bb375dcae753bb8e568b3cc8fec679adfd11bc6d9ecf129 | 不存在 |
| missing-last-month | offline_ready | 4217 | 9d9043bafdab287aa26615b1d7e44af31d45c0571872c4dc6a4728c10e0148af | 不存在 |

两题为独立补充检查，真实模型尚未测；原五题已停止，第一题通过／第二题未完全通过／第三题未通过的记录不改。当前v3源码ZIP形成于本次修改之前，故并不包含本次别名和新完成协议；后续交付须另打包复验，不能用旧包声称含当前改动。

下一步按已有调用许可先通知，再核当日价格、账户和快照，只运行豆油一次；评分后通过才运行缺月份一次。任何失败立即停止，不重发刷分。
