# G1 B：逐商品资料与请求投影

## 本轮交付

新生成的原始事实卡采用archived-policy-facts-v2。主案例五商品、候选光伏案例两商品共用增强器；运行时商品名称读取绑定发布目录的登记表，不读取活动工作区覆盖版本。保存登记表文本、哈希、行引用，名称明确属于登记元数据，不是法律原文。

各商品新增名称、原文共享条款、原产条件、生效时间/时区/事件、一般条件及例外状态，以及逐字段引用。政策引用包含policy_id、data_version、chunk_id、文档/片段哈希、URL。条件和例外尚未核全，因此是unknown、带原因和空引用，不编造适用证据。候选案例登记表没有中文名称，保留英文并明确中文名unknown及原因，不用自动翻译冒充登记值。

原文保留完整已核查段落，避免截取税号所在行而漏掉共享条件。投影中这些段落标为共享原文背景，不是本次分析商品清单；例如钨段落仍可能提到其他钨税号，但当前product_rates只有用户选择的商品。无关的硅段落不发送。

## 旧证据兼容

旧v1及无schema历史/测试资料保留既有bundle构建行为。只有v2事实卡引入投影，投影自身使用archived-policy-facts-projection-v2，不能冒充完整事实卡。policy-facts.json保存完整原件，其哈希仍绑定完整原件；模型证据与短卡只显示当前范围。审阅时从完整事实卡和固定贸易证据重建投影，修改投影不能绕过一致性验证。

没有修改原始政策文件、贸易数据、旧运行产物或旧实验成绩。没有开放候选案例。

## 测试证据

命令：`PYTHONPATH=src:. .venv/bin/python -m unittest tests.test_policy_facts_contract tests.test_g1_repairs tests.test_solar_release tests.test_primary_interpretation_flow tests.test_research_brief_v2 tests.test_reviewed_draft tests.test_business_workflow tests.test_interpretation_review_store tests.test_review_revisions -q`：当时47项通过。

随后新增单商品实际链路测试，单独执行`tests.test_g1_repairs.G1RepairTests.test_single_product_real_pipeline_preserves_full_archive`，1项通过：真实本地发布数据、模拟模型，验证完整五商品存档→单商品入模→审阅重建→导出名称/未知条件。合计48项。无外部模型调用；不能作为真实AI能力成绩。

其他新增回归：两案例字段绑定、字段遗漏/错误来源/跨版本/错误时间/登记内容篡改拒绝、单商品投影不改变原件、v1保持旧构建行为。未对所有私人历史运行逐份执行兼容扫描；未做新文字浏览器视觉验收。

## 给使用者的解释

这不是训练模型，而是把它拿到的资料组织准确。以前问一种商品，它会拿到整组商品资料；现在当前分析范围明确分开，原文仍可追溯。名称、税率、日期都由程序提供，AI负责解释统计观察。例外未核清就明确说不知道，而不是推断无需缴税。

## 后续

A/B已分别实现并局部回归；G1仍不能整体宣布通过。下一步C：固定按产品职责划分的测试入口、资源依赖清单及干净临时目录复现。按锁定验收规范执行；若发现历史兼容或方法冲突，停止扩大修改并审查。C之后作G1最终采纳，随后才按原G2预算执行真实模型对照。不新增政策、不反复试失败因果方向，不提交推送。
