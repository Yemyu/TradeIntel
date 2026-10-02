# TradeIntel

[中文](README.zh-CN.md) · [Examples](web/design-preview/cases/index.json) · [Model tests](docs/MODEL_SELECTION.md) · [Local setup](docs/LOCAL_RUN.zh-CN.md)

TradeIntel is a research assistant for U.S. goods trade. Ask about a product's imports or exports, compare monthly figures, and look up related policy notices. The model selects the tools; Python retrieves trade records, calculates comparisons, and builds reports with charts and source references.

There are two ways to explore the project: browse the four saved examples, or run the application locally and ask your own questions. The showcase does not require an API key. The local assistant uses your model provider's API; a separate data-only mode works without a model.

## Examples

| Example | What it shows |
|---|---|
| [Soybean trade](web/design-preview/cases/soybean-trade.json) | An import question followed by “What about exports?”, with reports for each direction |
| [Soybean oil](web/design-preview/cases/soybean-oil.json) | Distinguishing a processed product from raw soybeans |
| [Tungsten and solar materials](web/design-preview/cases/policy-materials.json) | An edited report combining a saved tariff notice and monthly import figures |
| [Missing month](web/design-preview/cases/missing-month.json) | Explaining unavailable data rather than substituting a different month |

The files above contain the saved examples. From the repository root, open them as conversations and charts with:

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory web/design-preview
```

Visit `http://127.0.0.1:8000/`. No trade-data bundle or API key is needed to read these saved examples. The first two contain model-assisted queries; the policy report is an edited explanation, and the missing-month example shows a program safeguard.

A typical local conversation starts with “How have recent U.S. soybean imports changed?” The assistant looks up the product, checks available dates, and queries the monthly data. You can then ask “What about exports?” without entering the product again. Report cards open charts, monthly amounts, and source notes; returning to the conversation keeps the context.

## Features

- **Product lookup:** search the official commodity catalog by name or code. Ambiguous names prompt a clarification rather than silently selecting a different product.
- **Trade queries:** view imports and exports separately, compare available months, and inspect all-partner totals or trade with China.
- **Follow-up questions:** change direction, product, partner, or date range in the same conversation.
- **Policy retrieval:** search registered local notices and retain their conditions and source references.
- **Reports:** read charts alongside calculated summaries, expand the monthly table, and print or save a PDF.
- **Data-only mode:** choose a scope manually and generate the same trade figures without an API key.

## How it works

The assistant uses a single tool-calling loop. A model searches the catalog, requests data, retrieves policy material when relevant, and selects the reports to return. Tools check product identifiers, dates, partners, and references before accepting a request.

Trade figures are not taken from model memory. Python reads prepared Census tables and calculates totals and changes. The current public report summaries also come from those calculations. Policy search uses lexical/BM25 retrieval over registered documents, including related conditions; it is not an unrestricted web search.

Reports and conversations are saved locally so they can be reopened. The model can decide what to query, but it cannot make missing values become zero or replace an unavailable month without the required confirmation. Historical causal research and earlier report-writing experiments remain in the repository; neither is a requirement of the current application.

## Run locally

You need the source code, Python, and the separate processed trade-data bundle. **A Git clone alone does not include that bundle.** It contains 124 files, approximately 579 MB uncompressed, and currently has no public download link. Obtain the bundle before attempting a trade query. Installation has been checked on macOS; Windows support has not been verified.

From the repository root, use the existing project environment or create one:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Unpack the data bundle into a new ignored directory, such as `.local/trade-data-bundle-1/`. The directory supplied below must contain both `BUNDLE_MANIFEST.json` and `data/`:

```bash
PYTHONPATH=src:. .venv/bin/python scripts/trade_demo_data_bundle.py verify --root .local/trade-data-bundle-1
.venv/bin/python scripts/run_web.py --trade-data-root .local/trade-data-bundle-1
```

Open `http://127.0.0.1:8765/preview/`. Keep the terminal running; Ctrl-C stops the server. If that port is occupied, pass a free port with `--port` rather than stopping another application.

