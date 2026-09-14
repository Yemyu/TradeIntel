# 0127：政策参考答案的独立复核准备

> 0128更正：下文把人工复核作为开发前置条件过于严格，已由[0128](0128-ai-reviewed-development-route.zh-CN.md)撤销。AI来源复核可支持明确标记的开发测试；既有人工待审状态保留，不能冒称人工金标。

日期：2026-09-13。模型建议为 Astra 中；本阶段不调用外部 API、不训练模型，也不把 AI 自查结果写成独立人工金标。

## 本轮完成

新增 [`scripts/verify_policy_reference.py`](../../scripts/verify_policy_reference.py)。它不相信当前 facts 文件里的结论，而是重新读取本地官方 PDF，检查：

- 文件存在且 SHA-256 仍为 `3e27dfb420dc308a079e7a71f2715fa29ed00fbbd84dbec4514f2cd66b9cf301`；
- 第 1 页有“on or after July 6, 2018”的生效日期原文；
- 第 2 页有“additional duty of 25 percent ad valorem”的税率原文；
- 消费/从仓库提取消费的适用范围仍在原文中；
- 两项 facts 仍绑定到预定页码、来源 ID 和当前待人工状态。

运行：

```bash
source .venv/bin/activate
python scripts/verify_policy_reference.py \
  --output /tmp/tradeintel-policy-reference-0127.json
```

实际运行结果为 `ai_assisted_check_passed_pending_human_review`，所有结构检查通过，`human_review.status` 仍为 `pending_independent_human_review`。

## 为什么不能自动改成已审核

程序能确认“本地文件没有换、预期文字确实存在、facts 没有偷偷改页码”，但不能代替人判断这两句话是否被正确理解，也不能凭空生成审核者身份。因此这一步把材料准备到可复核状态，保留最后的人读源文件记录。

复核者需要直接打开同一份 PDF，确认三件事：日期是否为 2018 年 7 月 6 日、额外税率是否为 25%、消费/仓库范围限定是否完整。然后记录身份、时间、文件 SHA-256，以及每项判断和理由。AI 辅助检查可以作为附件，但不能填写“人工已审”。

## 边界与后续

本轮不是新的模型实验，没有基线、训练或性能指标变化，也不解冻在线批次。完成真实批次前，还要把人工复核记录纳入快照，并明确题数、指标、token 预算、停止条件和“首次硬失败即停止”的规则。因果分析仍未采纳。
