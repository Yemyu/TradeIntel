# Model tests

[中文](MODEL_SELECTION.zh-CN.md) · [Project](../README.md)

The tests check tool selection, task completion, unsupported requests, and the figures in saved reports. They provide a practical reference for choosing a model.

## Results after the v3 fixes

| Model / reasoning | Channel | Normal tasks completed | Boundary cases handled | Saved reports verified | Main issues |
|---|---|---:|---:|---:|---|
| GPT-6.1 Sol / Low | Codex chat bridge, 12 turns | 9/9 | 3/3 | 9/9 | All tasks completed; missing dates and insufficient tariff evidence handled correctly |
| GPT-6.1 Sol / Medium | Codex chat bridge, 12 turns | 9/9 | 3/3 | 10/10 | All tasks completed; the chat retained context from an earlier test |
| GPT-6 Luna / Max | Recovered Codex chat run, 12 planned turns, 11 executed | 7/9 | 2/3 | 8/8 | Rubber stopped at clarification; its follow-up was skipped. The tariff explanation did not reach the public answer |
| DeepSeek-V4.1 Flash / high | API, 12 planned turns, 11 executed | 8/9 | 2/3; one dependent turn skipped | 14/14 | Tungsten policy task exceeded the six-response limit; an attempted month substitution was blocked |

The run used 34 requests, with an estimated cost of CNY 0.35 from reported usage. Strict tool decisions passed 7/10 model-assisted turns. The rubber task returned the correct six-month main report but also requested a twelve-month window, which fails the fixed-window action check. The unavailable-month task was handled safely only after the program blocked the model's attempted substitution. The policy task did not publish its unverified explanation; its follow-up was skipped.

Both request and response used `deepseek-flash`, currently documented by the provider as DeepSeek-V4.1-Flash, with thinking enabled and high reasoning. The October 2, 2026 run uses the same nine normal and three boundary tasks. [API run record](handoff/runs/20261002-US-FINAL-REGRESSION-LIVE.zh-CN.md).

Sol Low and Medium each passed 11/11 strict tool-decision checks. The unsupported-partner case was a zero-response program precheck, not a model answer. Low saved both trade directions in one report; Medium saved separate reports. Both groups passed checks for ten directional series. [Sol review](handoff/runs/20261002-CHAT-V3-COMPARISON-REVIEW.zh-CN.md).

Luna's recovered run used 29 chat decisions and passed 8/10 strict tool-decision checks. Its runner marked eight turns completed, but the tariff turn published only a trade report. The correct raw explanation was not included in the public answer, so that boundary task remains incomplete. Eight report containers and nine directional series passed verification. The earlier zero-response failure and quota interruption are preserved separately; the recovered run had already seen some of the questions. [Luna review](handoff/runs/20261002-LUNA-V3-FINAL-REVIEW.zh-CN.md). These are chat-bridge runs, not GPT API integration tests. Medium retained earlier test context.

## Earlier results (tool protocol v2)

| Model / reasoning | Channel | Normal tasks completed | Boundary cases handled | Saved reports verified | Main issues |
|---|---|---:|---:|---:|---|
| GPT-6 Luna / Max | Codex chat bridge, 12 turns | 4/9 | 2/3 | 4/4 | Rubber, cocoa beans, and tungsten stopped at clarification; three dependent turns skipped |
| GPT-6.1 Sol / Low | Codex chat bridge, 12 turns | 7/9 | 3/3 | 7/7 | Rubber and its follow-up were incomplete; R04 was restarted after interruption |
| GPT-6.1 Sol / Medium | Codex chat bridge, 12 turns | 9/9 | 3/3 | 9/9 | All normal tasks completed; an earlier result summary had been read before the run |
| DeepSeek-V4.1 Flash / high | API continuation, 11 planned turns, 9 executed | 4/8 planned; 4/7 executed | 2/3 planned; 2/2 executed | 5/5 | Both-direction, rubber, and tungsten tasks incomplete; two dependent turns skipped |

**Task completion** means retrieving the requested product, direction, partner, and dates and returning a report. A normal task that stops at clarification is incomplete.

**Boundary handling** means explaining unavailable dates, unsupported partners, or insufficient tariff information without substituting another scope. Clarification can be the correct result here. Luna's third boundary case was skipped because its prerequisite was incomplete.

**Report verification** checks saved amounts, scope, unknown values, calculated summaries, sources, and the public report view. One turn can produce multiple reports. This is separate from the correctness of every model action.

DeepSeek's strict raw-decision check passed 3/8 responses. One attempted month substitution was blocked by the program; another response added an unrequested partner query. The five verified reports do not make those actions correct.

## Test setup

