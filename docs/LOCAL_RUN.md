# Local guide

**English** | [简体中文](LOCAL_RUN.zh-CN.md)

[Project](../README.md) · [Features and coverage](CURRENT_PRODUCT.md) · [Model tests](MODEL_SELECTION.md) · [Data download](https://github.com/Yemyu/TradeIntel/releases/tag/showcase-20261002)

Reading the public examples needs no installation. To ask your own questions, start the local service and configure your model API key. Data-only mode generates reports without a model key.

## First installation

Python 3.13 is recommended. The [full installation record](handoff/runs/20260927-FULL-INSTALL-QA.zh-CN.md) used macOS and Python 3.13.3. Session and report storage requires the POSIX `fcntl` module, so native Windows is not supported.

Clone the current main branch and create a project environment. Both version checks should show Python 3.13.x:

```bash
git clone https://github.com/Yemyu/TradeIntel.git
cd TradeIntel
python3.13 --version
python3.13 -m venv .venv
.venv/bin/python --version
.venv/bin/python -m pip install -r requirements.txt
```

Download `trade-demo-data-20260927-isolated-v2.zip` from the [Release](https://github.com/Yemyu/TradeIntel/releases/tag/showcase-20261002). It contains 124 processed data files, about 64 MiB compressed and 579 MB uncompressed. Cloning the repository does not download this bundle. The ZIP also includes `BUNDLE_MANIFEST.json` and a short Chinese guide; it contains no source code, raw Census ZIPs, model keys, MySQL database, or policy-document database.

Replace `/path/to/` with your download location. On macOS, check the ZIP's SHA-256:

```bash
shasum -a 256 "/path/to/trade-demo-data-20260927-isolated-v2.zip"
```

The digest must match:

```text
1ec80a664972fe8e1d3da212d975aa760bd62319b87ff00caaa0cb8ed90433e6
```

From the repository root, extract to a new directory under `.local/`, which Git ignores, then verify:

```bash
mkdir -p .local
unzip "/path/to/trade-demo-data-20260927-isolated-v2.zip" -d ".local/trade-data-bundle-1"
PYTHONPATH=src:. .venv/bin/python scripts/trade_demo_data_bundle.py verify --root ".local/trade-data-bundle-1"
```

Continue after verification returns `"status": "verified"`. The `--root` and `--trade-data-root` arguments point to the directory containing both `BUNDLE_MANIFEST.json` and `data/`. An already extracted bundle can be used directly with the same verification step. Verification runs offline.

## Start the application

```bash
.venv/bin/python scripts/run_web.py --trade-data-root ".local/trade-data-bundle-1"
```

Open `http://127.0.0.1:8765/preview/`. Keep the terminal running; Ctrl-C stops the service. If the port is in use, choose another:

```bash
.venv/bin/python scripts/run_web.py --port 8898 --trade-data-root ".local/trade-data-bundle-1"
```

That opens at `http://127.0.0.1:8898/preview/`. The service is intended for local use and listens on `127.0.0.1` by default.

## Model settings

Open **Model settings** in the chat workspace:

1. Select Zhipu GLM, DeepSeek, or Qianwen, matching the platform that issued your key.
2. Choose a preset or enter a model ID supported by that platform. The page currently provides reasoning settings for DeepSeek.
3. Enter your API key and save. The local service stores it; the public website does not. You can keep a key when switching models on the same provider, but changing providers requires a new key.
4. Optionally use **Test connection**. It sends a short request and may incur provider charges. A successful connection test checks connectivity; report quality is evaluated separately.

Saving settings, browsing examples and reopening reports send no model request. Assistant questions send the question and tool results to your configured provider and are billed under its rules.

The GPT results in [Model tests](MODEL_SELECTION.md) came from Codex chats; they do not establish GPT API support in this application.

## Questions and reports

Start with “How have recent U.S. soybean imports changed?”, then ask “What about exports?”. Use **Send** or Enter; Shift+Enter inserts a newline. Report cards open charts and monthly values; return to chat to continue.

To change products, ask “Switch to soybean oil imports”. Ambiguous names or scopes require clarification. In **Data only**, you confirm the product, direction and dates yourself; no model key is required.

Conversations and reports survive a refresh. Opening examples, reports or the other language does not resubmit a question. Moving between views retains an unsent draft; a full refresh does not save that draft.

## View saved examples

The [public website](https://yemyu.github.io/TradeIntel/?lang=en) opens the four saved conversations and charts without installation. To view them from a clone, run this from the repository root:

```bash
python3.13 -m http.server 8000 --bind 127.0.0.1 --directory web/design-preview
```

Open `http://127.0.0.1:8000/`. This static preview needs no trade-data bundle or API key. It displays saved examples; your own questions use the local application described above.

## Maintaining an existing installation

Reuse the project's `.venv` and check its interpreter with `.venv/bin/python --version`. When `requirements.txt` changes, update that environment with `.venv/bin/python -m pip install -r requirements.txt`.

For a new data bundle, extract to a new directory, verify it, then restart with `--trade-data-root` pointing to that directory. Keep the previous bundle for rollback.

The GitHub Pages CI uses Python 3.12 for a static build with the standard library. That check is separate from the full local installation record using Python 3.13.3.

## Data and troubleshooting

- **How recent is the data?** The latest month is July 2026. Imports have 48 non-contiguous months; exports cover August 2025–July 2026. This is not a real-time feed.
- **What if a requested month is missing?** The app explains the gap. Request a different month explicitly; it does not silently substitute the latest one.
- **Does an amount show quantity?** No. Values can change with quantity and prices; the report does not directly infer a policy's effect.
- **The service will not start.** Check the data-root directory, the verification result, and the port. If bundle verification fails, check the ZIP's digest and extract a fresh copy to a new directory.
- **A model request failed.** Check the endpoint, model name and key. Unknown outcomes are not automatically retried, to avoid duplicate charges.
- **Why is there no policy result?** Only registered and enabled notices are searchable. The trade bundle does not supply a complete policy corpus; an edited showcase report is not a newly registered document.

[macOS installation record (Chinese)](handoff/runs/20260927-FULL-INSTALL-QA.zh-CN.md) · [Showcase guide](PUBLIC_SHOWCASE.md) · [Public website](https://yemyu.github.io/TradeIntel/?lang=en)
