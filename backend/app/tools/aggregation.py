"""Aggregation Tool: top-N, period-over-period growth and decomposition of change."""

from __future__ import annotations

import pandas as pd

from app.agent.schemas import Filter, Period, SQLRecord, ToolResult
from app.database.connection import DatabaseError
from app.tools.sql import GROUP_SQL, METRIC_SQL, NEEDS_PRODUCTS, filter_clauses, records, run_sql
from app.tools.sql_safety import SQLValidationError

SMALL_BASE_SHARE = 0.01  # groups below 1% of the previous-period total are flagged


def _metric_in(metric: str, cond: str) -> str:
    if metric == "revenue":
        return f"SUM(CASE WHEN {cond} THEN s.revenue ELSE 0 END)"
    if metric == "quantity":
        return f"SUM(CASE WHEN {cond} THEN s.quantity ELSE 0 END)"
    col = "s.invoice_id" if metric == "orders" else "s.customer_id"
    return f"COUNT(DISTINCT CASE WHEN {cond} THEN {col} END)"


def _two_period_sql(metric: str, dimension: str | None, current: Period, previous: Period,
                    filters: list[Filter]) -> tuple[str, list]:
    params: list = []
    cond = "s.invoice_date >= ? AND s.invoice_date < ?"
    select, group = [], []
    if dimension:
        for expr, alias in GROUP_SQL[dimension]:
            select.append(f"{expr} AS {alias}")
            group.append(expr)
    select.append(f"{_metric_in(metric, cond)} AS current_value")
    select.append(f"{_metric_in(metric, cond)} AS previous_value")
    params += [current.start, current.end, previous.start, previous.end]
    sql = "SELECT " + ", ".join(select) + " FROM sales s"
    if (dimension in NEEDS_PRODUCTS) or any(f.dimension in NEEDS_PRODUCTS for f in filters):
        sql += " LEFT JOIN products p ON p.product_id = s.product_id"
    where = [f"(({cond}) OR ({cond}))"]
    params += [current.start, current.end, previous.start, previous.end]
    where += filter_clauses(filters, params)
    sql += " WHERE " + " AND ".join(where)
    if group:
        sql += " GROUP BY " + ", ".join(group)
    return sql, params


