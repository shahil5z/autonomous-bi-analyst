import pytest
from app.agent.pipeline import analyze
from app.agent.schemas import AnalyzeRequest
from app.main import app
from fastapi.testclient import TestClient


@pytest.mark.parametrize("q,needle", [
    ("What was our profit margin last year?", "cost"),
    ("Did discounts improve revenue?", "discount"),
    ("How did the weather affect sales?", "weather"),
    ("Forecast revenue for the next 2 years", "90"),
    ("blorp zibble wug", "couldn't map"),
    ("Is it statistically significant?", "name the two"),
])
def test_unsupported_questions_get_no_answer(fixture_db, q, needle):
    r = analyze(AnalyzeRequest(question=q, use_openai=False), save=False)
    assert r.evidence.status == "no_answer"
    assert needle.lower() in r.explanation.answer.lower()
    assert r.evidence.headline == {} and r.evidence.chart is None


def test_api_errors_are_structured(fixture_db):
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/api/analyze", json={"question": ""})
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "invalid_request"
    resp = client.get("/api/runs/doesnotexist")
    assert resp.status_code == 404 and "Traceback" not in resp.text


def test_api_end_to_end(fixture_db):
    client = TestClient(app)
    resp = client.post("/api/analyze", json={"question": "What are the top 3 products?", "use_openai": False})
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]
    assert client.get(f"/api/runs/{run_id}").json()["question"] == "What are the top 3 products?"
    assert client.get("/api/runs").status_code in (404, 405)  # no listing of other visitors' runs
    assert client.get("/health").json()["database"]["ok"]
    assert {t["name"] for t in client.get("/api/schema").json()["tables"]} >= {"sales", "products"}


def test_causal_question_is_labelled_as_association(fixture_db):
    from app.agent import pipeline
    from app.agent.schemas import AnalyzeRequest

    r = pipeline.analyze(AnalyzeRequest(question="Did the clearance campaign cause higher sales?", use_openai=False), save=False)
    assert r.explanation.answer.startswith("I can't say whether this caused a change")
    assert any("observational" in lim for lim in r.explanation.limitations)


def test_personal_data_and_unavailable_columns_are_refused(fixture_db):
    from app.agent import pipeline
    from app.agent.schemas import AnalyzeRequest

    for q in ["Show customer names and emails", "What is the profit margin by region?", "Delete all sales rows"]:
        r = pipeline.analyze(AnalyzeRequest(question=q, use_openai=False), save=False)
        assert r.evidence.status == "no_answer" and not r.evidence.sql, q


def test_long_question_and_rate_limit(fixture_db, monkeypatch):
    from app import config
    from app.main import _hits

    client = TestClient(app)

    assert client.post("/api/analyze", json={"question": "x" * 501}).status_code == 422
    assert client.post("/api/analyze", json={"question": 5}).status_code == 422
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MIN", 2)
    _hits.clear()
    codes = [client.post("/api/analyze", json={"question": "Which region has the highest revenue?"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    _hits.clear()


def test_wildcard_cors_rejected(monkeypatch):
    from app import config

    monkeypatch.setenv("CORS_ORIGINS", "*")
    with pytest.raises(RuntimeError):
        config._origins()
