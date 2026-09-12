# TradeShock AI

Current review (0119): pending or rejected main fact reviews now stop the runner, failed reference arithmetic is rejected, and baseline fact judgments require review evidence. Strict policy cases use a separately frozen official-facts file; the runner can capture a redacted self-consistent HTTP payload at the compatible model's final opener boundary, while synthetic fixtures without that boundary remain unverified. Registered-window recomputation, the host gap-review hook, final delivery reinspection, and an explicit source/data/runtime snapshot are now wired; transitive packages, semantic human review, complete combined-fixture coverage, and online acceptance remain pending. See the [review and remaining implementation checklist](docs/decisions/0119-controls-integration-review.zh-CN.md). Earlier checkpoints below are historical.

An evidence-grounded AI assistant for analysing trade-policy shocks and trade diversion.

Current design (0118): the runner now saves an independent trade baseline, compares the model-derived scope before execution, checks paired policy settings before either answer, and stores redacted provider-neutral payload captures plus pending human fact-review packets. Human semantic review and full acceptance remain pending; this is synthetic/offline infrastructure, not model accuracy. Online execution stays disabled. See the [implementation handoff](docs/decisions/0118-independent-controls-contract.zh-CN.md) and [Chinese learning guide](docs/learning/phase-50-independent-comparison.zh-CN.md). The checkpoints below are historical.

Current review (0117): repaired acceptance via empty reviews, false fact scores for negated statements, and missing endpoint arithmetic checks. Synthetic protocol completion is separate from acceptance readiness, which remains false. The independent intent baseline, paired semantic review and full dependency freeze are still pending. The 0116 completion claims below are historical and superseded by [0117](docs/decisions/0117-acceptance-reaudit.zh-CN.md).

Current audit (0116): the former hard-coded A/B paths were removed and replaced with real offline controls. A recomputes trade values directly from the declared source table; B asks the same policy question without retrieved evidence and records the actual baseline answer and fact gap. Review, delivery hashes, message capture, dependency freezing and acceptance bindings are covered by 589 local tests with 0 external API calls. `acceptance_ready` is only an offline protocol result, not a model accuracy score; the 0111 online runner remains disabled pending Astra review. See the [0116 decision and implementation boundary](docs/decisions/0116-runner-audit.zh-CN.md).

Audit update (0114): additional synthetic tests exposed premature question completion, truncated-response acceptance, lost usage, and unverified review witnesses in the new acceptance component. These defects were repaired; the integration handoff was then implemented offline. See [review and integration handoff](docs/decisions/0114-acceptance-guard-review.zh-CN.md). The checkpoints below are historical, not acceptance certification.

Audit update (0113): the 0112 prospective acceptance guards are now implemented and covered by synthetic counterexamples (11 new tests; full suite 566 tests; 0 API calls). They block reviewer override of transport/structure failures, freeze-input tampering, unknown usage and the 80,000-token boundary. The 0111 runner remains disabled; this is acceptance infrastructure, not a new model score. See the [implementation decision](docs/decisions/0113-prospective-acceptance-guards-implementation.zh-CN.md) and [Chinese learning guide](docs/learning/phase-45-acceptance-guards.zh-CN.md).

Audit update (0112): the 0111 prospective candidate set and runner did not pass review. Live execution of that runner is disabled pending protocol repairs; its offline checks establish numeric consistency only, not acceptance readiness. The four reviewed development scenarios remain valid. See the [current audit](docs/decisions/0112-prospective-audit.zh-CN.md); the checkpoint below is historical.

Latest development checkpoint (2026-09-12): four known natural-language development scenarios passed explicit host review, and a new 24-question prospective set was frozen and independently checked offline (0 API calls). This is not independent accuracy or unattended-product validation. The everyday natural-language CLI now shares the strict workflow configuration used by the reviewed path; see the [0111 Chinese handoff](docs/decisions/0111-prospective-set-frozen.zh-CN.md) and [learning guide](docs/learning/phase-44-prospective-set.zh-CN.md). Earlier sections below describe historical components.

