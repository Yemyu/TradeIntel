# S1 公告确认、独立绑定与指定检索

日期：2026-09-19  
执行模型：Luna 最高  
范围：离线代码与测试；0 次真实模型/API 调用；未修改旧冻结记录；未提交/推送。

## 目标

让一份新公告在确认后拥有自己的服务器端 `policy_binding`，并让检索严格使用该公告版本；旧主案例仍按原路径工作。S1 不负责把新公告的税号接入贸易数据，也不生成伪造金额报告。

## 交付

- 新增 `src/tradeintel_ai/announcement_store.py`：公告存储、路径校验、同一 `policy_id` 的线程/进程锁、原子写入。
- `announcement_flow.py`：候选摘要在服务器登记；启用时重算并比较当前字段摘要、登记摘要和客户端期望摘要；新增 `resolve_policy_binding` 与 `search_policy_binding`。
- `session_store.py`：会话和任务保存窄化的政策绑定；任务去重键包含候选摘要，避免同一 `doc_version` 的不同候选复用旧任务。
- `web_app.py`：新公告确认从服务器解析绑定，审计确认元数据不直接进入客户端会话合同；绑定但未覆盖时明确返回 S2 边界。
- `web/announcement-import.html`：启用请求携带服务器返回的候选摘要。

## 验收

定向命令：

```text
PYTHONPATH=src:. .venv/bin/python -m unittest -q \
  tests.test_s1_policy_binding tests.test_k3_announcement_flow \
  tests.test_k3_web_routes tests.test_k4_announcement_parser \
  tests.test_e3_sessions tests.test_j1_j4_integration \
  tests.test_k1_boundaries tests.test_k2_provider_executor \
  tests.test_provider_executor_hardening
```

结果：88 项通过。

覆盖的关键反例：

1. 候选字段被改动时，不能借用旧 `candidate_digest` 启用；
2. 并发提交不会写出半份候选记录；
3. 未启用/未知公告不能直接成为会话绑定；
4. 会话/任务只保存窄化绑定，审计确认元数据不会污染合同；
5. 指定公告检索不会回退到主案例；
6. 旧主案例的会话、J1—J4/K1—K4 边界保持通过。

## 当前边界与下一步

新公告目前可以“确认并检索政策原文”，但还不能声称有对应贸易金额覆盖。下一阶段 S2 复用现有已发布贸易快照，逐项核对 HTS8、原产地、月份、统计口径和来源哈希，再把覆盖记录接入确定性 A3 报告；覆盖不足必须返回 missing/partial/unknown，不能补零或借用主案例五个商品。

