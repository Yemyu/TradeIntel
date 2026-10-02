# Luna 测试恢复交接

当前产品已完成v3最小修复，其他模型由主会话统一审阅。这里不提供它们的答案或成绩。

## 已修复并离线验收

`tmp/handoff-runs/us-agent-chat-compare-20261002-v3/luna-recovery/`已准备好新runner、原样bridge、用户问题与唯一批准政策文档，不需要测试对话再复制或修改代码。7项离线测试通过，真实文件队列产生两次synthetic请求/响应，生产Agent首次创建会话并正确继承；另测独立会话、旧错误复现、零响应不能completed、失败计数。fake烟测不属于模型成绩，0API。首题前预检合同v3、数据与题目/政策SHA通过；正式manifest尚不存在，没有启动正式十二题。旧luna目录逐文件hash核对不变。详见新目录OFFLINE_READY.json。

运行命令（在项目根目录）：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. .venv/bin/python tmp/handoff-runs/us-agent-chat-compare-20261002-v3/luna-recovery/run_agent.py
```

runner会输出REQUEST_READY并等待。每次只读这个新目录requests里的当前请求，由当前对话模型依据原样messages/tools写一个responses/<同名>.json，形状严格为text与tool_calls；call含call_id/name/arguments。使用apply_patch新建一次，不能覆盖原答；runner收到后执行实际工具并给下一请求。到RUN_FINISHED才是脚本终态；需核对实际决策/响应/工具数，零请求不算运行成功。

## 可直接粘贴到测试对话

本次实际模型请记录为用户确认的 GPT-6 Luna Max。工作目录 /Users/ye/dev/projects/TradeIntel。

前一组Luna测试没有调用模型：首轮把request_id当作已存在session_id传入，生产接口报“会话不存在”。只修测试脚本的初始化，不修改生产代码。允许只读旧luna目录里的run_agent.py和bridge.py源码作为接口参考，不读取旧manifest、报告、responses、requests、case结果，亦不读取其他模型产物、模型表或评分金标。

保留旧目录 tmp/handoff-runs/us-agent-chat-compare-20261002-v3/luna/ 的全部文件，包含旧脚本，不改一个字节。新目录luna-recovery已经修复：首轮session_id=None，成功返回后保存真实session_id，追问继承。先核对OFFLINE_READY的脚本摘要；若新目录已有正式记录则停，不换目录偷跑，不再修代码。

离线smoke已通过，不再把fake混进正式成绩。按 docs/handoff/US_AGENT_CHAT_COMPARISON_V3_20261002.zh-CN.md 的既定工具桥接流程启动已准备runner一次正式十二轮。只读其中允许的用户问题、生产system/tools、数据及已确认政策输入。不要用脚本生成正式模型决策、手动读CSV代替工具或直接写报告。每个动态请求由当前对话模型独立回答一次，生产TradeResearchAgent执行工具并返回新请求。不得读金标或其他答案帮助通过。

使用项目.venv；保持today=2026-10-01、每题6响应/12工具、组48决策/120分钟。API=0，不联网、不读密钥、不装依赖、不改src/scripts/tests/evals/docs，不提交推送。输出token无法测量如实记录，不编造usage。前置未completed依赖跳过，所有失败证据保留，不重试刷绿。

正式执行首题前记录代码、解释器、题目、数据、政策和合同v3 SHA；结束再核对。保存每个原始request/response、audit_callback工具反馈、公开session、正式报告、manifest.json和REPORT.zh-CN.md。模型实际档位以用户确认记录。只核对运行完整性，不能自评准确率。运行完给主会话manifest和REPORT绝对路径，并报完成/澄清/失败/跳过计数。

若初始化或桥接仍失败，保存最小复现后停止；不改产品会话合同迁就脚本，不再自动换目录重测。
