# Learning Profile and Collaboration Rules

Last updated: 2026-08-28

## Current background

- Academic background: Economics.
- Python: understands basic syntax and has completed previous projects. The goal is not to practise writing syntax from memory, but to understand and direct AI-assisted implementation.
- SQL: has learned part of the MySQL syntax.
- Databases: database design, data modelling, indexes, transactions, and data pipelines should be treated as new topics.
- AI engineering: LLM tools, agents, RAG, evaluation, and responsible-AI engineering should be taught from the beginning.
- Quantitative advantage: has experience with economic reasoning, regression, consumer research, forecasting, and real-world data analysis through existing portfolio projects.

## Long-term direction

- Build toward an AI engineer or a role combining data and AI.
- Use this project both as an NTU Master of Computing in Applied AI application project and as a structured learning journey.
- Finish with genuine understanding of the system, its decisions, evidence, and limitations rather than memorising implementation syntax.
- Develop AI-native project leadership: define requirements, choose between approaches, instruct AI, inspect outputs, design verification, and diagnose failures.

## Teaching and collaboration rules

For every new concept or project stage, use this sequence:

1. Explain the real problem the concept solves in plain language.
2. Show where it sits in the whole system and what goes in and comes out.
3. Present the realistic options, trade-offs, and recommended choice.
4. Explain what AI can implement reliably and what still requires human judgement.
5. Let AI produce the implementation, tests, and documentation.
6. Review evidence and outputs together, diagnose failures, and record the decision.
7. Verify that the learner can explain why the choice was made, how it was checked, and where it may fail.

Additional rules:

- Introduce at most one or two major new concepts at a time.
- Do not require writing routine syntax, loops, API clients, SQL boilerplate, or framework code from memory.
- Explain code details only when they affect data correctness, system behaviour, debugging, security, cost, or an architectural decision.
- Do not use unexplained framework behaviour: generated code is acceptable, unexplained system decisions are not.
- Separate required MVP knowledge from optional advanced material.
- Keep a Chinese glossary for unavoidable English technical terms.
- Prefer visible, testable intermediate results over hidden complexity.
- The assistant should create implementation code, configuration, tests, repetitive logic, and first drafts of documentation.
- The learner owns the problem definition, domain assumptions, acceptance criteria, important trade-offs, interpretation of evidence, and final claims.
- The learner should be able to read the system at a high level, run it, inspect key inputs and outputs, and use tests or logs to challenge AI-generated work; writing code from scratch is optional.
- Before each stage, provide a short learning list with expected outcomes, not a large list for the entire project at once.
- All developer tools and Python packages must be installed inside the project's own virtual environment, never into the system environment.

## Technology decision already made

MySQL remains the learning and development database because the learner already knows some MySQL syntax and wants to demonstrate data capability. A lightweight read-only snapshot may be added later so reviewers can run the demo without installing MySQL. This is a packaging decision, not a replacement for learning MySQL.

## What the learner needs to understand

- The purpose and boundaries of each system component.
- Data types, schemas, keys, joins, missing values, and data quality as concepts; exact conversion syntax need not be memorised.
- What a model or agent is allowed to conclude from the available evidence.
- How evaluation questions, expected answers, logs, and tests reveal errors.
- How to give AI a precise task with inputs, outputs, constraints, and acceptance criteria.
- Which decisions are reversible implementation choices and which can invalidate the analysis.
