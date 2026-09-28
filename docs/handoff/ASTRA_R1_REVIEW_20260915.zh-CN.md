# Astra对Workbuddy E1—E3交付的审查与集中修复单

日期：2026-09-15。结论：有实质工程进展，暂不通过R1真实实验准备门。E2/E3是部分后端实现，未完成产品验收。本文件优先于此前“E1—E3全部完成”的阶段概括；原日志保留。

## 1. 已核实的正向结果

- 本轮执行 `PYTHONPATH=src:. .venv/bin/python -m unittest tests.test_e1_hardening tests.test_e2_policy_search tests.test_e3_sessions`，66项通过。
- 检查现有真实开发产物 `tmp/handoff-runs/20260915-2224-e1-budget-measurement/`：四个artifact哈希与measurement一致；restore(view,sidecar)==business_payload(catalog)；请求重新估算13299。
- 原畸形ID处理、A3展开、紧凑视图和新增模块有实际代码，不是只补文档。
- 接受13299低于16000这一预算事实：8000是目标，不必为凑目标删条款。最终加入输出合同后的完整实际请求仍须重新计量。
- 本轮没有重跑全量1013项；47项与历史完全一致、零新增回归目前是执行方报告，不能用66项测试替代全量差异核实。

## 2. E1阻断项：输入与输出必须真的接通

### F1 实际准备链仍使用旧预算/旧请求

`prepare_brief_v3_offline.py`仍输出原始messages并以8000标blocked_budget；`run_fake_experiment.py`只接受prepared状态，且同时把原始约31k请求与紧凑请求纳入16000门。主案例即使紧凑后13299，按这两个脚本仍不能贯通。

修复：新增独立紧凑协议准备命令/模式与schema，保存实际待发送messages、view、sidecar、完整catalog、A3和严格manifest；只对实际待发送请求执行硬门，原始请求大小仅作诊断。不要修改旧冻结包。manifest必需文件集合不可为空，核实问题、catalog及sidecar绑定；中断包拒绝。fake输出超过2000应阻止成功状态，目前仅记录output_within_gate仍能标成功。

验收：真实主案例从准备→fake执行连续成功；缺一个必需文件、改问题/sidecar、空hash清单、中断包、输出超限均拒绝。保存同一条可复现命令和完整产物。

### F2 短ID输出未接回真实校验

view_request要求模型用短ID，但未给出完整v3 JSON输出schema；validate仍只认识原始ID。fake回答由原catalog生成长ID，绕过了真实模型将遇到的转换。将fake回答的观察/事实/来源替换为本包短ID后，原校验报duplicate or unknown observation。

修复：C请求必须带明确v3字段合同。保留模型原答，新增仅在声明的ID字段进行短ID→长ID转换的响应适配器，使用受信任本包sidecar，拒绝未知别名；解释原文不得替换。再调用原catalog校验和审阅。B/C共享同一业务view，仅输出合同不同；完整C合同也计预算。

验收：fake从实际view的短ID生成回答，经过同一个响应适配器和正式校验；错别名、跨包别名、目录摘要错误拒绝；原文中碰巧出现f1等字符串保持不动。

## 3. E2阻断项：版本、覆盖和检索边界

### F3 文档正文变化但版本不变（已复现）

build_document的doc_version只含doc_id、source_id、document_sha256与parser；未提供文件hash时，相同source ID改正文仍得同一版本。即使原文件相同，解析文本变化也需要可追踪的新解析版本/正文摘要。validate还要求section ID跨全部文档唯一，妨碍同一文档不同版本共存。

修复：版本摘要包含规范化的来源正文hash、原文件hash（有/无明确标识）、解析版本与必要来源身份；validate重新计算摘要。段落唯一键采用(doc_version,section_id)，不要求不同版本段落局部ID不同。offset当前是Python字符索引，明确标character，不声称UTF-8字节位置。

验收：相同输入稳定；正文变化→版本变化；两版相同source_id/para编号可并存；旧引用仍指向旧正文；篡改版本/正文拒绝。

### F4 无贸易查询也标exact；空引文通过（已复现）

build_coverage默认按whole_hts8推断trade_coverage=exact，没有任何贸易数据证据。build_candidates接受quote=""，因为空字符串总在正文里。parse_code_precision对hs6_only仍强制8位，不能表达真实6位编码。

修复：贸易覆盖缺证据时明确unknown/not_checked；只有受信任查询产物提供商品、月份、版本、可用性后才能标exact/partial/none。保留政策范围和数据覆盖独立两层，partial政策范围不得宣传精确政策敞口。known引用须非空字符串及有效位置；HS6保存6位并禁止扩成HTS8；同理显式表达HTS10/部分范围。候选确认前重验文档store与候选schema/digest、政策身份、字段状态和缺失项，不能只认自算hash。

