# Public showcase

[🇨🇳 简体中文](PUBLIC_SHOWCASE.zh-CN.md) · [Project](../README.md) · [Quickstart](LOCAL_RUN.md)

The [public website](https://yemyu.github.io/TradeIntel/?lang=en) presents the project, saved exchanges, query steps, and charted reports. Switching languages keeps the selected case and report. Run the local application to ask your own questions; browsing the showcase sends no new model request.

## Examples

| Example | What it shows | Record type |
|---|---|---|
| Soybean imports, then exports | Follow-up questions with separate import and export reports | Saved model-assisted queries |
| Soybean oil imports | Product lookup for soybean oil, code 1507, and twelve months of import data | Saved model-assisted query |
| Tungsten and solar materials | Notice background, import values, and China-origin shares for five product codes | Report compiled from saved material |
| The requested month is not available | August is unavailable; the program blocks a query substituted for July | Missing-data record |

English exchanges correspond to the saved Chinese records. Reports retain products, dates, values, and sources; the policy report also lists its compilation date. See [Model tests](MODEL_SELECTION.md) for results across configurations.

## Preview from a clone

From the repository root:

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory web/design-preview
```

Open `http://127.0.0.1:8000/` to read exported cases without the trade-data bundle. New queries, conversation storage, and model settings require the local Python service described in Quickstart.

## GitHub Pages build

Pages builds the website from checked-in public examples using the Python standard library. CI uses Python 3.12. No model key, private sessions, or trade-data bundle is required. Choose an output directory that does not exist:

```bash
PYTHONPATH=src:.:tests python3 -S -m unittest test_github_pages_build
PYTHONPATH=src:. python3 -S scripts/build_github_pages.py --output tmp/pages-build/site
PYTHONPATH=src:. python3 -S scripts/build_github_pages.py --verify tmp/pages-build/site
```

`.github/workflows/pages.yml` deploys 14 allowlisted static assets. The build checks case structure, report scope, and calculations; it does not replace verification against source records. The online showcase excludes the question form, model settings, keys, and local sessions.

## Export from source records

Maintainers use `scripts/build_public_showcase.py` to export cases from locally saved source records. This requires those records and is not a visitor setup step:

```bash
PYTHONPATH=src:. .venv/bin/python scripts/build_public_showcase.py --output tmp/showcase-check/site
PYTHONPATH=src:. .venv/bin/python scripts/build_public_showcase.py --verify tmp/showcase-check/site
PYTHONPATH=src:. .venv/bin/python scripts/serve_public_showcase_qa.py --site tmp/showcase-check/site
```

Use `http://127.0.0.1:8897/TradeIntel/preview/` to check pages and assets under the repository subpath. Audit files are saved beside the output directory and are not published. The exporter refuses to overwrite an existing output directory.

PDFs are generated with the browser's print function. The existing [print check record (Chinese)](handoff/runs/20261001-U2-PRINT-PDF.zh-CN.md) and [test guide](TESTING.md) describe checks that have been performed.
