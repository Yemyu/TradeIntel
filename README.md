# TradeShock AI

An evidence-grounded trade-policy research assistant under development. The product goal is to connect official policy scope to trade data, run verifiable calculations and produce cited briefings with update tracking. The current checkout includes one newly registered 2025 Section 301 exposure case across 19 verified months; the broader product is not yet complete.

**Scope decision (2026-09-13):** self-developed causal identification has been removed from the product roadmap. Historical experiments remain available as records, not pending product requirements. [Current roadmap](PROJECT_PLAN.md).

[中文项目介绍与演示](docs/DELIVERY.zh-CN.md) · [中文操作说明](docs/learning/using-the-research-entry.zh-CN.md) · [Acceptance results](docs/experiments/product-acceptance.zh-CN.md)

[Concise three-file showcase](docs/showcase/README.zh-CN.md) provides the project scope and two archived reports without internal learning notes or request captures.

## What it does

- Proposes a structured read-only trade query from a Chinese question; execution requires confirmation.
- Retrieves page-linked policy evidence using lexical/BM25 retrieval and query expansion; GLM optionally drafts cited explanations.
- Computes monthly amounts and descriptive comparisons in code, with sources and scope limitations.
- Queries the registered 2025 tungsten/wafers/polysilicon case through a read-only tool using exact HTS8 scope and monthly source fingerprints.
- Stops missing-scope and unsupported requests; checks supported explicit comparison-direction phrases.

This is an AI application, not a trained foundation model. There is no fine-tuning, multi-agent deployment or accepted causal-effect estimate. The policy corpus covers indexed narrative text from two historical notices, not a complete tariff database or current legal guidance.

## View results without running anything

- [Real policy + trade report](docs/experiments/phase-0140-live/combined-report.zh-CN.md)
- [New-policy exposure report (2026-07)](data/processed/policy_exposure/report_2026_07.zh-CN.md)
- [New-policy 19-month exposure summary](data/processed/policy_exposure/window_summary_2025-01_2026-07.zh-CN.md)
- [Query-tool learning note](docs/learning/policy-exposure-query-tool.zh-CN.md)
- [Review and limitations](docs/experiments/phase-0140-live/README.zh-CN.md)
- [Fixed six-scenario acceptance, including the failure](docs/experiments/product-acceptance.zh-CN.md)

The fixed development acceptance recorded 5 passes and 1 failure (supported tasks: 2/3; boundaries: 3/3), using 7 GLM-4.7 calls / 14,640 reported tokens. This small assistant-designed and assistant-reviewed set is not independent accuracy. A later offline direction-guard fix does not change the model result. Earlier no-evidence controls also answered the repeated policy facts correctly: no RAG accuracy uplift is claimed.

## Run on a prepared checkout

Install dependencies only in the project virtual environment; skip creation if a working `.venv` already exists:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Prepared local trade tables, policy text and manifests are also required. Package installation alone does not rebuild the data. An isolated working-tree export with a new Python 3.12 virtual environment passed the offline demo on the same macOS machine after supplying the two policy PDFs, source manifest and omitted trade panel. Cross-platform installation and full data rebuild remain unverified. [Exact requirements and review](docs/RELEASE_REVIEW.zh-CN.md).

Check the four files omitted from a normal Git checkout without downloading or changing anything:

```bash
.venv/bin/python scripts/verify_portable_data.py
```

The command's `"status": "ready"` means only the four listed files match; it does not certify application readiness or the rest of the checkout. The exact paths, public source URLs and SHA-256 values are in [PORTABLE_DATA_MANIFEST.json](data/PORTABLE_DATA_MANIFEST.json). Missing, mismatched or incomplete manifests return a non-zero exit. The source-manifest hash binds the archived metadata including its retrieval timestamp; downloading the same PDFs again can produce different metadata and requires review rather than blindly changing the expected hash.

To make a plain folder containing those four files, without overwriting an existing path:

```bash
.venv/bin/python scripts/prepare_portable_data_bundle.py --output tmp/portable-data-bundle
```

