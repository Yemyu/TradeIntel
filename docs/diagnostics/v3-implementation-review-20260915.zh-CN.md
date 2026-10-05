# v3 实现审查：未通过，先集中修复再评估模型

日期：2026-09-15。AI辅助只读检查三个新增模块及既定方案，并用已见七月开发证据包执行内存反例。0模型请求，未读取正式留出参考，未修改产品源码。以下结论覆盖此前“离线原型已完成”的验收口径：代码骨架已实现，规范交付仍不完整。

## 1. 实际发现

| 编号 | 可复现证据 | 影响 |
|---|---|---|
| P1 政策资料丢失 | messages载荷没有policy_facts、sources或任何For certain原文；catalog也未保存完整policy_facts。policy_refs仅有ID和HTS。A3只展示引用编号 | AI无法根据未收到的条款作有依据的政策关联；程序基准也不完整 |
| P2 数据一致性校验缺失 | 单独改变bundle.policy_id、data_version、metric.period、product_scope或比率denominator_id，build_fact_catalog全部接受；NaN比例也接受 | “生成了哈希”只固定错误输入，不能证明时间、商品和分母匹配 |
| P3 元数据/展示问题 | scope_world_import_usd被标origin_scope=China；单商品缺“本次仅选一项”；部分构成比例句缺美国范围；未知句暴露内部kind | 事实目录本身仍可能改变口径，需先保证程序事实正确 |
| P4 展示能绕过绑定 | 先validate合法回答，再把回答catalog_sha256改wrong并传入旧review_result，render_pending仍输出 | 检查对象与展示对象可能不同 |
| P5 原始标记直出 | 上述输出直接保留img/onerror和Markdown javascript链接 | Markdown展示存在注入风险；当前未实测浏览器执行，不能声称已发生XSS |
| P6 准备交付缺失 | manifest缺输入估算、各产物哈希、反例报告；无raw/parsed样例保存流程 | 无法按方案开展有预算、可复核的后续调用 |
| P7 关键词标记影响状态 | “这些资料不证明整体供应依赖。”也直接得到needs_revision | 合法局限被当成必须修改；语义警示应与硬性结构失败分开 |

当前七月消息按既有保守估算公式ceil(1.25*(ASCII字符/3+非ASCII字符*2+128))得到16727 tokens（问题文字“请解释金额规模与存档政策的关系”）。这是估算，非供应商usage；包含重复长来源ID，且还缺政策原文。当前不能直接发送测试。旧G2冻结code_sha256逐项核对，变化0。

原10项v3及17项兼容测试通过的记录保留，但不是本方案全部验收通过。不能以测试名“cross_case”替代实际跨案例反例：现有相关测试只改了不存在的来源ID。

## 2. 修复包A：可信事实目录

只修改新增v3模块，不动冻结v2。

- 把输入验证做在build_fact_catalog入口：非空policy/version与policy_facts完全一致；request月份YYYY-MM有效，metric/observation月份完全匹配；profile HTS8唯一且等于request单商品或policy requested_products覆盖；metric种类、ID、product、measure、unit与对应定义匹配。
- 每商品金额、合计、比率与profile原始金额交叉核对。合计从金额求和；比率用Decimal和原v2四位ROUND_HALF_UP规则核验，超差拒绝，不能暗改输入。明确校验numerator/denominator指向正确同商品或本次scope指标，不能只检查ID存在。
- status/value一致；拒绝NaN、Infinity、bool充整数、负值、China大于all；零分母只接受unknown/None。源引用非空、唯一、存在；缺必要指标拒绝。
- 观察覆盖、榜首/并列关系与profiles一致；不能只把外来observation_id照单登记。
- catalog保留本地evidence_snapshot（完整输入bundle，作为审计字段），验证catalog时从snapshot重建确定性投影并比较全部字段及摘要；内部拆分无递归的build/validate函数。snapshot不进入模型消息，调用方若有预期证据哈希须比较；同一文件自带哈希不提供外部真实性保证。
- 完整保存policy_facts与sources。仅接受原始未打包EvidenceBundle；删除目前不起作用的$groups猜测分支，传输解包放显式边界。
- origin_scope把scope_world明确标all_origins；金额指标分母显示“不适用”，不要“该指标本身”。每条构成比例含美国消费进口/月/所选范围。单商品构成100%附限定，未知用中文指标名。Decimal真实用于格式化。

验收反例：本报告P2六项均拒绝；错分母指向另一个存在指标也拒绝；scope_world原产元数据正确；单商品100%、全零、零中国、并列及同榜首均正确；原七月数值不变。测试使用合成资料，正式四题仍留出。