验收：不传数据结果不能exact；有效数据也不能把ex范围变成整税号精确敞口；空quote、畸形quote拒绝；真实HS6可记录但不能跑HTS8精确查询。

### F5 跨政策和停用内容仍可进入检索（已复现）

build_document_store允许不同policy_id文档，PolicySearch未按policy_id过滤。store标expected但仅装other政策enabled文档，仍命中。include_superseded=True还允许disabled文档返回。

修复：查询明确绑定policy_id；每个候选段落与依赖均检查政策、文档版本、status及日期，候选未确认不得入正式范围。include_superseded只允许显式历史引用，不允许disabled；状态在结果中可见。BM25合并键使用版本+段落ID。

### F6 共同条款只靠两个正则，例外尚未补齐（源码确认）

_required_context只找take effect/entered及of China首个命中，没有方案要求的dependency_ids，也不检查分散的例外/限定。top_k裁切还可能丢掉多税号请求中的后续精确命中，尽管注释称不会。

修复：在文档候选/登记步骤维护有证据依据的required dependency映射（生效、原产地、条件、例外；未确定则明确incomplete），检索沿稳定ID补齐，缺任何必需项不得成功。多税号全部覆盖或返回未覆盖税号；top_k只限制一般命中，共同依赖不得被裁掉。

验收：独立段落例外、句尾500字符后的限制、同政策两版、不同政策同税号、disabled+include_superseded、两个税号top_k=1均加入反例。12题原开发集保留，再补这些新失败题；不得把补题后的开发成绩称盲测。

## 4. E3阻断项：持久化与实际产品接线

### F7 同秒新建会话覆盖旧记录（已复现）

create_session用标题+精确到秒的时间计算ID。同一秒默认标题创建两次，第二次覆盖第一份文件，原消息消失。

修复：UUID随机唯一ID、严格session_id格式与目录内路径校验、创建不覆盖；读改写加单进程/跨进程适当锁或revision比较，原子替换本身不解决并发丢更新。对同一任务的生成许可也要原子领取。

验收：冻结同一秒连续创建保持不同ID和原消息；两份旧revision并发保存拒绝覆盖；重复请求只有一个可进入真实生成。没有网络调用即可测试。

### F8 追问未确认已写入当前请求（源码确认）

换商品虽返回scope_reconfirm_required，resolve_followup仍直接set_request写盘；多月取最后一个月；从请求提取税号后删除旧商品，会把“旧税号+新税号”误读成单一换商品。task_key不含policy_version。

修复：追问返回candidate_request，需范围复核/用户确认时不改已确认请求；多月/多商品需求完整保留并澄清或显示明确支持边界；任务摘要含政策证据版本。未知任务mark_failed路径目前被TRANSITIONS拒绝，修复为仅显式人工处理可用并保存决定者/理由。重试绑定原任务请求，不能用已变化的会话请求冒充原重试。

### F9 页面和更新入口仍未完整（已确认部分未做）

web_app尚无新增session_store/policy_search/policy_candidates接线。controlled_update.update_status把版本created_at当last_checked；无变化检查并未持久写检查时间。真实官方抓取与差异/候选确认闭环尚待实现。

修复：按原E3合同接会话与候选API、证据和预览界面，保留原审阅门；明确模型/数据/待确认/失败状态；持久记录检查时间与结果，不混淆版本创建时间。实现官方source registry、抓取大小/超时/重定向检查、dry-run及修订候选审批入口。调度示例可提供，实际周期启用待用户指定频率。

验收：两条用户路径fixture浏览器贯通、刷新恢复、重复点击一次任务、确认前无执行、更新失败保留旧版、无变化后检查时间更新。仅CLI读取活动版不足以完成E3。

## 5. 执行顺序、预算与返回门

建议Workbuddy集中完成F1—F9；这些是已明确的实现修复，适合低成本执行。先F1/F2形成真实开发包，再F3—F6与F7—F9接线；普通代码不每项返回Astra。原代码/历史产物保留，勿修改旧实验hash来刷绿。

R1暂不通过，原因是协议未贯通，不是13299超预算。不要求进一步压到8000；修好后连同完整C输出schema重新估算≤16000，再交证据。新实验仍最多14次的既定上限；本轮实际0次，模型/端点/参数和正式题尚未冻结。

R2资料由Astra后续从官方来源选择并核对，用户不需要提供逐字段金标。新公告冻结需要先检查开发接触记录，当前不声称已有未见参考。E2/E3修复无需等待R2。

下一次回Astra需交：真实开发包从prepare到fake完整运行、短ID响应闭环、以上反例结果、两条fixture浏览器路径、受影响回归及基线差异。再集中冻结R1/R2和审查真实AI结果。本轮只审查与明确方案，不实施生产代码修复。
