# Luna测试运行器修复就绪

用户要求“你修完我再发给luna”。只新增隔离luna-recovery目录及交接记录，生产代码、原题、旧答案/脚本/冻结不改；0外部API、未提交推送、未启动正式测试。

新run_agent.py从旧源码复制，首轮不再传尚不存在session_id：通过turn_with_session传None，返回后保存真实ID，追问沿用。同目录bridge原样复用，用户问题与唯一政策文档逐字节SHA相同。新run_id明确recovery，旧目录保持原失败旁证。

额外修正记录真实性：failed与unknown_outcome计数如实相加；零响应批次标failed_without_model_responses，有失败/未知轮标completed_with_runner_failures，不无条件称completed。这不改变产品或模型评分。

离线7/7（test_runner_offline.py）：旧错误在模型前复现、首轮+追问、独立会话、实际FileQueueModel两请求/两响应/两工具反馈及生产会话继承、零请求状态、失败终态、报告失败计数。实际桥接烟测第一遍因临时测试runtime父目录未建而失败，修正测试fixture创建目录后全过；不改生产代码、不把初次失败当旧基线。所有fake数据只在临时目录，不填入正式requests/responses或模型成绩。

复用真实_preflight验证数据bundle、生产合同v3、问题与政策复制SHA均通过，formal manifest不存在。新目录OFFLINE_READY.json记录源码与输入哈希、原目录逐文件不变、0正式运行。

交接见../LUNA_V3_RECOVERY_20261002.zh-CN.md，runner已准备，不让测试对话再改代码。下一步用户在GPT-6 Luna Max对话执行一次十二题并保存新manifest/REPORT后交主会话评分；不自动发消息或运行正式答题。
