# Astra 最小产品与归档方案（2026-09-19）

## 目的

把 TradeShock AI 收敛为一条可以解释、演示和继续维护的产品链，同时保留历史研究的可追溯性。当前不删除原始数据、ZIP、`.local` 状态、冻结记录和历史报告。

## 最小产品定义

用户输入一个贸易政策研究问题，系统完成：

1. 登记或选择官方政策版本；
2. 展示商品范围、条件、例外和原文引用；
3. 查询固定版本的贸易数据并计算金额、份额和变化；
4. 生成确定性事实报告；
5. 让模型只解释已提供事实（模型内容必须进入人工审阅）；
6. 用户审阅后导出；
7. 新公告先进入 disabled 候选，确认后再触发数据覆盖检查和旧报告重绑定。

因果识别、预测、微调、多智能体和通用 RAG 不属于当前交付门槛。因果相关代码只负责显示“当前不能给出因果结论”的安全状态，不能进入报告中的因果结论。

## 保留层

### 产品运行层

- `src/tradeintel_ai/web_app.py`
- `src/tradeintel_ai/policy_exposure_tools.py`
- `src/tradeintel_ai/exposure_version_store.py`
- `src/tradeintel_ai/controlled_update.py`
- `src/tradeintel_ai/repository.py`
- `src/tradeintel_ai/policy_documents.py`
- `src/tradeintel_ai/policy_candidates.py`
- `src/tradeintel_ai/policy_search.py`
- `src/tradeintel_ai/announcement_flow.py`
- `src/tradeintel_ai/announcement_parser.py`
- `src/tradeintel_ai/source_registry.py`
- `src/tradeintel_ai/session_store.py`
- `src/tradeintel_ai/session_brief.py`
- `src/tradeintel_ai/brief_fact_catalog.py`
- `src/tradeintel_ai/brief_business_view.py`
- `src/tradeintel_ai/evidence_linked_brief.py`
- `src/tradeintel_ai/response_contract.py`
- `src/tradeintel_ai/provider_executor.py`

这些文件共同构成页面、政策候选、证据、固定版本查询、报告、审阅和受控更新链。不能按“文件名看起来像旧代码”删除。

### 展示和验收层

保留 `web/index.html`、`web/session-research.html`、`web/update-check.html`、`web/announcement-import.html`，以及 K1/K2/J/K3/K4 定向测试和中文版使用说明。它们直接证明当前页面边界和失败行为。

### 数据层

保留当前政策原文、来源 manifest、活动数据版本、贸易明细、MySQL 导入所需数据和原始压缩包。`data/` 体积大是数据问题，不应通过删除源数据解决。

## 归档层

以下是待核对依赖的归档候选，不是可直接执行的移动/删除清单：

- `scripts/build_causal_*`、`scripts/build_control_eligibility.py`、`scripts/build_prepolicy_matching.py`、`scripts/check_prepolicy_trajectory.py` 及对应测试/报告；
- `scripts/freeze_g2_research.py`、`scripts/prepare_g2_revision.py`、`scripts/run_g2_research.py`、旧 G2 产物；
- 已被当前统一入口替代的 `analysis_planner_v2/v3/v4.py`、旧 `intent_*` 回放脚本和对应历史测试；
- `vendor/course-reference/` 及课程检查脚本；课程源码只作为学习资料，不作为运行依赖；
- `tmp/` 中除 K1/K2/J/K3/K4 最新复核产物之外的中间运行包。

归档前必须输出逐文件源路径、目标路径、内容哈希、引用方、恢复命令。所有当前入口与脚本的递归依赖都保留；不得把“网页未导入”当作无依赖。跟踪文件可用 git mv，未跟踪文件需单独可逆移动；tmp 不能移入受版本控制的目录，里面可能含私有运行内容。原始冻结材料原路径保留，优先在导航和默认测试入口中隔离历史内容。

第一批物理删除清单为空。课程适配器已被主入口引用，vendor 参考源码与适配器不能混为一谈。最小产品保留列表只是入口模块，不是穷尽依赖的白名单。

## 暂缓处理层

