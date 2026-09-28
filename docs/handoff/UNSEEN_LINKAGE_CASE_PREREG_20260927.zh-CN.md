# 新关联方案：单份未参与开发公告的事前登记

2026-09-27，登记时尚未执行本轮网页搜索。目标是验证已完成 B4 的公告流程能否按真实原文给出恰当的统计背景或明确无图结果。一次案例不用于估算总体准确率，也不计入模型评测。

## 假设、对照和选择顺序

假设：冻结实现能保留一份新公告的关键范围与限制，并按人工参考判断生成相称报告，严重误导为零。对照为已见 R2 的 18 税号/12 月/71,062,824 美元回归，已于 B4 通过；本阶段不重复把 R2 当新材料。

固定查询依次为 `site:govinfo.gov 2025 China April additional duties CBP Federal Register implementation`、`site:govinfo.gov 2025 Section 301 product exclusions extension Federal Register`。按工具返回顺序考察官方独立公告，跳过仓库记录已见的文号与整期公报。第一份可完整读取并保存的未见公告即锁定，无论参考结论是何种分流，都不因无法画图换样本。最多三份新候选；只有正文/必需附件确实无法完整获取才继续下一份。登记所有排除和访问失败。

已见排除至少包括 R2 `2025-23912`、`2026-19537`、`2026-17925`、`2026-15181`、`2025-19568`、`2019-17865`、`2025-02293`、`2026-19498`、`2025-03677`、`2025-15010`、`2025-07325`，以及上述材料已读的相关修订。新文号在锁定前须再检索仓库/本地评测目录，记录是否已参与过开发。

## 参考判断先于产品执行

先读原文和必要附件，写出适用对象、原文税率及性质、条件/例外、日期、原产地、可对应的统计总体和预计分流。事实逐条保留准确引文与位置；程序准备/报告尚未运行时保存并计算参考文件摘要。正文不为了适配字段而删条款。

本轮参考由当前 Astra 根据官方原文整理，并非独立经济学家或人类法律审阅者的金标。执行可以验证新材料流程、数据一致性和前置参考是否被保留；不得称“独立人工法律验收通过”。存在决定分流的实质歧义时保留歧义并停在参考审查，不靠程序接受倒推参考正确。

后续执行使用空白隔离存储，保留全部原文，13 字段未知项明确原因。有数据的路线先使用页面默认月份；缺源包或连续月份时如实记失败，不缩月后当原任务通过。无图路线不传月份。任何为探查问题进行的第二范围均另记诊断。数据只读，代码/门槛/提示词不得根据这份公告结果修改；修复后此材料即属开发已见，原失败保留。

## 指标与停止条件

记录：（1）预先判断与产品路线是否一致；（2）关键条件/例外是否完整进入确认单和报告；（3）有图时金额/编码/中国大陆与香港口径及文件版本是否一致；（4）无图时金额和图表是否都缺席；（5）刷新/重启读回、中文及英文界面的关键范围表达。错误声称政策覆盖额、政策因果、现行税率或把局部范围当全范围，任一出现即失败，不用免责声明抵消错误正文。

预算：最多三份新候选，模型 API 0 次、MySQL 写入 0 次，不推送、不扩数据采集、不修改产品代码；原件总下载上限 20 MiB，超过则记录获取限制并停止。本阶段只完成材料与参考；下一执行阶段由低成本模型按固定断言运行，不能改参考刷通过。

## 冻结实现和数据

工作区 HEAD `b5551385a614a048ca99c6141115fc25f8ecf118`，含未提交 B4；下列 SHA-256 是关键行为文件指纹，不能只用 HEAD 复现此工作区。执行前必须核对；若变化先说明差异，不更新指纹后假装原版通过。

```text
8d3d2651e0e3ff99b25501d217e0801d96dd52575b1d547fdfbf495cd4592496  src/tradeintel_ai/announcement_linkage.py
08c50fde073e384dc2c950393b90ee89b63e78dde0364a2351798ebeb577ddfa  src/tradeintel_ai/announcement_context_report.py
648862e8528b04c5167b5544fc027ab85bf6b767f4e5e3e615371d6c30d67345  src/tradeintel_ai/announcement_country_context.py
070976a759b567ddc1a271de42a90a13cb3814f172056f968fb2fa29ff25b4c2  src/tradeintel_ai/announcement_source_card.py
517d34b87ea40e846a1cd57a6a2c5307d8ebc29e86c110fc8c515b1a3d288855  src/tradeintel_ai/announcement_statistics_report.py
848ce2ab630d7cc24e7e7838bad11c17f7cef47277edc16d7f17e783c949a69c  src/tradeintel_ai/announcement_flow.py
1f84d12c16111423e7191a3d12e1d0b55403a6495dffec55688be8bd3847b6cd  src/tradeintel_ai/policy_candidates.py
744f08e0e161eb82c57cf8a9d4ead96665438f5f15549351a27660582f1027e1  src/tradeintel_ai/policy_documents.py
de2731d8eb9579e88eb5880640777822b28de46da43450fae4976090a351f57f  src/tradeintel_ai/trade_data_repository.py
12a87f978d302ad00aa0d95b1e6762fcc1b5a3d63410917305b90e588b28250e  src/tradeintel_ai/trade_classification_catalog.py
192954b7f5d78e494bbdcd09f5a11b3fe34a0b12735b6546b85a5fed743d82eb  src/tradeintel_ai/trade_report_store.py
20f3ca53778fdb662cbead77b01fc44327b51b8cef2fafd0994d013f20645e94  src/tradeintel_ai/web_app.py
201769e8bcd01049276fc434d9c07b6fc51a6c60221fe560caea11ef8e8ed4fd  web/announcement-import.html
9e62dcd8868e5543ee8e8d022ce2babd3a508d9c28541c1a7b3c3c2d97789310  web/design-preview/live.js
335603c54721e8489907109e709bba209afcdeaaf5fc53ac843424ac1abaa207  data/processed/trade_hts10/manifest.json
7b02107219363c7551f2ce94fc2ddd64336b0c2e982297384c579645f46297a3  data/processed/trade_classification/manifest.json
```
