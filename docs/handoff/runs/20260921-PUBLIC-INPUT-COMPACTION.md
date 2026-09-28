# 2026-09-21 多期公开解释输入收敛实施记录

> 当前状态：前置记录中的 A/B 未通过问题已按 v2 规格修复。最新实现、审计数字和停止条件见 [`20260921-PUBLIC-INPUT-V2-IMPLEMENTATION.md`](20260921-PUBLIC-INPUT-V2-IMPLEMENTATION.md)。本文件保留前置运行记录，不覆盖当前状态。

> 后续 Astra 审查撤回本记录的“A/B/C 完成”“无损送模”结论：完整备份可恢复，但发送内容有观察筛选、指标语义及引用链接缺失。原运行数字保留作诊断，不是正式放行依据。当前按 [审查与修复规格](../ASTRA_COMPACTION_REVIEW_20260921.zh-CN.md)继续。

## 阶段

模型建议：Luna 最高。Astra 已锁定 A/B/C 方案，本阶段只做规范明确的离线实现和材料生成；没有调用模型或供应商 API。

## 交付

1. 新增 `src/tradeintel_ai/public_input_view.py`：把送模内容变成有版本的紧凑视图，指标采用列/行结构，观察目录保留完整 ID，政策条款保留逐字文本和官方链接；主机 sidecar 保存完整原始报告和政策上下文，`restore_view(build_view(...))` 做无损还原校验。
2. `public_brief_explanation.py` 改为使用同一视图构造器；模型不再只收到前六条比较观察，输出上限仍是六条，`eligible=false` 观察不能被引用。
3. `public_report.py` 接入已绑定的政策事实，在读者稿中渲染存档状态、生效时间、原产地、逐 HTS8 税率、条件/例外状态、限制和官方来源。
4. `scripts/prepare_public_eval_diagnostic.py` 生成四个自然问题的诊断包，未覆盖旧目录，输出 `tmp/public-brief-eval-v1/diagnostic-compaction-20260921-v5/`。

## 预算结果

采用项目已有的保守估算 `ceil(1.25*(ASCII/3 + nonASCII*2 + 128))`，目标 8000、硬门 16000：

| 题目 | 估算输入 tokens | 字符数 | 结论 |
|---|---:|---:|---|
| Q1 | 15362 | 25639 | 低于硬门，但接近 |
| Q2 | 7979 | 12665 | 接近目标 |
| Q3 | 15372 | 25643 | 低于硬门，但接近 |
| Q4 | 15362 | 25639 | 低于硬门，但接近 |

所有题 `within_hard_gate=true`，诊断结果 `api_calls=0`。这个估算不是各厂商账单 tokenizer 的精确值，因此不能据此宣布已经放行正式模型评测。

基础静态检查：`.venv/bin/python -m compileall -q src scripts` 通过，`git diff --check` 通过；Q1 smoke 检查确认政策报告、紧凑视图和观察目录都已生成。本阶段没有运行单元测试，也没有发出网络请求。

## 边界与后续

- 没有删除月份、商品、法律条件、未知状态或来源正文；未修改旧冻结记录。
- 四题仍是诊断材料，不是独立正式评测：自然语言提案入口、固定追问摘要、独立参考答案和真实 tokenizer 预算仍待验收。
- 下一阶段先由 Astra 中做最终合同/预算审查；若通过，再由 Luna 最高按六配置计划准备正式请求。千问已按用户决定移出候选，不再尝试。