以下文件目前不能直接判断为旧代码：`tools.py`、`agent.py`、`capability_contract.py`、`structured_workflow.py`、`unified_research.py`、`policy_workflow.py`、`natural_v2.py`。它们仍被网页或安全拒答链间接使用。

`tools.py` 中的因果状态读取虽然不做因果估计，却是防止模型越界声称因果的安全门；在替换前必须先把该门改成最小的 `causal_status` 接口并通过回归测试。

## 先修复，再瘦身

### P0-1：真实 provider 适配

`provider_executor.run_experiment(provider=None, authorize_real_call=True)` 当前只读取冻结标记，没有实例化 `OpenAICompatibleModel`，随后会对 `None` 调用并落为 `unknown_outcome`。修复要求：

- 从冻结配置构造唯一的 `OpenAICompatibleModel`；
- 将其 `complete` 适配成执行器需要的 `(raw_text, usage)`；
- 记录模型名、端点、请求摘要和 usage；
- 在无冻结标记、无授权或配置不完整时继续拒绝；
- 增加“授权路径使用可注入假客户端”的测试，禁止真实网络。

### P0-2：额度账本不可恢复

`ledger_remaining_slots()` 只计算每个 run 的最新事件；`unknown_outcome → resolved_*` 后会恢复已发生调用的槽位。正确规则是：只要写入 `started`，该槽永久计费；`resolved_*` 只改变审计状态，不释放槽。修复后增加两个反例：失败标记不返还槽、授权重试使用新槽。

### P0-3：真实实验前冻结

P0 修复通过后仍不立即调用模型。必须先冻结模型、端点、温度、输出上限、正式题和泄漏规则；再使用一次开发题进行人工审阅。任何一次严重越界都停止，不通过换模型反复试。

## 执行顺序

1. 修复 P0-1/P0-2，加入针对性测试，保持真实 API 关闭；
2. 运行最小产品依赖扫描，输出“保留/归档/仍被引用”清单；
3. 可逆归档历史脚本、旧实验输出和课程参考，回归页面与定向测试；
4. 更新 README、PROJECT_PLAN 和 STATUS，使它们只描述最小产品；
5. Astra 复核归档差异和 P0 测试；
6. 只有用户明确授权并且冻结文件存在时，才运行有限真实 AI 验收。

## 2026-09-19 P0 执行进度

- 已修复实际客户端构造，冻结 temperature/max_tokens/thinking 进入请求；端点与本地凭证配置必须一致。未设置真实冻结标记，未读真实密钥，0 次真实 API。
- 已修复按历史调用预留计数，resolved 不再释放槽；这里是保守的实验预算占用，不代表供应商已实际扣款。
- 新增进程文件锁和线程锁，串行覆盖去重、预留、调用和落盘；本地实验允许这段串行执行，后续如需高并发另行设计。
- 非法 JSON 落为 invalid_response；原答和 usage 先保存；超长 C 回答在解析前拦截。失败结束状态不允许隐式重复调用。
- 新增独立临时目录测试 8 项，不依赖 tmp 开发包；联合原 K2 测试共15项通过。真实客户端路径使用假 complete 截获实际构造的 payload，未联网。
- 仍待处理：新公告状态与会话 policy_version 的真正绑定、覆盖与报告接线；模型输出语义审阅；完整默认测试/历史测试分层。不能将新公告 rebind_required 提示当作已完成失效控制。

## 采纳 Sprite 方案的标准

Sprite 的方案只有同时满足以下条件才采纳：

- 能指出最小产品的入口和每个保留模块；
- 不删除版本、引用、审阅和失败恢复；
- 将历史实验归档而不是混入运行路径；
- 提供可逆步骤和回归门；
- 不把离线 stub 结果写成模型质量；
- 不要求为展示效果引入多智能体、微调或额外数据库。

如果不能满足，继续使用当前代码做收敛更稳妥。

## 下一执行包 S1—S4：接线设计（Astra 复核后，2026-09-19）

