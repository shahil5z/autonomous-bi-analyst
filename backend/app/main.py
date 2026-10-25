"""FastAPI app for ABI Analyst."""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import config
from app.agent.followups import DEFAULT_SUGGESTIONS
from app.agent.pipeline import analyze
from app.agent.schemas import AnalyzeRequest, AnalyzeResponse
from app.database import connection
from app.database.schema import ALLOWED_SCHEMA, TABLE_DESCRIPTIONS
from app.services import runs

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("abi")

app = FastAPI(title="ABI Analyst API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@app.exception_handler(RequestValidationError)
async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    return _error(422, "invalid_request", f"Invalid request: {'.'.join(str(x) for x in first.get('loc', []))} {first.get('msg', '')}".strip())


@app.exception_handler(HTTPException)
async def _http(_: Request, exc: HTTPException) -> JSONResponse:
    return _error(exc.status_code, "not_found" if exc.status_code == 404 else "error", str(exc.detail))


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
    log.error("Unhandled error: %s", type(exc).__name__)
    return _error(500, "internal_error", "Something went wrong while analysing. No answer was produced.")


@app.get("/health")
def health() -> dict:
    try:
        lo, hi = connection.data_range()
        db = {"ok": True, "date_range": [lo.isoformat(), hi.isoformat()]}
    except connection.DatabaseError:
        db = {"ok": False}
    return {"status": "ok", "database": db, "openai_configured": config.openai_enabled(), "model": config.OPENAI_MODEL}


@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze_endpoint(req: AnalyzeRequest) -> AnalyzeResponse:
    try:
        return analyze(req)
    except connection.DatabaseError:
        raise HTTPException(status_code=503, detail="The database is not available.") from None


@app.get("/api/runs")
def list_runs(limit: int = 30) -> dict:
    return {"runs": runs.list_runs(max(1, min(limit, 100)))}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    if not run_id.isalnum() or len(run_id) > 32:
        raise HTTPException(status_code=404, detail="Run not found.")
    run = runs.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@app.get("/api/schema")
def schema() -> dict:
    lo, hi = connection.data_range()
    return {"date_range": [lo.isoformat(), hi.isoformat()],
            "tables": [{"name": t, "description": TABLE_DESCRIPTIONS[t],
                        "columns": [{"name": c, "description": d} for c, d in cols.items()]} for t, cols in ALLOWED_SCHEMA.items()],
            "source": {"name": "Online Retail II", "url": "https://archive.ics.uci.edu/dataset/502/online+retail+ii", "licence": "CC BY 4.0"}}


@app.get("/api/suggestions")
def suggestions() -> dict:
    return {"suggestions": DEFAULT_SUGGESTIONS}
