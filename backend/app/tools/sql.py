"""SQL Query Tool: compiles a structured QuerySpec into a parameterised SELECT,
validates it with the safety layer and runs it on the read-only connection."""

from __future__ import annotations

from datetime import date
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from app import config
from app.agent.schemas import Filter, Metric, Period, SQLRecord, ToolResult
from app.database import connection
from app.tools.sql_safety import SQLValidationError, validate_sql

GroupBy = Literal["region", "country", "product", "category", "year", "quarter", "month"]

METRIC_SQL: dict[str, str] = {
    "revenue": "SUM(s.revenue)",
    "quantity": "SUM(s.quantity)",
    "orders": "COUNT(DISTINCT s.invoice_id)",
    "customers": "COUNT(DISTINCT s.customer_id)",
}
GROUP_SQL: dict[str, list[tuple[str, str]]] = {
    "region": [("s.region", "region")],
    "country": [("s.country", "country")],
    "product": [("s.product_id", "product_id"), ("p.description", "product")],
    "category": [("p.category", "category")],
    "year": [("EXTRACT(YEAR FROM s.invoice_date)", "year")],
    "quarter": [("CAST(date_trunc('quarter', s.invoice_date) AS DATE)", "quarter_start")],
    "month": [("CAST(date_trunc('month', s.invoice_date) AS DATE)", "month_start")],
}
FILTER_COLUMN = {"region": "s.region", "country": "s.country", "category": "p.category", "product": "p.description"}
NEEDS_PRODUCTS = {"product", "category"}


class QuerySpec(BaseModel):
    metric: Metric = "revenue"
    group_by: list[GroupBy] = Field(default_factory=list, max_length=2)
    filters: list[Filter] = Field(default_factory=list)
    period: Period | None = None
    order: Literal["desc", "asc"] = "desc"
    limit: int = Field(default=20, ge=1, le=500)


def _literal(v: object) -> str:
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def display_sql(sql: str, params: list) -> str:
    out, i = [], 0
    for ch in sql:
        if ch == "?" and i < len(params):
            out.append(_literal(params[i]))
            i += 1
        else:
            out.append(ch)
    return "".join(out)


def canonical_filter_values(f: Filter) -> list[str]:
    """Match user/LLM filter values against real distinct values (case-insensitive)."""
    table, col = {"region": ("sales", "region"), "country": ("sales", "country"),
                  "category": ("products", "category"), "product": ("products", "description")}[f.dimension]
    known = {v.lower(): v for v in connection.distinct_values(table, col)}
    out = []
    for v in f.values:
        match = known.get(v.strip().lower())
        if match is None:
            raise SQLValidationError(f"Unknown {f.dimension} value.")
        out.append(match)
    return out


def period_clause(period: Period | None, params: list) -> str | None:
    if period is None:
        return None
    params.extend([period.start, period.end])
    return "s.invoice_date >= ? AND s.invoice_date < ?"


def filter_clauses(filters: list[Filter], params: list) -> list[str]:
    clauses = []
    for f in filters:
        values = canonical_filter_values(f)
        clauses.append(f"{FILTER_COLUMN[f.dimension]} IN ({', '.join('?' for _ in values)})")
        params.extend(values)
    return clauses


def compile_spec(spec: QuerySpec) -> tuple[str, list]:
    params: list = []
    select, group = [], []
    for g in spec.group_by:
        for expr, alias in GROUP_SQL[g]:
            select.append(f"{expr} AS {alias}")
            group.append(expr)
    select.append(f"{METRIC_SQL[spec.metric]} AS {spec.metric}")
    needs_p = any(g in NEEDS_PRODUCTS for g in spec.group_by) or any(f.dimension in NEEDS_PRODUCTS for f in spec.filters)
    sql = "SELECT " + ", ".join(select) + " FROM sales s"
    if needs_p:
        sql += " LEFT JOIN products p ON p.product_id = s.product_id"
    where = []
    pc = period_clause(spec.period, params)
    if pc:
        where.append(pc)
    where += filter_clauses(spec.filters, params)
    if where:
        sql += " WHERE " + " AND ".join(where)
    if group:
        sql += " GROUP BY " + ", ".join(group)
        time_group = spec.group_by and spec.group_by[0] in ("year", "quarter", "month")
        sql += " ORDER BY 1 ASC" if time_group else f" ORDER BY {spec.metric} {spec.order.upper()}"
    sql += f" LIMIT {spec.limit}"
    return sql, params


def run_sql(purpose: str, sql: str, params: list | None = None, max_rows: int | None = None) -> tuple[pd.DataFrame, SQLRecord]:
    """Validate then execute. Every tool goes through this single gate."""
    params = params or []
    safe_sql = validate_sql(sql, max_rows=max_rows or config.SQL_MAX_ROWS)
    df = connection.execute(safe_sql, params)
    clean_params = [p.isoformat() if isinstance(p, date) else p for p in params]
    record = SQLRecord(purpose=purpose, sql=safe_sql, params=clean_params,
                       display_sql=display_sql(safe_sql, clean_params), row_count=len(df))
    return df, record


def records(df: pd.DataFrame) -> list[dict]:
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d")
        elif out[col].dtype == object:
            out[col] = out[col].map(lambda v: v.isoformat() if isinstance(v, date) else v)
        elif pd.api.types.is_float_dtype(out[col]):
            out[col] = out[col].round(4)
    out = out.astype(object).where(pd.notna(out), None)
    return out.to_dict(orient="records")


def query_tool(spec: QuerySpec) -> ToolResult:
    try:
        sql, params = compile_spec(spec)
        df, rec = run_sql(f"{spec.metric} by {', '.join(spec.group_by) or 'total'}", sql, params)
    except (SQLValidationError, connection.DatabaseError) as exc:
        return ToolResult(tool="sql_query", ok=False, error=str(exc))
    if df.empty:
        return ToolResult(tool="sql_query", ok=False, no_answer=True, sql=[rec],
                          error="The query returned no rows for the requested filters/period.")
    return ToolResult(tool="sql_query", ok=True, rows=records(df), sql=[rec], method="sql_aggregation",
                      data={"metric": spec.metric, "group_by": spec.group_by})