### Integrated research brief (experimental)

A confirmed entry now combines exact trade calculations, policy retrieval, optional bounded GLM generation and source-traceable Chinese reporting. Explicit scope selection is required; this is not autonomous planning or a causal estimator. Default mode makes no API calls. [中文使用与学习说明](docs/learning/phase-13k-research-brief.zh-CN.md).

```bash
.venv/bin/python scripts/run_research_brief.py --question '第一批公告何时生效？' --policy-as-of 2018-07-06 --months 2018-09 2018-10 --origin other_origins --confirm
```

Add `--generate` for one bounded live request. Reports preserve generated claims separately from calculations and review notes. [Integrated development results](docs/experiments/phase13k-results.zh-CN.md).

### Experimental policy-document retrieval (Phase 13a)

Phase 13e integration: the same CLI now supports bounded GLM-4.7 generation (thinking disabled, 512 output tokens), strict completion checks, format-only normalization, and separate raw/normalized audit records. `--replay-last` demonstrates the archived real answer offline; it is not a new live evaluation. [中文使用说明](docs/learning/phase-13e-unified-policy-workflow.zh-CN.md).

Page-traceable lexical retrieval over five narrative pages from two verified 2018 USTR notices. Includes Chinese query expansion, BM25 versus term-overlap development comparison, publication cutoffs, and an optional single-call generation interface with citation-ID validation. This is not a complete tariff database, fine-tuning, or independently validated live RAG. The archived-plan business integration is offline; existing model scores remain unchanged.

- [中文学习说明与参考答案](docs/learning/phase-13a-policy-retrieval.zh-CN.md)
- [Development results and limitations](docs/experiments/phase13a-policy-retrieval/review.zh-CN.md)

Using the fingerprint-verified text snapshot included under `docs/experiments/phase13a-policy-retrieval/`:

```bash
.venv/bin/python scripts/run_policy_retrieval.py
```

Outputs local evidence previews in `tmp/policy-retrieval/`; no API call by default. `--generate` uses the project-scoped API key or hidden terminal input for GLM-4.7 and writes a new `run-...` audit directory. Generated claims remain unverified drafts pending semantic review. The historical replay requires the local archived response; it never substitutes that answer for a different question.

> 项目方向、已完成内容、未完成原因和后续边界，以[项目总参考文件](docs/PROJECT_CONTEXT_REFERENCE.zh-CN.md)为准。它用于恢复上下文，不能用阶段日志替代。

## Current status

2026-09-10 HTS8 route update: 692 stable metadata candidates were aggregated to a 29-month pre-policy HTS8 panel (20,068 rows). Applying the frozen 24-positive-China-month screen leaves 243 main-route candidates; in NAICS4 3332 this is 38 treated and 24 control candidates. This is a screening result, not a matched sample or causal estimate. See the [Chinese candidate result](docs/decisions/0052-hts8-candidate-panel-results.zh-CN.md) and [learning guide](docs/learning/phase-12i-hts8-candidate-screening.zh-CN.md).

2026-09-10 data-preparation update: the reusable pre-policy HTS10 detail layer for 2016-01 to 2018-05 is complete (29 months, 496,126 rows). Every month reconciles to the frozen all-origin HS6 panel, and the 29 original Census ZIP archives are retained locally until the data design is settled. The 17 uncovered HTS10 leads are screening candidates only; they have not been adopted as controls and no causal effect is claimed. See the [Chinese extraction decision](docs/decisions/0048-hts10-retention-and-extraction.zh-CN.md), [candidate-screening result](docs/decisions/0049-hts10-candidate-screening-results.zh-CN.md), and [Chinese learning guide](docs/learning/phase-12g-hts10-screening.zh-CN.md).

2026-09-06 audit: fabricated scores for the unrun direct-model baseline have been withdrawn. The 60-question report measures development tool contracts, not final-answer correctness. Models may call five query tools; evidence assembly is host-only. Unverified drafts return `needs_review` (CLI exit code 3). Missing months remain null. No live-model evaluation or causal estimate has been established. See the [Chinese audit guide](docs/learning/phase-10d-quality-audit.zh-CN.md) and [evaluation protocol](docs/decisions/0008-evaluation-and-trust-boundary-audit.zh-CN.md).

