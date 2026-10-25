"""Local storage of analysis runs (SQLite). No API keys or personal data are stored."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from threading import Lock

from app import config

_lock = Lock()
SCHEMA = """CREATE TABLE IF NOT EXISTS analysis_runs (
  id TEXT PRIMARY KEY, question TEXT NOT NULL, created_at TEXT NOT NULL, plan TEXT NOT NULL,
  tools_used TEXT NOT NULL, evidence TEXT NOT NULL, final_answer TEXT NOT NULL, response TEXT NOT NULL)"""


def _conn() -> sqlite3.Connection:
    config.RUNS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.RUNS_DB_PATH)
    con.execute(SCHEMA)
    return con


def save_run(response: dict) -> None:
    with _lock, _conn() as con:
        con.execute("INSERT OR REPLACE INTO analysis_runs VALUES (?,?,?,?,?,?,?,?)", (
            response["run_id"], response["question"], datetime.now(UTC).isoformat(timespec="seconds"),
            json.dumps(response["plan"]), json.dumps(response["evidence"]["tools_used"]), json.dumps(response["evidence"]),
            response["explanation"]["answer"], json.dumps(response)))


def get_run(run_id: str) -> dict | None:
    with _lock, _conn() as con:
        row = con.execute("SELECT response, created_at FROM analysis_runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        return None
    out = json.loads(row[0])
    out["created_at"] = row[1]
    return out
