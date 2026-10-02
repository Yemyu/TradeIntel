# Local guide

**English** | [简体中文](LOCAL_RUN.zh-CN.md)

[Project](../README.md) · [Model tests](MODEL_SELECTION.md) · [Data download](https://github.com/Yemyu/TradeIntel/releases/tag/showcase-20261002)

Reading the public examples needs no installation. To ask your own questions, start the local service and configure your model API key. Data-only queries need no model or MySQL.

## Source and data

Use Python 3.12 and the current main branch. Installation was verified on macOS; the report store uses POSIX file interfaces, and Windows has not been verified.

```bash
git clone https://github.com/Yemyu/TradeIntel.git
cd TradeIntel
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Reuse the project's existing environment if already installed; do not install into system Python. The [Release](https://github.com/Yemyu/TradeIntel/releases/tag/showcase-20261002) supplies `trade-demo-data-20260927-isolated-v2.zip`: about 64 MiB compressed, 579 MB uncompressed. Its manifest lists 124 data files; the ZIP also contains the manifest and a short Chinese guide. The old name TradeShock in that guide refers to this project.

SHA-256:

```text
1ec80a664972fe8e1d3da212d975aa760bd62319b87ff00caaa0cb8ed90433e6
```

On macOS, run `shasum -a 256 /path/to/trade-demo-data-20260927-isolated-v2.zip` and compare. Extract to a new directory rather than overwriting earlier data:

```bash
mkdir -p .local
unzip /path/to/trade-demo-data-20260927-isolated-v2.zip -d .local/trade-data-bundle-1
PYTHONPATH=src:. .venv/bin/python scripts/trade_demo_data_bundle.py verify --root .local/trade-data-bundle-1
```

Continue only if verification returns `"status": "verified"`. The data-root directory contains both `BUNDLE_MANIFEST.json` and `data/`, not just the inner `data/` folder. The bundle includes no source code, raw Census ZIPs, model keys, MySQL database or policy-document database. Verification makes no network or model request.

## Start the application

```bash
.venv/bin/python scripts/run_web.py --trade-data-root .local/trade-data-bundle-1
```

Open `http://127.0.0.1:8765/preview/`. Keep the terminal running; Ctrl-C stops the service. If the port is in use, choose another:

```bash
.venv/bin/python scripts/run_web.py --port 8898 --trade-data-root .local/trade-data-bundle-1
```

That opens at `http://127.0.0.1:8898/preview/`. Do not stop another application to free its port. The service listens only locally by default and should not simply be exposed to the internet.

## Model settings

Open **Model settings** in the chat workspace:

1. Select the platform that issued your key. Use a model name it actually supports; a Codex display name is not necessarily an API model identifier.
2. Choose a preset or enter a custom model. Reasoning options depend on the provider.
3. Enter your API key and save. The local service stores it; the public website does not. You can keep a key when switching models on the same provider, but changing providers requires a new key.
4. Optionally use **Test connection**. It sends a short request and may cost money; success verifies that request, not every future answer.

Saving settings, browsing examples and reopening reports send no model request. Assistant questions send the question and tool results to your configured provider and are billed under its rules.

## Questions and reports

Start with “How have recent U.S. soybean imports changed?”, then ask “What about exports?”. Use **Send** or Enter; Shift+Enter inserts a newline. Report cards open charts and monthly values; return to chat to continue.

To change products, ask “Switch to soybean oil imports”. Ambiguous names or scopes require clarification. In **Data only**, you confirm the product, direction and dates yourself; no model key or MySQL connection is required.

Conversations and reports survive a refresh. Opening examples, reports or the other language does not resubmit a question. Moving between views retains an unsent draft; a full refresh does not save that draft.

## Data and troubleshooting

- **How recent is the data?** The latest month is July 2026. Imports have 48 non-contiguous months; exports cover August 2025–July 2026. This is not a real-time feed.
- **What if a requested month is missing?** The app explains the gap. Request a different month explicitly; it does not silently substitute the latest one.
- **Does an amount show quantity?** No. Values can change with quantity and prices; the report does not directly infer a policy's effect.
- **The service will not start.** Check the data-root directory, verification and port. Do not rewrite a manifest or delete original data to bypass checks.
- **A model request failed.** Check the endpoint, model name and key. Unknown outcomes are not automatically retried, to avoid duplicate charges.
- **A new bundle is available.** Extract to a new directory, verify, then change the startup parameter. Keep the old version.
- **Why is there no policy result?** Only registered and enabled notices are searchable. The trade bundle does not supply a complete policy corpus; an edited showcase report is not a newly registered document.

[macOS installation record (Chinese)](handoff/runs/20260927-FULL-INSTALL-QA.zh-CN.md) · [Public website](https://yemyu.github.io/TradeIntel/?lang=en)
