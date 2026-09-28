# v4 单题开发执行器：离线实现与验收

日期：2026-09-28。范围：只实现冻结四题的单配置开发试跑入口；**未向模型发请求，未产生模型成绩**。

## 完成

- 新增 `scripts/run_trade_model_v4_dev.py`。默认 `--case v4-1` 仅核验冻结包、代码/数据摘要、产品本机配置、输入尺寸与本地账本，不发网络请求也不写账本。本机预检返回 `ready`、请求 4,565 字节、四题预留费用估算 $0.0513216；这不是实际扣费或账户硬上限。
- 真正的单题路径设两道命令行开关、当天价格确认日期和一次性账本。先写 `provider_call_started`，再最多调用一次；同题已有账本或孤儿原答一律拒绝重试。固定请求为 DeepSeek `deepseek-flash`、high、8,192 总生成 token、90 秒截止。只保存脱敏元数据、原答 SHA 和本地原文，不保存或打印密钥。
- 前题须在冻结材料和模型参数身份一致的条件下，通过人工事实审阅，下一题才可放行；合同通过只是 `needs_review`，不等于答案正确。阅读增益必须填页面与原答的两段真实引文，且都确实存在于冻结页面基线和原答中。严重错误、无响应、合同拒绝或结果未知均停后续题；三题零增益会提前停止第四题。
- 假服务测试涵盖授权门、同题 4 线程并发仅一次调用、冻结篡改、配置不符、孤儿原答、账本身份变化、空正文/`length`、超字节、JSON 拒绝、服务商 400、超时与未知结果、审阅引文及严重错误停机。

## 实际验收

- `PYTHONPATH=src:. .venv/bin/python -m unittest tests.test_trade_model_v4_dev_runner tests.test_trade_model_v4_freeze tests.test_trade_explanation_v4 tests.test_trade_explanation_http`：初次 **32/32 通过**。
- `PYTHONPATH=src:. .venv/bin/python scripts/freeze_trade_model_v4.py --verify --output evals/trade_model_v4/frozen/20260928-v1`：4 题、`frozen_inputs_no_model_results`、`model_calls=0`。
- `PYTHONPATH=src:. .venv/bin/python scripts/run_trade_model_v4_dev.py --case v4-1`：`ready`、`api_calls_this_check=0`；没有创建真实题号账本。
- 没有运行全仓测试；没有做真实服务商连通测试，也没有验证真实响应格式或实际费用。没有改 MySQL、旧 v3 账本、旧冻结成绩，未提交、未推送。

## 下一道门

用户需要单独同意具体的收费试跑配置与预算；同意前只允许离线检查。即使同意，也须在请求当天复核官方价格，一次只发第一题，保留原答并人工审阅后再决定下一题。**用户允许继续写代码，不等于允许开始收费调用。**

## 同日离线补验

- 增加真实 HTTP 适配器的**内存假响应**测试：从冻结 `messages.json` 构造完整 `/chat/completions` 请求，核对 `deepseek-flash`、思考开启、`high`、`max_tokens=8192`、无工具，假服务回复经过适配器和 v4 合同后才进入 `needs_review`。整个测试没有打开网络连接；测试用占位密钥没有进入结果和账本。
- [DeepSeek 官方价格页](https://api-docs.deepseek.com/quick_start/pricing/)同日显示 Flash 峰时缓存未命中输入 $0.30/百万 token、输出 $1.20/百万 token；[思考模式说明](https://api-docs.deepseek.com/guides/thinking_mode/)支持 `high`。官方把 API 请求名 `deepseek-flash` 映射到 DeepSeek-V4.1-Flash；执行器允许服务回显请求名或该版本名，其他型号仍拒绝。此核价不代表已经发生收费调用。
- 补验后上述四组测试 **33/33 通过**；本机只读预检仍为 `ready`、`api_calls_this_check=0`，真实 v4 账本目录没有题号文件。未做真实连通性、实际回答质量或实际账单验收。
