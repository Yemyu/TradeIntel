# TradeShock AI

An evidence-grounded AI assistant for analysing trade-policy shocks and trade diversion.

## Current status

Learning and development stage 0: system map, AI–human responsibilities, and verifiable AI-assisted implementation.

This repository is currently local-only. It will not be published until its scope, documentation, and privacy have been reviewed.

## Project documents

- [Learning-first project plan](./PROJECT_PLAN.md)
- [Learning profile and collaboration rules](./LEARNING_PROFILE.md)
- [Stage 0 learning guide](./docs/learning/phase-00-foundations.md)

## Local environment

The project uses Python 3.12 in a project-local virtual environment:

```bash
source .venv/bin/activate
python --version
```

No third-party Python packages are required in stage 0.

## First validated policy source

The initial historical case is the U.S. Section 301 List 1 action effective 6 July 2018. Reproduce the official tariff-code extraction with:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/download_policy_sources.py
python -m src.policy.extract_ustr_list1
python -m unittest discover -s tests -v
```

The extraction retains the original `9033.00` entry and applies the later official correction to `9033.00.90` with source-page provenance.
