# Evaluation materials

**English** | [简体中文](README.zh-CN.md)

[Project](../README.md) · [Model results](../docs/MODEL_SELECTION.md) · [Engineering tests](../docs/TESTING.md)

This directory contains structured questions, scoring requirements, reference answers, and version manifests. The presence of a question set or reference does not mean a model passed it. See the model results page for the current published scores and their limits.

## Current model tests

[us_agent_retest_v1/scenarios.json](us_agent_retest_v1/scenarios.json) contains twelve U.S. trade scenarios: product lookup, import/export follow-ups, product changes, policy retrieval, and boundary cases for missing months, unsupported partners, and insufficient tariff evidence. The file retains its original design version. See [results and scoring](../docs/MODEL_SELECTION.md) for execution methods, completion rates, and report verification.

GPT groups answered in Codex chats; DeepSeek and GLM used the application's API. GPT scores do not establish the application's GPT API compatibility. Some chats included earlier test context and were not independent blind tests. Review was AI-assisted, with report amounts also checked against data files.

## Other questions and scoring resources

- `questions.jsonl` and `gold_answers.json`: earlier tool-contract development questions and factual references.
- `final_questions.jsonl`, `final_gold.json`, and `final_manifest.json`: a forty-question candidate set, evaluator references, and original frozen-version information.
- `trade_model_v4/`: fixed report-interpretation requests, program-generated report baselines, and scoring JSON used by module regression tests.
- Other JSON, JSONL, and CSV files: module-development questions, acceptance inputs, references, or version information. Each file's description and status define its use.

These materials were designed by the project maintainer, not an independent third-party benchmark. Models should receive only questions and evidence from authorized tools; evaluator-only answers and expected fields must not enter model requests or feedback. AI-assisted review must be marked `ai_assisted`, not described as independent human review.

Historical sessions, raw outputs, and some frozen evidence are stored locally and are not fully distributed with the public source. Version manifests may retain original paths and digests for checking historical versions. Cloning the repository alone does not reproduce every historical experiment.
