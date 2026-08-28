# Learning Profile and Collaboration Rules

Last updated: 2026-08-28

## Current background

- Academic background: Economics.
- Python: understands basic syntax and can write small pieces of code, but has not yet built a complete AI system independently.
- SQL: has learned part of the MySQL syntax.
- Databases: database design, data modelling, indexes, transactions, and data pipelines should be treated as new topics.
- AI engineering: LLM tools, agents, RAG, evaluation, and responsible-AI engineering should be taught from the beginning.
- Quantitative advantage: has experience with economic reasoning, regression, consumer research, forecasting, and real-world data analysis through existing portfolio projects.

## Long-term direction

- Build toward an AI engineer or a role combining data and AI.
- Use this project both as an NTU Master of Computing in Applied AI application project and as a structured learning journey.
- Finish with genuine understanding rather than a repository that cannot be explained independently.

## Teaching and collaboration rules

For every new concept or project stage, use this sequence:

1. Explain the real problem the concept solves in plain language.
2. Introduce only the minimum prerequisite knowledge needed for the stage.
3. Give a small worked example before touching the main project.
4. Let the learner write the stage's most important logic.
5. Review the code together and explain errors and trade-offs.
6. Record what was learned and verify that the learner can explain it in their own words.

Additional rules:

- Introduce at most one or two major new concepts at a time.
- Do not use unexplained framework code or large copy-pasted implementations.
- Separate required MVP knowledge from optional advanced material.
- Keep a Chinese glossary for unavoidable English technical terms.
- Prefer visible, testable intermediate results over hidden complexity.
- The assistant may create boilerplate, configuration, tests, and repetitive code; the learner should write the core learning logic.
- Before each stage, provide a short learning list with expected outcomes, not a large list for the entire project at once.
- All developer tools and Python packages must be installed inside the project's own virtual environment, never into the system environment.

## Technology decision already made

MySQL remains the learning and development database because the learner already knows some MySQL syntax and wants to demonstrate data capability. A lightweight read-only snapshot may be added later so reviewers can run the demo without installing MySQL. This is a packaging decision, not a replacement for learning MySQL.

