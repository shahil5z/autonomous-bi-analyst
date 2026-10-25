"""OpenAI is mocked: these tests check parsing, validation and grounding, not the live API."""

from app import config
from app.agent import pipeline
from app.agent.analyzer import from_llm
from app.agent.grounding import check_grounding
from app.agent.schemas import AnalyzeRequest, Explanation, LLMQuestionParse
from app.ai import openai_service


def llm_parse(**kw):
    base = dict(intent="growth_ranking", metrics=["revenue"], dimensions=["region"], time_period="2011-Q2", comparison_period=None,
                filter_regions=[], filter_countries=[], entities=[], top_n=None, horizon_days=None, requires_visualization=True,
                unsupported_reason=None)
    base.update(kw)
    return LLMQuestionParse(**base)


def test_from_llm_resolves_periods_and_defaults(fixture_db):
    pq = from_llm(llm_parse(), "q")
    assert pq.parser == "openai" and pq.time_period.label == "2011-Q2" and pq.comparison_period.label == "2010-Q2"


def test_from_llm_drops_unknown_entities(fixture_db):
    pq = from_llm(llm_parse(intent="revenue_ranking", filter_regions=["Atlantis", "united kingdom"]), "q")
    assert pq.filters[0].values == ["United Kingdom"]


def test_from_llm_rejects_long_forecast(fixture_db):
    pq = from_llm(llm_parse(intent="forecast", horizon_days=400), "q")
    assert pq.intent == "unsupported"


def test_invalid_llm_output_falls_back(fixture_db, monkeypatch):
    monkeypatch.setattr(config, "openai_enabled", lambda: True)
    monkeypatch.setattr(openai_service, "parse_question", lambda q, s="": (None, "OpenAI parse output failed validation"))
    monkeypatch.setattr(openai_service, "explain", lambda ev: (None, "OpenAI disabled"))
    r = pipeline.analyze(AnalyzeRequest(question="zzzz unknown words", session_id="x"), save=False)
    assert r.parsed.intent == "unsupported" and r.evidence.status == "no_answer" and "validation" in (r.parsed.parser_note or "")


def test_llm_used_only_when_deterministic_unsure(fixture_db, monkeypatch):
    calls = []
    monkeypatch.setattr(config, "openai_enabled", lambda: True)
    monkeypatch.setattr(openai_service, "parse_question", lambda q, s="": calls.append(q) or (llm_parse(intent="revenue_ranking"), None))
    monkeypatch.setattr(openai_service, "explain", lambda ev: (None, "mock"))
    r = pipeline.analyze(AnalyzeRequest(question="Which region has the highest revenue?", session_id="y"), save=False)
    assert calls == [] and r.openai_calls == 1  # explain only
    r = pipeline.analyze(AnalyzeRequest(question="where do we earn the bulk of our money geographically", session_id="y2"), save=False)
    assert calls and r.parsed.parser == "openai" and r.openai_calls == 2


def test_grounded_llm_explanation_accepted(fixture_db, monkeypatch):
    monkeypatch.setattr(config, "openai_enabled", lambda: True)

    def fake_explain(ev):
        h = ev.headline
        return Explanation(answer=f"{h['leader']} has the highest revenue at £{h['leader_value']:,.0f}.",
                           evidence_bullets=[f"{h['runner_up']}: £{h['runner_up_value']:,.2f}"], analysis="Ranking from SQL.",
                           limitations=["Observational."], follow_ups=["x"]), None

    monkeypatch.setattr(openai_service, "explain", fake_explain)
    r = pipeline.analyze(AnalyzeRequest(question="Which region has the highest revenue?", session_id="z"), save=False)
    assert r.explanation_source == "openai" and r.grounding.passed
    assert r.follow_ups == r.explanation.follow_ups and "x" not in r.follow_ups  # follow-ups come from results


def test_hallucinated_number_rejected(fixture_db, monkeypatch):
    monkeypatch.setattr(config, "openai_enabled", lambda: True)
    monkeypatch.setattr(openai_service, "explain", lambda ev: (Explanation(
        answer="Revenue grew 37.2% to £4,321,987.", evidence_bullets=[], analysis="", limitations=[], follow_ups=[]), None))
    r = pipeline.analyze(AnalyzeRequest(question="Which region has the highest revenue?", session_id="h"), save=False)
    assert r.explanation_source == "template" and "grounding" in r.explanation_note


def test_causal_language_rejected_for_campaign(fixture_db):
    r = pipeline.analyze(AnalyzeRequest(question="Did the campaign coincide with higher sales?", session_id="c", use_openai=False), save=False)
    bad = Explanation(answer="The campaign caused higher sales.", evidence_bullets=[], analysis="", limitations=[], follow_ups=[])
    assert not check_grounding(bad, r.evidence).passed
    ok = Explanation(answer="We cannot say the campaign caused higher sales.", evidence_bullets=[], analysis="", limitations=[], follow_ups=[])
    assert check_grounding(ok, r.evidence).passed


def test_compact_evidence_is_small(fixture_db):
    r = pipeline.analyze(AnalyzeRequest(question="What is the largest sales anomaly?", session_id="a", use_openai=False), save=False)
    payload = openai_service.compact_evidence(r.evidence)
    assert len(payload["supporting_rows"]) <= 12 and "series" not in payload["stats"]


def test_em_dashes_are_stripped_from_explanations():
    from app.agent.schemas import Explanation
    from app.ai.openai_service import sanitize_explanation

    exp = Explanation(answer="UK led \u2014 by far", evidence_bullets=["a\u2014b"], analysis="x", limitations=[], follow_ups=[])
    out = sanitize_explanation(exp)
    assert out.answer == "UK led, by far"
    assert "\u2014" not in out.model_dump_json()
