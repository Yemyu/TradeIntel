# Documentation

[🇨🇳 简体中文](README.zh-CN.md) · [Project](../README.md)

## Using TradeIntel

| Guide | Contents |
|---|---|
| [Local setup](LOCAL_RUN.md) | Environment, data download, model settings, and startup |
| [Features and coverage](CURRENT_PRODUCT.md) | Queries, follow-ups, reports, and supported data |
| [Public showcase](PUBLIC_SHOWCASE.md) | Saved examples, static preview, and Pages build |
| [Model tests](MODEL_SELECTION.md) | Fixed scenarios, results, settings, and scoring |
| [Engineering tests](TESTING.md) | Test commands and required local files |
| [Data notes](../data/README.md) | Data bundle, statistical measures, and source files |
| [Frontend](../web/design-preview/README.md) | Page assets, report rendering, and build commands |

## Technical references

- `contracts/`: output formats and validation rules.
- `evaluation/` and `../evals/`: evaluation criteria, questions, and reference material.
- `releases/`: published data-bundle metadata and file checksums.
- `decisions/`, `diagnostics/`, and `experiments/`: technical records for individual implementations and experiments. Their dates and results refer to those runs, not to current installation steps.
- Retained files in `handoff/` are source protocols and verification records referenced by evaluation scripts or published results. They are not a setup guide.

Start with the guides above for the current application. Some experimental files are read by code or tests and remain at their existing paths to preserve source references and frozen evidence.
