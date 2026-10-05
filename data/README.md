# Data

**English** | [简体中文](README.zh-CN.md)

[Project](../README.md) · [Local guide](../docs/LOCAL_RUN.md) · [Data download](https://github.com/Yemyu/TradeIntel/releases/tag/showcase-20261002)

The local application uses processed U.S. Census import and export data. The current Release supplies 124 data files separately from the source repository: 48 import monthly tables, 12 export monthly tables, 60 product-classification indexes, three manifests, and a Chinese product-search index.

## Coverage and definitions

| Dataset | Available months | Classification and value |
|---|---|---|
| U.S. imports | January 2016–May 2018 and January 2025–July 2026: 48 non-contiguous months | HTS10; imports for consumption, USD |
| U.S. exports | August 2025–July 2026: 12 continuous months | Schedule B10; total exports on the FAS basis, USD |
| Trading partners | All origins/destinations combined, or China | China is a partner in U.S. statistics, not a China Customs reporting dataset |

Product search uses the published monthly classifications and is not limited to the showcase examples. Import and export classifications and value definitions differ; the application displays them separately rather than subtracting them as a trade balance. Missing months remain missing. Changes in value describe trade activity and do not establish changes in quantity, prices, or the causal effect of a policy.

## Download and verify

Download `trade-demo-data-20260927-isolated-v2.zip` from the [Release](https://github.com/Yemyu/TradeIntel/releases/tag/showcase-20261002). It is about 64 MiB compressed and 579 MB uncompressed. The ZIP also includes `BUNDLE_MANIFEST.json` and a short Chinese guide.

SHA-256:

```text
1ec80a664972fe8e1d3da212d975aa760bd62319b87ff00caaa0cb8ed90433e6
```

Follow the [local guide](../docs/LOCAL_RUN.md) to extract the ZIP into a new directory. From the repository root, using the project environment:

```bash
PYTHONPATH=src:. .venv/bin/python scripts/trade_demo_data_bundle.py verify --root .local/trade-data-bundle-1
```

Continue only when verification returns `"status": "verified"`. The data-root directory must contain both `BUNDLE_MANIFEST.json` and `data/`. Verification checks the manifest, allowed paths, file sizes, digests, and dataset versions without downloading data or calling a model. Everyday queries read files and do not require MySQL. The bundle contains no application code, model credentials, raw Census ZIPs, or complete policy-document database.

## Sources and directory layout

The monthly manifests record official source URLs and archive digests. Published processed-file digests and classification versions support reproducible queries.

| Location | Contents |
|---|---|
| [processed/trade_hts10/manifest.json](processed/trade_hts10/manifest.json) | Census import sources; processed HTS10 monthly tables are supplied in the Release |
| [processed/trade_scheduleb10/manifest.json](processed/trade_scheduleb10/manifest.json) | Census export sources, monthly table paths, and digests |
| [processed/trade_classification/manifest.json](processed/trade_classification/manifest.json) | Monthly product classifications bound to import/export versions |
| `processed/policy/`, `processed/policy_exposure/` | Registered policy-case metadata, outputs, and version records |
| `processed/analysis/`, `processed/causal/`, `candidates/` | Earlier research outputs and candidate-case records; some remain dependencies of existing tools or tests |
| `raw/` | Local source material; raw archives are excluded from the trade-data Release |
| `sample/` | Synthetic teaching sample, separate from observed trade data |

Official archive examples: [July 2026 imports](https://www.census.gov/trade/downloads/2026/Merch/im_m/IMDB2607.ZIP) and [July 2026 exports](https://www.census.gov/trade/downloads/2026/Merch/ex_m/EXDB2607.ZIP). Full monthly source references are in the manifests above.

Policy retrieval uses registered and enabled documents. The trade-data bundle does not supply a complete policy corpus or prove which individual transactions are subject to a notice. Earlier matching and causal-study records document past research; causal identification is not a current application feature. Keep source records and version digests intact when maintaining the data, and verify a new bundle before changing the application's data-root parameter.
