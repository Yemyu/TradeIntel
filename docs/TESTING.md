# Tests

[🇨🇳 简体中文](TESTING.zh-CN.md) · [Project](../README.md) · [Model results](MODEL_SELECTION.md)

Engineering tests check query tools, stored reports, HTTP routes, and the interface. Model evaluations separately measure task completion with a configured model. Scripted unit-test responses are not model-evaluation results.

## Interface tests

From the repository root, using the project environment:

```bash
node --test tests/*.test.cjs
PYTHONPATH=src:.:tests .venv/bin/python -m unittest test_chat_workspace_assets test_trade_agent_report_view
```

Node tests use DOM fixtures rather than a full browser. Browser navigation, responsive layout, and PDF checks are separate; see the [showcase guide](PUBLIC_SHOWCASE.md).

## Data and Agent regression

Some Python tests require the verified trade-data bundle or saved evaluation records. These are excluded from Git. Bundle-dependent tests may skip without the data; tests that export the original showcase also need its source sessions. Check prerequisites before interpreting a skipped test as a pass.

With the required local records available:

```bash
PYTHONPATH=src:.:tests .venv/bin/python -m unittest \
  test_us_agent_retest test_us_retest_final \
  test_trade_agent_catalog_contract test_trade_agent_policy_merge_contract \
  test_trade_agent_mainline test_trade_agent_boundaries \
  test_trade_agent_request test_trade_agent_language \
  test_trade_agent_report_view test_trade_agent_metrics \
  test_chat_workspace_assets test_public_showcase
```

The October 2 check passed 135 Python tests in this group; web-route tests were checked separately. The [repository check record (Chinese)](handoff/runs/20261002-REPOSITORY-REVIEW-AND-PUSH.zh-CN.md) describes that run and its environment.

## Portable website build

The Pages builder needs only the checked-in public examples and the Python standard library. CI uses Python 3.12:

```bash
PYTHONPATH=src:.:tests python3 -S -m unittest test_github_pages_build
PYTHONPATH=src:. python3 -S scripts/build_github_pages.py --output tmp/pages-build/site
PYTHONPATH=src:. python3 -S scripts/build_github_pages.py --verify tmp/pages-build/site
```

The output directory must not already exist. The build checks the 14 public assets and excludes local application settings and sessions. Website checks do not add to model-evaluation scores.

## Full test suite

To include earlier experiments and causal research:

```bash
PYTHONPATH=src:.:tests .venv/bin/python -m unittest discover -s tests
```

The full suite is not passing. The October 2 run executed 1,739 tests and recorded 10 failures and 118 errors, including subtests. Reported issues included frozen experimental inputs, dated authorization fixtures, and four SciPy import failures in that environment. The repository check record contains the details.

The current Agent regression is a separate test group, not evidence that those full-suite failures have been fixed. Tests and frozen evidence are retained.

## Model evaluation

The test commands above do not call model APIs. Model evaluations use fixed questions, data versions, configuration, reference checks, and a call budget. [Model tests](MODEL_SELECTION.md) lists the five configurations, scores, settings, and scoring method.

## Documentation checks

```bash
PYTHONPATH=src:.:tests .venv/bin/python -m unittest test_public_documentation
```

These checks cover local links in the current public guides, language counterparts, and private planning files excluded from the tracked tree.
