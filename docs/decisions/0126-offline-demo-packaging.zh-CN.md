# 0126：严格流程的可复现离线演示包

日期：2026-09-13。模型建议为 Luna 最高；本阶段不调用外部 API、不训练模型，也不改变 0121—0125 已锁定的验收协议。

## 本轮交付

新增 [`scripts/run_strict_offline_demo.py`](../../scripts/run_strict_offline_demo.py)，用三个固定的本地 fixture 演示严格注册工作流：

1. 贸易查询规划：展示范围、月份、金额口径和“只做描述性比较”的边界。
2. 政策问答：展示同一问题的“有证据/无证据”配对，以及事实审核包、引用和最终中文报告绑定。
3. 信息不足：展示系统先澄清，不会猜测商品、月份或金额口径。

运行命令：

```bash
source .venv/bin/activate
python scripts/run_strict_offline_demo.py --output /tmp/tradeintel-offline-demo-0126
```

输出目录必须不存在；这样可以避免把新运行结果混入旧审计材料。运行不会打开网络连接，也不需要 API key。

## 已验证的结果

一次全新临时目录运行得到：

```json
{
  "status": "completed",
  "question_status_counts": {"accepted": 2, "accepted_terminal": 1},
  "call_count": 5,
  "acceptance_ready": false,
  "semantic_accuracy_measured": false,
  "network_calls": 0
}
```

`run-summary.json` 会保留每题的请求、响应、控制组、审核提交、事实审核和交付指纹。UUID、时间戳和文件哈希会随每次运行变化，因此“可复现”指同样的流程和状态能够重现，不承诺字节级相同。

## 必须怎样解读

这个演示证明的是工程流程能在没有网络时完整走通：输入被冻结、主/B条件可核对、事实审核和报告文件互相绑定、信息不足会停在澄清状态。`offline fixture` 的回答是程序写好的接线标签，不是 GLM 或任何真实模型的准确率，也不是人工语义审核。

因此本轮没有把 `acceptance_ready` 改为 `true`，也没有解冻在线批次。正式真实成绩仍需先完成独立参考答案的人工复核，再冻结题数、指标、预算和停止条件。

## 审核入口

- 演示目录索引：[`phase-0126-offline-demo/README.zh-CN.md`](../experiments/phase-0126-offline-demo/README.zh-CN.md)
- 固定预期摘要：[`expected-summary.json`](../experiments/phase-0126-offline-demo/expected-summary.json)
- 中文学习说明：[`Phase 58`](../learning/phase-58-offline-demo.zh-CN.md)
- 自动回归：[`tests/test_offline_demo_0126.py`](../../tests/test_offline_demo_0126.py)
