> 本报告由 research-plan-4 生成：模型先提出计划，用户确认后才执行。
> 会话修订：1
> 原始问题：第一批关税何时生效，额外税率是多少？政策资料截止日是2018-07-06；查询其他原产地整体2018-09和2018-10的美元消费进口额，比较2018-10相对于2018-09，只做描述性比较，不做因果分析；第一批关税，政策整体范围。
> 本次模型调用 2 次；交付状态请查看 delivery-status.json。

逐项需求执行记录（不代表语义覆盖已验证）：

- request-001：第一批关税何时生效，额外税率是多少？；已生成草稿，内容待核对
- request-002：查询其他原产地整体2018-09和2018-10的美元消费进口额，比较2018-10相对于2018-09，只做描述性比较，不做因果分析；第一批关税，政策整体范围。；程序执行完成，语义待核对

# TradeShock：贸易与政策研究简报

> 实验性研究草稿，不是因果结论，也不是自动审定的政策意见。

## 1. 这份报告回答什么

第一批关税何时生效，额外税率是多少？

政策资料截止：2018-07-06。该日期只筛选政策文件，不限制下面历史贸易观察期。
贸易范围：美国进口 / List 1暴露范围 / 其他原产地整体（不含中国） / 政策整体；消费进口额，美元。

范围由模型根据自然语言提出，经确认后执行；确认不等于语义正确，仍需逐项核对原话与证据。

## 2. 贸易数据告诉我们什么（程序计算）

| 请求月份 | 进口额（美元） |
|---|---:|
| 2018-09 | 36,587,820,118 |
| 2018-10 | 41,012,723,839 |

所列月份合计：77,600,543,957 美元。
明确比较：2018-10 相对 2018-09
基准窗口：2018-09
当前窗口：2018-10
金额变化：4,424,903,721 美元；变化率：12.09%。
这是明确登记或指定窗口的描述性比较，不是全年变化、政策前后平均效应或因果估计；登记窗口也不等于因果识别。

## 3. 政策文件怎样解释（AI 草稿与证据分开）

检索桥接表达（只用于寻找候选原文，不替代原问题）：effective date additional duty rate first batch Section 301 tariff list 1

生成状态：draft_requires_semantic_review；回答来源：live；本次新 API 调用：1。
引用编号有效只代表来源存在；文字是否被原文支持，仍需审查。

第一批关税针对中国产品，额外税率为25%。

引用：initial_notice:p1:w4068-6468, initial_notice:p2:w4500-6900

该关税适用于2018年7月6日或之后进入消费或从仓库提取供消费的产品。

引用：initial_notice:p1:w4068-6468

具体生效时间为2018年7月6日美国东部夏令时00:01。

引用：initial_notice:p2:w4500-6900, initial_notice:p2:w3650-6050

审查提醒（第3条）：用户未明确询问精确时刻；检查它是否为必要条件，不自动删除。

## 4. 不能从这里得出的结论

当前研究设计状态：blocked_before_pretrend_v3。
本报告没有估计因果效应。政策文件说明规则，贸易表显示观察结果；把两者放在一起，不等于证明关税造成了这些变化。
政策资料库仅含两份公告的已索引正文，不覆盖完整附件、后续全部修订或现行税率；政策整体暴露口径不等同于逐笔应税交易。

## 5. 可核查来源

贸易工具的来源及校验指纹（完整记录见同目录 result.json）：

- data/processed/policy/section301_list1_event.csv；SHA256：86d1c255ac8c3d139143b50175cbc0b05cd03bd875a0e7994006429382b8fdba
  来源网址：https://ustr.gov/sites/default/files/2018-13248.pdf
- data/processed/causal/policy_exposure_hs6.csv；SHA256：0acdbe2ed73e8ff4204b1b35511a447490cbcc35ebf6b42ab37f16dc1f1bddaa
- data/processed/causal/causal_trade_panel_manifest.json；SHA256：9c338f6e3a1c4698d937bf1a864bf191adf19d4d85d4310d90f5fbb38720ee0d
- data/processed/analysis/policy_case_monthly.csv；SHA256：0638c2074fb7ec0059c5a94ad56d01c264ba6f5215f5701aac532d37f6104400
- IMDB1809.ZIP；SHA256：dc5c1617a6481aa66c966766f8d93ad9ef76289ee02e4d6c620651bebe13cd9e
  来源网址：https://www.census.gov/trade/downloads/2018/Merch/im_m/IMDB1809.ZIP
- IMDB1810.ZIP；SHA256：d08670b3212e20e3ecd41888b732edec9c5970e83612a83430a699b028d196dc
  来源网址：https://www.census.gov/trade/downloads/2018/Merch/im_m/IMDB1810.ZIP
