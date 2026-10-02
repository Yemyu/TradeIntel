# Tests

[Project](../README.md) · [Model results](MODEL_SELECTION.md)

Engineering tests check the tools, stored reports, HTTP routes, and interface. Model tests are separate: they record whether a particular configuration completes the tasks. Scripted responses in a unit test are not model results.

## Interface checks

From the repository root:

```bash
node --test tests/*.test.cjs
PYTHONPATH=src:.:tests .venv/bin/python -m unittest test_chat_workspace_assets test_trade_agent_report_view
```

The Node tests use a DOM fixture, not a full browser. Earlier browser and PDF checks are recorded in the [showcase guide](PUBLIC_SHOWCASE.zh-CN.md).

## Data and Agent regression

Some Python tests use the publisher's verified data bundle and saved runs. These files are intentionally excluded from Git. Tests needing the bundle may skip without it; tests that rebuild the original showcase need the publisher's saved source records as well. A fresh clone is enough to read the four exported examples, but not to reproduce every data-dependent test.

With those local prerequisites installed, the current regression command is:

```bash
PYTHONPATH=src:.:tests .venv/bin/python -m unittest \
  test_us_agent_retest test_us_retest_final \
  test_trade_agent_catalog_contract test_trade_agent_policy_merge_contract \
  test_trade_agent_mainline test_trade_agent_boundaries \
  test_trade_agent_request test_trade_agent_language \
  test_trade_agent_report_view test_trade_agent_metrics \
  test_chat_workspace_assets test_public_showcase
```

The October 2 check passed all 135 tests in that command and all 56 Node tests. The additional web-route suite passed separately; see the [repository review](handoff/runs/20261002-REPOSITORY-REVIEW-AND-PUSH.zh-CN.md) for the complete check record.

## Public website build

The portable Pages build reads only the checked-in public examples. It runs with Python 3.12's standard library, without private sessions or the trade-data bundle:

```bash
PYTHONPATH=src:.:tests python3 -S -m unittest test_github_pages_build
PYTHONPATH=src:. python3 -S scripts/build_github_pages.py --output tmp/pages-build/site
```

The October 2 publication check passed 24 Python interface/export tests and all 59 Node tests. The original-session export, portable build and deployed site matched across all 14 public assets. This is a website check, not a new model test.

## Historical suite

To include earlier experiments and causal research:

```bash
PYTHONPATH=src:.:tests .venv/bin/python -m unittest discover -s tests
```

The full suite is **not green**. The October 2 run executed 1,739 tests and recorded 10 failures and 118 errors, including subtests. Most refer to old frozen experiments, dated authorization fixtures, or outdated test inputs; four historical modules also failed to import the installed SciPy binary on this machine. These issues are listed in the repository review, not hidden by resetting hashes or removing tests. The current Agent regression above is a separate check, not a replacement for the full-suite result.

## Model runs

Running the commands above does not send model requests. A model experiment uses fixed questions, source versions, configuration, reference checks, and a budget. Results and settings are described on the [model test page](MODEL_SELECTION.md).
