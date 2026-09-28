# 2026-09-15 课程模块离线适配验证

- 实际执行模型：Luna 最高
- 阶段目标：验证课程的证据卡片、固定数据库工具、研究状态和缓存边界能否映射到TradeIntel，不运行课程服务。
- 开始/结束：2026-09-15 19:24；本地短阶段
- API调用数：0；模型调用数：0；数据库写入：0
- 未执行：Docker、课程初始化SQL、MySQL连接、课程依赖安装、下载目录代码导入

## 修改

- `scripts/check_course_adapter_offline.py`：标准库离线契约检查。
- `src/tradeintel_ai/course_adapters.py`：TradeIntel自己的适配边界（不是复制课程业务代码）。
- `tests/test_course_adapter_offline.py`：4项fixture测试。
- `docs/handoff/COURSE_CODE_REVIEW.zh-CN.md`：删去无关授权前置，改为模块化复用表述。
- `docs/handoff/CLOUD_AGENT_REVIEW.zh-CN.md`、`MASTER_PLAN.zh-CN.md`、`STATUS.zh-CN.md`：同步三个项目、现有MySQL保留和当前阶段。

## 验收

```text
.venv/bin/python scripts/check_course_adapter_offline.py
course adapter offline checks: 7 passed

.venv/bin/python -m unittest tests/test_course_adapter_offline.py
Ran 4 tests in 0.000s — OK
```

这些结果只证明适配契约的拒绝边界：不接受任意SQL、不跨数据版本复用缓存、无来源/解析失败不能标记完成；不证明课程代码运行成功或生成质量。现有TradeIntel重复模块未删除，原始Downloads目录未改动。

## 当前判断

三个项目不需要整套合并：RAG工作台提供交互参考，CloudAgent提供固定工具/路由参考，DeepResearch提供研究阶段参考。TradeIntel自己的MySQL、贸易计算、政策版本、证据和审阅链保留。下一阶段可以把这些契约接到现有聊天/报告入口；若必须改动核心证据合同或恢复语义不清，暂停并回Astra。
