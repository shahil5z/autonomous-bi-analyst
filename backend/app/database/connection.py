"""Read-only DuckDB access with a statement timeout."""

from __future__ import annotations

import threading
from datetime import date
from functools import lru_cache

import duckdb
import pandas as pd

from app import config


class DatabaseError(RuntimeError):
    pass


_lock = threading.Lock()
_base: duckdb.DuckDBPyConnection | None = None
_base_path: str | None = None


def _connection() -> duckdb.DuckDBPyConnection:
    global _base, _base_path
    path = str(config.DB_PATH)
    with _lock:
        if _base is None or _base_path != path:
            if not config.DB_PATH.exists():
                raise DatabaseError("Database file not found. Run scripts/run_pipeline.py first.")
            _base = duckdb.connect(path, read_only=True, config={"enable_external_access": "false"})
            _base.execute("SET lock_configuration = true")
            _base_path = path
        return _base


def reset_connection() -> None:
    global _base, _base_path
    with _lock:
        if _base is not None:
            _base.close()
        _base, _base_path = None, None
    data_range.cache_clear()
    distinct_values.cache_clear()


def execute(sql: str, params: list | None = None, timeout_s: float | None = None) -> pd.DataFrame:
    """Execute an already-validated SELECT on a read-only cursor."""
    cur = _connection().cursor()
    timer = threading.Timer(timeout_s or config.SQL_TIMEOUT_S, cur.interrupt)
    timer.start()
    try:
        return cur.execute(sql, params or []).fetchdf()
    except duckdb.InterruptException as exc:
        raise DatabaseError("Query exceeded the time limit.") from exc
    except duckdb.Error as exc:
        raise DatabaseError(f"Database error: {type(exc).__name__}") from exc
    finally:
        timer.cancel()
        cur.close()


@lru_cache(maxsize=1)
def data_range() -> tuple[date, date]:
    row = execute("SELECT MIN(invoice_date) AS lo, MAX(invoice_date) AS hi FROM sales").iloc[0]
    return pd.Timestamp(row["lo"]).date(), pd.Timestamp(row["hi"]).date()


@lru_cache(maxsize=8)
def distinct_values(table: str, column: str) -> tuple[str, ...]:
    from app.database.schema import ALLOWED_SCHEMA

    if column not in ALLOWED_SCHEMA.get(table, {}):
        raise DatabaseError("Column not allowlisted")
    df = execute(f"SELECT DISTINCT {column} AS v FROM {table} WHERE {column} IS NOT NULL ORDER BY 1")
    return tuple(str(v) for v in df["v"])
