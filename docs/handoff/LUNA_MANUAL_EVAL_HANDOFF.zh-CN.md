# Luna 最高：公共四题独立对话测试交接

这份交接给一个**全新的、没有本项目历史聊天记录的 Luna 最高推理会话**。它只负责生成四个原始回答；当前主会话之后再做统一审阅和评分。

## 给新会话的提示词

```text
你现在负责 TradeIntel 项目的独立模型验收。当前模型是 GPT-5.6 Luna，最高推理。请先进入项目根目录：
/Users/ye/dev/projects/TradeIntel

你的任务是使用项目已经冻结的四道公共题，生成 Luna 的原始回答并保存到项目中。不要调用任何外部 API，不要修改题目、提示词、数据或评分规则。

重要的盲测规则：在四道题全部生成以前，不要读取这些位置中的任何模型答案、评分或失败分析：
- tmp/public-brief-eval-v1/formal-runs-20260922/
- docs/handoff/runs/20260922-DEEPSEEK-EVAL.md
- tmp/public-brief-eval-v1/formal-runs-20260922/score.json

只读取每道题自己的送模文件：
tmp/public-brief-eval-v1/candidate-service-20260922-v1/requests/q1/messages.json
tmp/public-brief-eval-v1/candidate-service-20260922-v1/requests/q2/messages.json
tmp/public-brief-eval-v1/candidate-service-20260922-v1/requests/q3/messages.json
tmp/public-brief-eval-v1/candidate-service-20260922-v1/requests/q4/messages.json

每个 messages.json 已经包含完整 system 和 user 消息。严格按照其中的 system 约束回答，只输出一个 JSON 对象，不要加 Markdown 代码围栏、解释或前后说明。q2、q3、q4 要按各自文件中的 request_context 理解上下文，不能读取其他模型的回答。

按 q1、q2、q3、q4 顺序执行。每道题完成后，把你实际输出的原始 JSON 字符串保存到：
tmp/public-brief-eval-v1/manual-runs-20260922/luna-highest-q1/raw-response.txt
tmp/public-brief-eval-v1/manual-runs-20260922/luna-highest-q2/raw-response.txt
tmp/public-brief-eval-v1/manual-runs-20260922/luna-highest-q3/raw-response.txt
tmp/public-brief-eval-v1/manual-runs-20260922/luna-highest-q4/raw-response.txt

同时为每题保存一份 run.json，只记录：question_id、model_id=gpt-5.6-luna、reasoning_effort=max、channel=codex_session、status=received、raw_sha256、started_at、finished_at。不要填写虚构的 API token 或 API 次数；api_calls 固定为 0，说明这是对话渠道。

每道题的 raw-response.txt 必须是你实际输出的完整 JSON，不能人工润色、修数字、补字段。保存后再继续下一题。四题全部保存后，再运行项目生产解析器检查四个原答；把解析结果分别保存为对应目录的 validation.json。解析失败也要保留原答，并在 validation.json 记录错误，不要修改原答后重跑。

最后只在项目中写一份 manifest.json 到：
tmp/public-brief-eval-v1/manual-runs-20260922/manifest.json

manifest 至少包含：schema_version=manual-public-brief-eval-v1、model_id、reasoning_effort、channel、questions=[q1,q2,q3,q4]、每题 raw_sha256、每题 status、api_calls=0。不要写入任何 API key。

完成后告诉我四个文件是否都已保存，以及每题的保存路径；不要评价模型好坏，主会话会统一审阅。
```

## 固定产物位置

新会话只能写入：

`tmp/public-brief-eval-v1/manual-runs-20260922/luna-highest-q1/`

`tmp/public-brief-eval-v1/manual-runs-20260922/luna-highest-q2/`

`tmp/public-brief-eval-v1/manual-runs-20260922/luna-highest-q3/`

`tmp/public-brief-eval-v1/manual-runs-20260922/luna-highest-q4/`

完成后回到当前主会话，我会检查原答摘要、运行记录和生产解析结果，再按四项标准审阅。这个对话渠道不会和 GLM、DeepSeek 的 API 结果混在同一张表里。
