# 移除千问、准备四题输入

用户决定不再测试千问；不再尝试该地址、消耗余额或自动升级Max。GLM5.3仍因额度错误暂停。

当前候选六配置：Luna最高、Sol中（干净Codex会话）；GLM4.6V与4.5-Air（拟开启思考）；DeepSeek Flash与Pro（拟low思考）。同样四题，最多24答。配置需要随最终材料冻结，连通探测不是正式成绩。

## 本轮实现与验证

- `session_brief.build_temporal_session_brief`复用已有、原文哈希校验的主案例政策事实，从绑定数据版本对应的仓库读取三个原文来源，放入policy_context。
- `session_explanation`在生产prepare、保存、恢复时传递并校验政策上下文；policy_id、data_version、policy_view必须与报告一致。上下文及原文进入快照摘要，非对象输入拒绝。
- 该路径仅支持已登记主案例的archived_event；新的policy_binding或verified_as_of不能悄悄套用存档条款，明确拒绝。旧快照无上下文仍可读取，不回写历史实验。新增政策接线不是“现行全部税则验证”。
- 新增 `scripts/prepare_public_eval_diagnostic.py`：离线构建生产响应和模型消息，输出至新目录、不覆盖已有包；明确标记diagnostic_only_not_frozen，无任何provider调用代码。
- 已实际生成四题诊断输入：`tmp/public-brief-eval-v1/diagnostic-no-qwen-20260921/`。默认窗口由已发布版本推导为2026-02..07，Q2仅38180000，三条政策原文均实际进入消息。
- 定向回归：`tests.test_public_explanation_flow`与`tests.test_session_explanation_flow`共6项通过，含新非对象/错版本反例及prepare→submit→review→export链。`git diff --check`通过。未跑全量，不声称整体全绿；未提交推送；本轮0 API。

## 必须先处理的输入问题

生产消息序列化后Q1/Q3/Q4约848,600字符（856KB），Q2约261,400字符（265KB）。这些是字符/字节实测，不是token实测。原因至少包括public_messages同时放入观察目录和完整多期evidence；必须进一步拆解大小，不能照旧单月请求预算声称已满足16000 token硬门。

因此没有冻结或发送正式四题。除了体积问题，诊断包仍没有验证自然问句→提案的产品入口、Q2固定前题摘要接入、独立评分参考及provider总输出/思考预算。显式构造request只用于查看当前生产解释输入，不能冒充端到端用户体验验收。

## 下一阶段建议：Astra中

先设计并核准多期模型输入投影，不在本轮随意删字段。要求：

1. 逐字段计量，区分模型解释必需信息与留在主机的重复明细。
2. 保留观察ID、正确分母、比较许可/未知状态、来源映射及完整相关法律条件；不得只为省token删除未知/限制。
3. 固定同一生产构造器供产品和评测使用；主机保留完整证据及摘要，所有可引用观察可回查。
4. 以完整输入的程序事实为对照，校验范围/金额/可比性/政策绑定不变；不是用正式模型答案反复调题。
5. 先离线达成既有16000 token预算口径，再验证自然提案与固定追问上下文、冻结参考。未通过不调用；不扩大模型名单。

此后Luna最高实现与跑常规检查，Astra最后审查，再开始六配置四题。本轮不存在任何新增模型准确率。