Learning and development stage 9c: the initial eligibility run correctly stopped at a 1.0822% ambiguous-value share. A precommitted exact Census HTS10 continuity rule then resolved only codes whose official 2016/2017 code, full description, units, validity, and WCO candidate all agree. After rebuilding the affected 2016 panel, all six eligibility gates passed: ambiguity is 0.0109%, with 315 treated and 893 clean-control candidates. Three pre-registered policy-pre matching experiments were then audited: the first failed balance, the global-balance refinement was infeasible for all 284 treated families, and the final maximum-cardinality design was also infeasible at the original 252/315 coverage floor. No causal result exists; the project now transfers to the evidence-grounded AI layer, which will make this limitation explicit rather than inventing a causal estimate.

The repository has been pushed to a private GitHub remote as a development checkpoint. It is not a public release; no causal effect estimate is claimed.

## Project documents

- [Learning-first project plan](./PROJECT_PLAN.md)
- [Learning profile and collaboration rules](./LEARNING_PROFILE.md)
- [Stage 0 learning guide](./docs/learning/phase-00-foundations.md)
- [Phase 1 Chinese learning guide: trade-data inventory](./docs/learning/phase-01-trade-inventory.zh-CN.md)
- [Phase 2 Chinese learning guide: policy and trade join](./docs/learning/phase-02-policy-join.zh-CN.md)
- [Phase 3 Chinese learning guide: MySQL data layer](./docs/learning/phase-03-mysql.zh-CN.md)
- [Phase 4 Chinese learning guide: data quality layer](./docs/learning/phase-04-data-quality.zh-CN.md)
- [Phase 5 Chinese learning guide: statistical design](./docs/learning/phase-05-statistical-design.zh-CN.md)
- [Experiment protocol 0001: Section 301 List 1 statistical design](./docs/experiments/0001-section301-list1-statistical-design.zh-CN.md)
- [Phase 6 Chinese learning guide: control-group design](./docs/learning/phase-06-control-design.zh-CN.md)
- [Phase 7 Chinese learning guide: control eligibility](./docs/learning/phase-07-control-eligibility.zh-CN.md)
- [Phase 8 Chinese learning guide: exact mapping resolution](./docs/learning/phase-08-exact-mapping-resolution.zh-CN.md)
- [Phase 9 Chinese learning guide: pre-policy matching and the blocked balance gates](./docs/learning/phase-09-prepolicy-matching.zh-CN.md)
- [Phase 9c Chinese learning guide: maximum-cardinality matching and the final block](./docs/learning/phase-09c-cardinality-matching.zh-CN.md)
- [Decision 0002: exact HTS10 continuity rule](./docs/decisions/0002-exact-hts10-continuity.zh-CN.md)
- [Decision 0003: pre-policy matching design](./docs/decisions/0003-prepolicy-matching-design.zh-CN.md)
- [Decision 0004: globally balanced optimal matching experiment](./docs/decisions/0004-globally-balanced-optimal-matching.zh-CN.md)
- [Phase 10 Chinese learning guide: evidence-grounded AI application design](./docs/learning/phase-10-ai-application-design.zh-CN.md)
- [Phase 10a Chinese learning guide: evidence tools and deterministic baseline](./docs/learning/phase-10a-evidence-tools.zh-CN.md)
- [AI 60-question contract evaluation report](./data/processed/ai/ai_evaluation_report.md)
- [Phase 10b Chinese learning guide: model—tool loop and safety guard](./docs/learning/phase-10b-model-tool-loop.zh-CN.md)
- [Phase 10c Chinese learning guide: real-model adapter](./docs/learning/phase-10c-real-model-adapter.zh-CN.md)
- [Phase 10e Chinese learning guide: final-model evaluation](./docs/learning/phase-10e-live-evaluation.zh-CN.md)
- [Decision 0005: evidence-grounded AI application layer](./docs/decisions/0005-evidence-grounded-ai-application.zh-CN.md)
- [Decision 0006: maximum-cardinality overlap matching v3](./docs/decisions/0006-maximum-cardinality-overlap-matching.zh-CN.md)
- [Decision 0007: real-model adapter](./docs/decisions/0007-real-model-adapter.zh-CN.md)
- [Decision 0008: evaluation and trust-boundary audit](./docs/decisions/0008-evaluation-and-trust-boundary-audit.zh-CN.md)
- [Decision 0009: frozen live-evaluation protocol](./docs/decisions/0009-live-evaluation-protocol.zh-CN.md)
- [Final evaluation question-set guide](./evals/README.zh-CN.md)
- [Data contract 0003: causal control-data extension](./docs/contracts/0003-causal-control-data-contract.zh-CN.md)
- [Policy exposure evidence table](./data/processed/causal/trade_action_exposure.csv)
- [List 1 exclusion timeline](./data/processed/causal/list1_exclusion_timeline.csv)
- [HTS history mapping](./data/processed/causal/hts_history_mapping.csv)
- [Mapping report](./data/processed/causal/mapping_report.md)
- [All-origin trade-panel report](./data/processed/causal/causal_trade_panel_report.json)
- [All-origin trade-panel source manifest](./data/processed/causal/causal_trade_panel_manifest.json)
- [Control-build status report](./data/processed/causal/control_build_report.md)
- [Control-eligibility report](./data/processed/causal/control_eligibility_report.md)
- [Treated mapping exceptions](./data/processed/causal/treated_mapping_exceptions.csv)

