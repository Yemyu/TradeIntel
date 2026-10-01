# 贸易 Agent 首题：调用前只读核对

日期：2026-09-29。**没有发送模型推理请求，没有创建首题真实账本；本记录不是收费调用许可。**

- 当天直接读取 [DeepSeek 官方模型与价格页](https://api-docs.deepseek.com/quick_start/pricing/)：`deepseek-flash` 对应 DeepSeek-V4.1-Flash；每百万 token，输入缓存命中峰时 0.006 美元/非峰时 0.003 美元，缓存未命中峰时 0.30/非峰时 0.15 美元，输出峰时 1.20/非峰时 0.60 美元。价格可能调整，发起调用当天需再核。
- 依照官方[余额接口](https://api-docs.deepseek.com/api/get-user-balance/)对已配置的 DeepSeek 账户做一次只读 GET：HTTP 200，`is_available=true`，币种 CNY；未打印密钥和余额金额。该标志只表示服务商认为账户可调用，不是用户对本次费用的授权。
- 当前产品配置身份未变：DeepSeek `deepseek-flash`、thinking enabled / high。本机首题离线预检 `offline_ready`，首轮消息 4,167 字节，快照 `9d0a60baf358bc2bdd87cb837332dded9c66ab190b42279a98b991340a5b3ddd`，一次性首题账本不存在。
- 事前规则仍是只发第一题、最多4次模型回复/8次工具调用、每次 `max_tokens=4096`/超时90秒；失败、未知结果或严重事实错误即停，绝不自动重发。程序没有账户级美元硬扣费上限，实际费用须等服务商 usage/账单；不得把上述参数换算成保证金额。

下一步：等待用户**明确允许首题最多一次收费尝试**。得到许可后再复查当天价格、账户、快照和账本，才可启用真实调用；其余四题不随之授权。
