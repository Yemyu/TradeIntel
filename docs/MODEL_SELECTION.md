# Model tests

[🇨🇳 简体中文](MODEL_SELECTION.zh-CN.md) · [Project](../README.md)

Twelve practical scenarios cover product lookup, import/export follow-ups, product changes, policy retrieval, and unavailable data. The table reports task completion, verified reports, and the main issues to help readers choose a model.

## Results

| Model / reasoning | Normal tasks completed | Boundary cases handled | Saved reports verified | Main issues |
|---|---:|---:|---:|---|
| GPT-6.1 Sol / Low | 9/9 | 3/3 | 9/9 | All tasks completed; missing dates and insufficient tariff evidence handled correctly |
| GPT-6.1 Sol / Medium | 9/9 | 3/3 | 10/10 | All tasks completed |
| GPT-6 Luna / Max | 7/9 | 2/3 | 8/8 | Rubber stopped at clarification and its follow-up was skipped; the tariff explanation was absent from the answer |
| DeepSeek-V4.1 Flash / high | 8/9 | 2/3; one skipped | 14/14 | Tungsten policy task exceeded the response limit; an attempted month substitution was blocked |
| GLM-5.3-Flash / High | 8/9 | 2/3; R06 handled by program precheck, P02 skipped as dependent | 10/10 | Tungsten policy lookup did not produce a report; a related-product query was rejected, followed by an extra China-source query |

Each group has nine normal tasks and three boundary cases. A normal task must retrieve the requested product, direction, partner, and dates and return a report. Unnecessary clarification counts as incomplete. Boundary cases require explaining missing data or insufficient evidence without substituting a different product, month, or statistical measure.

Report verification checks products, dates, partners, amounts, unknown values, calculations, and sources. One task can produce several reports, so report counts are not question counts. Correct report figures do not mean every model action was correct.

## Findings

**Sol Low and Medium** both completed the twelve tasks. Low saved imports and exports in one report; Medium saved separate reports, accounting for the different counts. Both groups passed checks for ten directional series. Low was sufficient for these tasks; the highest reasoning setting is not automatically needed.

**Luna Max** stopped at clarification for natural rubber, so its follow-up was not executed. Its raw tariff explanation was correct, but the final answer delivered only the trade report, not the explanation. That boundary case therefore did not pass. Eight saved reports and nine directional series passed verification.

**DeepSeek-V4.1 Flash** completed eight normal tasks. The rubber main report was correct, but the model also requested a twelve-month window. For the missing-month case, it attempted to query the latest available month; the program blocked that substitution before the model explained the gap. The tungsten policy task did not finish within six responses, and its dependent tariff question was skipped. No explanation that failed citation checks was published.

**GLM-5.3-Flash High** completed eight of nine normal tasks. All ten generated reports passed checks for data, scope, and source fields. It handled the unavailable requested month correctly; the unsupported Brazil-partner request was blocked by a program precheck and did not reach the model. The tungsten-policy task did not produce a report: after the catalog marked the product as a related candidate, the model made two rejected trade queries, including an additional query for China, then asked the user to clarify the product scope. Its dependent tariff follow-up was skipped. This run is partial, not a full-set pass. The 10/10 figure is report-data verification, not an overall model accuracy score.

Raw tool decisions were separately scored for the earlier four groups: 11/11 for each Sol group, 8/10 for Luna, and 7/10 for DeepSeek. These checks are separate from report verification. The GLM run has not received a full manual item-by-item raw-decision score on this same scale, so it should not be compared directly with those figures.

## Model settings

- **GPT-6.1 Sol:** one group each at Low and Medium.
- **GPT-6 Luna:** one group at Max.
- **DeepSeek-V4.1 Flash:** thinking enabled, high reasoning. Both request and response used `deepseek-flash`, identified as V4.1 Flash in the provider documentation.
- **GLM-5.3-Flash:** the API request and response identified `glm-5.3-flash`, with High reasoning. The run used 30 evaluation requests plus two short connectivity probes. Reported usage totaled about 77,370 tokens; the estimate at the published rate was about CNY 0.0733. The provider bill was not independently verified. The full run report is local and is not an independent human review of writing quality.
- The DeepSeek group used 34 requests, with an estimated cost of CNY 0.35 from reported usage (CNY 0.354654 before rounding), not a provider invoice. GPT groups have no comparable API usage or cost record.

Use the exact model name supported by your provider rather than inferring its version from a display label. Data-only mode needs no model if you only want charts and figures.

<details>
<summary>Test setup and scoring</summary>

The October 2, 2026 tests used the same twelve questions and fixed task requirements. Unrun dependent cases remain in the planned denominator; they are not counted as model failures or successes. The Brazil-partner question was handled by a program precheck, not counted as a model tool decision. GLM ran the 12-case plan, but P02 was skipped because P01 did not complete.

GPT groups answered tool requests in Codex chats; DeepSeek and GLM ran through the application's API. GPT chat scores do not verify this application's GPT API compatibility. Luna and Sol Medium chats included earlier test context and were not independent blind tests. Review was AI-assisted, with report amounts also checked against data files.

Completion is based on the answer and reports delivered to the user, not just whether the runner finished. Unexecuted follow-ups remain in the planned task count rather than being removed to raise completion rates.

</details>

## Questions and review records

- [Twelve questions](../evals/us_agent_retest_v1/scenarios.json)
- [Sol Low and Medium review](handoff/runs/20261002-CHAT-V3-COMPARISON-REVIEW.zh-CN.md)
- [Luna Max review](handoff/runs/20261002-LUNA-V3-FINAL-REVIEW.zh-CN.md)
- [DeepSeek run and review](handoff/runs/20261002-US-FINAL-REGRESSION-LIVE.zh-CN.md)
- [GLM-5.3-Flash High review (Chinese)](handoff/runs/20261002-GLM-FLASH-REVIEW.zh-CN.md)
