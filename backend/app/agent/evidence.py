"""Builds the Evidence object from tool output and validates it."""

from __future__ import annotations

import math
import re
from typing import Any

from app.agent.planner import ALL_DATA
from app.agent.schemas import Evidence, ParsedQuestion, ToolResult, ValidationCheck
from app.tools.sql import QuerySpec, compile_spec, run_sql

TABLE_RE = re.compile(r"\b(?:FROM|JOIN)\s+(\w+)", re.IGNORECASE)


def _finite(obj: Any) -> bool:
    if isinstance(obj, float):
        return math.isfinite(obj)
    if isinstance(obj, dict):
        return all(_finite(v) for v in obj.values())
    if isinstance(obj, list):
        return all(_finite(v) for v in obj)
    return True


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def headline_for(pq: ParsedQuestion, r: ToolResult) -> dict:
    d, rows, i = r.data, r.rows, pq.intent
    m = pq.metrics[0]
    if i == "metric_total":
        h = {"metric": m, "total": rows[0][m]}
        if pq.filters:
            h["filter"] = "; ".join(f"{f.dimension}={', '.join(f.values)}" for f in pq.filters)
        return h
    if i == "revenue_ranking":
        dim = (pq.dimensions or ["region"])[0]
        key = "product" if dim == "product" else dim
        top = rows[0]
        h = {"metric": m, "dimension": dim, "leader": top[key], "leader_value": top[m], "groups_returned": len(rows)}
        if len(rows) > 1:
            h.update(runner_up=rows[1][key], runner_up_value=rows[1][m], gap_to_runner_up=round(top[m] - rows[1][m], 2))
        return h
    if i == "top_products":
        return {"metric": m, "dimension": "product", "top_product": rows[0]["product"], "top_value": rows[0][m],
                "top_share_pct": round(rows[0]["share_pct"], 2), "n": len(rows),
                "top_n_share_pct": round(sum(x["share_pct"] for x in rows), 2), "total": d["total"]}
    if i == "growth_ranking":
        dim = d["dimension"]
        key = "product" if dim == "product" else dim
        eligible = [x for x in rows if not x["small_base"] and x["growth_pct"] is not None]
        h = {"metric": m, "dimension": dim, "current_total": d["current_total"], "previous_total": d["previous_total"],
             "overall_growth_pct": round((d["current_total"] - d["previous_total"]) / d["previous_total"] * 100, 2)}
        if eligible:
            h.update(fastest=eligible[0][key], fastest_growth_pct=round(eligible[0]["growth_pct"], 2),
                     fastest_current=eligible[0]["current_value"], fastest_previous=eligible[0]["previous_value"])
            if len(eligible) > 1:
                h.update(second=eligible[1][key], second_growth_pct=round(eligible[1]["growth_pct"], 2),
                         gap_pct_points=round(eligible[0]["growth_pct"] - eligible[1]["growth_pct"], 2))
        return h
    if i in ("period_change", "drivers"):
        h = {k: d[k] for k in ("metric", "previous_total", "current_total", "change", "change_pct")}
        h["direction"] = "increase" if d["change"] > 0 else "decrease" if d["change"] < 0 else "no change"
        first_dim = "category" if i == "drivers" else "region"
        dims = d.get(f"by_{first_dim}", [])
        if dims:
            h[f"largest_{first_dim}_contributor"] = dims[0]["name"]
            h[f"largest_{first_dim}_change"] = dims[0]["change"]
        prods = d.get("by_product", [])
        pos = [p for p in prods if p["change"] > 0]
        neg = [p for p in prods if p["change"] < 0]
        if pos:
            top = max(pos, key=lambda p: p["change"])
            h.update(top_positive_product=top["name"], top_positive_product_change=top["change"])
        if neg:
            low = min(neg, key=lambda p: p["change"])
            h.update(top_negative_product=low["name"], top_negative_product_change=low["change"])
        if pq.filters:
            h["filter"] = "; ".join(f"{f.dimension}={', '.join(f.values)}" for f in pq.filters)
        return h
    if i == "trend":
        return {k: v for k, v in d.items()}
    if i == "segment_value":
        top = rows[0]
        return {"top_segment": top["segment"], "top_segment_label": top["label"], "top_segment_customers": top["customers"],
                "top_segment_revenue": top["revenue"], "top_segment_revenue_share_pct": round(top["revenue_share_pct"], 2),
                "top_segment_customer_share_pct": round(top["customer_share_pct"], 2),
                "top_segment_median_recency_days": top["median_recency_days"], "top_segment_median_frequency": top["median_frequency"],
                "top_segment_median_monetary": top["median_monetary"], "k": d["k"], "silhouette": d["silhouette"],
                "customers_segmented": d["customers"]}
    if i == "anomaly":
        if not d.get("anomalies_found"):
            return {"anomalies_found": 0}
        keys = ["date", "weekday", "revenue", "expected", "deviation", "robust_z", "direction", "iqr_flag", "anomalies_found",
                "largest_order_share_pct", "top_product_cancelled_units"]
        h = {k: d[k] for k in keys}
        if d["by_region"]:
            h.update(top_region=d["by_region"][0]["region"], top_region_deviation=round(d["by_region"][0]["deviation"], 2))
        if d["top_products"]:
            tp = d["top_products"][0]
            h.update(top_product=tp["product"], top_product_revenue=tp["day_revenue"], top_product_units=tp["units"])
        if d["top_orders"]:
            h.update(largest_order_invoice=d["top_orders"][0]["invoice_id"], largest_order_revenue=d["top_orders"][0]["order_revenue"])
        return h
    if i == "forecast":
        keys = ["horizon_days", "best_model", "best_label", "best_mae", "best_rmse", "baseline_mae", "baseline_rmse",
                "beats_baseline", "forecast_total", "holdout_start", "holdout_end", "best_mape_pct",
                "interval_level_pct", "interval_error_low", "interval_error_high"]
        h = {k: d[k] for k in keys}
        h["forecast_start"], h["forecast_end"] = d["forecast"][0]["day"], d["forecast"][-1]["day"]
        return h
    if i in ("campaign_effect", "compare_groups"):
        keys = ["group_a", "group_b", "n_a", "n_b", "mean_a", "mean_b", "median_a", "median_b", "mean_difference", "ci95_low",
                "ci95_high", "primary_test", "primary_p", "significant", "cohens_d", "effect_size_label", "mann_whitney_p", "welch_p"]
        h = {k: d[k] for k in keys}
        for extra in ("higher_group", "relative_difference_pct", "window", "total_revenue_a", "total_revenue_b"):
            if extra in d:
                h[extra] = d[extra]
        return h
    if i == "association":
        return {k: d[k] for k in ("chi2", "p_value", "dof", "cramers_v", "n", "significant", "effect_size_label")}
    if i == "correlation":
        return {k: d[k] for k in ("n", "pearson_r", "pearson_p", "pearson_ci95", "spearman_rho", "spearman_p")}
    return {}


