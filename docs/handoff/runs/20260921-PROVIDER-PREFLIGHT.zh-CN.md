# 国内模型连通检查与候选配置

日期：2026-09-21。用户授权检查三家提供的密钥及指定候选。本轮仅发送 `Reply only OK.`，未发送项目数据、正式四题或评分参考；未保存密钥。无自动重试，未修改旧实验冻结记录。

## 实际结果

每个型号一次POST、输出上限128、非流式、35秒超时、禁止重定向。

| 端点/请求型号 | 探测设置 | 结果 | 返回型号 | 输入/输出tokens |
|---|---|---|---|---|
| 智谱 / glm-5.3-flash | thinking enabled，reasoning_effort low | HTTP429，code1113 | 无 | 未返回 |
| 智谱 / glm-4.5-air | thinking disabled | HTTP200，stop，有回答 | glm-4.5-air | 13/2 |
| 智谱 / glm-4.6v | thinking disabled | HTTP200，stop，有回答 | glm-4.6v | 14/3 |
| DeepSeek / deepseek-flash | thinking disabled | HTTP200，stop，有回答 | deepseek-flash | 8/1 |
| DeepSeek / deepseek-v4-pro | thinking disabled | HTTP200，stop，有回答 | deepseek-v4-pro | 8/1 |
| 阿里云北京 / qwen3.8-flash | enable_thinking false，max_completion_tokens128 | URLError，无HTTP响应 | 无 | 未返回 |

实际地址：智谱 `https://open.bigmodel.cn/api/paas/v4/chat/completions`；DeepSeek `https://api.deepseek.com/chat/completions`；千问 `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`。

四次成功响应合计43输入、7输出、50tokens。另两次没有用量回执；未读取账单，不声称实际扣费金额或具体抵扣了哪个资源包。

