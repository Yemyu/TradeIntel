# Features and data coverage

[🇨🇳 简体中文](CURRENT_PRODUCT.zh-CN.md) · [Project](../README.md) · [Quickstart](LOCAL_RUN.md)

TradeIntel queries trade data and policy documents through a conversation, then saves the results as charted reports. The current version includes U.S. imports and exports, with all-partner totals and China-specific queries.

## Queries and follow-ups

Ask about a product by name or code, such as “How have recent U.S. soybean imports changed?” The assistant looks up the product, checks available months, and queries the values. “What about exports?” keeps the product context and changes direction. Switching to another product, such as soybean oil, triggers a new catalog lookup.

Report cards open monthly charts, the latest value, supported month-to-month comparisons, exact-value tables, and sources. Conversations and reports are saved locally and can be reopened. Reports can be printed or saved as PDFs.

## Model and program roles

The model identifies the product, direction, partner, and dates; calls catalog, trade, and policy tools; reads their results; and decides whether to query further, clarify the scope, or finish.

Query tools read prepared official data, validate the scope, and calculate values. The program generates summaries and charts, checks report references, and saves the result. Current reports use these calculations and retrieved evidence rather than free-form economic analysis written by the model. See [Model tests](MODEL_SELECTION.md) for completion results across configurations.

Policy retrieval uses keywords, BM25, and code matching over registered, enabled local documents and their related conditions. It does not collect notices from across the web. Whether a policy applies to a particular product still requires checking the notice's terms.

## Data coverage

| Dataset | Included coverage |
|---|---|
| U.S. imports | Jan 2016–May 2018 and Jan 2025–Jul 2026: 48 months in two non-contiguous ranges |
| U.S. exports | Aug 2025–Jul 2026: 12 consecutive months |
| Products | Published official commodity catalogs |
| Partners | All origins/destinations combined, or China |
| Policies | Registered and enabled local documents |

China is a partner in U.S. statistics. The current source is the U.S. Census Bureau; no separate Chinese customs dataset is included.

The latest included month is July 2026. “Recent” uses available data. A request for an unavailable month returns a gap notice; using another month requires confirmation. Missing values remain unknown rather than being replaced with zero.

Imports use imports-for-consumption values; exports use total exports on an FAS basis and are displayed separately. A change in value alone does not establish a change in quantity or price, or the effect of a policy.

Future extensions may add China and other countries. Each new source requires data collection and checks of commodity classifications, dates, and statistical definitions.

## Access

- [Public showcase](https://yemyu.github.io/TradeIntel/?lang=en): browse four saved examples and reports in English or Chinese.
- Local application: follow [Quickstart](LOCAL_RUN.md), download the data bundle, start the service, and configure a GLM, DeepSeek, or Qianwen API.
- Data-only mode: confirm a product and dates manually to generate the same data reports without a model key.

Use the `main` branch. The trade-data bundle is supplied separately through the [Release](https://github.com/Yemyu/TradeIntel/releases/tag/showcase-20261002). See [Data notes](../data/README.md) for coverage and sources.

[Showcase guide](PUBLIC_SHOWCASE.md) · [Model tests](MODEL_SELECTION.md) · [Tests](TESTING.md)
