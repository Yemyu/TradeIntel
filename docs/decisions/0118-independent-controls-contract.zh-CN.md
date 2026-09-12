# 0118：独立查询基准与政策配对审查契约

> 0119复审更正：本文件的设计要求继续有效，后追加的实现说明不代表全部满足。事实待审/拒绝原先仍会完成，现已修复；实际HTTP payload未捕获、快照仍partial、两组schema仍不同。当前证据和补齐清单见[0119](0119-controls-integration-review.zh-CN.md)。

## 本阶段交付与边界

这是0117要求的设计与首轮离线接线阶段：锁定输入、输出、评分、停止条件，并在现有prospective_acceptance模块加入compare_trade_scope、validate_policy_pair和逐事实审查结构校验。prospective_runner现在会在规划调用前保存贸易baseline、在执行前比较主组范围、在政策两组调用前比较配置并在两组完成后保存脱敏的provider-neutral payload捕获；政策事实包默认仍为pending_human。正式acceptance_ready保持false。没有新模型实验，也没有训练模型；后续不能把合成运行结果当作模型准确率。

## A：独立请求先于模型存在

每个贸易支持案例在调用前保存私有baseline.json：case_id、原问题sha256、完整request={trade,comparison}、独立审查者、来源文件哈希、逐月参考金额、比较公式及结果。request必须包含policy_id、operation、metric、origin、granularity、months、hs6、causal_effect；comparison保留kind和方向或登记ID。金额来自源表独立读取，参数由审查者按题文确定。不可从主组的preview、plan、result、summary生成或补全baseline。

调用前冻结baseline文件及题文；模型工厂仍只接收公开id/question。已有0111参考已经看过且语义审查未完，只能作历史候选材料，不升级称未见题。当前只用明确标记的开发fixture完成接线。

执行次序：先运行独立A请求并用源表复算；再让模型提出计划。主组计划经既有plan/gap审查后才执行。compare_trade_scope逐字段比较独立request与主组request，输出差异；该比较只能评分、拒绝，不能用金标准自动修复主组参数、选择工具或添加任务。月份列表按集合排序比较；endpoint方向必须原样比较；bool与整数不可互换。两边数值相等不能覆盖范围差异。

A使用既有execute_request只读入口；用单独源表算法核对每月金额、完整性、总额、差额和百分比（百分数，Decimal四舍五入两位；零基数为null）。HS6其他原产地为all_origin减china。登记窗口的reference/current月份从冻结的registered_comparison_windows.json和比较ID独立解析，保持ID语义与月份并存；不得从主组summary取月份。登记窗口接线失败应明确not_implemented并阻止正式验收，不能删题来提高分数。

## 政策：先拆清要测的两种能力

端到端主流程测“理解问题—检索—回答”；政策配对只测“相同政策问题下，提供项目证据是否改善回答”。两项分开报告。若规划把政策问题改坏，端到端记失败；不能靠把正确金标准问题送回主流程来补救。

配对输入来自调用前冻结的公开policy_question与policy_as_of。组合案例的政策子问题须在运行前由审查者逐字提取核对，保留原完整问题。两组使用同一模型、同一base_url、temperature、timeout、thinking关闭、stream=false、max_tokens=768；相同输出schema。validate_policy_pair在两组调用前比较这些有效配置。须捕获适配器实际发送的脱敏payload，并验证与预先配置一致；声明相同但实际不同视为协议失败。

主/B回答统一为claims数组，每条含text和citations；B允许citations=[]。主组system说明根据给定文档作答，B说明使用已有知识、未知可说明；公共要求（历史范围、不得推断因果、最多6条、语言和输出格式）完全一致。两份prompt及差异一并冻结。该实验评估“证据辅助工作流相对无检索基线”，不声称只改变证据一个变量的纯消融实验。若要纯消融，另行设计，不能悄悄更换当前结论口径。

## 同一逐事实审核表

每个案例调用前冻结facts数组；每项含id、题文引文、所需事实、可接受改写、官方证据id/页码/摘录/源hash、出版日、适用范围及截止日。公告日期与Federal Register出版日期分开，不把2018-06-15和2018-06-20混用；参考无截止日前证据则案例预检失败。

主/B每组分别提交相同结构的审查表：

