# 第二题“出口呢？”离线预检重建（2026-09-29）

紧接[页面离线验收](20260929-TRADE-AGENT-BROWSER-OFFLINE.zh-CN.md)，运行既有 `run_trade_agent_followup_pilot.preflight()`，仅打印不含密钥的最小核对字段，没有进入 `run_live` 或发送服务商请求。

| 项目 | 结果 |
| --- | --- |
| 预检状态 | `offline_ready` |
| 模型/推理 | `deepseek-flash` / `high`，只是配置核对，未调用 |
| 实际待发首轮请求 | 4,493 字节；SHA-256 `d62ada6e6993bc0520f196cd2edf3b25dbee383fe7b6aa25f76d2e78ad598e42` |
| 完整快照 SHA-256 | `a1b030cb6274c82dac65b9cfbfc0151b356affc9fcaa1e069d423d5cd8b75cce` |
| 首题会话 | `4c96e6e2cf6c4897b899a5c1dedc75e6`，只读绑定 |
| 第二题账本 | 不存在；未占用一次性槽 |

前次实施记录中的 `20408ead…` 快照已失效，不能用于后续实调；本记录中的新快照也只在源码、配置、会话及数据未变化时有效。相关 Python `unittest` 27/27、全部 Node 30/30、`git diff --check` 通过。第一次误用 `pytest` 时项目虚拟环境没有该模块；改用本项目测试实际采用的 `unittest` 后全绿，未安装全局依赖。

本步 0 次模型推理调用、0 次 MySQL 写入、未提交或推送。未重新核当天价格或账户状态；预检不等于获准收费。要做真实第二题仍需用户明确允许**该题最多一次付费尝试**，再核价格/账户和完全一致的新快照。