def build_evidence(question: str, pq: ParsedQuestion, results: list[ToolResult]) -> Evidence:
    r = results[0]
    periods = {}
    if pq.time_period:
        periods["current" if pq.comparison_period else "period"] = f"{pq.time_period.label} ({pq.time_period.start} to {pq.time_period.end} exclusive)"
    elif pq.intent in ("metric_total", "revenue_ranking", "top_products"):
        periods["period"] = ALL_DATA
    if pq.comparison_period:
        periods["comparison"] = f"{pq.comparison_period.label} ({pq.comparison_period.start} to {pq.comparison_period.end} exclusive)"
    sql = [s for x in results for s in x.sql]
    tables = sorted({t.lower() for s in sql for t in TABLE_RE.findall(s.sql)})
    if not r.ok:
        return Evidence(question=question, status="no_answer" if r.no_answer else "error", analysis_type=pq.intent,
                        method=r.method or "none", sql=sql, tables=tables, periods=periods, tools_used=[x.tool for x in results],
                        no_answer_reason=r.error or "The analysis could not be completed.", limitations=r.limitations)
    stats = {k: v for k, v in r.data.items() if k not in ("series", "daily_series", "forecast", "history_tail", "holdout", "campaigns",
                                                       "by_region", "by_product", "by_category", "top_orders", "top_products")}
    rows = r.rows[:60]
    ev = Evidence(question=question, status="answered", analysis_type=pq.intent, method=r.method,
                  headline=_sanitize(headline_for(pq, r)), supporting_data=_sanitize(rows),
                  columns=list(rows[0].keys()) if rows else [], stats=_sanitize(stats), sql=sql, periods=periods, tables=tables,
                  limitations=r.limitations, tools_used=[x.tool for x in results])
    if pq.intent == "anomaly":
        ev.stats["top_products"] = r.data.get("top_products", [])
        ev.stats["top_orders"] = r.data.get("top_orders", [])
    if pq.intent == "campaign_effect":
        ev.stats["campaigns"] = r.data.get("campaigns", [])
    if pq.intent == "forecast":
        ev.supporting_data = r.data["forecast"]
        ev.columns = ["day", "forecast"]
    return ev


