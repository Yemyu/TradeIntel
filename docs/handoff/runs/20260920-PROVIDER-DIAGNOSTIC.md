# 模型接口诊断收口（2026-09-20）

## 实际结果

- S3首次D1-B的unknown_outcome记录原样保留，旧实验仍stopped；其具体失败原因无法事后恢复。
- 无密钥GET连通性检查收到HTTP401：仅说明检查时DNS/TLS/HTTP路径可达，不验证密钥。
- 另做一次独立认证诊断：GLM-4.7、temperature=0、thinking disabled、max_tokens=16、timeout=20秒，提示仅Reply OK only；无自动重试。
- 诊断返回HTTP429，无模型回答、无usage；不能单凭状态码判断限流、资源包、余额或账户限制，也不能确定计费。
- 原始安全记录：`tmp/glm-auth-diagnostic-20260920-1/diagnostic.json`。诊断没有使用研究题或参考答案，不计为模型质量实验。

## 代码改动与验证

- model_adapter安全分类HTTP/TLS/DNS/超时等异常，仅保存类别和HTTP状态，不存密钥、响应正文或任意异常消息。
- provider_executor在unknown_outcome结果/清单/账本保存安全分类，不返还槽位。
- diagnose_glm_once.py一次性诊断先记录started，输出目录存在即拒绝重复执行；不保存密钥和响应正文。
- 29项定向测试通过：provider_error_details、tradeintel_ai_model_adapter、provider_executor_hardening、k2_provider_executor。
- 本轮未重跑全量，不能声称全量通过。未提交、未推送；既有修改保留。

## 下一步与停止条件

1. 用户核对BigModel控制台目标模型可用资源包、余额、并发/速率限制；无需再把同一密钥贴回聊天。
2. 外部状态未变化，不继续短诊断、不运行C/正式题、不擅自换模型。
3. 若状态恢复，由Astra中裁定新有限实验，沿用已核对材料，重新冻结当前执行代码；不激活旧实验、不改旧哈希、不把失败请求当作模型能力失败。
4. 锁定后Luna最高可执行；真实回答质量与采纳结论由Astra中审查。
