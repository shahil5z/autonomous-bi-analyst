"""Time-Series Tool: monthly and daily series with completeness checks."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.agent.schemas import Filter, ToolResult
from app.database.connection import DatabaseError, data_range
from app.tools.sql import METRIC_SQL, NEEDS_PRODUCTS, filter_clauses, records, run_sql
from app.tools.sql_safety import SQLValidationError


def daily_series(metric: str = "revenue", filters: list[Filter] | None = None) -> tuple[pd.DataFrame, object]:
    params: list = []
    filters = filters or []
    sql = f"SELECT s.invoice_date AS day, {METRIC_SQL[metric]} AS value FROM sales s"
    if any(f.dimension in NEEDS_PRODUCTS for f in filters):
        sql += " LEFT JOIN products p ON p.product_id = s.product_id"
    where = filter_clauses(filters, params)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " GROUP BY s.invoice_date ORDER BY s.invoice_date"
    df, rec = run_sql(f"daily {metric}", sql, params, max_rows=5000)
    df["day"] = pd.to_datetime(df["day"])
    return df, rec


def monthly_trend(metric: str, filters: list[Filter]) -> ToolResult:
    params: list = []
    sql = f"SELECT CAST(date_trunc('month', s.invoice_date) AS DATE) AS month_start, {METRIC_SQL[metric]} AS value FROM sales s"
    if any(f.dimension in NEEDS_PRODUCTS for f in filters):
        sql += " LEFT JOIN products p ON p.product_id = s.product_id"
    try:
        where = filter_clauses(filters, params)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " GROUP BY 1 ORDER BY 1"
        df, rec = run_sql(f"monthly {metric}", sql, params)
    except (SQLValidationError, DatabaseError) as exc:
        return ToolResult(tool="timeseries", ok=False, error=str(exc))
    if len(df) < 3:
        return ToolResult(tool="timeseries", ok=False, no_answer=True, sql=[rec], error="Not enough months of data.")
    df["month_start"] = pd.to_datetime(df["month_start"])
    _, hi = data_range()
    last_month_end = (df["month_start"].iloc[-1] + pd.offsets.MonthEnd(0)).date()
    partial = hi < last_month_end
    df["complete"] = True
    if partial:
        df.loc[df.index[-1], "complete"] = False
    full = df[df["complete"]].reset_index(drop=True)
    slope = float(np.polyfit(np.arange(len(full)), full["value"], 1)[0])
    peak, low = full.loc[full["value"].idxmax()], full.loc[full["value"].idxmin()]
    data = {
        "metric": metric, "months": int(len(full)),
        "first_month": full["month_start"].iloc[0].strftime("%Y-%m"), "first_value": round(float(full["value"].iloc[0]), 2),
        "last_month": full["month_start"].iloc[-1].strftime("%Y-%m"), "last_value": round(float(full["value"].iloc[-1]), 2),
        "peak_month": peak["month_start"].strftime("%Y-%m"), "peak_value": round(float(peak["value"]), 2),
        "low_month": low["month_start"].strftime("%Y-%m"), "low_value": round(float(low["value"]), 2),
        "mean_monthly_value": round(float(full["value"].mean()), 2), "linear_slope_per_month": round(slope, 2),
        "partial_last_month_excluded": bool(partial),
    }
    out = df.assign(month=df["month_start"].dt.strftime("%Y-%m"))[["month", "value", "complete"]]
    lim = ["The final month is partial and excluded from the summary." if partial else "",
           "A linear slope is a simple summary and ignores strong year-end seasonality."]
    return ToolResult(tool="timeseries", ok=True, data=data, rows=records(out), sql=[rec], method="monthly_aggregation",
                      limitations=[x for x in lim if x])