### 中文学习版

- [首个政策案例：为什么选 Section 301 List 1](./docs/decisions/0001-initial-policy-case.zh-CN.md)
- [数据契约：数据从哪里来、怎样才算正确](./docs/contracts/0001-section301-list1-data-contract.zh-CN.md)
- [数据质量契约：哪些数据允许进入分析](./docs/contracts/0002-trade-data-quality-contract.zh-CN.md)

## Local environment

The project uses Python 3.12 in a project-local virtual environment:

```bash
source .venv/bin/activate
python --version
```

No third-party Python packages are required in stage 0.

Run the local evidence-tool and model-loop demos (no API key required):

```bash
source .venv/bin/activate
python scripts/run_tradeintel_ai.py "2018年关税后中国进口下降多少？能证明关税导致下降吗？"
python scripts/run_tradeintel_ai.py --mock-agent "关税导致中国进口下降了吗？"
python scripts/evaluate_tradeintel_ai.py
```

The first command uses the deterministic routing baseline; `--mock-agent` demonstrates a provider-neutral model/tool loop and the causal safety guard. The 60-question report measures the local tool contract, not an external LLM.

After configuring `TRADEINTEL_MODEL_BASE_URL`, `TRADEINTEL_MODEL_NAME`, and (when required) `TRADEINTEL_MODEL_API_KEY` in the current shell, the same CLI can run one real-model smoke test:

```bash
python scripts/run_tradeintel_ai.py --live-agent "2018 年 Section 301 List 1 后中国相关商品进口变化是多少？"
```

The key is read only from the environment and must never be committed. The live adapter is documented in [`phase-10c-real-model-adapter.zh-CN.md`](./docs/learning/phase-10c-real-model-adapter.zh-CN.md); without a key, use the offline modes above.

## First validated policy source

