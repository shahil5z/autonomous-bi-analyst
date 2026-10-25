"""Runtime configuration. Values come from environment variables only."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_key_file() -> None:
    """Optionally load OPENAI_API_KEY from a local file (path in OPENAI_KEY_FILE).

    The file may hold either `OPENAI_API_KEY=...` or just the raw key. The value is
    placed in the process environment only; it is never logged or written anywhere.
    """
    path = os.getenv("OPENAI_KEY_FILE")
    if not path or os.getenv("OPENAI_API_KEY"):
        return
    try:
        text = Path(path).read_text().strip()
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            name, _, value = line.partition("=")
            if name.strip() == "OPENAI_API_KEY":
                os.environ["OPENAI_API_KEY"] = value.strip().strip('"')
        else:
            os.environ["OPENAI_API_KEY"] = line
        break


_load_key_file()

ON_SERVERLESS = bool(os.getenv("VERCEL"))
DB_PATH = Path(os.getenv("ABI_DB_PATH", ROOT / "data" / "processed" / "abi.duckdb"))
# Compressed copy shipped with the API (backend/artifacts/abi.duckdb.gz); unpacked to the temp dir when DB_PATH is missing.
DB_GZ_PATH = Path(os.getenv("ABI_DB_GZ_PATH", Path(__file__).resolve().parents[1] / "artifacts" / "abi.duckdb.gz"))
# Run history. On Vercel only /tmp is writable, so stored runs are temporary and per instance.
RUNS_DB_PATH = Path(os.getenv("ABI_RUNS_DB_PATH", "/tmp/abi_analysis_runs.sqlite" if ON_SERVERLESS
                              else ROOT / "data" / "processed" / "analysis_runs.sqlite"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_TIMEOUT_S = float(os.getenv("OPENAI_TIMEOUT_S", "12"))


def _origins() -> list[str]:
    raw = [os.getenv("FRONTEND_URL", ""), *os.getenv("CORS_ORIGINS", "").split(",")]
    origins = sorted({o.strip().rstrip("/") for o in raw if o.strip()})
    if "*" in origins:
        raise RuntimeError("Wildcard CORS origin is not allowed; set FRONTEND_URL / CORS_ORIGINS explicitly.")
    return origins or ["http://localhost:3000"]


CORS_ORIGINS = _origins()
# Abuse protection (in-memory, so limits apply per server instance).
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "10"))
RATE_LIMIT_PER_DAY = int(os.getenv("RATE_LIMIT_PER_DAY", "150"))
MAX_QUESTION_CHARS = 500
SQL_MAX_ROWS = int(os.getenv("SQL_MAX_ROWS", "500"))
SQL_TIMEOUT_S = float(os.getenv("SQL_TIMEOUT_S", "10"))


def openai_enabled() -> bool:
    return bool(os.getenv("OPENAI_API_KEY")) and os.getenv("ABI_DISABLE_OPENAI", "0") != "1"
