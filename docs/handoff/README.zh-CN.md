# 固定交接入口

项目目录：`/Users/ye/dev/projects/TradeIntel`。

> **当前状态（2026-09-19）**：K1/K2 已完成，K3 测试+页面、K4 确定性公告解析、K5 中文使用说明也已完成。恢复任务先读 `STATUS.zh-CN.md` 顶部及 `runs/20260919-1948-K3-K5.md`，不要按下方历史的 E1—E3 交接点重复施工。

所有执行者（Workbuddy、Luna或其他人）先读：

1. 本文件。
2. `ASTRA_EXECUTION_DESIGN_20260915.zh-CN.md`：当前Astra方案与E1—E4验收标准；MASTER_PLAN保留历史背景，冲突时新方案优先。
3. `STATUS.zh-CN.md`：唯一当前执行位置。
4. 项目根目录AGENTS.md（如存在）、`../PROJECT_CONTEXT_REFERENCE.zh-CN.md`及当前阶段涉及的代码。

固定写入位置：

- `STATUS.zh-CN.md`：每阶段结束/被中断前更新；不能只留在聊天中。
- `runs/<YYYYMMDD-HHMM>-E1.md`（按E1—E4命名）：每次执行的追加记录，不覆盖旧记录。
- `RETURN_TO_ASTRA.zh-CN.md`：当前需高推理审阅的问题；已处理的版本保存进runs，再写新问题。
- `tmp/handoff-runs/<run-id>/`：较大运行产物；交接只引用相对路径，不把整个tmp入Git。

每份执行记录包含：实际执行模型、开始/结束、修改文件、验收命令与结果、API调用数/usage、未完成事项、下一步。不要写密钥。

允许在用户打开本项目后执行ASTRA_EXECUTION_DESIGN中的E1—E3离线阶段。真实API需先通过相应审阅门、冻结新预算并确认本地配置；旧G2不可重跑。不得提交推送、公开仓库、删除旧实验或系统安装依赖。

跨机器交接：Git可能没有未跟踪代码、数据、tmp证据或.venv。先检查文件与manifest所需资源；缺文件报出清单，不能默默改用合成数据声称真实通过。本机脏工作区先记git status及相关文件哈希，保留原改动。新环境只在项目虚拟环境安装依赖。

Luna已依据新方案更新 `WORKBUDDY_PROMPT.zh-CN.md` 并生成 `WORKBUDDY_INPUTS.zh-CN.md`。用户可把启动指令全文交给Workbuddy；Workbuddy尚未启动。
