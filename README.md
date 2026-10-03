# TradeIntel — International trade research assistant

**🌐 English** | [🇨🇳 简体中文](README.zh-CN.md)

[Demo](https://yemyu.github.io/TradeIntel/?lang=en) · [📊 Sample report](https://yemyu.github.io/TradeIntel/?case=policy-materials&report=r1&lang=en#report) · [Quickstart](#quickstart) · [Model tests](docs/MODEL_SELECTION.md) · [Data download](https://github.com/Yemyu/TradeIntel/releases/tag/showcase-20261002)

TradeIntel is an open-source agent for trade research. Ask about a product by name or code, look up trade data and related policy documents, and follow up about a different direction, partner, or period.

The current release includes U.S. import and export data, with all-partner totals and China-specific queries. The latest included month is July 2026; the coverage table below lists the date ranges.

The model interprets questions, carries context into follow-ups, and uses tool results to decide what to query next. Python validates the query scope and data, calculates the figures, and generates reports with charts and sources.

The public website contains four saved examples. To ask your own questions, run the application locally and configure your model provider's API. A data-only mode lets you choose a scope and read the same trade figures without a model.

## Features

- **Product lookup:** search the official commodity catalog by name or code. Ambiguous names prompt a clarification rather than silently selecting a different product.
- **Trade queries:** view imports and exports separately, compare available months, and inspect all-partner totals or trade with China.
- **Follow-up questions:** change direction, product, partner, or date range in the same conversation.
- **Policy retrieval:** search registered local notices and retain their conditions and source references.
- **Reports:** read charts alongside calculated summaries, expand the monthly table, and print or save a PDF.
- **Data-only mode:** choose a scope manually and generate the same trade figures without an API key.

## Demo

| Example | What it shows |
|---|---|
| [Soybean trade](https://yemyu.github.io/TradeIntel/?lang=en&case=soybean-trade#cases) | An import question followed by “What about exports?”, with reports for each direction |
| [Soybean oil](https://yemyu.github.io/TradeIntel/?lang=en&case=soybean-oil#cases) | Distinguishing a processed product from raw soybeans |
| [Tungsten and solar materials](https://yemyu.github.io/TradeIntel/?lang=en&case=policy-materials#cases) | An edited report combining a saved tariff notice and monthly import figures |
| [Missing month](https://yemyu.github.io/TradeIntel/?lang=en&case=missing-month#cases) | Explaining unavailable data rather than substituting a different month |

The links open saved conversations and charts. The public website makes no model request and is not an online chat service. To read these examples from a clone:

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory web/design-preview
```

Visit `http://127.0.0.1:8000/`. No trade-data bundle or API key is needed to read these saved examples. The first two contain model-assisted queries; the policy report is an edited explanation, and the missing-month example shows a program safeguard.

A typical local conversation starts with “How have recent U.S. soybean imports changed?” The assistant looks up the product, checks available dates, and queries the monthly data. You can then ask “What about exports?” without entering the product again. Report cards open charts, monthly amounts, and source notes; returning to the conversation keeps the context.

## Quickstart

You need Python 3.12, the source code, and the separate [processed trade-data bundle](https://github.com/Yemyu/TradeIntel/releases/tag/showcase-20261002). The bundle contains 124 data files, about 579 MB uncompressed; the ZIP is about 64 MiB. **Cloning the repository does not download it.** Local installation has been checked on macOS; Windows has not been verified.

From the repository root, use the existing project environment or create one:

```bash
git clone https://github.com/Yemyu/TradeIntel.git
cd TradeIntel
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Download `trade-demo-data-20260927-isolated-v2.zip` from the Release and check its SHA-256:

```text
1ec80a664972fe8e1d3da212d975aa760bd62319b87ff00caaa0cb8ed90433e6
```

Replace `/path/to/` in the command below with the download location. Continue only if bundle verification returns `"status": "verified"`.

Unpack the data bundle into a new ignored directory, such as `.local/trade-data-bundle-1/`. The directory supplied below must contain both `BUNDLE_MANIFEST.json` and `data/`:

```bash
mkdir -p .local
unzip /path/to/trade-demo-data-20260927-isolated-v2.zip -d .local/trade-data-bundle-1
PYTHONPATH=src:. .venv/bin/python scripts/trade_demo_data_bundle.py verify --root .local/trade-data-bundle-1
.venv/bin/python scripts/run_web.py --trade-data-root .local/trade-data-bundle-1
```

Open `http://127.0.0.1:8765/preview/`. Keep the terminal running; Ctrl-C stops the server. If that port is occupied, pass a free port with `--port` rather than stopping another application.

In **Model settings**, select your provider, enter its supported model name and your API key, then save. Saving does not send a model request; **Test connection** does and may incur charges. Submit a question in the chat to use the assistant. Without a key, select **Data only** and confirm the product and dates yourself. Keys are stored by the local service, not embedded in the public showcase. MySQL is not needed for everyday web queries.

See the [local guide](docs/LOCAL_RUN.md) for bundle verification, model settings, and operation. GitHub Pages can host the saved showcase, but cannot run this Python backend.

## Model tests

The tests check whether a model uses the tools to complete a task, handles unsupported requests correctly, and returns reports whose figures can be verified.

| Model / reasoning | Normal tasks completed | Boundary cases handled | Saved reports verified |
|---|---:|---:|---:|
| GPT-6.1 Sol / Low | 9/9 | 3/3 | 9/9 |
| GPT-6.1 Sol / Medium | 9/9 | 3/3 | 10/10 |
| DeepSeek-V4.1 Flash / high | 8/9 | 2/3; one skipped | 14/14 |
| GLM-5.3-Flash / High | 8/9 | 2/3; R06 program precheck, P02 skipped | 10/10 |
| GPT-6 Luna / Max | 7/9 | 2/3 | 8/8 |

Each run planned nine normal tasks and three boundary cases. Both Sol configurations completed the set. DeepSeek and GLM did not deliver the tungsten policy report; GLM's dependent tariff follow-up was skipped. Luna stopped for clarification on natural rubber and omitted the tariff explanation. A task can produce more than one report, so report counts differ. Skipped tasks are not counted as either model failures or successes. See [Model tests](docs/MODEL_SELECTION.md) for the questions, scoring criteria, settings, and issues.

## Data coverage

| Dataset | Included coverage |
|---|---|
| U.S. imports | 48 processed months: January 2016–May 2018 and January 2025–July 2026 |
| U.S. exports | August 2025–July 2026, 12 consecutive months |
| Products | Published commodity catalogs; not limited to the five policy-demo products |
| Partners | All origins/destinations combined, or China |
| Policies | Registered and enabled local documents |

The latest included month is July 2026. “Recent” refers to available data; a requested missing month is reported as unavailable. Import values use the imports-for-consumption measure, while exports use total exports on an FAS basis. They are displayed separately, not subtracted to claim a trade balance. Value changes do not by themselves establish changes in quantity, prices, or the effect of a policy.

The current version starts with U.S. import and export data. Future work may add datasets from China and other countries, after collecting the data and checking product classifications and statistical definitions.

## How it works

The assistant uses a single tool-calling loop rather than a fixed query form:

1. The model interprets the product, direction, partner, and dates, using the previous turn when answering a follow-up.
2. It checks the catalog and available dates, then calls trade or policy tools. The tools retrieve records, validate the scope, and calculate the figures.
3. The model reads the returned results and decides whether to query further, ask about genuine ambiguity, or finish with reports and references from this turn.
4. The program validates the report references, saves the result, and displays charts, summaries, exact values, and sources.

Step 3 can return to step 2. For example, an import query may be followed by an export query or a search for a related policy notice. The model selects which reports to return; the program determines the primary report for display.

Trade figures are not taken from model memory. Python reads prepared Census tables and calculates totals and changes. The current public report summaries also come from those calculations. Policy search uses lexical/BM25 retrieval over registered documents, including related conditions; it is not an unrestricted web search.

Reports and conversations are saved locally so they can be reopened. The model can decide what to query, but it cannot make missing values become zero or replace an unavailable month without the required confirmation.

MySQL is used in data engineering and verification; everyday web queries read verified data files and need no database server.

## Documentation

| Location | Contents |
|---|---|
| `src/tradeintel_ai/` | Agent, query tools, validation, report storage, and local web service |
| `scripts/` | Data preparation, verification, server startup, and evaluation commands |
| `web/design-preview/` | Bilingual showcase, local chat, and report reader |
| `tests/` | Python and browser-DOM regression tests |
| `evals/` | Evaluation questions, contracts, and frozen reference material |
| `data/` | Source metadata and prepared data; large datasets are supplied separately |
| `docs/` | Setup, test results, and data notes |

[Current functionality](docs/CURRENT_PRODUCT.zh-CN.md) · [Showcase guide](docs/PUBLIC_SHOWCASE.zh-CN.md) · [Model tests](docs/MODEL_SELECTION.md)

For targeted page and report tests (some Python tests need the publisher's local data and saved source records):

```bash
node --test tests/report_view.test.cjs tests/public_cases_ui.test.cjs tests/trade_explanation_ui.test.cjs tests/announcement_import_ui.test.cjs
PYTHONPATH=src:.:tests .venv/bin/python -m unittest test_chat_workspace_assets test_public_showcase test_trade_agent_report_view
```

See [Tests](docs/TESTING.md) for regression commands and local prerequisites.
