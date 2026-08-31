# TradeShock AI

An evidence-grounded AI assistant for analysing trade-policy shocks and trade diversion.

## Current status

Learning and development stage 8: the initial eligibility run correctly stopped at a 1.0822% ambiguous-value share. A precommitted exact Census HTS10 continuity rule then resolved only codes whose official 2016/2017 code, full description, units, validity, and WCO candidate all agree. After rebuilding the affected 2016 panel, all six eligibility gates pass: ambiguity is 0.0109%, with 315 treated and 893 clean-control candidates. Matching, balance, and pre-trend checks remain pending; no causal result exists yet.

This repository is currently local-only. It will not be published until its scope, documentation, and privacy have been reviewed.

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
- [Decision 0002: exact HTS10 continuity rule](./docs/decisions/0002-exact-hts10-continuity.zh-CN.md)
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

The mapping is deliberately conservative: `ex` and one-to-many relationships remain ambiguous unless the frozen exact Census HTS10 continuity rule passes every official-field check. The rebuilt all-origin panel and eligibility layer now pass all six qualification gates. This permits matching to begin, but it does not satisfy balance or pre-trend gates; see [`control_build_report.md`](./data/processed/causal/control_build_report.md).

After the mapping is verified, rebuild the compact all-origin HS6 panel with:

```bash
python scripts/build_causal_trade_panel.py --start 2016-01 --end 2019-12
```

This reads every origin from the official monthly detail files, retains only China and all-origin totals after mapping, removes each raw ZIP after successful processing, and records checksums in `causal_trade_panel_manifest.json`. The completed frozen scope is January 2016–December 2019 (48 months; 247,124 HS6-by-month rows). Its all-sample mapping coverage is 96.23% by all-origin value and 98.86% by China value. Twelve affected 2016 months were rebuilt; 36 later months were reused only after exact year-level mapping comparison proved them unchanged. The panel does not choose controls or estimate a causal effect by itself.

Run the frozen pre-policy eligibility and policy-contamination gates with:

```bash
python scripts/build_control_eligibility.py
```

This produces auditable treated/control/excluded labels and a value-ranked mapping-exception table. The current run passes all six frozen gates: treated pre-policy value coverage is 99.98%, year-by-HTS10 coverage is 99.86%, ambiguous value is 0.0109%, and the eligible pools contain 315 treated and 893 controls. No post-policy outcome is used for selection. Matching has not yet been run.
