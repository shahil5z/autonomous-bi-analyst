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
    assert any(r["id"] == run_id for r in client.get("/api/runs").json()["runs"])
    assert client.get("/health").json()["database"]["ok"]
    assert {t["name"] for t in client.get("/api/schema").json()["tables"]} >= {"sales", "products"}
