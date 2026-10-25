# Evaluation report (Phase 1)

Run: 2026-10-26 01:26 IST (UTC+5:30), `python scripts/run_eval.py --modes template,openai`, model `gpt-4o-mini`.
Raw output: `evals/results/latest.json` (git-ignored, regenerate with the command above).

## What is measured

18 questions in `evals/questions.yaml`: 14 answerable (including two follow-ups that depend on conversation context)
and 4 that should be refused (weather, a 2-year forecast, a prompt injection, a SQL injection).

Ground truth is recomputed by `run_eval.py` with pandas directly from the raw parquet file, using its own
re-implementation of the cleaning rules (only the country-to-region map and the synthetic campaign dates are shared
with the pipeline).

| Metric | Meaning |
|---|---|
| tool_ok | Expected intent / tool chosen (unsupported for the 4 refusal questions) |
| exec_ok | Ran without error and produced evidence (or a proper no-answer) |
| numeric_ok | Headline numbers within tolerance of the pandas ground truth (answerable questions only) |
| sql_ok | Every executed SQL statement passes the SQL validator again |
| complete | Answer, evidence, limitations and SQL present (or a no-answer reason) |
| grounded | Final explanation passes the grounding check |

## Results

| Metric | Template mode (no OpenAI) | OpenAI mode |
|---|---|---|
| tool_ok | 18 / 18 | 18 / 18 |
| exec_ok | 18 / 18 | 18 / 18 |
| numeric_ok | 14 / 14 | 14 / 14 |
| sql_ok | 18 / 18 | 18 / 18 |
| complete | 18 / 18 | 18 / 18 |
| grounded | 18 / 18 | 18 / 18 |
| Median latency | 0.01 s | 2.575 s |
| OpenAI calls | 0 | 14 |
| Explanations written by OpenAI | 0 | 12 of 14 answerable |

In OpenAI mode two drafts were rejected and replaced by the template:

- q07 (customer segments): the draft was too short to be useful (fewer than 6 words).
- q13 (Western vs Northern Europe order values): the draft used causal wording.

The 4 refusal questions are answered by rules before any OpenAI call, so they use no tokens.

## Selected verified values (system output = pandas ground truth)

| Question | Value |
|---|---|
| Highest-revenue region | United Kingdom, £16,799,849.90 |
| Fastest-growing region, 2011-Q3 vs 2010-Q3 | Western Europe, +10.05% |
| Revenue change 2011-Q2 to Q3 | +£447,827.24 (+22.47%) |
| Top product | REGENCY CAKESTAND 3 TIER, £330,590.32 |
| Largest daily anomaly | 2011-12-09, £198,094.64 |
| Clearance campaign vs other days (synthetic) | Mann-Whitney p = 0.821 |
| 30-day forecast, best holdout MAE | Seasonal naive £12,677.83 |
| Orders in November 2011 | 2,751 |
| Log price vs log units | Pearson r = -0.414 |

## Caveats (read these before quoting the numbers)

- The question set is small and was written and refined by the developer while building the system, so these
  scores show the system works on the questions it was designed for. They are not a measure of general accuracy.
- Several fixes were made after earlier eval runs exposed bugs (for example a follow-up that silently ignored a
  filter). Only the final run is reported here.
- All eval questions match the rule-based parser, so the optional LLM parser is not exercised by this eval. It was
  checked by hand on 3 vague questions only.
- Ground truth shares the region map and campaign dates with the pipeline, so errors there would not be caught.
- LLM output varies between runs; the OpenAI-mode counts could differ on a rerun.