- config/causal_control_design.json；SHA256：6b8aeb74f8d71518d67cd9c5f57db33fa79d85b3955559f170691e5718060375
- data/processed/causal/control_eligibility_report.json；SHA256：f271a8064fc4aa8bdfa1a56786eeb673e2599f142648bc33714727a6420d9854
- data/processed/causal/matching_balance_report.json；SHA256：d56736bd61a4cd8b1a65fd5c7bd36a7b06c37cf11117836d5d5990e21d327b0a
- data/processed/causal/matching_balance_report_v2.json；SHA256：f847942edd66041ea2777832157369e710229b26a6b5bd5cf88b259a9f0c2c53
- data/processed/causal/matching_balance_report_v3.json；SHA256：5e072fc9f972a51b15aef478607623fd2c2d441c2463d977a721ed68bf1592e9

政策候选原文（窗口扩展未改变原检索排名）：

### initial_notice:p1:w4068-6468

出版日期：2018-06-20；第1页；原文字符 4068–6468。
来源：https://ustr.gov/sites/default/files/2018-13248.pdf#page=1
SHA256：3e27dfb420dc308a079e7a71f2715fa29ed00fbbd84dbec4514f2cd66b9cf301

> to Technology 
> Transfer, Intellectual Property, and 
> Innovation 
> AGENCY: Office of the United States 
> Trade Representative. 
> ACTION: Notice of action, request for 
> comments, and notice of public hearing. 
> SUMMARY: The U.S. Trade 
> Representative (Trade Representative) 
> has determined that appropriate action 
> in this investigation includes the 
> imposition of an additional ad valorem 
> duty of 25 percent on products from 
> China classified in the subheadings of 
> the Harmonized Tariff Schedule of the 
> United States (HTSUS) set out in Annex 
> A of this notice. The Trade 
> Representative has further determined 
> to establish a process by which U.S. 
> stakeholders may request that particular 
> products classified within a covered 
> tariff subheading in Annex A be 
> excluded from these additional duties. 
> Further, the Office of the U.S. Trade 
> Representative (USTR) is seeking public 
> comment and will hold a public hearing 
> regarding a proposed additional action 
> in this investigation. The proposed 
> additional action is the imposition of an 
> ad valorem duty of 25 percent on 
> products of China classified in the 
> HTSUS subheadings set out in Annex C 
> of this notice. 
> DATES: 
> Applicable date of duties: The 
> additional duties set out in Annex A to 
> this notice are applicable with respect to 
> products that are entered for 
> consumption, or withdrawn from 
> warehouse for consumption, on or after 
> July 6, 2018. 
> Comment and hearing deadline: To be 
> assured of consideration, you must 
> submit comments and responses with 
> respect to the proposed list of products 
> in Annex C to this notice in accordance 
> with the following schedule: 
> June 29, 2018: Due date for filing 
> requests to appear and a summary of 
> expected testimony at the public 
> hearing and for filing pre-hearing 
> submissions. 
> July 23, 2018: Due date for submission 
> of written comments. 
> July 24, 2018: The Section 301 
> Committee will convene a public 
> hearing in the main hearing room of the 
> U.S. International Trade Commission, 
> 500 E Street SW, Washington, DC 20436 
> beginning at 9:30 a.m. 
> July 31, 2018: Due date for submission 
> of post-hearing rebuttal comments. 
> ADDRESSES: USTR strongly prefers 
> electronic submissions made through 
> the Federal eRulemaking Portal: http:// 
> www.regulations.gov. Follow the 
> instructions for submitting comments in 
> sections D, E, and F below. The docket 
> number is USTR–2018–0018. 
> FOR FURTHER IN

### initial_notice:p2:w4500-6900

出版日期：2018-06-20；第2页；原文字符 4500–6900。
来源：https://ustr.gov/sites/default/files/2018-13248.pdf#page=2
SHA256：3e27dfb420dc308a079e7a71f2715fa29ed00fbbd84dbec4514f2cd66b9cf301

