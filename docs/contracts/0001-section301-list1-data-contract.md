# Data Contract 0001: Section 301 List 1

中文学习版：[`0001-section301-list1-data-contract.zh-CN.md`](0001-section301-list1-data-contract.zh-CN.md)

- Status: Draft for implementation
- Date: 2026-08-28
- Related decision: `docs/decisions/0001-initial-policy-case.md`

## 1. Goal

Build a traceable monthly dataset that links the official Section 301 List 1 policy definition to U.S. imports by product and origin country.

The first dataset must support this question without relying on an LLM to calculate the answer:

> After 6 July 2018, how did China's import value and import share change for List 1 products, and which other suppliers gained share?

## 2. Inputs

### Policy input

- Source: USTR/Federal Register Notice of Action dated 20 June 2018
- Official PDF: `https://ustr.gov/sites/default/files/2018-13248.pdf`
- Relevant content: Annex A, the 818 HTSUS tariff subheadings
- Policy origin: China
- Additional tariff rate: 25%
- Effective date: 2018-07-06
- Entry basis: Entered for consumption or withdrawn from warehouse for consumption

### Trade input

- Source: U.S. Census international trade data
- Dataset: Monthly U.S. imports by Harmonized System code and origin country
- Period: 2016-01 through 2019-12
- Preferred detail: HTS 10-digit
- Value measure: Monthly imports for consumption
- Coverage: All origin countries for affected products; dashboard views may later show only leading suppliers

The initial implementation should prefer official public bulk files so the project does not require the user's email address or an API key. The Census API can be added later as an incremental-update method.

## 3. Required outputs

### `policy_events`

| Field | Meaning |
|---|---|
| `policy_id` | Stable identifier, such as `us_301_list1_2018` |
| `policy_name` | Human-readable policy name |
| `importer` | United States |
| `target_origin` | China |
| `announcement_date` | 2018-06-15 |
| `effective_date` | 2018-07-06 |
| `additional_rate` | 0.25 |
| `source_url` | Official source |

### `policy_products`

| Field | Meaning |
|---|---|
| `policy_id` | Link to policy event |
| `raw_hts` | Code exactly as printed in the initial Annex A |
| `canonical_hts8` | Audited eight-digit code used for matching |
| `source_annex` | Annex A |
| `source_page` | PDF page containing the code |
| `amended` | Whether a later official notice corrected the printed code |
| `amendment_source_url` | Official correction source when applicable |
| `exclusion_status` | Initially `not_yet_modelled` |

### `trade_import_monthly`

| Field | Meaning |
|---|---|
| `year` / `month` | Observation period |
| `origin_code` / `origin_name` | Supplier country |
| `hts10` | Detailed U.S. import commodity code |
| `hts8` | First eight digits used to link policy scope |
| `import_value_consumption_usd` | Monthly import value entering consumption |
| `quantity_1` / `quantity_unit_1` | First quantity measure where available |
| `source_last_update` | Revision date supplied by the source |
| `source_file` | Exact downloaded source file |

### `analysis_panel`

| Field | Meaning |
|---|---|
| Product, country and month fields | Analysis key |
| `listed_in_list1` | Product appears in Annex A |
| `target_origin` | Origin is China |
| `post_effective_month` | Month is July 2018 or later |
| `scheduled_treatment` | Listed product × China × post period |
| `exclusion_modelled` | Whether exclusions have been incorporated |
| Import value, share and quantity fields | Analysis outcomes |

`scheduled_treatment` must not be presented as final effective tariff exposure until product exclusions are incorporated.

## 4. Rules

1. Preserve tariff codes as text so leading zeroes cannot disappear.
2. Preserve `raw_hts` exactly as printed and keep any official correction as a separate canonical field.
3. The initial Annex A entry `9033.00` must be corrected to `9033.00.90` using the official 16 August 2018 amendment; it must never be silently padded or guessed.
4. Derive `hts8` from the first eight characters of a valid 10-digit import code.
5. Store money as a numeric value in U.S. dollars and reject negative values.
6. Preserve raw source files unchanged and record download date plus checksum.
7. Do not silently drop malformed policy codes, unknown countries, missing values, or duplicate keys.
8. Keep revised source releases distinguishable from earlier downloads.
9. Do not mix general-import value and imports-for-consumption value under one field name.
10. Do not call a product a clean control until it has been checked against later tariff lists.
11. Do not make causal claims until exclusions, anticipation, comparison groups, and pre-trends have been examined.

## 5. Failure behaviour

- If the initial Annex A does not yield exactly 818 unique listed codes after excluding the implementation heading `9903.88.01`, stop and produce an extraction audit.
- If the only non-eight-digit entry is not `9033.00`, or the official amendment does not explicitly replace it with `9033.00.90`, stop rather than guessing a correction.
- If an HTS code has the wrong length or contains non-digits, retain the raw text in an error report and exclude it from joins.
- If a monthly source file is missing, mark that month incomplete rather than treating it as zero trade.
- If value fields fail numeric conversion, report the source file and row identifier.
- If duplicate product-country-month rows remain after expected aggregation, stop the panel build and report the duplicate dimensions.
- If source classifications change across years, require an explicit concordance decision.

## 6. Acceptance checks

The first implementation is accepted only when:

1. Initial Annex A produces 818 unique listed codes: 817 eight-digit entries plus the documented `9033.00` exception.
2. The official amendment is verified and produces a canonical list of 818 unique eight-digit codes by replacing `9033.00` with `9033.00.90`.
3. Policy rate and effective date match the official notice.
4. All 48 months from January 2016 through December 2019 are represented or explicitly marked missing.
5. Monetary values are numeric and non-negative.
6. Every processed row points back to an exact source file and retrieval record.
7. Product-country-month keys are unique at the declared aggregation level.
8. At least one independent aggregate total is reconciled against the official source within a documented tolerance.
9. Automated tests cover policy-code parsing, date boundaries, code matching, duplicate detection, and missing-month behaviour.
10. The data-quality report distinguishes zero trade, missing data, invalid data, and suppressed data where applicable.
11. No secret or API key appears in Git or generated output.

## 7. AI implementation instruction

AI should implement the pipeline in small auditable steps:

1. Download and fingerprint the official policy notice.
2. Extract Annex A codes and create an extraction audit.
3. Obtain and inventory the official monthly import source files.
4. Parse raw fields without modifying the source files.
5. Validate schema, types, codes, coverage, and duplicates.
6. Build the policy-to-import mapping.
7. Produce the analysis panel and data-quality report.
8. Run automated acceptance checks before loading curated tables into MySQL.

Each step must write a machine-readable manifest and must be runnable without an LLM.
