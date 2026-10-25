from app.agent.pipeline import analyze
from app.agent.schemas import AnalyzeRequest


def ask(q, sid="s1"):
    return analyze(AnalyzeRequest(question=q, session_id=sid, use_openai=False), save=False)


def test_ranking_evidence_object(fixture_db):
    r = ask("Which region has the highest revenue?")
    ev = r.evidence
    assert ev.status == "answered" and ev.analysis_type == "revenue_ranking"
    assert ev.headline["leader"] == "United Kingdom"
    assert ev.sql and "sales" in ev.tables
    assert all(c.passed for c in ev.validation)
    assert any(c.name.startswith("group totals reconcile") for c in ev.validation)
    assert r.grounding.passed and r.explanation_source == "template"
    assert r.openai_calls == 0
    assert [s.stage for s in r.lineage] == ["Data source", "Tables", "Query", "Analysis", "Visualization", "Explanation"]


def test_follow_up_uses_context(fixture_db):
    first = ask("Which region grew fastest between 2011-01 and 2011-05?", sid="ctx")
    assert first.parsed.intent == "growth_ranking"
    follow = ask("What products drove that growth?", sid="ctx")
    assert follow.parsed.intent == "drivers" and follow.parsed.is_follow_up
    region = first.evidence.headline["fastest"]
    assert any(f.values == [region] for f in follow.parsed.filters)


def test_follow_up_suggestions_reference_results(fixture_db):
    r = ask("Which region has the highest revenue?")
    assert any("United Kingdom" in s for s in r.follow_ups)


def test_every_template_number_is_grounded(fixture_db):
    for q in ["What are the top 3 products?", "What is the largest sales anomaly?", "Forecast revenue for the next 14 days",
              "Which customer segment is most valuable?", "Did the campaign coincide with higher sales?",
              "Compare France and Germany", "Show the monthly revenue trend"]:
        r = ask(q, sid=q[:10].replace(" ", "_"))
        assert r.evidence.status == "answered", (q, r.evidence.no_answer_reason)
        assert r.grounding.passed, (q, r.grounding)
