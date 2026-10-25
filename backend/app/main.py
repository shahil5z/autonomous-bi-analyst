"""FastAPI app for ABI Analyst."""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request, Response
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

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("abi")

app = FastAPI(title="ABI Analyst API", version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
                   max_age=600)

# Per-IP sliding-window limits on /api/analyze. Kept in memory: each serverless instance has its own counters.
_hits: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown"))[:64]


def _rate_limited(ip: str) -> str | None:
    now = time.time()
    q = _hits[ip]
    while q and now - q[0] > 86400:
        q.popleft()
    if len(q) >= config.RATE_LIMIT_PER_DAY:
        return "Daily question limit reached for this address. Please try again tomorrow."
    if sum(1 for t in q if now - t < 60) >= config.RATE_LIMIT_PER_MIN:
        return "Too many questions in a short time. Please wait a minute and try again."
    q.append(now)
    if len(_hits) > 5000:  # bound memory
        for k in list(_hits)[:1000]:
            _hits.pop(k, None)
    return None


@app.middleware("http")
async def _limits(request: Request, call_next) -> Response:
    if request.method == "POST" and request.url.path == "/api/analyze":
        if int(request.headers.get("content-length") or 0) > 4096:
            return _error(413, "payload_too_large", "Request body is too large.")
        msg = _rate_limited(_client_ip(request))
        if msg:
            return JSONResponse(status_code=429, content={"error": {"code": "rate_limited", "message": msg}}, headers={"Retry-After": "60"})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store")
    return response


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
    return {"status": "ok", "database": db, "openai_configured": config.openai_enabled(), "model": config.OPENAI_MODEL,
            "run_storage": "temporary (/tmp, per instance)" if config.ON_SERVERLESS else "local SQLite"}


@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze_endpoint(req: AnalyzeRequest) -> AnalyzeResponse:
    try:
        return analyze(req)
    except connection.DatabaseError:
        raise HTTPException(status_code=503, detail="The database is not available.") from None


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
