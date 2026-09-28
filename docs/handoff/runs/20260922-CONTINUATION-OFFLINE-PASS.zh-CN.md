# 续测离线贯通验收

## 结果

2026-09-22，Astra完成续测材料和执行链验收。39项定向测试通过，0次真实API，生产账本保持原样，未提交推送。

新服务题包：`tmp/public-brief-eval-v1/service-v3-audited-20260922`。
新冻结：`tmp/public-brief-eval-v1/v3-freezes-20260922/flash-v3-audited.json`。
离线结果：`tmp/public-brief-eval-v1/continuation-audit-20260922/offline-result.json`。

四道题的messages与host response共8份材料逐字节等同旧high-v2题包；来源manifest中的文件摘要和实际首题请求摘要也核对通过。新v3冻结额外绑定登记脚本，旧冻结不改。

注意：先运行直接构建器生成的`candidate-v3-audited-20260922`不是服务题包，Q2上下文与旧版不同，未用于续测。改用既有`prepare_public_service_candidate.py`实际服务流程后全部一致，没有删除差异字段或重写旧材料。

## 已实测链路

1. 登记命令dry-run校验24份材料通过。
2. 复制历史首题的两条事件到临时账本，目标配置明确改为offline_injected渠道，仅作测试。
3. 重复登记幂等，不产生Q1运行或成绩。
4. run_injected发送原样Q2消息给stub，返回生产解析器可接收的占位答复，进入awaiting_semantic_review。
5. 换输出目录重复Q2被拒；没有Q2语义审阅时Q3也被拒；stub合计调用一次。
6. 汇总无whole_pass；离线结果不是模型成绩。生产账本文件摘要前后相同。

## 下一步

实验假设保持：观察Flash高推理在相同输入下能否减少旧低推理的事实边界错误。不是保证通过。旧Q1为minor_error历史参考，不计v3 Q1成绩，不能拼出混合四题通过率。

当前环境TRADEINTEL_DEEPSEEK_API_KEY未配置。获得可用凭证后，仅登记正式历史前置并调用Q2；不得重跑Q1、不得重试Pro。每题审阅再继续；重大错误、未知结果或预算失败即停止。候选只接收messages，不接收参考、审阅或此前答案。参数沿用已冻结deepseek-flash/high、temperature=0、max_tokens=8192、90秒总截止、正文2000字符。

无需新方案或新增框架。常规执行可Luna最高，语义判断与是否采纳由Astra中完成。17项旧默认题包摘要报错仍在，和本次39项定向通过分开报告。