| 字段 | 必填规则 |
|---|---|
| case_id、arm、packet_sha256、reviewer、reviewed_at | 绑定具体案例、组别、原文与身份，禁止跨题/跨组复用 |
| facts | 每个冻结fact_id恰好一次：supported / missing / contradicted / unverifiable及原因 |
| claim_indices、quote、source_id、evidence_excerpt | supported或contradicted须指向真实回答及冻结证据；missing允许无claim但必须说明未回答什么 |
| claims | 每条实际输出claim恰好一次审查：supported / unsupported / contradicted / uncertainty；列关联fact_id与理由 |
| citation_review | 仅主组额外检查引用存在、截止日和是否支持主张；B没有项目引用不扣事实分 |

分句、claim关联及语义结论由有身份的审查者作出，程序核对完整性、原文摘录、哈希、来源日期和链接。既有answer_checklist和gap协议继续复用，但不得自动把fixture的pass改写为人工supported。引用存在不能自动判事实正确。整段回答即使把几个事实写在同一claim里，每个事实也须分别判断；额外编造的内容不能因不在题目清单里就被忽略。

例如“不是25%”应为contradicted；“百分之二十五”可为supported；“我不知道”通常为missing；“税率25%，因此所有进口下跌都由关税导致”税率事实可对，但额外因果主张为unsupported。程序不能靠字符串自动给这些结论。

## 计分与停止条件

- 事实覆盖率：人工supported事实数 / 冻结所需事实数。另报missing、contradicted、unverifiable数量。
- 多余错误主张：逐组报告unsupported/contradicted的实际claim数及总claim数；它不是“幻觉率”自动估计。
- 严格问题通过：范围正确、所需事实全supported、无unsupported/contradicted/unverifiable事实或主张，主组引用也通过。若存在不确定陈述，由清单规定是否影响所需事实完成，不能默认通过。
- 配对改善：只在两组都完成有效调用且人工审查完整时计算同题差异；必须同时展示最初冻结题数、实际完成配对数、未运行及中断数。不能把未完成B算作零分来宣称主组更好。
- B答错是被记录的实验结果，不是要求重试的故障。系统性字段缺失、传输错误、截断、未知用量、快照变化首错停止；不重试，不续跑。有效但答错的主组按原首个业务失败规则停止后续题，留下固定分母。
- 不要求RAG必须赢才采纳实验。可采纳的是过程可信且所有预先声明检查完整；性能另行报告。正式发布门槛须在真实题运行前明确，不能看结果再定。

## 冻结与最终绑定清单

调用前保存快照本体，明确列出实际src/tradeintel_ai模块、运行脚本、注入fixture/审查器代码、有效配置及prompt、题文、baseline、facts、登记窗口、所有DataPaths实际使用文件、语料JSON与原PDF、依赖锁定记录和Python版本。文件清单及目录成员也须冻结；不静默跳过缺失文件。仅对实际使用文件求hash，避免把整个data目录或无关ZIP反复读取。无法声明注入代码来源时保持partial且禁止正式验收。

完成绑定必须串起同一case/snapshot下的真实调用、计划审查、gap审查、A执行和复算、实际交付目录及marker哈希、答案审查、适用的B调用/审查。确认报告文件与review packet一致后，再做收尾重验。账本内validation/status不能由调用者声明即生效。

## 下一实现单元：Astra中复审后再决定是否进入真实题

沿用现有prospective_runner、prospective_acceptance、answer_checklist和ResearchPolicyModel；不新增并行运行框架。首轮离线接线已覆盖独立A入口、配对配置/捕获、事实审查包和完整快照字段，并新增5项集成测试；事实审查默认待人工，正式绑定仍未把它算作语义通过。下一步由Astra中复审接线差异，再决定是否补组合/边界fixture、扩充反例和准备新的离线整链；在线入口继续关闭。

本阶段的两个纯函数只验证输入相等/不同及配对配置；不证明基准独立来源，也不证明真实HTTP payload相同。这两项证明由上述接线承担。

## 本阶段验证记录

2026-09-13：0118首轮接线后全套`PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`共602项通过（30.978秒）；随后定向9项回归测试通过，`git diff --check`通过。包含新增范围/配对/事实审查集成测试；测试使用合成/模拟调用，不代表真实模型表现改善。0外部API调用，未提交或推送GitHub。
