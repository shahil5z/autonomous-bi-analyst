"""End-to-end analysis workflow: analyze -> plan -> route -> validate -> evidence -> explain."""

from __future__ import annotations

import time
import uuid

from pydantic import ValidationError

from app import config
from app.agent import followups
from app.agent.analyzer import deterministic_parse, from_llm
from app.agent.context import store
from app.agent.evidence import build_evidence, validate_evidence
from app.agent.grounding import check_grounding
from app.agent.planner import make_plan
from app.agent.router import run_step
from app.agent.schemas import AnalyzeRequest, AnalyzeResponse, Evidence, LineageStep, TraceStep
from app.agent.templates import template_explanation
from app.ai import openai_service
from app.database.connection import data_range
from app.services import runs
from app.tools.visualization import build_chart

SOURCE = "UCI Online Retail II (CC BY 4.0)"


def analyze(req: AnalyzeRequest, save: bool = True) -> AnalyzeResponse:
    t0 = time.perf_counter()
    sid = req.session_id or uuid.uuid4().hex[:16]
    ctx = store.get(sid)
    use_ai = req.use_openai and config.openai_enabled()
    calls = 0
    trace: list[TraceStep] = []
    question = " ".join(req.question.split())

    pq, confident = deterministic_parse(question, ctx)
    parser_note = None
    if not confident and use_ai:
        calls += 1
        raw, err = openai_service.parse_question(question, ctx.summary)
        if raw is not None:
            try:
                pq = from_llm(raw, question)
            except (ValidationError, ValueError):
                parser_note = "OpenAI parse rejected by validation; deterministic result kept."
        else:
            parser_note = err
    pq.parser_note = parser_note
    trace.append(TraceStep(label="Understood question", status="done",
                           detail=f"intent: {pq.intent} ({pq.parser} parser{', follow-up' if pq.is_follow_up else ''})"))
    if pq.metrics:
        trace.append(TraceStep(label=f"Identified metric: {pq.metrics[0]}", status="done"))
    if pq.time_period:
        detail = pq.time_period.label + (f" vs {pq.comparison_period.label}" if pq.comparison_period else "")
        trace.append(TraceStep(label="Selected periods", status="done", detail=detail))

    plan = make_plan(pq)
    trace.append(TraceStep(label="Planned analysis", status="done", detail=f"{len(plan.human_steps)} steps"))

    results = [run_step(step) for step in plan.steps]
    for step, r in zip(plan.steps, results, strict=True):
        trace.append(TraceStep(label=f"Ran {step.tool} tool", status="done" if r.ok else "failed",
                               detail=step.description if r.ok else (r.error or "failed")))
        if r.sql:
            trace.append(TraceStep(label="Queried data (read-only)", status="done", detail=f"{len(r.sql)} validated SELECT(s)"))

    if pq.intent == "unsupported":
        ev = Evidence(question=question, status="no_answer", analysis_type="unsupported", method="none",
                      no_answer_reason=pq.unsupported_reason)
    else:
        ev = build_evidence(question, pq, results)
    lo, hi = data_range()
    ev.periods["data_available"] = f"{lo.isoformat()} to {hi.isoformat()}"
    ev.validation = validate_evidence(ev, pq) if ev.status == "answered" else []
    if ev.status == "answered" and not all(c.passed for c in ev.validation):
        failed = ", ".join(c.name for c in ev.validation if not c.passed)
        ev.status, ev.no_answer_reason = "error", f"The result failed validation ({failed}), so no answer is shown."
    trace.append(TraceStep(label="Validated result", status="done" if ev.status == "answered" else "skipped",
                           detail=f"{sum(c.passed for c in ev.validation)}/{len(ev.validation)} checks passed" if ev.validation else ""))

    if ev.status == "answered" and plan.chart and pq.requires_visualization:
        ev.chart = build_chart(ev, results[0].data)
    trace.append(TraceStep(label="Generated visualization", status="done" if ev.chart else "skipped",
                           detail=ev.chart.title if ev.chart else "no chart needed"))

    explanation = template_explanation(ev, pq)
    source, note = "template", None if use_ai else "OpenAI not used: deterministic template explanation."
    grounding = check_grounding(explanation, ev)
    if use_ai and ev.status == "answered":
        calls += 1
        llm, err = openai_service.explain(ev)
        if llm is not None:
            g = check_grounding(llm, ev)
            if g.passed and len(llm.answer.split()) < 6:
                note = "OpenAI explanation rejected (answer too short to be useful); template used."
            elif g.passed:
                explanation, source, grounding = llm, "openai", g
            else:
                note = "OpenAI explanation rejected by grounding check (" + ", ".join(
                    (g.unmatched_numbers and [f"unsupported numbers: {', '.join(g.unmatched_numbers[:4])}"] or [])
                    + (g.causal_language and ["causal wording"] or [])
                    + (g.unknown_names and [f"names not in evidence: {', '.join(g.unknown_names[:3])}"] or [])) + "); template used."
        else:
            note = f"{err}; template used."
    trace.append(TraceStep(label="Generated explanation", status="done",
                           detail="OpenAI (grounding check passed)" if source == "openai" else "deterministic template"))

    sugg = followups.suggest(pq, ev)
    explanation.follow_ups = sugg
    lineage = [
        LineageStep(stage="Data source", detail=SOURCE + (" + synthetic campaigns (seed 42)" if "campaigns" in ev.tables or "calendar" in ev.tables else "")),
        LineageStep(stage="Tables", detail=", ".join(ev.tables) or "none"),
        LineageStep(stage="Query", detail=f"{len(ev.sql)} validated read-only SELECT(s)" if ev.sql else "no query"),
        LineageStep(stage="Analysis", detail=ev.method.replace("_", " ")),
        LineageStep(stage="Visualization", detail=f"{ev.chart.type} chart: {ev.chart.title}" if ev.chart else "none"),
        LineageStep(stage="Explanation", detail=f"OpenAI {config.OPENAI_MODEL}, grounded in evidence" if source == "openai" else "Deterministic template from evidence"),
    ]
    focus, fdim = followups.focus_of(pq, ev)
    store.update(sid, pq, focus, fdim, explanation.answer)
    resp = AnalyzeResponse(
        run_id=uuid.uuid4().hex[:12], session_id=sid, question=question, parsed=pq, plan=plan, evidence=ev,
        explanation=explanation, explanation_source=source, explanation_note=note, grounding=grounding, follow_ups=sugg,
        trace=trace, lineage=lineage, openai_calls=calls, duration_ms=int((time.perf_counter() - t0) * 1000))
    if save:
        runs.save_run(resp.model_dump(mode="json"))
    return resp