本节优先于前面概括性清单。当前主链与旧实验都保留原路径；先减少默认入口和文档歧义，再做文件搬迁。新公告分析是最终产品的必需能力，不能在精简中删掉；日常自动检查是受控更新的后续接线，不假装已经实现。

### 已核实的连接缺口

| 位置 | 实际行为 | 影响 |
| --- | --- | --- |
| `policy_cases.py:CASES/resolve_case` | 只有两个静态案例，其中一个仍 candidate | 任意新公告 policy_id 无法进入查询 |
| `web_app.py:_handle_session_post` | 确认时将 policy_version 和 data_version 都设成活动贸易快照版本 | 公告变更未成为独立会话约束 |
| `session_brief.py:build_session_brief` | 只允许主案例，政策引用从旧 corpus 读取 | 新公告启用不会自动成为报告证据 |
| `announcement_flow.py:confirm_and_enable` | 返回 rebind_required，不对会话执行绑定或失效检查 | 提示不等于实际重绑定 |
| `announcement_flow.py:coverage_report` | 每次调用 build_coverage(candidate)，没有传贸易查询结果 | 即使有数据也一直 not_checked |
| `announcement_parser.py / policy_search.py` | 核心能力有离线测试，尚未由新公告页面全链路使用 | 不能称已完成生产 RAG |
| `controlled_update.py:run_update_cycle` | fetch=None 返回 no_fetch_source | 检查按钮不等于联网更新 |

### S1：公告确认、版本绑定与检索（Luna 最高执行）

只修改现有 `announcement_flow.py`、`policy_candidates.py`、`policy_documents.py`、`policy_search.py`、`web_app.py`、`session_store.py` 和对应页面/测试。

1. 将公告路径与可重入锁迁入 announcement_flow；web_app 导入该函数，兼容旧函数名，消除底层存储反向依赖网页模块。导入、确认、启用必须使用同一个 policy_id 文件锁覆盖完整读改写。
2. submit 保存不可变 candidate_digest 和 doc_version；enable 必须携带用户已看到的 expected_candidate_digest，并在锁内重新核验。字段冲突可留在候选，但不能启用为可用政策规则；unknown 保留原因，只允许缺少该字段时仍有意义的操作。
3. 会话扩展可选 `policy_binding={policy_id,doc_version,candidate_digest}`。旧主案例继续按原快照解释，不能将旧 session 中的 data hash 冒充新公告 doc_version。新绑定由服务器读取确认记录构建，不能信任前端自由填写。
4. 从已确认的指定公告构建 PolicySearch；指定 doc_version 精确检索，条件/例外依赖缺失时展示 incomplete_required_context；不得回退主案例或无关公告。启用仅表示可使用已审阅文档，不等于覆盖齐全或可以计算税款。
5. 公告变更后，新问题须重新确认；已经完成的历史报告继续固定旧版本可读/可导出。正在生成的任务使用原绑定快照，不静默替换新公告；撤销/禁用明确提示并阻止以其作为新研究依据。

验收：并发导入+启用不丢文档；submit 后字段改动不能用旧 digest 启用；冲突不能启用；两版正文引用互不混用；无新公告绑定的旧会话仍可访问；新公告任务不会读默认主案例。无需模型调用。

#### S1 实施结果（2026-09-19，Luna）

- 已把公告文件存储与可重入锁迁入 `announcement_store.py`；导入、候选提交、启用和绑定使用同一份服务器端读改写路径。
- `candidate_digest` 现在由服务器登记；启用时同时校验客户端期望摘要、登记摘要和当前字段重算摘要。字段被改动后不能借用旧摘要启用。
- 会话/任务保存窄化的 `policy_binding`（`policy_id`、`doc_version`、`candidate_digest`，可选 `data_version`）；服务器重新读取 enabled 公告后才建立绑定，确认记录等审计元数据不会混入客户端合同。
- `search_policy_binding` 只检索绑定的 `doc_version`，不会回退主案例；旧主案例会话仍走原路径。新公告尚未完成贸易覆盖时，网页确认后明确停在 S2 边界，不生成伪造金额报告。
- 定向回归 88 项通过（含摘要篡改、并发提交、服务器绑定和指定版本检索反例）；全程 0 次真实 API、未改旧冻结记录。S1 不等于新公告已完成数据覆盖，S2 仍待执行。

