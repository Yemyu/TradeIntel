# FR2026-19516 独立单次入口离线验收

日期：2026-09-28。范围：按[既定方案](../ANNOUNCEMENT_READING_UNSEEN_RUNNER_DESIGN_20260928.zh-CN.md)新增专用冻结器、单次执行器及必要的假服务回归。没有模型调用、政策启用或数据库写入。

## 交付

- `scripts/freeze_announcement_reading_unseen.py` 固定案例身份、答前参考清单原有SHA、其中13个文件摘要、请求/原文/提示摘要与完整离线包；只从两条已验证消息构造POST体。生成的候选包在 `evals/announcement_reading_v2/frozen/fr-2026-19516-unseen-v1/`，已有目录不能覆盖。
- `scripts/run_announcement_reading_unseen_once.py` 用本案例独立私有账本记录先于假HTTP，并将原答与技术审阅分开保存。默认只读预检；`LIVE_RELEASED=False`，真实请求路径当前硬拒绝。临时假服务校验由测试进程局部打开该标记，不会改保存的源代码。
- 两个旧R2脚本均未编辑。新案候选冻结目录与R2目录分开，账本名也不同。

## 离线结果

| 核查 | 结果 |
| --- | --- |
| 已锁阅读消息 | 27,615/28,000字节；54锚点，完整校验通过 |
| 实际候选POST体 | 27,784/30,000字节；SHA-256 `e5edd95789ace28583cd27a8899da99b541360ad37e97fbe9d5ee548c977356a` |
| 新候选冻结清单 | SHA-256 `11221cda0918889971b887e607e85bef9ebcb8369bd446505ccd909983689fe0`；预检 `verified_offline_candidate`、`not_started`、`api_calls=0` |
| 假服务 | 新案定向7项通过：默认不发、参考/源/请求/POST篡改拒绝、先记账、私有原答、四线程只发一次、超时结果未知不重试、非法正文不进入审阅 |
| 旧R2 | 原冻结校验 `verified_offline`，原请求体23,377字节、摘要仍一致 |

候选配置写着 DeepSeek `deepseek-flash`、high、`max_tokens=12288`，只是让冻结器和假服务有精确字节可核；本案例的当天价格、计划费用门和最终响应别名还未确认。候选清单 `planned_usd_limit=null`，不能用于真实发送。执行器静态 `LIVE_RELEASED=False`，费用与正式一次许可确认后应建立**新的最终冻结版本**，不能覆盖此候选包或只改布尔值绕过代码摘要。

相关定向命令：

```sh
PYTHONPATH=src:. .venv/bin/python -m unittest tests.test_announcement_reading_unseen_once -q
PYTHONPATH=src:. .venv/bin/python -m scripts.run_announcement_reading_unseen_once
PYTHONPATH=src:. .venv/bin/python -m scripts.freeze_announcement_reading_dev --verify
```

本步结果：完成；独立候选包和假服务边界验收通过，真实调用0次。
下一步：核准本案例准确的服务型号、端点、参数、当日价格与费用门，并形成可审阅的最终一次调用方案。
下一步模型：GPT-6 Sol Max；原因：下一步需要决定与冻结正式模型配置及预算；切换：请切换后确认。
