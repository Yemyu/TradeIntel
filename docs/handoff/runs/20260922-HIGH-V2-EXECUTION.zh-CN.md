# 高推理配置及首题验证

本轮是新提示词+高推理的组合开发验收。数据和四个问题延续旧案例；不能将变化只归因于high，也不是新的盲测。

官方参数依据：

- [DeepSeek思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)支持low/high/max。本轮仅开放low/high，拒绝没有锁定的max、关闭思考配high，以及登记档位与请求不一致。
- [GLM-4.6V文档](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-4.6v)列出思考开关，未核实独立high档，暂不安排所谓GLM high；旧测试已经开启思考。

新矩阵 `evals/public_brief_v1/provider_matrix_high_v2.json`；新生产题包 `tmp/public-brief-eval-v1/candidate-high-v2-20260922/`；两份独立冻结在 `tmp/public-brief-eval-v1/high-v2-freezes-20260922/`；结果在 `tmp/public-brief-eval-v1/high-v2-runs-20260922/`。旧文件不覆盖。

19项相关测试通过。两份新冻结实际校验通过；将冻结high改成low会拒绝。题包输入估算15914/12699/15934/15914。总输出8192、正文估算2000、超时90秒保持，预检与首题合并执行。

Flash high Q1 已完成：finish_reason=stop，26.303秒；prompt 11535，completion 5026（其中reasoning 4330），total 16561。正文预算估算2540，超过2000，状态blocked_output_budget，停止后续题。不自动重试、不临时加预算。厂商completion减reasoning为696，与保守估算不等同；本次是项目估算预算不通过，不能声称厂商正文耗费2540token。

诊断性阅读发现Flash现能说出具体已核验环比方向及同商品来源，较旧答案更具体。但正式未通过预算门，不给予整题通过分。未完成独立语义验收，不宣称正确率提升。

Pro high Q1：请求已发送，但超过90秒仍在http.client读取chunked响应。07:25:42 UTC检查时已距开始133秒，随后人工Ctrl-C中断本地读取。发现现有timeout是网络读超时，不是总时长门。原始started记录已补恢复说明并置unknown_outcome、api_calls=1，账本追加unknown_outcome；服务端是否继续生成、实际用量及计费未知，没有自动重试。不能把此项算语义错误。

本轮实际请求2次，各模型仅Q1。Flash预算未通过、Pro结果未知，两配置停止；Q2—Q4未运行。没有4/4新成绩。响应没有回显推理档位时，只证明请求发送了官方支持的high参数，不声称平台独立证明实际推理强度。

下一步先修执行器总时长约束及中断记账，再讨论预算估算是否适合中文正文；不直接加预算重跑。建议Astra中确定可跨运行环境的总时长中止方式，Luna最高实现；不得把socket timeout继续写成已验证的90秒总时长门。任何代码修改后需新冻结，保留本轮未知结果。