智谱[官方错误码](https://docs.bigmodel.cn/cn/api/api-code)将1113解释为账户欠费。专属Air/V资源可用并不意味着新型号也有额度；本轮不要求充值、不继续尝试5.3。截图通用token包已失效，按次/搜索资源不作为文本推理额度。

千问无密钥HEAD诊断同一官方主机也出现 `SSL_ERROR_SYSCALL`。当前是连接层阻断，不是已经证明密钥错误或模型不存在；不关闭TLS验证、不把密钥发给第三方中转、不换地区盲试。恢复官方端点连接后再探测一次。用户密钥的sk-ws前缀本身不能判为无效。

## 统一四题的候选（尚未开跑）

| 配置 | 拟用思考设置 | 作用 |
|---|---|---|
| Luna最高 | 用户选择的最高推理；实际可核实配置留档 | Codex干净会话基准，不是API成绩 |
| Sol中 | 中推理；实际可核实配置留档 | 第二个Codex会话对照 |
| glm-4.6v | thinking enabled；不杜撰high/max档 | 利用现有资源，纯文本输入也可用；不因此声称测过视觉能力 |
| glm-4.5-air | thinking enabled；不杜撰high/max档 | 低成本对照；与旧关闭思考失败记录分别展示 |
| deepseek-flash | thinking enabled，reasoning_effort low | 轻量API候选 |
| deepseek-v4-pro | thinking enabled，reasoning_effort low | 用户要求的Pro对照，不称作4.1 Pro |
| qwen3.8-flash | enable_thinking true，reasoning_effort low | 小余额候选，网络恢复后再运行 |

这里的正式候选设置不同于超短连通探测；思考设置仍需用非正式开发输入验证预算与适配，然后与实际请求包一起冻结。连通成功不表示思考模式、JSON合同或产品准确率通过。

本次用户新增两个智谱和两个DeepSeek候选，将首轮上限由5配置×4题调整为7配置×4题=28份正式回答；不是必须用满。GLM5.3暂停，Qwen Max不在首轮。每配置先Q1/Q2，重大语义错误则停止，接口错误单列；未跑题不纳入已答分母。先保留旧程序报告对照，不照某个模型答案修改提示后继续同版评分。

Air新实验假设是“开启思考且使用已修复的公共多期输入可能改善旧错误”，不是重跑旧B/C/E。只有生产输入、参考与预算冻结后才运行，出现同类范围/分母错误即停止，不追加重试。各模型只读相同题目实际messages，不读评分参考、旧失败分析及其他回答。

千问Flash整阶段预算上限人民币0.50元（含正式前小样），实际账单未知时采用官网未命中缓存价格及请求/生成上限保守计费，不依赖缓存或赠送；预算无法确认则不发请求。正式前核实max_completion_tokens同时约束思考与正文，初始总上限8192；其余厂商也须确认输出预算是否含思考，不能把2000字最终合同当成总计费上限。Max只有Flash质量不达标后另列新配置，重算费用再决定，不自动升级消耗余额。

## 官方型号核对

- [智谱5.3 Flash](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-5.3-flash)：仅支持thinking enabled，不是免费模型的同义词。
- [智谱价格](https://docs.bigmodel.cn/cn/guide/start/pricing)：专属资源与通用余额要分别核对。
- [DeepSeek型号与价格](https://api-docs.deepseek.com/quick_start/pricing)：本次英文官方页为deepseek-flash（V4.1-Flash）与deepseek-v4-pro（V4-Pro-0813）；接口返回名称一致，但别名并非底层权重身份证明。实际运行记录日期与response.model。
- [DeepSeek思考配置](https://api-docs.deepseek.com/guides/thinking_mode/)：low/high/max；本轮拟low，不遍历档位。
- [千问3.8 Flash](https://help.aliyun.com/zh/model-studio/qwen3-8-flash)、[兼容接口](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)：低档思考和总输出上限需显式配置；不把商业API名字等同于开源许可证。

## 下一步

### 千问接入地址更正（用户控制台截图确认）

用户提供platform.qianwenai.com的API Keys截图，按量付费Base URL为此前粘贴的 `https://maas.qianwenaiapi.com/compatible-mode/v1`，可见密钥掩码与用户此前提供的匹配。后续应以这个配套地址为准，不能继续默认该密钥属于dashscope北京端点；旧地址探测结果不代表正确服务端的账户状态。

以新地址/chat/completions做一次极短qwen3.8-flash请求（非思考、max_completion_tokens128、30秒超时、禁止重定向），约0.38秒返回SSLEOFError，仍无HTTP响应和usage。无密钥curl HEAD在默认设置和--noproxy下也均TLS失败；后者不保证绕过系统VPN/TUN。因此尚不能确定是代理、线路还是远端握手问题；未证明充值/密钥/模型存在问题。未关闭TLS校验、未改系统网络设置、未保存凭证。累计8次连通POST尝试、4次成功，正式四题仍0答。下一网络诊断是用户将该域名走国内直连后复查；其他模型材料准备不受阻。

### 用户要求的千问复查（同日）

用户明确要求再次尝试后，以相同北京官方端点、qwen3.8-flash、非思考、128总输出上限、25秒超时再发一次极短请求。约0.38秒返回URLError，底层为SSLEOFError / UNEXPECTED_EOF_WHILE_READING；没有HTTP响应、模型回答或usage。这是TLS连接层失败，不能判定余额不足、密钥失效或模型不可用；充值不一定能解决此故障。未关闭证书验证、未使用第三方中转、未继续自动重试。累计7次连通尝试，4次返回模型回答；正式四题仍0答。GLM4.6V/4.5-Air上轮已成功，不因用户重复询问再消耗额度。

Luna最高先补真实服务端policy_context绑定，核验自然问句→范围提案，准备并冻结四题实际请求与独立参考；不立即批量调用。Astra复核后开始模型验收。当前正式四题仍为0答，前端不提前，模型成绩不由本文件的连通结果替代。