### S2：真实贸易覆盖与确定性报告（Luna 执行，语义异常返回 Astra）

复用 `repository.py`、`policy_exposure_tools.py`、`exposure_version_store.py` 和现有贸易明细读取；不增加第二套数据库。不通过改 CASES 字典“假装”任意公告的数据已经存在。

1. 先核查现有已发布快照能覆盖的商品、原产地、月份、指标和统计编码版本。为公告建立只读绑定记录（放在公告存储现有记录下）：来源 dataset/case_id、data_version、月份、税号、原产地、统计口径、来源哈希、校验结果。记录由服务器查询生成，前端不可提交 exact 标志。
2. 第一版仅接受可验证的完整 HTS8 商品统计范围；未知、HS6、ex/文字限定和部分HTS10分别保持缺失或部分覆盖。即使 HTS8 完整，也称“该商品统计范围内的贸易金额”，不称逐票法律适用额、税基或损失。
3. 优先复用已发布的主案例商品快照。如果新公告包含它没有的税号，返回 missing_codes 和来源缺口；不得拿主案例五税号代替。新增商品需从现有 HTS10 数据与官方 ZIP 提取、校验并发布新资源，作为单独数据接入任务。
4. coverage_report 读取已核验记录并复核版本/请求一致后传给 build_coverage。空记录=not_checked；成功查询但缺数据=none/partial，不能补零。
5. session_brief 根据绑定选择政策证据与贸易查询。新公告必须以确认字段构建政策事实；不得调用主案例的固定税率模板。复用事实目录与 A3 格式，保留逐商品税率、条件/例外、时间与来源。新报告同时记录 policy_binding 和 data_version。

验收：同一已覆盖税号配两份不同公告产生各自引用与条件；错国别/错月/缺税号不误标 exact；partial 不等于政策全部受影响金额；覆盖确认后切换活动数据，旧报告数字不变；新公告正文和金额都出现在导出报告。先用合成反例验证连接，再用未参与开发的官方公告做迁移验收。迁移公告不是模型训练材料，不宣称独立学术金标。

#### S2 实施结果（2026-09-20，Luna）

- 新增 `announcement_report.py`：只读取已登记、已发布的贸易来源案例，按公告 HTS8 和月份过滤，并把来源 `case_id`、贸易版本、覆盖摘要和来源限制写入公告存储。
- 新增 `check_trade_coverage` 与 `POST /api/announcements/coverage/check`；前端只能提交月份和来源案例请求，金额、`exact` 状态和 `data_version` 均由服务器查询生成。
- 完整 `whole_hts8 + China + 已发布月份` 可得到 `exact`；主案例没有的税号返回 `none`/`missing_codes`；ex、HS6、文字限定或部分 HTS10 保持 `partial`，不扩成完整税号。
- 新公告的确定性 A3 报告已复用现有事实目录和报告渲染器，政策事实从该公告自己的候选引文构建，不再调用主案例固定税率模板；报告明确显示来源案例和统计覆盖边界。
- `session-research` 的证据/生成路径已能读取带 exact 覆盖的公告绑定；没有 exact 覆盖时拒绝生成金额报告。新增 S2 + S1/K/J 定向 Python 92 项、页面 4 项通过；全量 1115 项仍是历史冻结/既有失败与 SciPy ABI 环境问题（3 failures、48 errors），没有把它写成全量全绿。
- S2 的未参与开发官方公告迁移仍未宣称完成；当前已有合成跨边界验收，下一步应选一份真实新公告做 R2 迁移复核，再决定是否进入 S3 的有限 AI 解读。

### S3：把真实 AI 接到唯一会话主入口（三段式）

前提是 S1/S2 有完整程序稿。保持 A3 无模型路径可用，增加显式“生成 AI 解读”，复用 provider_executor 和已有逐项审阅服务，不重建 agent 框架。

