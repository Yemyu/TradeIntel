# 2026-09-22 公共四题执行器控制层收口

模型建议：Luna最高执行；Astra已经锁定了控制边界，本轮不需要重新做方法设计。

## 本轮完成

- `src/tradeintel_ai/public_eval_ledger.py`：固定在 `.local/experiments/public-brief-v1/`，使用跨进程文件锁和原子JSON写入；唯一键绑定题包MANIFEST摘要、provider配置摘要和题号，换输出目录不能重复领取。
- `scripts/run_public_brief_eval.py`：加入独立冻结校验、运行时/评分文件/题包摘要绑定；真实执行每次只能传一题；使用冻结参数和禁止重定向的HTTP opener；原答、返回模型、finish reason、usage、参数、耗时先落盘，再结构解析。
- `scripts/freeze_public_brief_provider.py`：只有矩阵候选被明确登记为 `ready_for_formal` 后才写冻结文件；当前六个候选都还未达到该状态，因此命令只拒绝、不联网。
- `scripts/review_public_brief_answer.py`：把原答摘要绑定到人工或AI辅助语义审阅；`pass`/`minor_error` 才能放行下一题，`major_error` 停止该配置。
- `scripts/score_public_brief_eval.py`：从运行记录和审阅账本生成“已运行/计划、收到原答、结构通过、语义通过、整题通过率、主要问题”表；未审阅和未运行题不会被算成通过。
- 失败语义分开记录：`unknown_outcome`/transport error、`raw_save_failed`、`invalid_response`、`blocked_output_budget`、`awaiting_semantic_review`；任何异常结束理由都不能伪装成结构通过。

## 离线验收

```text
tests.test_public_eval_controls       7 passed
tests.test_public_brief_eval_runner   8 passed
tests.test_public_eval_scoring        2 passed
tests.test_named_freeze + K2 tests   23 passed
git diff --check                       passed
Python compile                         passed
API调用                                0
```

完整仓库发现 1223 项中 3 failures、49 errors；它们与既有历史冻结哈希守卫、SciPy 本机动态库和旧因果/意图实验有关，不是本轮公共执行器控制测试引入的错误。本轮没有修改这些旧冻结记录，也没有用刷哈希的方式让它们变绿。

## 当前剩余门

1. 为每个要比较的模型单独核实实际返回的 model ID、思考字段/档位、总输出预算和费用记录；审阅后才把矩阵的一项改成 `ready_for_formal`。
2. 用 `freeze_public_brief_provider.py` 生成不可覆盖的冻结文件。
3. 先执行 q1，保存原答并完成隐藏模型名的语义审阅；只有非重大错误才能执行 q2，依次到 q4。

截至本记录，正式回答仍为 **0/4**，没有任何模型正确率结论。评分脚本只是汇总已审阅结果，不会凭空产生分数。
