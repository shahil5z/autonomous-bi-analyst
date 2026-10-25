# Project context

**What**: ABI Analyst, a natural-language BI analyst over UCI Online Retail II. Student Data Science portfolio project.
**Status**: Phase 1 complete, local only. No deployment, no remote repo.

## Key decisions
- LLM never computes numbers; SQL/Python tools do. OpenAI is optional (parse fallback + explanation wording) and every
  LLM explanation passes a grounding check, otherwise a labelled template is used.
- DuckDB read-only; typed query specs compiled to SELECT; single `validate_sql` gate (sqlglot, allowlists, LIMIT cap).
- Rule-based parser first; LLM parser only when the rules are not confident.
- Forecast: three simple models compared on a holdout against a seasonal-naive baseline; max horizon 90 days.
- Campaigns are synthetic and labelled as such everywhere.

## Layout
backend/ (FastAPI, agent/, tools/, database/, ai/), frontend/ (Next.js 16), scripts/ (pipeline, eval), evals/, docs/, data/.

## Verified state (2026-10-26)
75 backend tests, Ruff, ESLint, tsc and next build pass. Eval 18/18 on all metrics in template and OpenAI modes
(see docs/evaluation_report.md). Playwright e2e passed on desktop and mobile (script kept outside the repo).

## Not done / not verified
PowerShell commands (not tested), PostgreSQL compatibility (not tested), deployment (out of scope).

## Phase 2 candidates
- Larger, independently written eval set; exercise the LLM parser in the eval.
- Persist conversation memory; netting cancellations against original orders.
- Prediction intervals for forecasts; backtesting over several origins.
- Deployment (needs approval), Postgres option, auth/rate limiting if exposed publicly.