The folder is a data supplement, not a standalone project or a zip archive. It contains no API configuration, credentials, Census ZIP archives, or temporary run records. Copy its `data/` directory into a prepared checkout and run the verification command again.

From the repository root, in an interactive terminal:

```bash
TRADEINTEL_MODEL_TIMEOUT=180 .venv/bin/python scripts/run_unified_research.py --question '只列出2018-09与2018-10中国的美元消费进口额，商品用第一批关税政策整体范围；逐月列数，不比较，不估计因果。' --confirm
```

Review the preview; type `yes` only if correct. The final output prints the report path under `tmp/unified-research/`. This example makes one planning call; a policy question with `--generate` can make an additional generation call. Preview-only mode still calls the planner; restarting creates a new attempt.

The CLI reads private project-local provider configuration when present, otherwise environment settings and a hidden key prompt. Never commit keys, `.local/`, or private raw runs. The everyday report reads prepared files; it does not require an active MySQL login.

To run the deterministic new-case query without an API key:

```bash
.venv/bin/python scripts/run_policy_exposure_query.py --origin China --start 2025-01 --end 2026-07 --output tmp/policy-exposure-query.json
```

This produces verified descriptive amounts and source references. It does not call an LLM and does not estimate a policy effect.

To open the local Chinese page (no public deployment):

```bash
.venv/bin/python scripts/run_web.py
```

Open the printed `http://127.0.0.1:8765` address. The page's data query is
deterministic and reads only the registered 2025 Section 301 exposure case.
The page also shows the locally activated data version and the latest
added/revised-month difference; it does not download new data by itself.
Its research question box supports bounded single-month queries, descending
product rankings and archived policy explanations, using up to two model calls.
This entry has offline integration tests; live task acceptance remains pending.
See the [Chinese question-entry guide](docs/learning/business-question-entry.zh-CN.md).
The complete Chinese workflow (fixed data version → AI review → export) is in [full workflow guide](docs/learning/full-workflow.zh-CN.md).
The three AI-demo buttons are explicit, bounded GLM runs; the browser never
receives the project-local API key. A successful run returns a review-required
Markdown report, while a failed run remains a local diagnostic record. See the
[Chinese page learning note](docs/learning/web-demo.zh-CN.md) for the complete
workflow and interpretation of the numbers.

The fixed `--exposure-demo` route now uses an evidence-only JSON report contract: the model selects investigation priorities while code renders computed facts and provenance. Invalid free-form output is retained but not delivered. This interim constrained mode has offline tests, not a new live-model success claim. [Chinese explanation](docs/learning/policy-exposure-report-boundary.zh-CN.md).

## Zero-network engineering demo

```bash
.venv/bin/python scripts/run_strict_offline_demo.py --output tmp/delivery-offline-demo
```

Use a fresh output path. Prepared local data are still required. Responses and review labels are fixtures, not real model answers or a quality benchmark. [Explanation](docs/experiments/phase-0126-offline-demo/README.zh-CN.md).

## Limitations and remaining work

The original plan included causal research, but this is no longer a product requirement. No accepted causal estimate is claimed, and descriptive changes must not be called tariff effects. This is currently a bounded prototype requiring scope and citation review, not an unattended production analyst.

The new-case live demo (`--exposure-demo`) obtained correct tool-derived amounts, but its economic interpretation failed review (unsupported supply/capacity claims). See the [Chinese review](docs/learning/policy-exposure-live-review.zh-CN.md). The local page now provides a bounded query/AI-demo entry and displays the sealed update pointer, but it does not make free economic interpretation reliable or collect data online. Remaining work includes evidence-bounded interpretation, cross-period comparability, limited task evaluation and broader policy coverage. Existing reports, page tests and tool tests do not complete these goals. No public deployment or publication is implied.

[Project plan](PROJECT_PLAN.md) · [Long-term context](docs/PROJECT_CONTEXT_REFERENCE.zh-CN.md) · [Historical README](README.history.md)
