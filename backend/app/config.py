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

DB_PATH = Path(os.getenv("ABI_DB_PATH", ROOT / "data" / "processed" / "abi.duckdb"))
RUNS_DB_PATH = Path(os.getenv("ABI_RUNS_DB_PATH", ROOT / "data" / "processed" / "analysis_runs.sqlite"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_TIMEOUT_S = float(os.getenv("OPENAI_TIMEOUT_S", "20"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
SQL_MAX_ROWS = int(os.getenv("SQL_MAX_ROWS", "500"))
SQL_TIMEOUT_S = float(os.getenv("SQL_TIMEOUT_S", "10"))


def openai_enabled() -> bool:
    return bool(os.getenv("OPENAI_API_KEY")) and os.getenv("ABI_DISABLE_OPENAI", "0") != "1"
