# Phase 0126 离线演示审核索引

本目录只保存固定预期摘要，不保存某一次运行的动态审计目录。请用新的临时目录运行脚本，避免覆盖或混入旧材料：

```bash
source .venv/bin/activate
python scripts/run_strict_offline_demo.py --output /tmp/tradeintel-offline-demo-0126-run
```

运行后按下面顺序查看：

1. `run-summary.json`：确认总状态、3 题、5 次 fixture 调用、`acceptance_ready=false`。
2. `SYN-TRADE-01/preview.json`：贸易查询的范围和描述性比较边界。
3. `SYN-POLICY-01/policy-pair-contract.json`：有证据/无证据两组的共同设置。
4. `SYN-POLICY-01/fact-review-summary.json`：事实审核材料和指纹是否完整。
5. `SYN-CLARIFY-01/preview.json`：信息不足时的澄清终点。

固定摘要见 [`expected-summary.json`](expected-summary.json)。动态目录中的 UUID、时间戳和哈希会变化，这是正常的审计指纹行为。

这个目录不提供模型准确率、RAG 泛化成绩、人工语义审核结论或因果估计；这些内容需要后续独立设计和真实证据。

