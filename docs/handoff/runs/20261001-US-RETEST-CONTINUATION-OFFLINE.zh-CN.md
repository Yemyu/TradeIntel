# 参考修订与11轮续批：集中实施完成

日期：2026-10-01；实施档GPT-6 Luna Max。按`../US_RETEST_REFERENCE_AND_CONTINUATION_20261001.zh-CN.md`执行，0新API、未提交推送，不改产品src/提示/工具协议/前端/原数据。

## 已完成

- 独立参考profile `manifest_available`：从同一冻结CSV包覆盖48进口月+12出口月，保留断点；原core12默认和数值不变。Gold与核验规则不进入模型上下文。
- 核验状态分开：verified / failed / unverified_reference。缺参考不冒充null观测、不连带生成假摘要错误；有参考的错值/错来源/错主范围与内部矛盾仍失败。原R01用旧gold现核为unverified，用新gold可核两报告；不改原v4结果。
- 新`prepare-continuation`保留原12题IDs与分组，allowlist只含剩余11题；R01仅是摘要绑定的事后上下文锚点。按白名单逐字节复制原session/两报告/政策库及确认，不拷贝密钥、不手填scope、不修改原runtime。
- 续批permit-v2绑定新旧freeze、父证据、原11题和已花费；谱系累计最多48HTTP/10CNY，旧5次/0.036040元计入。保留5.24288元每发保守预留。新120分钟执行窗须获有限授权。
- 一次性父→子claim与双owner锁；不同目录重复领取、子批重启、未知账本和漂移拒绝。claim目前未创建；真实运行才写新追加receipt，不覆盖旧记录。
- score/status按新11轮（正常8/边界3）单列，不重复计R01、不自动合并旧发布门；待审模型准确率为null，不展示成0%。

## 实际验收

统一相关套件 **120项全过，91.057秒**，receipt：`tmp/handoff-runs/us-agent-retest-20261001-v5/inputs/OFFLINE_ACCEPTANCE.json`。

包括真实适配器+模拟HTTP：R02读取原大豆会话，R03切换豆油且同SID，6次模拟请求，R01无工厂调用/claim/HTTP；新增参考缺口、实际错误、累计第49次、预算不足、未知预留、新时间窗未授权、二次目录/重启、父账本pending/orphan/已领取题、bootstrap/父摘要/allowlist篡改等拒绝反例。

新参考60个(flow,month)单元，保留null；原v4关键资料hash逐项验证不变；新freeze **394文件**已读回验证：`1c2cce88c83169c786a2c518fee2610821ef4b1eb1448f7f967585d84166e3dc`。新增未批准的许可请求位于`inputs/CONTINUATION_PERMISSION_REQUEST.json`，不是有效permit。

未运行：剩余11轮真实模型调用、其最终语义审阅；全仓历史冻结套件、浏览器和PDF本阶段未重跑（未改产品/前端）。脚本响应不算模型成绩；0.036040元是旧5发的峰值估算，不是供应商账单核实值。

## 下一步仅为实测

当前包`tmp/handoff-runs/us-agent-retest-20261001-v5/`已完成离线验收和freeze，仅缺绑定此freeze的新有限许可；政策字段没有变化，不重问公告确认，也不重新索要API。用户确认剩余11轮/新120分钟窗口/累计10元与48次后，核供应商价格与原配置，保存真实授权消息依据并按现有run入口执行。

命令（仅在有效permit生成后）：

```sh
PYTHONPATH=src:. .venv/bin/python scripts/run_us_agent_retest.py run --root tmp/handoff-runs/us-agent-retest-20261001-v5 --data-root tmp/handoff-runs/trade-demo-data-20260925 --permit tmp/handoff-runs/us-agent-retest-20261001-v5/inputs/CNY_CONTINUATION_PERMIT.json
```

run前只读`verify_continuation(initial=True)`和`verify_snapshot`；自由文案安全短审沿用现有落盘机制，不额外调API评委。未知或终止不原样重试，保存结果统一汇报，不增加新模块。

本步结果：集中实施完成，120项相关测试全过，续批包已冻结，0新API。
下一步：有限许可下实测剩余11轮并统一审阅汇总。
下一步模型：GPT-6 Luna Max；原因：方案和执行门已固定，属于既定实验执行；切换：无需。