The initial historical case is the U.S. Section 301 List 1 action effective 6 July 2018. Reproduce the official tariff-code extraction with:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/download_policy_sources.py
python -m src.policy.extract_ustr_list1
python -m unittest discover -s tests -v
```

The extraction retains the original `9033.00` entry and applies the later official correction to `9033.00.90` with source-page provenance.

## First trade-data inventory

Place the official July 2018 Census archive temporarily at `data/raw/trade/IMDB1807.ZIP`, then run:

```bash
python scripts/inventory_census_import.py
```

The script streams the fixed-width detail member, filters to the audited List 1 codes, and writes a compact origin summary, a product-origin-month aggregate, and an inventory report. It does not estimate a policy effect.

The processed outputs record the official source URL, filename, byte size, retrieval time, and SHA-256 checksum. The raw ZIP is not required to remain in the project after successful processing; see [`data/README.md`](./data/README.md).

## Multi-month panel

The resumable pipeline processes one month at a time and removes each raw ZIP after successful processing:

```bash
python scripts/build_trade_panel.py --start 2016-01 --end 2019-12
```

It writes one generated CSV per month under `data/processed/trade/monthly/`, a 48-month source manifest, and a combined `trade_import_monthly.csv`. The full generated panel is intentionally ignored by Git; the one-month sample remains as the readable example.

## Descriptive policy baseline

Audit the policy, lineage, codes, and 48-month panel before analysis:

```bash
python scripts/audit_data_quality.py --mysql-login-path tradeintel
```

Then join the verified Section 301 event and product list to the local panel:

```bash
python scripts/analyze_policy_case.py
```

This writes a monthly before/transition/after table, an origin-level change table, and a JSON summary under `data/processed/analysis/`. It is explicitly descriptive and does not claim a causal tariff effect.

Build the frozen same-calendar-month statistical baseline with:

```bash
python scripts/build_statistical_baseline.py
```

The primary descriptive window compares August–December 2018 with the same months in 2017 and always carries `causal_claim=false`. The experiment protocol documents the hypotheses, leakage controls, adoption thresholds, and stopping rules before a causal model is attempted.

Build the official policy-contamination evidence layer with:

```bash
python scripts/build_policy_contamination.py
```

This parses and checks the official List 1/2/3 notices, records Section 232/201 scope rules, downloads the List 1 exclusion notices, and writes source hashes. The cross-year mapping is built separately from official Census history/concordance files and the WCO 2012→2017 table:

```bash
python scripts/build_hts6_mapping.py
```

The mapping is deliberately conservative: `ex` and one-to-many relationships remain ambiguous unless the frozen exact Census HTS10 continuity rule passes every official-field check. The rebuilt all-origin panel and eligibility layer passed all six qualification gates. The first frozen matching run then passed coverage (90.16%) but failed balance for the pre-policy trend slope and China share. A pre-registered globally balanced refinement was infeasible, and the final maximum-cardinality experiment could not retain the required 252/315 treated candidates while preserving the frozen balance and reuse limits; see [`matching_balance_report_v3.md`](./data/processed/causal/matching_balance_report_v3.md). The project intentionally stops before pre-trend estimation and does not publish a causal result.

After the mapping is verified, rebuild the compact all-origin HS6 panel with:

```bash
python scripts/build_causal_trade_panel.py --start 2016-01 --end 2019-12
```

This reads every origin from the official monthly detail files, retains only China and all-origin totals after mapping, removes each raw ZIP after successful processing, and records checksums in `causal_trade_panel_manifest.json`. The completed frozen scope is January 2016–December 2019 (48 months; 247,124 HS6-by-month rows). Its all-sample mapping coverage is 96.23% by all-origin value and 98.86% by China value. Twelve affected 2016 months were rebuilt; 36 later months were reused only after exact year-level mapping comparison proved them unchanged. The panel does not choose controls or estimate a causal effect by itself.

Run the frozen pre-policy eligibility and policy-contamination gates with:

```bash
python scripts/build_control_eligibility.py
```

This produces auditable treated/control/excluded labels and a value-ranked mapping-exception table. The current run passes all six eligibility gates: treated pre-policy value coverage is 99.98%, year-by-HTS10 coverage is 99.86%, ambiguous value is 0.0109%, and the eligible pools contain 315 treated and 893 controls. Matching uses only the clean pre-policy window and no post-policy outcome. The first method failed balance, the global method was infeasible, and the maximum-cardinality method could not meet the 252/315 coverage floor under the frozen balance and reuse limits. No candidate panel or event study is generated. Phase 10 now implements the read-only evidence tools and evaluation contract for the AI assistant, with causal refusal enforced by the blocked status.
