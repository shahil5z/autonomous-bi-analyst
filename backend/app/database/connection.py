"""Read-only DuckDB access with a statement timeout."""

from __future__ import annotations

import gzip
import os
import shutil
import tempfile
import threading
from datetime import date
from functools import lru_cache
from pathlib import Path

import duckdb
import pandas as pd

from app import config


class DatabaseError(RuntimeError):
    pass


_lock = threading.Lock()
_base: duckdb.DuckDBPyConnection | None = None
_base_path: str | None = None


def _resolve_db_path() -> Path:
    """Use DB_PATH if present, otherwise unpack the shipped gzip copy once into the temp dir (the only writable
    place on a serverless host). The temp file is replaced atomically so concurrent cold starts never see half a file."""
    if config.DB_PATH.exists():
        return config.DB_PATH
    packed = config.DB_GZ_PATH
    if not packed.exists():
        raise DatabaseError("Database file not found. Run scripts/run_pipeline.py first.")
    target = Path(tempfile.gettempdir()) / f"abi-{packed.stat().st_size}.duckdb"
    if not target.exists():
        partial = target.with_suffix(f".{os.getpid()}.part")
        with gzip.open(packed, "rb") as src, open(partial, "wb") as dst:
            shutil.copyfileobj(src, dst, length=1 << 20)
        partial.replace(target)
    return target


def _connection() -> duckdb.DuckDBPyConnection:
    global _base, _base_path
    with _lock:
        path = str(_resolve_db_path())
        if _base is None or _base_path != path:
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
