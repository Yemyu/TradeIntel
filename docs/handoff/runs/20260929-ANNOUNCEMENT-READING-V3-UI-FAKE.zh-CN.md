# 公告阅读 v3：只读页面与离线假回答

日期：2026-09-29。范围：第二包，**0 次模型 API、0 次 MySQL**；未提交、未推送。旧 FR2026-19516 正式失败记录与旧 v2 调用程序不变。

## 做了什么

- `web/announcement-import.html` 继续保留 v2 阅读笔记展示；新增独立 v3 展示分支。v3 按三组、十个检查点显示状态、可核对要点和原文位置。载入前重核文档版本、整篇原文 SHA、引用片段/位置 SHA、检查点及要点的对应关系；`incomplete_not_ready` 拒绝作为完成笔记显示。文本只用 `textContent`，不写入13字段确认表，也不碰提交、启用端点。
- `scripts/run_announcement_reading_v3_fake.py` 接收已保存的假回答 JSON，先复核离线包，再走**与真实回答相同的 v3 解析器**；保存原答、审阅 JSON 与哈希清单。它没有服务商客户端，不会读取密钥或发请求。这是离线假回答流程，不是模型效果测试。
- Python 测试新增“包→假答→解析→审阅产物”路径；Node DOM 测试新增 v3 展示、定位来源、确认表不变、未完成拒绝。已有 v2 页面测试继续通过。

## 验证

- `PYTHONPATH=src:. .venv/bin/python -m unittest tests.test_announcement_reading_suggestions tests.test_announcement_reading_v3 -q`：**24/24 通过**。
- `node --test tests/*.test.cjs`：全套页面单测 **26/26 通过**，含补充 Unicode 字符与 Python 字符位置一致性反例。
- `git diff --check` 通过。旧冻结包校验已在第一包通过；本轮未更改其哈希锁定的 Python 源码。

## 使用边界

离线生成包：`PYTHONPATH=src:. .venv/bin/python scripts/prepare_announcement_reading_v3_offline.py --store <保存的单份公告store.json> --output <新目录>`。

离线假回答：`PYTHONPATH=src:. .venv/bin/python scripts/run_announcement_reading_v3_fake.py --store <同一store.json> --pack <上述目录> --answer <事先准备的假回答.json> --output <另一新目录>`。将输出的 `review.json` 在“新公告导入”页的“离线阅读笔记”处载入；页面当前文档必须是同一份正文和版本。

没有新公告的真实模型回答、语义评分或真人省时结果；页面只能保证引用位置一致，不能保证法律解释正确。v3 的正式 POST 参数、成本门、答案参考和一次性账本**尚未冻结**。下一阶段先只读复核这些证据与试验门，再决定是否准备新案例；未获单次收费许可不发 API。

本步结果：v3 只读页面与离线假回答路径已接通，Python 24/24、页面 26/26 通过；没有新模型成绩。
下一步：独立审查 v3 试验前的容量、评测参考及止损门，形成是否进入新未见公告试验的结论。
下一步模型：GPT-6 Sol Max；原因：新试验的正式协议、参考核对与费用边界尚未冻结，需要一次路线判断；切换：请切换后确认。
