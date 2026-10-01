# 第二题“出口呢？”：真实调用前只读核对

日期：2026-09-29（北京时间）。本阶段**没有发送模型推理请求**，没有创建第二题账本；这份记录不是收费许可。

- 当天读取 [DeepSeek 官方价格页](https://api-docs.deepseek.com/quick_start/pricing/)：请求型号 `deepseek-flash` 对应 DeepSeek-V4.1-Flash。每百万 token 的美元标价：缓存命中输入闲时/峰时 0.003/0.006，缓存未命中输入 0.15/0.30，输出 0.60/1.20。实际账单依服务商计量和时段，不保证固定金额。
- 对已配置账户按[官方只读余额接口](https://api-docs.deepseek.com/api/get-user-balance/)做一次 GET：HTTP 200，`is_available=true`，币种 CNY；没有打印 API Key 或余额金额。可用标志不等于用户授权费用。
- 本机第二题预检 `offline_ready`：DeepSeek `deepseek-flash` / high，原题“出口呢？”，首轮请求 4,415 字节、SHA-256 `7e3f2fbef86a04ae97a2e7e1901d638ea588bd5d5b9c5e14745d10a183ef497f`；快照 SHA-256 `81cc9c911e467fcc2b8aac3ad4bfb29a097329cb9d2c331c9b408c081c8bd2b2`，第二题账本不存在。配置和数据版本与已锁方案一致。
- 停止门仍是本题最多一次尝试、最多4次模型回复/8次工具调用/单次4096输出 token/90秒超时；失败或结果未知不重试。没有账户级硬扣费上限，不能把这些参数写成保证金额。

下一步仅在用户明确允许**第二题最多一次付费调用**后，重新核当日状态、快照和账本，并只发送这一题。首题与其余三题不会重跑或自动放行。
