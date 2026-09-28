# v3续测：锁定实现与执行顺序

> **2026-09-22实现完成**：历史前置事件、顺序检查、材料摘要校验和离线反例已完成；42项相关测试通过，0次API。当前真实项目账本未登记该事件，只完成只读材料预检。

本方案由Astra确定。v3评分附件已接入冻结摘要，42项相关离线测试通过，0次新API。本阶段按方案实现历史前置审阅功能并验证，不重新设计评分、不重问Q1。

## 为什么需要一个小改动

现有顺序锁要求同一配置中上一题已有语义审阅。历史Flash Q1因v2预算失败没有进入正式审阅账本；直接跑新v3 Q2会被正确拒绝。不能伪造started或semantic_review_passed事件解决。新增单独的historical_prerequisite记录即可，保留旧行为。

## 实现范围

已在public_eval_ledger.py增加register_historical_prerequisite；require_previous_review仅在普通前题审阅缺失时检查该独立记录。新命令scripts/register_public_historical_prerequisite.py验证真实材料和冻结后才登记。沿用同一个项目账本、文件锁和原子保存。

本次只允许Flash高推理历史Q1承接v3 Q2起点。参数必须同时给出旧run目录、旧freeze、新package、新freeze、四项review JSON；无需API key。记录schema至少包含event、target_prefix、question_id=q1、source_run_id、source_raw_sha256、source_run_sha256、source_freeze_sha256、source_manifest_sha256、target_manifest_sha256、target_freeze_sha256、review_sha256、reviewer、ai_assisted=true、verdict=minor_error、artifact_paths。该event不使用目标run_id，不创建started、不消耗API次数。

登记时必须检查：

1. 旧账本有唯一started及blocked_output_budget终态，旧run身份和原答摘要一致；拒绝unknown_outcome、重大错误、未有原答或新添冲突状态。
2. 旧freeze文件摘要对应旧started记录，旧manifest/消息与原记录相符；不拿当前源码验证历史runtime，否则会误拒绝历史。旧运行文件和材料必须重验磁盘摘要。
3. 新freeze按当前生产verify_freeze验证（开发测试可candidate，真实登记要求ready_for_formal），必须v3。只允许同一model_id/base_url/thinking/reasoning_effort/temperature/max_tokens，provider显示ID可以变化。
4. 对四题逐题比较messages.json和host_artifacts/response.json的内容摘要；新旧必须相同。若有时间戳等字段差异，不自行删字段来求相等，返回Astra判断。
5. 用当前生产解析器和v3预算函数离线检查旧原答；四项审阅文件对应20260922-FLASH-HIGH-Q1-SEMANTIC的结论（结构/相关/可用性true，事实false，minor_error）。校验通过只是前置材料合格，不能记作v3Q1成绩。
6. 同一target_prefix仅一个前置记录，完全一致请求可幂等返回，冲突拒绝；目标Q2已有started时拒绝新增/替换。每次顺序检查重新核对所登记文件摘要和目标freeze摘要，篡改或文件丢失即停止。
7. Q2之后仍使用现有普通逐题审阅；major_error停止、minor_error扣分后可继续。对Q3/Q4不得仅靠历史Q1跳过Q2等审阅。

汇总器不把historical_prerequisite当作run或得分；显示来源首题为历史参考、新配置Q1未运行。新API最多Q2—Q4三次，每题停下来审阅后继续。不计算混合四题通过率。

## 验证与停止

离线反例必须覆盖：正确登记后仅Q2获准；没有记录仍拒绝；major/unknown来源拒绝；旧原答/新消息/新freeze变更拒绝；缺文件拒绝；重复幂等与冲突拒绝；Q3仍等待Q2；汇总不增加答题数或通过数。用临时账本和注入provider，不接真实端点。

锁定假设：正确承接历史非重大错误审阅可以避免重复收费并保持来源可追溯，不假设能提高答案质量。对照为既有无承接记录时顺序锁拒绝。候选请求继续只看messages，不带旧答案/审阅。出现材料差异、协议冲突或边界无法表达时保存安全进度交回Astra。

当前不新增真实调用、不登记正式历史前置事件。实际路径只读预检已通过：source run `pub-20260922T072305-168f830f1a`、23份材料、目标v3冻结（candidate-v3-r5）和四题材料一致；API调用仍为0。正式登记前仍需明确是否承接该历史Q1并由Astra复核材料。Pro unknown保持；GLM此前停止决定保持。

## 交接给Luna的对话

读取docs/handoff/STATUS.zh-CN.md顶部和docs/handoff/runs/20260922-V3-CONTINUATION-PLAN.zh-CN.md，复核已完成的历史Q1前置审阅登记与顺序检查。保持0次API；不要在项目账本登记或重问Q1，除非用户明确承接且Astra复核材料。不要伪造通过事件、不要覆盖旧冻结。若材料差异返回Astra，不自行过滤差异字段。
