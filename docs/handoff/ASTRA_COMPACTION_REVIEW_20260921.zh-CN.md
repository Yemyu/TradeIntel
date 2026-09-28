# 多期输入审查及修复规格

> 2026-09-22后续审查已完成，以 [v2验收与剩余实施方案](ASTRA_V2_ACCEPTANCE_20260921.zh-CN.md) 为准。业务投影边界已明确裁定，33项定向测试通过；下文为此前规格与实施历史。

## 当前实施结果（2026-09-21，Luna Ultra 离线收口）

本文件中的前置审查已按规格落实到 v2 输入协议。当前结果不是模型质量成绩，也没有调用任何 API：

- `public-brief-input-view-v2` 已上线到诊断构造器；`decode_view(view)` 只读取实际送出的 view，不读取 sidecar。
- Q1/Q3/Q4 的 51/51 条观察、244/244 个指标可从 wire view 解码；Q2 为 11/11、68/68。每条观察的指标链接均在 wire 中，指标表明确区分 levels/comparisons/origins 及其列含义。
- `decode_view(view)` 与业务投影一致；修改 wire 数值后只重算 view hash，`restore_view` 仍会拒绝（不是用 sidecar 冒充送模无损）。
- 重新生成的诊断包为 `tmp/public-brief-eval-v1/diagnostic-v2-20260921/`。包含系统消息的项目估算输入 tokens 为 Q1/Q2/Q3/Q4 **15460/10605/15480/15460**，均低于 16000 硬门；Q1/Q3/Q4 仍高于 8000 目标，不能为了追目标删月份、商品或法律条件。
- 诊断包的 `api_calls=0`。自然语言范围提案、固定追问摘要、独立参考答案、供应商 tokenizer 和真实模型回答仍未验收，因此正式四题评测继续暂停。

以下“审查未通过”记录的是 v2 实施前的状态，保留作为问题来源与修复依据；不要把它当成当前唯一恢复点。

## 裁定

2026-09-21 Astra 审查：**A/B 不通过，C 部分实现，正式评测继续暂停。**
此前“A/B/C 已按设计完成”“可逆紧凑视图”的结论撤回。v5 的 15362/7979/15372/15362 是实际诊断估算，但它对应被筛选且含义不完整的输入，不能作为完整五商品六个月输入通过预算的证据。
用户目标仍为面向普通读者的政策与贸易数据简报。本轮不恢复因果研究、不追加数据库、前端或多智能体。问题来自本轮输入实现，尚不能据此判断任何运行模型的能力。

## 已复现问题

复现命令（不联网）：

```sh
PYTHONPATH=src:. .venv/bin/python scripts/audit_public_input_compaction.py \
  --package tmp/public-brief-eval-v1/diagnostic-compaction-20260921-v5 \
  --output tmp/public-brief-eval-v1/astra-compaction-audit-20260921/findings.json
```

输出文件已生成；脚本拒绝覆盖，复跑请用新输出名。

| 问题 | 实证 | 影响 |
|---|---|---|
| A1：本地备份冒充送模无损 | 修改 view 数值并重算 view hash 后，restore 仍从 sidecar 返回原对象，四题均复现 | roundtrip 只证明备份能读回，未证明模型看到同一组业务事实；不是声称可绕过会话摘要 |
| A2：指标含义丢失 | 指标的完整 ID 被 m1/m2 替换，未发送语义类型/映射；全部来源、中国、非中国金额的其他字段可相同 | 模型必须猜每个数的含义，易引入分母/范围错误 |
| B1：月份与指标被过滤 | Q1/Q3/Q4 只有 20/51 条可引用观察、100/244 个指标；Q2 为 10/11、44/68 | 与原设计完整目录相冲突，整体序列观察也被排除 |
| B2：观察到指标的链接没有发出 | build_view 生成 selected_observations.metric_ids，但 messages 发送另一份不含 metric_ids 的目录 | 模型不能沿观察 ID 精确定位指标；靠文本/顺序猜配对 |
| A3：政策只投影部分字段 | _compact_policy 未保留完整 details / registration / field_refs 等；完整正文存在于 sources 并不证明逐字段关系完整 | 不能宣称所有法律含义和字段对应关系无损 |
| C1：政策更新观察缺失 | 四题 watchlist 都没有 policy_revision | 原设计要求关注后续公告变化，当前只关注统计/来源/口径 |
| C2：快照兼容未分派 | save/load 仍用当前 public_messages 重建全部 v1 快照 | 改提示后旧快照会因派生消息不一致被拒；源码风险，尚未枚举所有用户旧会话 |