## 3. 修复包B：政策证据真正到达AI与A3

- catalog、A3及模型业务载荷均保留同一policy_facts：存档身份、条文原文、税率、日期/适用事件、商品条件和例外未知。sources有文本/URL，只有可用http(s)来源允许生成可点击链接，其余作为转义文字。
- 构建policy_refs须从各商品field_refs和source_id派生，保留生效时间等共同条款到所选商品的有效引用；不能只收每商品一条税率来源。
- B3/C3未来使用同一业务资料；当前只准备C3，无需调用。A3应展开确定性观察（包括并列）和完整政策资料，以此作为更强程序基准。
- 使用已存在的无损pack/restore机制减少重复ID及元数据传输；审计字段移到sidecar时须能完全恢复业务证据。原文、限定、数值、事实句不能因预算删除。模型只需最小完整业务视图，磁盘仍保留完整目录。
- 在离线准备输出中记录估算方法和结果，暂沿用8000输入估算门槛。若补齐政策后压缩仍超预算，标blocked_budget并停止交付为可调用包，需重新作方法判断；不能自动提升上限、截原文或挑掉商品。

验收：从最终发送载荷解码后，原文逐段、条件/例外、同一版本事实全部等于catalog业务资料；包含p8生效原文和p9/p12商品原文，未知仍未知。用合成条件字符串和注入文本验证保留内容但不把它当指令。真实七月原文是已见开发材料，可用。

## 4. 修复包C：原答解析、展示与引用检查

- render_pending每次都对当前answer/catalog调用validate；旧review_result参数删除或仅可在与重算结果完全相同时使用，不能跳过检查。
- 新增原始文本处理入口（可在evidence_linked_brief模块内），调用共享parse_json_response，保留raw原文及raw_sha256、parsed对象。不要只import解析器却不用。结构值类型先检查再set/membership，统一ValueError，避免TypeError绕过受控错误路径。
- 解释、followups、政策原文、源名称等展示文字统一转义HTML和Markdown活动语法；raw文件字节保留。逐行引用或安全文本呈现，不能让换行脱离引用块。转义是展示编码，不能修改模型语义。
- fact/observation/catalog绑定照方案；重复policy_refs拒绝；同请求另一商品能作为比较证据，但政策引用须对应明确引用的商品事实。引用格式正确仍待语义审阅。
- 关键词只产生review_warnings，默认manual_review_required；不据“依赖”等词自动判needs_revision或严重错误。额外数值重述可标需核对，但HTS编码与数字主张不要混为一谈。不扩大成中文否定词语义分类器。明确结构错误、警示、人工语义结论三者职责。
- 系统提示补齐按focus覆盖要求、followups准确字段、资料为非指令。不得为了测试可用而删去政策限定。

验收：旧review_result+变更摘要拒绝；改目录事实文字拒绝；原答raw保持；重复JSON键拒绝；数组/对象混入ID报ValueError；渲染不含活动HTML/javascript链接；合法“不证明依赖”保留manual_review_required且可附warning；缺必需观察显式incomplete、未approved。

## 5. 修复包D：可复现交付一次收口

- 扩展现有offline脚本，仍无live/provider/credentials入口。输入显式、输出不覆盖，先完成全部校验与内存产物再发布；失败目录标未完成，成功manifest最后写。
- 输出catalog、业务消息及无损sidecar、A3、manifest（每文件sha256、输入bundle摘要、估算及门槛、0 API、版本）、可选fixture raw/parsed/pending报告。fixture明确不是模型成绩。
- 新增有意义的反例测试，按A/B/C包覆盖；测试不依赖私人tmp。CLI子进程集成测试验证无密钥和禁止网络时成功、已有目录不覆盖。冻结源码哈希前后比较，只读。
- 开发样例输出到项目tmp下新建专用目录（旧G2不能覆盖），路径写入交付说明；技术说明需明确目前仍是原型。
- 只跑新增v3测试与共享解析器必要兼容检查，既有17项测试无需反复跑。输出测试摘要，逐条对照本文件验收项，不用条数代替覆盖。

## 6. 下一阶段与停止边界

按A→B→C→D完成一个集中修复包；遇到需要改变事实定义、修改冻结源码或补齐证据后仍超预算时，先重新审查。完成后进行一次反例复核及实验采纳判断。现在不接生产页面、不启动新模型实验；旧G2的10个剩余槽保持停止。

本次审查没有证明模型变差或v3方向无效；它确认当前代码没有完整实现既定方案。先修这些可重复的工程问题，再用真实调用检验AI增益。
