# 美国重测：真实适配器发送边界离线接线

在新评测脚本内新增 GuardedOpener 与 RecordingModel，不改生产适配器或历史冻结源码。

- GuardedOpener 挂在现有适配器实际 opener 处，检查实际 request.data，而不是首轮语义JSON估算；包括工具后续轮和思考回传。超时上限90秒，超限/未授权不调用注入的 transport。
- RecordingModel 透传 config/request_params，完整返回原 ThinkingToolResponse，避免破坏私有推理回传；只保存公开 text、工具参数、白名单metrics，启动记录先落盘。
- 发送前预留保留为 unknown，不因失败释放或自动重发。HTTP送出不代表收到有效模型答案，记录保留此区分。
- 真实 DeepSeekThinkingToolModel + 模拟 transport 已验证两轮回传、第三轮超限拒绝；磁盘没有测试密钥或私有推理标记。

当前组件13项通过；额外适配器/metrics回归另见本轮输出。API调用0，CLI live仍关闭。该接线没有完成美元预留、冻结授权和评分，不能据此启动批测。运行中的源码/数据漂移校验、逐案例结果及依赖阻断仍待实现。

本步结果：实际适配器发送边界及响应录制离线接通。
下一步：实现报告独立核对与评分，再补冻结校验。
下一步模型：GPT-6 Luna Max；原因：核对规则和冻结范围已明确；切换：无需。
