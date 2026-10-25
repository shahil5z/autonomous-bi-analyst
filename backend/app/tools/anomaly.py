"""Anomaly Detection Tool: rolling robust z-score (median/MAD) with an IQR cross-check,
then drill-down into region and product contributions for the largest deviation."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.agent.schemas import ToolResult
from app.database.connection import DatabaseError
from app.tools.sql import records, run_sql
from app.tools.sql_safety import SQLValidationError
from app.tools.timeseries import daily_series

WINDOW = 28
THRESHOLD = 3.5


def robust_anomalies(values: pd.Series, window: int = WINDOW, threshold: float = THRESHOLD) -> pd.DataFrame:
    """Trailing-window robust z-score (current point excluded from its own baseline)."""
    prev = values.shift(1)
    med = prev.rolling(window, min_periods=window).median()
    mad = prev.rolling(window, min_periods=window).apply(lambda w: np.median(np.abs(w - np.median(w))), raw=True)
    q1 = prev.rolling(window, min_periods=window).quantile(0.25)
    q3 = prev.rolling(window, min_periods=window).quantile(0.75)
    iqr = q3 - q1
    z = 0.6745 * (values - med) / mad.replace(0, np.nan)
    out = pd.DataFrame({"value": values, "expected": med, "robust_z": z,
                        "iqr_low": q1 - 1.5 * iqr, "iqr_high": q3 + 1.5 * iqr})
    out["is_anomaly"] = out["robust_z"].abs() > threshold
    out["iqr_flag"] = (values < out["iqr_low"]) | (values > out["iqr_high"])
    return out


def detect_largest_anomaly() -> ToolResult:
    try:
        df, rec = daily_series("revenue")
    except (SQLValidationError, DatabaseError) as exc:
        return ToolResult(tool="anomaly", ok=False, error=str(exc))
    s = df.set_index("day")["value"].astype(float)  # trading days only
    res = robust_anomalies(s)
    flagged = res[res["is_anomaly"]]
    if flagged.empty:
        return ToolResult(tool="anomaly", ok=True, sql=[rec], method="rolling_robust_z",
                          data={"anomalies_found": 0, "threshold": THRESHOLD},
                          limitations=["No day exceeded the robust z threshold."])
    top_day = flagged["robust_z"].abs().idxmax()
    row = res.loc[top_day]
    day = top_day.date()
    win_start = (top_day - pd.Timedelta(days=WINDOW * 2)).date()
    sqls = [rec]
    try:
        reg, r1 = run_sql("region revenue on anomaly day vs trailing baseline",
                          "SELECT s.region AS region, SUM(CASE WHEN s.invoice_date = ? THEN s.revenue ELSE 0 END) AS day_revenue, "
                          "SUM(CASE WHEN s.invoice_date < ? THEN s.revenue ELSE 0 END) AS baseline_window_revenue "
                          "FROM sales s WHERE s.invoice_date >= ? AND s.invoice_date <= ? GROUP BY s.region",
                          [day, day, win_start, day])
        prod, r2 = run_sql("top products on anomaly day",
                           "SELECT s.product_id AS product_id, p.description AS product, SUM(s.revenue) AS day_revenue, "
                           "SUM(s.quantity) AS units, COUNT(DISTINCT s.customer_id) AS customers "
                           "FROM sales s LEFT JOIN products p ON p.product_id = s.product_id WHERE s.invoice_date = ? "
                           "GROUP BY s.product_id, p.description ORDER BY day_revenue DESC LIMIT 5", [day])
        cust, r3 = run_sql("largest orders on anomaly day",
                           "SELECT s.invoice_id AS invoice_id, s.country AS country, SUM(s.revenue) AS order_revenue "
                           "FROM sales s WHERE s.invoice_date = ? GROUP BY s.invoice_id, s.country ORDER BY order_revenue DESC LIMIT 5", [day])
        sqls += [r1, r2, r3]
        canc = pd.DataFrame()
        if len(prod):
            canc, r4 = run_sql("cancellations of the top product by the same customers within 30 days",
                               "SELECT c.invoice_id AS invoice_id, c.invoice_date AS invoice_date, c.quantity AS quantity FROM cancellations c "
                               "WHERE c.product_id = ? AND c.invoice_date >= ? AND c.invoice_date <= ? AND c.customer_id IN "
                               "(SELECT s.customer_id FROM sales s WHERE s.invoice_date = ? AND s.product_id = ?) ORDER BY c.quantity DESC LIMIT 5",
                               [prod["product_id"].iloc[0], day, day + pd.Timedelta(days=30).to_pytimedelta(), day, prod["product_id"].iloc[0]])
            sqls.append(r4)
    except (SQLValidationError, DatabaseError) as exc:
        return ToolResult(tool="anomaly", ok=False, error=str(exc), sql=sqls)
    trading_days = int(((s.index >= pd.Timestamp(win_start)) & (s.index < top_day)).sum())
    reg["baseline_daily_revenue"] = reg.pop("baseline_window_revenue") / max(trading_days, 1)
    reg["deviation"] = reg["day_revenue"] - reg["baseline_daily_revenue"]
    reg = reg.sort_values("deviation", key=abs, ascending=False)
    total_dev = float(row["value"] - row["expected"])
    reg["share_of_deviation_pct"] = reg["deviation"] / total_dev * 100 if total_dev else None
    top_order_share = float(cust["order_revenue"].iloc[0] / row["value"] * 100) if len(cust) else None
    series = res.reset_index().rename(columns={"index": "day"})
    series = series.assign(day=series["day"].dt.strftime("%Y-%m-%d"))[["day", "value", "expected", "is_anomaly"]]
    data = {
        "date": day.isoformat(), "weekday": top_day.day_name(), "revenue": round(float(row["value"]), 2),
        "expected": round(float(row["expected"]), 2), "deviation": round(total_dev, 2),
        "robust_z": round(float(row["robust_z"]), 2), "direction": "above" if total_dev > 0 else "below",
        "iqr_flag": bool(row["iqr_flag"]), "anomalies_found": int(len(flagged)), "threshold": THRESHOLD,
        "cancellation_window_days": 30, "window_trading_days": WINDOW, "by_region": records(reg), "top_products": records(prod),
        "top_orders": records(cust), "largest_order_share_pct": round(top_order_share, 2) if top_order_share else None,
        "series": records(series.tail(120)),
        "top_product_cancelled_units": int(canc["quantity"].sum()) if len(canc) else 0,
        "top_product_cancellation_invoices": [str(x) for x in canc["invoice_id"]] if len(canc) else [],
        "other_anomalies": [{"date": d.date().isoformat(), "robust_z": round(float(z), 2)}
                            for d, z in flagged["robust_z"].abs().sort_values(ascending=False).iloc[1:6].items()],
    }
    return ToolResult(tool="anomaly", ok=True, data=data, rows=records(reg), sql=sqls, method="rolling_robust_z_with_iqr_check",
                      limitations=["Baseline = median of the previous 28 trading days; holidays and seasonality are not modelled.",
                                   "Region baselines are average daily revenue over the preceding ~8 weeks of trading days.",
                                   "Drill-down shows where the deviation occurred, not why it occurred.",
                                   "Cancellations are removed from sales rather than netted, so a large order that was later cancelled still counts as revenue."])
