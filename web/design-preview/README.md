# Web interface

**English** | [简体中文](README.zh-CN.md)

This directory contains the shared HTML, CSS, and JavaScript for the bilingual project showcase, local chat workspace, and chart reports. The public website reads four saved examples; the local service enables questions with a user-configured model or data-only queries. See the [local guide](../../docs/LOCAL_RUN.md) for installation and model settings.

## Files

| File | Purpose |
|---|---|
| `index.html`, `style.css` | Page structure and styling |
| `app.js` | Navigation, language switching, globe, and the fixed policy chart |
| `live.js` | Local workspace, model settings, and backend requests |
| `report-view.js` | Shared report rendering and printing |
| `cases.js`, `cases/index.json`, `cases/*.json` | Four exported examples and their catalog |
| `data.json` | Saved import figures for five policy-example products, February–July 2026 |
| `vendor/` | Bundled globe dependency and license notices |

## Preview the public build

From the repository root, using Python 3.12:

```bash
PYTHONPATH=src:. python3 -S scripts/build_github_pages.py --output tmp/pages-preview/site
PYTHONPATH=src:. python3 -S scripts/build_github_pages.py --verify tmp/pages-preview/site
python3 -m http.server 8790 --bind 127.0.0.1 --directory tmp/pages-preview/site
```

Open [http://127.0.0.1:8790/](http://127.0.0.1:8790/). Choose a new output directory if the previous one already exists. The portable builder uses the standard library and checked-in examples, validates the public asset allowlist, and removes the local workspace and `live.js` from the output. It does not need private sessions, a trade-data bundle, or model credentials. The [Pages workflow](../../.github/workflows/pages.yml) uses this same builder.

To check the build and interface:

```bash
PYTHONPATH=src:.:tests python3 -S -m unittest test_github_pages_build
node --test tests/*.test.cjs
```

The Node checks use DOM fixtures; see [testing](../../docs/TESTING.md) for the scope and prerequisites.

## Run the local workspace

After preparing and verifying the trade-data bundle as described in the local guide:

```bash
.venv/bin/python scripts/run_web.py --trade-data-root .local/trade-data-bundle-1
```

Open [http://127.0.0.1:8765/preview/](http://127.0.0.1:8765/preview/). The local backend serves this interface and executes queries. Saved-example views do not submit new questions; assistant questions use the configured provider. Data-only mode works without a model key or MySQL.

## Components and data

The globe uses the bundled [COBE 0.6.5 module](https://esm.sh/cobe@0.6.5/es2022/cobe.bundle.mjs). Preserve [COBE's license](vendor/COBE-LICENSE) and [Phenomenon's license](vendor/PHENOMENON-LICENSE) when distributing the assets. The page loads the module locally. Layouts and SVG report charts are implemented in this project; the globe is a visual illustration, not a measured trade-flow map.

The checked-in case files and `data.json` are already exported. Rebuilding the original exports requires their saved source records; it is separate from the portable Pages build. See the [data guide](../../data/README.md) for current coverage, sources, and download instructions.
