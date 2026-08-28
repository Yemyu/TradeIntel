# Decision 0001: Initial Policy Case

- Status: Accepted
- Date: 2026-08-28
- Decision owner: Project team

## Decision

The first validated case will be the **United States Section 301 List 1 tariff action on imports from China**, effective 6 July 2018.

The initial research question is:

> After the 25% List 1 tariff took effect, did China's share of affected U.S. imports fall beyond its pre-policy pattern, and which alternative suppliers gained import share?

This is the historical validation case. Recent 2024–2026 policies will be added later as monitoring cases after the analytical and AI evaluation system has been validated.

## What exactly happened

USTR announced that the first action covered 818 U.S. tariff lines, approximately USD 34 billion of imports from China, with an additional duty of 25%. U.S. Customs and Border Protection began collecting the additional duty on 6 July 2018.

Primary policy sources:

- [USTR announcement, 15 June 2018](https://ustr.gov/about-us/policy-offices/press-office/press-releases/2018/june/ustr-issues-tariffs-chinese-products)
- [USTR List 1 action and exclusion archive](https://www.ustr.gov/issue-areas/enforcement/section-301-investigations/section-301-china/34-billion-trade-action)

## Options considered

| Candidate | Strength | Main weakness | Decision |
|---|---|---|---|
| U.S. Section 301 List 1, 2018 | Exact effective date, explicit tariff-line list, long pre/post period, many alternative suppliers | Later tariff lists and product exclusions must be modelled carefully | Selected |
| EU duties on Chinese BEVs, 2024 | Recent, one clear product family, high public interest | Existing portfolio is already automobile-heavy; provisional and definitive stages complicate timing; shorter post-period | Later monitoring case |
| U.S. washing-machine safeguard, 2018 | Clear product and visible supplier relocation | Too narrow for the main platform and tariff-rate quota design is specialised | Method demonstration only if useful |
| Recent U.S. tariff increases, 2024–2026 | Very current and suitable for live monitoring | Staggered effective dates and short post-period make validation weaker | Add after historical validation |

## Why this is the best first case

### 1. The policy event is observable

The system has a precise date, tariff rate, origin country, and official list of affected tariff lines. This gives the AI a structured event to retrieve instead of asking it to infer policy timing from news text.

### 2. The data match the question

The U.S. Census international trade datasets provide monthly U.S. imports by trading partner and Harmonized System code from 2010 onward. Import commodity codes can be queried at 2-, 4-, 6-, or 10-character detail. This allows the project to keep the policy definition at detailed U.S. tariff-code level rather than prematurely aggregating everything to broad HS categories.

Primary data documentation:

- [U.S. Census monthly international trade datasets](https://www.census.gov/data/developers/data-sets/international-trade.html)
- [U.S. Census import-HS variables](https://api.census.gov/data/timeseries/intltrade/imports/hs/variables.html)

### 3. It supports a real comparison

We can compare:

- China before and after the policy;
- affected and carefully selected unaffected products;
- China and alternative suppliers for the same products;
- actual dates and placebo dates.

A simple before/after chart will be descriptive evidence only. Stronger policy claims will require comparison groups, pre-trend checks, placebo tests, and uncertainty estimates.

### 4. It can demonstrate trade diversion

The same affected products can be followed across multiple supplier countries. The system can test whether falling Chinese import share coincided with gains by other suppliers rather than merely reporting a bilateral decline.

## Initial analytical boundary

- Importer: United States
- Treated origin: China
- Policy: Section 301 List 1 only
- Effective date: 2018-07-06
- Initial time window: 2016-01 through 2019-12
- Frequency: Monthly
- Preferred raw detail: U.S. HTS 10-digit import records, mapped to the 8-digit policy list
- Primary value measure: Imports for consumption, because the policy applies when goods enter U.S. consumption
- First output: A validated product-partner-month panel, not an AI answer

## Known risks that must not be hidden

1. Later Section 301 lists can contaminate a naive control group.
2. Product exclusions were granted after the initial action and some applied retroactively.
3. Announcements before 6 July may cause firms to import early in anticipation.
4. A fall in import value can reflect price and quantity changes; both should be inspected where quantities are comparable.
5. Alternative suppliers may themselves respond to the tariff, so they are evidence of diversion but not automatically a clean causal control.
6. HTS codes can change across years and require documented concordance.

These are not reasons to abandon the case. They define what the policy-event table, data-quality checks, and evaluation system must handle.

## Human and AI responsibilities for this decision

AI can retrieve official documents, parse tariff lists, write collection code, build candidate comparison groups, run robustness checks, and generate reports.

Human judgement remains responsible for whether the comparison group is economically credible, whether policy assumptions are defensible, and whether the final language is descriptive or causal.

