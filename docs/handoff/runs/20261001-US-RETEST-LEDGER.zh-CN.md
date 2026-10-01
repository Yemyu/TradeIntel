# 美国重测：离线包与账本基础

新增 `scripts/run_us_agent_retest.py`。当前仅支持 prepare/status；run 明确拒绝，不读取密钥，不建立网络连接。

离线包位于 `tmp/handoff-runs/us-agent-retest-20261001-v1/offline-package/`：独立参考、评测计划、12轮预分配请求ID和7会话映射分开保存。runtime 不含商品标准答案、评分规则或参考数字。已有目录拒绝覆盖。

RequestLedger 为后续接线准备的基础组件，尚未接入实际 provider：

- 跨进程文件锁及独占写入，已领取案例不能因重启自动重领。
- 未授权不预留；所有传入的实际 body 按65,536字节门检查。
- 48次预留上限，未知预留不释放；120分钟门。
- 只存 body 长度/哈希，不存正文、密钥或思考。

这些组件测试不等于真实 HTTP 发送边界验收：录制适配器、实际 opener 接线、金额预留、冻结校验、评分和政策确认仍未完成。布尔 authorized 只是内部测试参数，不能替代最终冻结授权记录；当前 CLI 无 live 路径。

验证：`PYTHONPATH=src:. .venv/bin/python -m unittest tests.test_us_agent_retest`，9项通过（含之前4项独立参考测试）。实际 prepare 成功，状态明确为 offline_partial_not_live_ready。

0 次 API；未提交、未推送，未修改旧记录。

本步结果：离线包和账本基础完成，9项测试通过，真实运行入口仍关闭。
下一步：政策候选准备与实际请求录制接线，再补冻结和评分验收。
下一步模型：GPT-6 Luna Max；原因：按已定设计继续实现；切换：无需。
