# R2 公告三字段阅读：单次调用的离线冻结与执行门

日期：2026-09-28。状态：**离线准备完成；真实模型请求 0 次；尚未授权调用。** 这是已参与开发的 R2 公告，不是盲测。

## 固定内容

- 冻结目录：`evals/announcement_reading_v2/frozen/r2-dev-20260928-v1/`；原文、33 段位置图、原 v2 消息、准确 POST 正文、七点参考及执行代码均有摘要绑定。
- 请求：DeepSeek `deepseek-flash`，开启思考、`high`，`max_tokens=12288`，JSON 对象，无工具、无温度参数。实际请求体 23,377 UTF-8 字节，SHA-256 `737e410a16ee4a0750e95269d17ad43065eb31b5caa4dc958880c8ec8bc89bb3`；manifest SHA-256 `6abda1602eee589cbd81b3bb83fcd0d085bd77b09cf75bd2b5e4007af17debaa`。
- 计划：一次请求、120 秒、响应上限 1 MiB、最终正文上限 6,000 字节。30,000 输入/12,288 输出 token 与 2026-09-28 核查的峰时价给出约 $0.0237456 预留，$0.03 是本地计划门，**不是服务商扣费硬上限**。实际调用日须重查官方价格和账户状态；本轮未做当日实时扣费验证。

## 执行边界与验收

新增 `scripts/freeze_announcement_reading_dev.py` 和 `scripts/run_announcement_reading_dev_once.py`。默认入口只读预检：冻结摘要一致、当前产品配置显示 DeepSeek `deepseek-flash`、账本 `not_started`。真实路径需要单次授权开关与当天价格确认；请求**先写私有账本**才发送。已经开始、超时、服务错误或中断均不自动重试；完整原答仅在本机 owner-only 目录存放。结构合格的三字段回答只到 `needs_human_review`，不能写政策候选、启用公告、修改 MySQL 或声称七点语义正确。

假服务反例：逐字节请求、先记账、4 线程并发仅 1 次、重复调用拒绝、HTTP 400/503、超时未知结果、空正文、截断、坏 JSON、错版本、假出处、错误模型、用量越界、响应过大及冻结文件篡改均按预期拒绝/停下。相关 Python **39/39** 通过；另一次误写了不存在的测试模块名，已用正确模块重跑通过，并非项目测试失败。`git diff --check` 通过。未运行真实 API/浏览器/MySQL/全量回归；没有提交或推送。

## 后续最小动作

先人工重新核对官方模型名称、当天价格和账户余额，再由用户单独授权**这一次** R2 开发调用；不能把普通“继续任务”解释为付费调用许可。调用后保存原答并按七点固定参考逐条人工审阅。7/7 且零严重错误也只算已见开发案，不宣称省时或新公告准确率。

## 2026-09-28 只读复核

再次运行默认预检：`verified_offline`、23,377 字节、请求与 manifest 摘要不变、当前本机配置为 DeepSeek `deepseek-flash`、专用账本 `not_started`、本轮 API 0 次。[官方价格页](https://api-docs.deepseek.com/quick_start/pricing/)当天显示 `deepseek-flash` 对应 DeepSeek-V4.1-Flash，峰时缓存未命中输入 $0.30/百万 token、输出 $1.20/百万 token，仍与本计划所用价格一致；[官方思考模式说明](https://api-docs.deepseek.com/guides/thinking_mode/)列出 `thinking.enabled` 与 `reasoning_effort=high`。没有调用余额接口，也没有以本地 `connected` 历史状态冒充当天服务连通。真实调用仍未获单独授权，因此停在调用门前。