The October 1, 2026 set contains nine normal and three boundary tasks: follow-ups, product changes, rubber, cocoa beans, policy retrieval, and unavailable data. GPT groups used all twelve turns; DeepSeek continued after an earlier R01 run, so their denominators differ. GPT settings were confirmed by the user. DeepSeek requested and returned `deepseek-flash`, recorded as V4.1 Flash under the provider information available for that run, with thinking enabled and high reasoning.

This section uses **tool protocol v2**. Current v3 repairs cover product aliases, both-direction candidates, policy merging, and citation feedback. Related offline tests passed 74 Python and 52 Node checks. Post-fix results are listed separately above; earlier answers and scores are unchanged.

GPT used a Codex chat bridge, not this application's GPT API adapter. Sol Medium had read an earlier summary; Sol Low restarted an interrupted turn. Review was AI-assisted. These setup differences are recorded alongside the results rather than collapsed into a cross-channel accuracy ranking.

## Choosing a model

After the fixes, Sol Low and Medium both completed nine normal tasks and handled all three boundary cases. Low is sufficient for this task set; higher reasoning is not automatically required. Neither chat run verifies GPT API integration in this application. DeepSeek Flash with thinking enabled/high has real API runs through the project, including both successes and incomplete tasks.

Use the exact model name and endpoint supplied by your provider. GLM's thinking switch is not a verified high-reasoning setting. Historical `deepseek-v4-pro` results identify an API alias, not a confirmed independent V4.1 Pro backend. For charts and figures alone, data-only mode needs no model.

The DeepSeek continuation added 33 HTTP requests; including the earlier R01 run, the total was 38. The peak cost estimate was CNY 0.341612, not a provider invoice. GPT chat groups made no external API requests and have no comparable API usage or cost record.

## Earlier report and notice tests

These tasks used different output requirements and are not added to the Agent scores.

| Date / task | Model / setting | Answers received | Recorded result | Main issue |
|---|---|---:|---|---|
| Sep 22, brief v1 | GPT-5.6 Luna / Max | 4 | 0/4 whole-task passes | Source confusion and value/volume wording |
| Sep 22, brief v1 | GPT-5.6 Sol / High | 4 | 3/4 whole-task passes | Price question lacked mechanisms and required evidence |
| Sep 22, brief v1 | GLM-4.6V / thinking enabled | 1 | 0/1; separate 401 without an answer | Output-contract violation |
| Sep 22, brief v1 | GLM-4.5-Air / thinking enabled | 0 | HTTP 400; no content score | Interface failure |
| Sep 22, brief v1 | DeepSeek Flash / low | 3 | Format 3/3; content 0/3 | Generic explanation and policy omissions |
| Sep 22, brief v1 | `deepseek-v4-pro` / low | 2 | Format 2/2; content 0/2 | Share/dependence confusion; unverified year-on-year claim |
| Sep 23, brief v2 | DeepSeek Flash / high | 3 | Structure/budget 2/3; content 1/3 | Over-explanation and truncation |
| Sep 23, brief v2 | `deepseek-v4-pro` / high | 0 | One request; outcome unknown | Timeout/interruption without a saved answer |
| Sep 24, trade v3 | DeepSeek Flash / high | 4 | Structure 4/4; content review not finalized | Format is not a content score |
| Sep 24, trade v3 | `deepseek-v4-pro` / high | 2 | Stopped after an error in the second answer | Latest-month change described as a whole-period trend |
| Sep 28, short explanation | DeepSeek Flash / high | 3 | Basic facts 3/3; added reading value 0/3 | Mostly repeated the program report |
| Sep 28, notice reading | DeepSeek Flash / high | 1 | Coverage 7/7; overall failed | Unsupported claim that the attachment was missing |
| Sep 28, notice reading | GPT-6 Luna / Max, chat | 1 | Coverage 7/7; no unsupported extra claim found | Previously seen notice, not an API run |

A separate earlier GLM-4.7 six-scenario test recorded 5/6 passes (supported tasks 2/3; boundaries 3/3) using seven calls. See its [record](experiments/product-acceptance.zh-CN.md). Historical Pro backend identity remains unconfirmed.

## Records

- [Questions](../evals/us_agent_retest_v1/scenarios.json)
- [GPT review](handoff/runs/20261001-CHAT-COMPARISON-REVIEW.zh-CN.md)
- [DeepSeek continuation](handoff/runs/20261001-US-RETEST-V5-LIVE.zh-CN.md)
- [v3 repairs](handoff/runs/20261001-MINIMAL-AGENT-REPAIR-OFFLINE.zh-CN.md)
- [Earlier brief review](handoff/runs/20260922-MODEL-SEMANTIC-AUDIT.zh-CN.md)
- [Sep 23 comparison](handoff/runs/20260923-MODEL-COMPARISON-TABLE.zh-CN.md)
- [Full historical notes](history/MODEL_SELECTION.before-public-edit-20261001.zh-CN.md)
