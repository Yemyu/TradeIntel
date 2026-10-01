# 美国重测：最终执行门交接

已完成的离线部件：独立CSV参考、12轮计划及隔离政策候选、真实适配器发送边界与响应/tool反馈录制、次数/字节/时间账本、显式美元预留基础、案例依赖、存档读回核数、政策引用核对、整包离线快照、逐题审阅模板。原始数据、旧成绩、生产政策未改，0 API。

当前不是live-ready。不得再将补一个基础部件称完整运行器已完成。

## 需要一次集中方案判断的两个未闭合点

1. AgentCaseExecutor故意返回pending_audit/accounting_complete=false，execute_cases的R01/R02门会因此停止。它安全，但不能自主完成整批。需要明确将哪些事前固定的确定性核对作为通路许可，哪些必须保留事后人工语义审阅；不能为了放行把numeric_complete改名为完整通过。
2. wire预留与money预留是独立组件；美元预留没有已核实的真实输入token上界，未知用量也不能核账。需要确定有限执行许可/保守费用目标与一次发送原子预留接法，不可将body字节换算当严格账单保证。正式run目前明确拒绝，不能直接打开。

此外政策13字段候选9known/4unknown尚未submit/confirm/enable；应在展示清楚候选及适用限制后取得真实确认，不能代填用户签名。已有OFFLINE_SNAPSHOT因后续源码变化已失效，必须新版本冻结，不改旧哈希。

## 相关文件

- 设计：docs/handoff/US_AGENT_RETEST_DESIGN_20261001.zh-CN.md
- 执行/账本/录制：scripts/run_us_agent_retest.py
- 评分：scripts/score_us_agent_retest.py
- 独立参考：scripts/build_us_agent_retest_reference.py
- 政策候选：scripts/prepare_us_retest_policy.py
- 测试：tests/test_us_agent_retest.py
- 产物：tmp/handoff-runs/us-agent-retest-20261001-v1/offline-package/

最小下一动作：只读复核上述两个门，给出一个可直接实施的最终闭环方案及明确许可条件；不扩商品/国家/模型、前端或研究设计。再由Luna Max实现和一次验收。未取得有限live许可前不发送请求。

本步结果：离线部件与逐题审阅材料完成，但整批运行许可仍有两个未闭合方案点。
下一步：集中定最终执行门、费用预留及人工确认路径，避免继续零碎补组件。
下一步模型：GPT-6 Sol Max；原因：通路门与事后审阅分工、费用预留接法尚未确定；切换：请切换后确认。
