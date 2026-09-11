# 0093：独立必答点清单已接入开发入口

## 交付

按0092实现，不新增题目、模型调用或研究口径。新CLI默认使用development-smoke-0093；旧编程调用默认仍使用0090布尔审查，不能拿旧模式当新清单验收。0091原始运行、拒绝记录及输出目录未改。

- 新模块`src/tradeintel_ai/answer_checklist.py`：独立清单读取、审查模板、逐项决定校验、回答/证据定位、文件变化检查。
- 清单`docs/evaluation/development-checklist-0093.json`：冻结原4题的必答点和贸易数值参考，不进入模型消息。生效日和税率分别审查，可引用同一个完整原问题。金额、方向、差额、百分比参照既有独立核对，百分比按计算契约保存字符串，而非浮点数。
- `run_development_smoke.py`不再只收approve，改收多行审查JSON，以单独一行END结束。展示原问题、清单、实际计划/答案、参考、文件位置及空白模板；无自动批准开关。可由助手实际阅读后填写，不要求用户理解代码。
- `run_batch(..., checklist_review=True)`冻结新清单与新提示模式，审查前保存packet，审查后保存脱敏submission与有效review。缺行、重复ID、空理由、未知状态、旧packet哈希不能批准。无效提交保留，批次停止；负向决定记录not_approved。
- 计划需要逐项covered或对应范围处理；scope_selection清单要求整题停在范围选择/澄清。答案需要逐项supported，同时整体审查通过；整体理由须检查额外无支持主张及因果边界。
- 政策supported要求存在的claim_index、精确claim_text、关联citation_id及证据原文摘录。保存证据对象哈希。贸易supported要求记录所有冻结checks，宿主按实际结果字段及类型逐项比较，不能让审查者临时选择参考答案。
- 审查绑定原问题、清单、artifact及本地交付文件哈希；回调返回后及后续调用前重新核验。审查结论称reviewer_supported/reviewer_plan_covered，保留semantic_coverage_verified=false。引用存在或摘录匹配不能证明它在语义上支持主张，仍需审查者理解。
- 新宿主开关allow_grouped_policy_requests只用于启用顺序原文覆盖的模式，允许同政策任务完整多问合并。开关进入确认指纹；旧数字偏移模式及原QUOTED_UNITS_PROMPT常量不追改。漏原文、错范围、不支持问题被忽略仍不允许。

## 验证结果

新增12项测试，包括共享claim的两条独立审查、漏答/矛盾/不可核实/整体失败、缺行/重复/空理由、无效claim/引用/摘录、清单与答案改变、冻结贸易参考与反向差额、不支持范围、文件变化、零调用预检、真实离线工作流的计划拒绝和答案拒绝。

其中贸易测试调用现有计算函数，对照已存历史数据，核对sequence与endpoint清单字段。两项集成测试调用真实工作流、使用模拟模型回答：计划被拒不执行；计划通过后模拟漏答保存答案审查并停止下一题。检查规划/回答消息未注入独立清单。它们是离线测试，不是GLM新成绩。

全套491项测试通过，16.930秒，日志`/tmp/tradeintel-0093-tests.log`。CLI零调用预检通过：development-smoke-0093、4份场景清单、new_api_calls=0、本进程无本地密钥。没有安装依赖，没有新API、训练、因果拟合、下载或推送，29ZIP未动。

## 输出与后续使用

新批次除原有manifest/batch/逐题planning/delivery外，根目录另有：

- `D89-1-plan-review-packet.json`：审查时看到的原始材料与清单。
- `D89-1-plan-review-submission.json`：提交的审查内容，已按本地凭据脱敏。
- `D89-1-plan-review.json`：验证后的逐项审查记录；格式无效时没有该有效记录，不代表通过。
- 对应的answer文件在真正进入答案审查时产生。

这些是未来运行的命名示例，不是今天已经生成新的真实批次。默认预检仍为`.venv/bin/python scripts/run_development_smoke.py`，不请求密钥、不调用模型。真实入口仍要求全新目录、可交互终端、审查者标识及本地凭据；禁止续跑0091。

下一阶段推荐Astra中：复核新提示、清单必答范围和实际语义记录，再冻结新的4题/6次调用开发批次。沿用0092假设、基准、防泄漏、门槛与首错停止规则；不是增加题库或开启旧24题验收。本阶段只完成实现，不能宣称真实答全问题已被解决。
