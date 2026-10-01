# 最小 Agent 修复：离线执行记录

2026-10-01。用户“继续任务”按其约定作为 GPT-6 Luna Max 切换确认；按 [唯一方案](../MINIMAL_AGENT_REPAIR_DESIGN_20261001.zh-CN.md)实施。真实数据只读，测试报告写临时目录；0 API、未改旧答案/原数据/冻结记录、未提交推送，未安装依赖。

## 已实现

- 目录搜索、匹配类型与原问题锚点共用已审中英别名；新增 heading_family，保留官方完整 heading 和中英范围说明。天然橡胶/可可豆/葡萄酒/钨制品不再因中英文差异卡住。裸钨、橡胶仍澄清，酒渣、矿砂、轮胎、加工品、明确排除子集不能借原料整组通过。英文未经审查的前缀不再自动升 exact。新增反例发现“可可豆油”误撞既有“豆油”规则，已修边界，原豆油/豆粕保护保留。
- 同轮 both:HS4/HS6 可投影到进口或出口，实际方向 ID 与目录来源 ID 分开保存；继续逐月校验目录、版本与描述。单向换方向、跨轮、伪 ID、缺月和不完整双方向 finish 仍拒绝。
- 政策身份比较只排除 hit.score/matched_codes，正文/版本/位置/完整依赖/例外等继续严格比较。首次 canonical bundle 保留，每次反馈仍是真实检索元数据；不截断法律条款、不改依赖算法/排名/预算。
- 工具协议 v3 明确 finish.source_ids 使用版本绑定 citation_id，不接受页面 source_id。拒绝反馈给出本轮实际报告/引用 ID；没有自动转换、代填答案或自动 finish，6轮/12工具/8192输出不变。
- 商品范围说明经保存、reader 和共享报告渲染到中英文单月进口/多月出口/双方向页面；旧出口短期间提示保留。只改此说明接线，未重做 UI。

## 验证

新增两份集中测试共15项，全部通过（18.778s），不是模型准确率。实际钨公告与数据的脚本模型走：目录→真实取数→两次政策搜索→错误页面ID受控拒绝→正确citation收尾，恰好6轮完成；原查询对的政策依赖经 check_policy_bundles 通过，报告/公开投影经 check_public_turn 与 v5 独立CSV参考核验通过。天然胶单向/双向报告通过 check_saved_report，范围说明完整保存与重读。

现行完整相关回归命令：

```sh
PYTHONPATH=src:.:tests .venv/bin/python -m unittest test_trade_agent_catalog_contract test_trade_agent_policy_merge_contract test_trade_agent_mainline test_trade_agent_boundaries test_trade_agent_language test_trade_agent_request test_trade_agent_policy_evidence test_trade_agent_report_view test_trade_classification_catalog test_trade_agent_supplemental_pilot.SupplementalTests.test_raw_soy_aliases_keep_derivatives_related_in_every_direction test_trade_agent_supplemental_pilot.SupplementalTests.test_finish_schema_only_requests_reference_fields
node --test tests/report_view.test.cjs tests/public_cases_ui.test.cjs tests/trade_explanation_ui.test.cjs tests/announcement_import_ui.test.cjs
```

最终组合 **74项全部通过（73.048s）**，包含新增15项；不累加重复运行题数。Node52项全过（最终120.097ms）；git diff --check、JS语法检查通过。

### 不能隐藏的旧协议拒绝

首次运行完整旧 supplemental 模块，63项中4项错误：旧试验 preflight 明确只接受 v2，新产品合同为 v3，所以旧试验拒绝。**这是本次升版触发，不冒称交接前已有失败**；没有修改这些测试、旧脚本、许可或freeze刷绿。现行豆油衍生物保护和 finish schema 两项保留回归；新增专门测试确认旧 v2 试验确实拒绝新 v3。旧批不能拿原许可继续运行。

因此不宣称全仓绿色；全仓历史冻结套件未重跑，4项旧运行成功预期仍与新合同不兼容。若以后维护旧试验的测试入口，须将“新合同应拒绝旧实验”与旧版本存档复现分开，而不是改生产 guard 或覆盖旧哈希。

## 保留证据与源码版本

原三组 manifest SHA 前后逐项相同：

| 产物 | SHA256 |
|---|---|
| luna/manifest.json | 35d93c70f292d508a2a273483ce2bb3f4c2dc303c78b9e019e7f42f1a877b05d |
| sol/manifest.json | c13405b062f77bf3dd583c32782a19c78c54cffd81470ea29e5fa4e5b1216128 |
| sol/medium-20261001/formal/manifest.json | ee637f7b49793c748323e9d7fa39cd28a1a0a6e66bf9fc45e190d36fb713b093 |

根为 `tmp/handoff-runs/us-agent-chat-compare-20261001/`。没有改原始响应或成绩；三份manifest相同不等于又验证了所有旧产物逐文件哈希。本次产品源码变化使旧输入源码快照不适合新实验，旧freeze必须保留，不能刷新后冒称同一版本。

| 修改的产品文件 | 修改前 SHA256 | 修改后 SHA256 |
|---|---|---|
| trade_classification_catalog.py | 12a87f978d302ad00aa0d95b1e6762fcc1b5a3d63410917305b90e588b28250e | 1654df9a488ac5364f99878568170e26b2e2fbea1b77f66c16a0ce20ea72b38e |
| trade_agent_tools.py | 8ad0a5bdf9f7a3a9c97bc590d7cc36e03fe40ef12d7c72826f8815908871ace3 | d9d417328785eceff79674de01c3f6a88e3a1ad74c45766d32f6afb96e8bbbc3 |
| trade_agent.py | 9f4b33b7bd0d030675923474659b987361250c60f3ba50fed14eff23102318ac | 86af8328aa5202aeab301203d152f02ba17ac5ae021c7b88a548cdab29ea2644 |
| report-view.js | ecbb4f459000c0f7f3fe484240cdc61cc2b3161461def091df87ee0f0156383c | bc310a8638df25e4fa02de72c0519d6352939aaab082145cb89eade65275da52 |

## 边界

这是用真实工具/数据的确定性回归，模型决策由脚本提供；没有证明修后 DeepSeek/GPT 的成功率提高，没有改模型表原分数。未跑新 API、真实浏览器/原生缩放/打印或全仓测试。旧 v5 不重启。若做新真实验证，另冻结新版本、评分与预算，不能复用旧许可。

本地入口补验：8898经lsof确认无监听，没有停止他人进程。用现有项目环境及原核验数据包启动新源码服务（exec session 93739），地址 http://127.0.0.1:8898/preview/ 。启动后仅GET页面、共享reader JS、贸易目录与安全模型状态，不POST、不收费；JS响应与当前工作区SHA相同。服务启动不等于新的浏览器/模型验收。

本步结果：最小修复已实现，现行相关74项和页面52项通过，独立核数与引用依赖通过；旧协议拒绝如实保留。
下一步：无，本轮最小修复目标已完成；不自动开启模型实验或复用旧许可。
下一步模型：无需；原因：当前目标已完成；切换：无需。