原有关联回归 `PYTHONPATH=src:. .venv/bin/python -m unittest tests.test_public_explanation_flow -q`：4 项中 3 项通过、1 项错误。错误是旧测试仍查找顶层 policy_context，需按新版协议验证真正解码得到的同一政策对象，不能删除此断言来刷绿。这项错误本身不是上述语义缺失的全部证据。

C 已有有效工作：政策背景确实进入程序 Markdown，并在报告摘要内；已绑定政策会经过 policy_id/data_version/policy_view 检查。保留这些接线。

## 预算对照

将完整 request、evidence、policy_context、watchlist 直接用现有 exact-value pack 去重，可严格还原；仅该负载、尚不含系统消息的保守估算为：Q1 38493、Q2 17897、Q3 38503、Q4 38493。说明仅通用 pack 还不足以达到 16000。不要把这个下限当成新正式请求，更不要原样发出去。

## 下一个实施包：修正业务含义与真正的无损传输

模型建议 Luna 最高，按下列规格完成一次集中实施；若仍超预算，保留量测并停止，不进一步裁商品/月/条件。

1. 定义 `public-brief-input-view-v2`。输入业务对象为 request + 完整 evidence + 完整 policy_context + watchlist。主机 report/审阅记录可保存在本地，但送模业务字段不能依赖私有备份才可解码。
2. 将 source_ids 完整数组放入发送的共享表；来源正文/URL 必须可解码。各原字段的存在性、null、顺序及值严格保留。采用已知字段的列行表与精确值引用，未知字段明确拒绝或无损携带，禁止 `.get` 静默删字段。
3. 只对声明的 ID 字段做短别名；发送原 ID 对照（可用公共前缀+后缀精确表达）以及明确指标含义，使 world/china/nonchina/share、比较类型和计量单位可区分。不得替换自由文本中恰好相同的字符。
4. 全部 observations 可引用，发送 id/kind/scope/comparability/metric_ids/fact_sentence；输出仍最多六条。取消当前按产品数量/锚月剔除观察的 select_observation_ids 规则。模型答复如用短 ID，先在声明字段恢复原 ID，再走原验证器。
5. `decode_wire(view)` 只能读取实际发送字段，禁止读取 sidecar 原对象。要求 `decode_wire(encode_wire(business)) == business`。保存原对象摘要并检查这个等式；任一数值/字段映射被改都要拒绝，重算 view 摘要也不能替代对原对象的校验。
6. 政策采用完整字段精确去重（包括条件/例外原因、原文、字段引用和登记范围）；不要继续 `_compact_policy` 的白名单投影。报告继续显示已实现的政策段。
7. 有政策材料时默认 watchlist 为 next_trade_release、policy_revision、coverage_gap（存在缺口）或 origin_mix；不超过三项，报告与模型输入同源。
8. 明确快照输入版本。现有 v1 快照按其原构造规则验证及回放；若确实无法恢复更早构造器，返回专门的“历史输入版本待迁移”状态并保留原文件，不能笼统称文件损坏。新 v2 快照不覆盖旧任务产物。先登记实际旧格式，再实现分派，禁止统一放宽摘要校验。

验收只做与这次风险相关的反例：全部观察/指标覆盖；world/china/非中国及份额类型不混；观察到指标一一可解析；null 与缺字段区别；相同 source 数组和不同顺序数组；原文含别名样式字符；新旧快照读回；逐字段政策相等；prepare→submit→review→export 保留政策。

预算必须量测最终完整 messages（系统、合同、字典均计入），16000 硬门保持。全量语义先通过再看预算，不能先追数字。若一次修订仍超门，则由 Astra 决定有依据的下一方案；不要反复试压缩到模型看不懂。

## 进入统一模型评测前还剩什么

先完成上述一包并审查，再连接自然问句范围提案、Q2 固定程序摘要和独立参考。这些都属于已有计划，暂不增加新的测试题。参考与候选输入分离；API/聊天模拟分开记录；六候选仍为 Luna 最高、Sol 中、GLM-4.6V/Air、DeepSeek Flash/Pro，参数待最终冻结。千问不继续尝试。

本轮 0 次模型 API、未提交推送、旧冻结记录未改。没有新增模型成绩，也没有宣称全项目回归通过。
