# 最后复测：评测接线修正与冻结完成

2026-10-02。用户“继续任务”按约定作为 GPT-6 Sol High 切换确认。阶段仅处理两处已复现的评测依赖，不改生产 Agent、原问题、数据、评分门、旧冻结或模型成绩。0 外部模型 API，未提交推送。

## 两处修正

1. `tests/test_us_retest_final.py` 的续批正向测试不再复制真实旧 v5。改为在临时目录用真实数据工具和脚本模型生成 R01 会话/报告，再构造显式 offline_fixture 的父记录与 bootstrap。调用真实 DeepSeek 适配器的模拟 HTTP 续批测试仍覆盖 R02/R03、上下文、账本、R01 不重跑、无 API 模型评分、父证据不变。新增独立检查：真实旧 v5 在当前源码下仍报 Ancestor evidence changed，旧冻结摘要不变。没有刷新历史哈希或删除原成功路径的验收断言。
2. `prepare_final` 显式采用已有 `manifest_available` 独立 CSV 参考，覆盖48进口月、12出口月。原 core12 构建模式保留；参考在 reference/，不进入 runtime 用户输入。新增完整包回归核对全部登记月份、可可豆中国金额仍未知、原十二问题/七会话不变、运行输入无金标字段、准备阶段不冒称已冻结。

统一 acceptance 纳入已有两份 v3 catalog/policy merge 合同测试；测试范围扩大而非缩小。产品 src/、evals/、data/ 无本轮 diff。

## 验收与新包

- 续批局部套件 7/7，12.696 秒。
- 统一离线验收 **137/137**，189.932 秒，回执 `inputs/OFFLINE_ACCEPTANCE.json`；不累加重复运行数，不称全仓绿色或模型准确率。
- 正式 finalize 完成，verify_snapshot 核验 **312文件**与目录成员，实际解释器/数据/政策确认绑定通过。
- 新目录：`tmp/handoff-runs/us-agent-final-regression-20261002-v3b/`。原失败 v3 包、OFFLINE_ACCEPTANCE、OFFLINE_SNAPSHOT 原样保留，不覆盖失败证据。
- 新冻结 SHA256：`a0551b699e660d0ab755ae7bec895eed01df307aeb637508648b0e5c0abebaa2`。
- 旧 v5 冻结 SHA256仍为 `1c2cce88c83169c786a2c518fee2610821ef4b1eb1448f7f967585d84166e3dc`；真实旧批继续拒绝。
- 未授权执行入口实测拒绝：`Finite permit mismatch: approved`。通过 mock 断言密钥加载0次、模型构造0次，未生成 batch 许可账本或模型答案；证据为 results/UNAUTHORIZED_ENTRY_CHECK.json。
- git diff --check通过，未装依赖、未跑浏览器/PDF或全仓测试。

政策确认复用的是同一摘要对应的旧真实授权记录，经既有 submit/confirm 接口建立新隔离副本；不是新的独立人工金标。评分基准日期保持2026-10-01，最新数据2026-07，新实际运行日期另记录。

## 唯一待办：手动降档与新有限收费许可

`inputs/PERMISSION_REQUEST.json` 只是 approved=false 的申请模板，不是放行记录；authorization_message_sha256与expires_at尚未填写，不能运行。不得把该模板改名当许可或拿旧 v5 许可补上。

下一步推荐 GPT-6 Luna Max：设计和接线已经确定，只剩执行这一批固定实验与证据审阅。用户须手动切换确认，并明确批准以下这一次新冻结实验：

- 单模型 DeepSeek deepseek-flash，thinking enabled/high；官方文档目前对应 DeepSeek-V4.1-Flash，正式响应中的型号另记。
- 原十二用户轮、七会话；最多48个HTTP、120分钟；每轮6响应/12工具/8192输出，不自动重试。
- **10元人民币规划上限**；按高峰未缓存输入2元/百万、输出8元/百万保守预留，估算与服务商实际扣费分开，不宣称能硬锁供应商账单。正式发送前重核价格/配置。
- 错商品/金额/月、伪引用、安全门绕过或未知失败停止；固定8/9正常、3/3边界、发布报告核数和引用无错的采纳门，不降门槛或换题。

价目原HTML及检查说明在新包 inputs/price-source-20261002.html 与 price-check-20261002.json；它们是官方文档记录，不是模型响应或账单。密钥沿用已有本地配置，未复制到实验包，不再索要密钥。

批准后以本次冻结摘要、新授权消息摘要和新的执行时间窗口创建实际 permit，再运行既有执行器；安全短审/最终审阅明确标 AI reviewer，不能冒充独立人工盲评。完成后只汇总一次并补模型页，不默认追加模型或无限修弱模型。

本步结果：两处评测接线修正，137/137及新冻结核验通过，0模型API。
下一步：取得本批10元人民币有限许可后，执行十二轮并统一汇总。
下一步模型：GPT-6 Luna Max；原因：方案与验收已固定，后续属于按规则执行；切换：请切换后确认。