def validate_evidence(ev: Evidence, pq: ParsedQuestion) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []
    if ev.status != "answered":
        return [ValidationCheck(name="analysis completed", passed=False, detail=ev.no_answer_reason or "")]
    checks.append(ValidationCheck(name="result is non-empty", passed=bool(ev.supporting_data or ev.headline)))
    checks.append(ValidationCheck(name="all numbers finite", passed=_finite(ev.headline) and _finite(ev.supporting_data)))
    checks.append(ValidationCheck(name="every query passed the SQL safety layer", passed=all(s.sql.lstrip().upper().startswith(("SELECT", "WITH")) for s in ev.sql),
                                  detail=f"{len(ev.sql)} validated quer{'y' if len(ev.sql) == 1 else 'ies'}"))
    if pq.intent == "revenue_ranking" and not pq.filters:
        # reconcile: sum over all groups == overall total (independent query)
        dim = (pq.dimensions or ["region"])[0]
        m = pq.metrics[0]
        if m in ("revenue", "quantity"):
            full, _ = run_sql("reconcile groups", *compile_spec(QuerySpec(metric=m, group_by=[dim], period=pq.time_period, limit=500)))
            tot, _ = run_sql("reconcile total", *compile_spec(QuerySpec(metric=m, period=pq.time_period, limit=1)))
            a, b = float(full[m].sum()), float(tot[m].iloc[0])
            checks.append(ValidationCheck(name="group totals reconcile with overall total", passed=abs(a - b) <= max(0.01, 1e-6 * abs(b)),
                                          detail=f"sum of groups {a:,.2f} vs total {b:,.2f}"))
    if pq.intent in ("period_change", "drivers"):
        d = ev.stats
        ok = abs(d["current_total"] - d["previous_total"] - d["change"]) < 0.05
        checks.append(ValidationCheck(name="change = current - previous", passed=ok))
    if pq.intent == "growth_ranking":
        checks.append(ValidationCheck(name="at least one group large enough to rank", passed="fastest" in ev.headline,
                                      detail="groups under 1% of the comparison total are not ranked"))
    if pq.intent == "forecast":
        checks.append(ValidationCheck(name="forecast length equals horizon", passed=len(ev.supporting_data) == ev.headline["horizon_days"]))
        checks.append(ValidationCheck(name="forecast values non-negative", passed=all(r["forecast"] >= 0 for r in ev.supporting_data)))
    if pq.intent in ("compare_groups", "campaign_effect"):
        checks.append(ValidationCheck(name="minimum sample size per group (8)", passed=min(ev.headline["n_a"], ev.headline["n_b"]) >= 8))
        checks.append(ValidationCheck(name="p-value within [0, 1]", passed=0 <= ev.headline["primary_p"] <= 1))
    if pq.intent == "segment_value":
        checks.append(ValidationCheck(name="segment customers sum to total", passed=sum(r["customers"] for r in ev.supporting_data) == ev.headline["customers_segmented"]))
    return checks