def _with_growth(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["change"] = df["current_value"] - df["previous_value"]
    df["growth_pct"] = (df["change"] / df["previous_value"].where(df["previous_value"] != 0)) * 100
    return df


def top_n(metric: str, dimension: str, period: Period | None, n: int, filters: list[Filter]) -> ToolResult:
    params: list = []
    cols = GROUP_SQL[dimension]
    select = ", ".join(f"{e} AS {a}" for e, a in cols)
    sql = f"SELECT {select}, {METRIC_SQL[metric]} AS {metric}, COUNT(DISTINCT s.invoice_id) AS orders_count FROM sales s"
    if dimension in NEEDS_PRODUCTS or any(f.dimension in NEEDS_PRODUCTS for f in filters):
        sql += " LEFT JOIN products p ON p.product_id = s.product_id"
    where = []
    if period:
        where.append("s.invoice_date >= ? AND s.invoice_date < ?")
        params += [period.start, period.end]
    where += filter_clauses(filters, params)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " GROUP BY " + ", ".join(e for e, _ in cols) + f" ORDER BY {metric} DESC LIMIT {int(n)}"
    tparams: list = []
    tsql = f"SELECT {METRIC_SQL[metric]} AS total FROM sales s"
    if any(f.dimension in NEEDS_PRODUCTS for f in filters):
        tsql += " LEFT JOIN products p ON p.product_id = s.product_id"
    twhere = []
    if period:
        twhere.append("s.invoice_date >= ? AND s.invoice_date < ?")
        tparams += [period.start, period.end]
    twhere += filter_clauses(filters, tparams)
    if twhere:
        tsql += " WHERE " + " AND ".join(twhere)
    try:
        df, rec = run_sql(f"top {n} {dimension} by {metric}", sql, params)
        tot, trec = run_sql(f"total {metric} (for shares)", tsql, tparams)
    except (SQLValidationError, DatabaseError) as exc:
        return ToolResult(tool="aggregation", ok=False, error=str(exc))
    if df.empty:
        return ToolResult(tool="aggregation", ok=False, no_answer=True, sql=[rec, trec],
                          error="No rows for the requested period/filters.")
    total = float(tot["total"].iloc[0] or 0)
    df["share_pct"] = df[metric] / total * 100 if total else None
    return ToolResult(tool="aggregation", ok=True, rows=records(df), sql=[rec, trec], method="top_n_ranking",
                      data={"total": round(total, 2), "metric": metric, "dimension": dimension})


def growth(metric: str, dimension: str, current: Period, previous: Period, filters: list[Filter]) -> ToolResult:
    try:
        sql, params = _two_period_sql(metric, dimension, current, previous, filters)
        df, rec = run_sql(f"{metric} by {dimension} for two periods", sql, params)
    except (SQLValidationError, DatabaseError) as exc:
        return ToolResult(tool="aggregation", ok=False, error=str(exc))
    if df.empty or df["previous_value"].sum() == 0:
        return ToolResult(tool="aggregation", ok=False, no_answer=True, sql=[rec],
                          error="No data in the comparison period, so growth cannot be computed.")
    df = _with_growth(df)
    prev_total = df["previous_value"].sum()
    df["small_base"] = df["previous_value"] < SMALL_BASE_SHARE * prev_total
    ranked = pd.concat([
        df[~df["small_base"]].sort_values("growth_pct", ascending=False),
        df[df["small_base"]].sort_values("growth_pct", ascending=False),
    ])
    eligible = ranked[~ranked["small_base"] & ranked["growth_pct"].notna()]
    return ToolResult(
        tool="aggregation", ok=True, rows=records(ranked), sql=[rec], method="period_over_period_growth",
        data={"metric": metric, "dimension": dimension, "eligible_count": int(len(eligible)),
              "current_total": round(float(df["current_value"].sum()), 2),
              "previous_total": round(float(prev_total), 2)},
        limitations=[f"Groups with less than {SMALL_BASE_SHARE:.0%} of the comparison-period total are flagged as small base and not ranked."],
    )


def change_decomposition(metric: str, current: Period, previous: Period, filters: list[Filter],
                         dimensions: tuple[str, ...] = ("region", "product")) -> ToolResult:
    sqls: list[SQLRecord] = []
    out: dict = {"metric": metric}
    try:
        sql, params = _two_period_sql(metric, None, current, previous, filters)
        tot, rec = run_sql(f"total {metric} in both periods", sql, params)
        sqls.append(rec)
        cur, prev = float(tot["current_value"].iloc[0] or 0), float(tot["previous_value"].iloc[0] or 0)
        if prev == 0 and cur == 0:
            return ToolResult(tool="aggregation", ok=False, no_answer=True, sql=sqls,
                              error="No data in either period for these filters.")
        out.update(current_total=round(cur, 2), previous_total=round(prev, 2), change=round(cur - prev, 2),
                   change_pct=round((cur - prev) / prev * 100, 2) if prev else None)
        rows: list[dict] = []
        for dim in dimensions:
            sql, params = _two_period_sql(metric, dim, current, previous, filters)
            df, rec = run_sql(f"{metric} change by {dim}", sql, params, max_rows=5000)
            sqls.append(rec)
            df = _with_growth(df)
            total_change = cur - prev
            df["share_of_change_pct"] = df["change"] / total_change * 100 if total_change else None
            name_col = "product" if dim == "product" else dim
            df = df.rename(columns={name_col: "name"})
            df["dimension"] = dim
            keep = ["dimension", "name", "previous_value", "current_value", "change", "growth_pct", "share_of_change_pct"]
            if dim == "product":
                df = df.sort_values("change")
                df = pd.concat([df.head(5), df.tail(5)]).drop_duplicates(subset=["product_id"])
            df = df.reindex(df["change"].abs().sort_values(ascending=False).index)
            out[f"by_{dim}"] = records(df[keep])
            rows += out[f"by_{dim}"]
    except (SQLValidationError, DatabaseError) as exc:
        return ToolResult(tool="aggregation", ok=False, error=str(exc), sql=sqls)
    return ToolResult(tool="aggregation", ok=True, rows=rows, sql=sqls, method="change_decomposition", data=out,
                      limitations=["Contributions are additive differences between periods; they describe where the change happened, not why."])