- Astra 先冻结一份实验配置和题目；正式库中 stub 与 real 必须使用分离账本/命名空间，避免 stub 消耗或阻断真实预算。当前修复已区分 provider_kind，但尚未做账本隔离，因此不得直接跑真实实验。
- 调用输入来自本任务已确认的事实目录，输出短 ID 还原后由原目录验证。任务引用实验 run_id，刷新只读取该结果；超时不自动重发；非法 JSON 和内容不合格可见且不可导出为正式 AI 报告。
- 实验接口保留 B/C 对照给开发者；产品只暴露一个受约束解读入口，不让普通用户选择实验合同或槽位。
- 复用 interpretation_review_store 做 AI 内容逐项审阅，导出绑定报告哈希、政策绑定和数据版本。A3 确认不能代替 AI 审阅。

实验假设：C 能在同资料下产出有据的解释，且不损害确定性事实。基准 A=程序稿，B=同资料自由回答；B/C 使用相同 view。开发题与正式四题分开，见过后修改的题只能算开发；正式题运行前冻结输入及评分参考。沿用零严重事实/范围错误、至少3/4核心解读可用且有支持增益的门槛；任一严重错误停止，保留失败、不补跑刷分。具体供应商/模型/输出参数尚未冻结，本文件不授权真实调用。

### S4：默认入口和文档精简（Luna 最高）

S1—S3 同一会话路径通后：首页只保留“研究助手”“资料与更新”“历史实验”三类导航，旧演示与 B/C 开发入口放到历史/开发页。历史路由暂时保留兼容，不直接删旧实现。

固定日常阅读入口为 README、PROJECT_PLAN、docs/USAGE.zh-CN.md、docs/handoff/STATUS.zh-CN.md；长上下文保留目标与边界，旧执行细节转为历史链接。必须先保留完整快照再合并正文。

测试分为产品验收与历史复现实验；产品测试不得容忍已知失败，历史冻结失败单独解释。调整默认测试范围必须提交精确模块名单及原因，不能通过隐藏当前缺陷制造全绿。

### 已核实的精简决定（逐文件/组）

| 文件/目录 | 本轮决定 | 实际依据 |
| --- | --- | --- |
| `src/tradeintel_ai/course_adapters.py` | 保留 | web_app 直接 import，不能与课程源码一起移走 |
| `scripts/freeze_g2_research.py` | 暂保留原路径 | g2_ledger、prepare_g2_revision 仍引用 estimate_tokens；先解除依赖再谈归档 |
| `src/tradeintel_ai/analysis_planner_v2.py` | 暂保留 | v3/v4、check_business_delivery、旧CLI直接引用 |
| `src/tradeintel_ai/analysis_planner_v3.py` | 暂保留 | run_confirmed_workflow 与组件脚本引用 |
| `src/tradeintel_ai/analysis_planner_v4.py` | 暂保留 | plan_value_normalization 与旧CLI引用 |
| `vendor/course-reference/` | 从日常导航退出，原路径保留 | 无须安装课程基础设施；源码体积小，移动收益低 |
| `tmp/`、旧 G2 冻结产物 | 不批量清除 | 部分测试及历史证据使用原路径，可能含唯一原答 |
| `data/raw/trade-detail/` | 保留 | 用户要求保留 ZIP，后续新商品接入仍需要 |
| 旧因果脚本/测试 | 列为历史执行范围，暂不移动 | 移动涉及旧导入与冻结校验，不是当前产品接线前提 |

这份审查没有批准任何物理删除。精简首先减少用户入口、默认执行范围与相互矛盾的状态文档，文件迁移等产品主路径稳定后再按逐项清单执行。

### 执行方下一句指令

从本文件 S1 开始，完成公告确认摘要、共享存储锁、独立政策绑定和指定版本检索；保留主案例兼容。不改真实冻结配置、不联网、不移动历史文件。用新增反例及现有 K1/K3/J 测试验收，完成后更新 STATUS 与本文件进度。如遇新公告事实无法适配现有合同，记录具体字段差异并返回 Astra，不另建平行报告系统。S2/S3 未接通前不得宣称项目完成。
