# 美国重测：隔离政策候选准备

新增 `scripts/prepare_us_retest_policy.py`。核验官方存档HTML的固定SHA256；将HTML实体解码并合并标签之间的连续正文，规范化空白后逐行核对既有p8/p9/p12片段。不改写引用文本。

真实离线产物在 `tmp/handoff-runs/us-agent-retest-20261001-v1/offline-package/runtime/`：

- `.local/announcement-docs/us_301_review2025_tungsten_solar.json`：独立disabled文档，版本 `docver-6ce73efd61200bf1`，原source ID保留，p8生效/入境、原产地及商品限定依赖映射齐备。
- `policy-review.json`：13字段待确认模板及完整登记片段；尚未提交候选、没有人工确认、没有启用。例外缺失判断仅针对登记片段，不推广到全部法规。

首次校验发现HTML标签与标点间被提取器人为插入空格；改为拼接原始文本节点后规范空白，三片段全部逐行匹配。未放宽句子、未做语义相似匹配。

新增两项测试：真实存档准备后保持disabled、默认检索无证据、重复准备拒绝；原文哈希变化在任何写入前拒绝。当前重测组件共11项通过，git diff --check通过。

0API，未改主根政策库，未提交未推送。冻结和实测仍未就绪。剩余为字段候选审核/确认、provider录制实际发送门、费用预留、冻结及评分。

本步结果：政策候选离线准备完成，11项组件测试通过。
下一步：接通实际请求录制和预算拒绝门，完成评分实现。
下一步模型：GPT-6 Luna Max；原因：继续按已确定接口和验收执行；切换：无需。
