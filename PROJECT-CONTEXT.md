# Project context

**What**: ABI Analyst, a natural-language BI analyst over UCI Online Retail II. Student Data Science portfolio project
(Project 2; Project 1 is market-intelligence-lab).
**Status**: Phase 2: audited, fixed, tested locally, pushed to GitHub (shahil5z/autonomous-bi-analyst), deployment to
Vercel in progress (see the Deployment section of README for live URLs once verified).

## Key decisions
- LLM never computes numbers; SQL/Python tools do. OpenAI is optional (parse fallback + explanation wording) and every
  LLM explanation passes a grounding check, otherwise a labelled template is used. Max 2 OpenAI calls per question.
- DuckDB read-only; typed query specs compiled to SELECT; single `validate_sql` gate (sqlglot, allowlists, LIMIT cap).
- Rule-based parser first; LLM parser only when the rules are not confident.
- Forecast: three simple models on a holdout vs seasonal-naive baseline; MAE/RMSE/MAPE; 80% band from holdout errors.
- Campaigns are synthetic and labelled as such everywhere. Causal questions get an "association only" note.
- Deployment: two Vercel projects (backend root `backend`, frontend root `frontend`), Git-connected, deploys on push.
  DB ships as backend/artifacts/abi.duckdb.gz (~6 MB) and is unpacked to /tmp. No Postgres (static read-only data).
  Run records: SQLite in /tmp (temporary). History/saved analyses: browser localStorage. The server-side run list
  endpoint was removed (it exposed other visitors' questions).
- Abuse limits: per-IP 10/min and 150/day in memory (per instance), 500-char questions, 4 KB bodies.

## Layout
backend/ (FastAPI, agent/, tools/, database/, ai/, artifacts/, index.py, vercel.json), frontend/ (Next.js 16),
scripts/ (pipeline, eval), evals/, docs/ (evaluation report, screenshots), data/ (README, sample/).

## Verified state (2026-10-26, local)
85 backend tests, Ruff, ESLint, tsc and next build pass. Eval 20 questions, all metrics pass in template and OpenAI
modes (docs/evaluation_report.md). Playwright e2e passed locally on desktop and mobile (script kept outside the repo).

## Not done / not verified
PowerShell commands (not tested), PostgreSQL compatibility (not tested).

## Future ideas
- Larger, independently written eval set; exercise the LLM parser in the eval.
- Hosted storage for runs/sessions; shared rate limiter.
- Backtesting over several origins for forecast intervals.