In **Model settings**, select your provider, enter its supported model name and your API key, then save. Saving does not send a model request; **Test connection** does and may incur charges. Submit a question in the chat to use the assistant. Without a key, select **Data only** and confirm the product and dates yourself. Keys are stored by the local service, not embedded in the public showcase. MySQL is not needed for everyday web queries.

See the [detailed local guide](docs/LOCAL_RUN.zh-CN.md) for bundle verification, model settings, and operation. GitHub Pages can host the saved showcase, but cannot run this Python backend.

## Model tests

The tests check whether a model uses the tools to complete a task, handles unsupported requests correctly, and returns reports whose figures can be verified.

| Model / reasoning | Test channel | Normal tasks completed | Boundary cases handled | Saved reports verified |
|---|---|---:|---:|---:|
| GPT-6.1 Sol / Low | Codex chat bridge | 9/9 | 3/3 | 9/9 |
| GPT-6.1 Sol / Medium | Codex chat bridge | 9/9 | 3/3 | 10/10 |
| DeepSeek-V4.1 Flash / high | API | 8/9 | 2/3; one skipped | 14/14 |
| GPT-6 Luna / Max | Recovered Codex chat run | 7/9 | 2/3 | 8/8 |

These results use the current v3 tool protocol. Both Sol chat runs completed the task set; DeepSeek's policy task was incomplete. Luna's recovered run stopped at rubber clarification and did not deliver its tariff explanation in the public answer. Low saved both trade directions in one report; Medium saved two reports, so their report counts differ. The [test page](docs/MODEL_SELECTION.md) includes settings, checks, interruptions, and earlier GLM/DeepSeek/GPT results. GPT chat runs do not verify GPT API integration in this application.

## Data coverage

| Dataset | Included coverage |
|---|---|
| U.S. imports | 48 processed months: January 2016–May 2018 and January 2025–July 2026 |
| U.S. exports | August 2025–July 2026, 12 consecutive months |
| Products | Published commodity catalogs; not limited to the five policy-demo products |
| Partners | All origins/destinations combined, or China |
| Policies | Registered and enabled local documents |

The latest included month is July 2026. “Recent” refers to available data; a requested missing month is reported as unavailable. Import values use the imports-for-consumption measure, while exports use total exports on an FAS basis. They are displayed separately, not subtracted to claim a trade balance. Value changes do not by themselves establish changes in quantity, prices, or the effect of a policy.

## Documentation and project layout

| Location | Contents |
|---|---|
| `src/tradeintel_ai/` | Agent, query tools, validation, report storage, and local web service |
| `scripts/` | Data preparation, verification, server startup, and evaluation commands |
| `web/design-preview/` | Bilingual showcase, local chat, and report reader |
| `tests/` | Python and browser-DOM regression tests |
| `evals/` | Evaluation questions, contracts, and frozen reference material |
| `data/` | Source metadata and prepared data; large datasets are supplied separately |
| `docs/` | Setup, test results, data notes, and development history |

[Current functionality](docs/CURRENT_PRODUCT.zh-CN.md) · [Showcase guide](docs/PUBLIC_SHOWCASE.zh-CN.md) · [Model tests](docs/MODEL_SELECTION.md) · [Development records](docs/handoff/STATUS.zh-CN.md)

For targeted page and report tests (some Python tests need the publisher's local data and saved source records):

```bash
node --test tests/report_view.test.cjs tests/public_cases_ui.test.cjs tests/trade_explanation_ui.test.cjs tests/announcement_import_ui.test.cjs
PYTHONPATH=src:.:tests .venv/bin/python -m unittest test_chat_workspace_assets test_public_showcase test_trade_agent_report_view
```

Earlier README content is preserved in [the documentation archive](docs/history/README.before-public-edit-20261001.md).

See [Tests](docs/TESTING.md) for the current regression commands, local prerequisites, and known failures in the historical suite.