> he Trade Act of 1974 (19 
> U.S.C. 2411(b), 2411(c), and 2414(a)), 
> the Trade Representative determines 
> that appropriate and feasible action in 
> this investigation includes the 
> imposition of an additional ad valorem 
> duty of 25 percent on products of China 
> covered in the tariff subheadings listed 
> in Annex A to this notice. Annex B to 
> this notice contains the same list of 
> tariff subheadings, with unofficial 
> descriptions of the types of products 
> covered in each subheading. 
> In order to implement this 
> determination, effective July 6, 2018, 
> subchapter III of chapter 99 of the 
> HTSUS is modified by Annex A of this 
> notice. Products of China that are 
> provided for in new HTSUS heading 
> 9903.88.01, as established by Annex A 
> of this notice that are entered for 
> consumption, or withdrawn from 
> warehouse for consumption, on or after 
> 12:01 a.m. eastern daylight time on July 
> 6, 2018, shall be subject to an additional 
> duty of 25 percent ad valorem. The rates 
> of duty applicable to products of China 
> that are provided for in new HTSUS 
> heading 9903.88.01 shall apply in 
> addition to all other applicable duties, 
> fees, exactions, and charges. 
> Any product listed in Annex A, 
> except any product that is eligible for 
> admission under ‘domestic status’ as 
> defined in 19 CFR 146.43, which is 
> subject to the additional duty imposed 
> by this determination, and that is 
> admitted into a U.S. foreign trade zone 
> on or after 12:01 a.m. eastern daylight 
> time on July 6, 2018, only may be 
> admitted as ‘privileged foreign status’ as 
> defined in 19 CFR 146.41. Such 
> products will be subject upon entry for 
> consumption to any ad valorem rates of 
> duty or quantitative limitations related 
> to the classification under the 
> applicable HTSUS subheading. 
> During the notice and comment 
> process, a number of interested persons 
> asserted that specific products within a 
> particular tariff subheading were only 
> available from China, that imposition of 
> additional duties on the specific 
> products would cause severe economic 
> harm to a U.S. interest, and that the 
> specific products were not strategically 
> important or related to the ‘‘Made in 
> China 2025’’ program. In light of such 
> concerns, and pursuant to sections 
> 301(b), 301(c), 304(a), and 307(a) of the 
> Trade Act of 1974 (19 U.S.C. 2411(b), 
> 2411(c), 2414(a), and 2417(a)), the Trade 
> Representative has determined that 
> USTR will esta

### initial_notice:p2:w3650-6050

出版日期：2018-06-20；第2页；原文字符 3650–6050。
来源：https://ustr.gov/sites/default/files/2018-13248.pdf#page=2
SHA256：3e27dfb420dc308a079e7a71f2715fa29ed00fbbd84dbec4514f2cd66b9cf301

> nology- 
> intellectual-property-chinas- 
> discriminatory-burdensome-trade- 
> practices). 
> USTR and the Section 301 Committee 
> have carefully reviewed the public 
> comments and the testimony from the 
> three-day public hearing. In addition, 
> and consistent with the Presidential 
> directive, USTR and the interagency 
> Section 301 Committee have carefully 
> reviewed the extent to which the tariff 
> subheadings in the April 6, 2018 notice 
> include products containing industrially 
> significant technology, including 
> technologies and products related to the 
> ‘‘Made in China 2025’’ program. Based 
> on this review process, the Trade 
> Representative has determined to 
> narrow the proposed list in the April 6, 
> 2018 notice to 818 tariff subheadings, 
> with an approximate annual trade value 
> of $34 billion. 
> Pursuant to sections 301(b), 301(c), 
> and 304(a) of the Trade Act of 1974 (19 
> U.S.C. 2411(b), 2411(c), and 2414(a)), 
> the Trade Representative determines 
> that appropriate and feasible action in 
> this investigation includes the 
> imposition of an additional ad valorem 
> duty of 25 percent on products of China 
> covered in the tariff subheadings listed 
> in Annex A to this notice. Annex B to 
> this notice contains the same list of 
> tariff subheadings, with unofficial 
> descriptions of the types of products 
> covered in each subheading. 
> In order to implement this 
> determination, effective July 6, 2018, 
> subchapter III of chapter 99 of the 
> HTSUS is modified by Annex A of this 
> notice. Products of China that are 
> provided for in new HTSUS heading 
> 9903.88.01, as established by Annex A 
> of this notice that are entered for 
> consumption, or withdrawn from 
> warehouse for consumption, on or after 
> 12:01 a.m. eastern daylight time on July 
> 6, 2018, shall be subject to an additional 
> duty of 25 percent ad valorem. The rates 
> of duty applicable to products of China 
> that are provided for in new HTSUS 
> heading 9903.88.01 shall apply in 
> addition to all other applicable duties, 
> fees, exactions, and charges. 
> Any product listed in Annex A, 
> except any product that is eligible for 
> admission under ‘domestic status’ as 
> defined in 19 CFR 146.43, which is 
> subject to the additional duty imposed 
> by this determination, and that is 
> admitted into a U.S. foreign trade zone 
> on or after 12:01 a.m. eastern daylight 
> time on July 6, 2018, only may be 
> admitted as ‘privileged foreign status’ as 
> defined 

## 6. 这次 AI 做了什么

采用 BM25 词法检索、同页上下文扩展、受证据约束的生成及引用结构检查。金额和变化率不交给模型编写；没有训练或微调模型，也不声称已经实现自主多智能体。
报告及原始响应可供人工审查；没有自动改写模型主张或给出语义准确率。
