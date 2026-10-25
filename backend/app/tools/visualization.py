"""Chart Generation Tool: builds a declarative ChartSpec only when a chart helps."""

from __future__ import annotations

from app.agent.schemas import ChartSpec, Evidence

MAX_POINTS = 400


def build_chart(evidence: Evidence, data: dict) -> ChartSpec | None:
    t = evidence.analysis_type
    rows = evidence.supporting_data
    try:
        if t == "revenue_ranking" and len(rows) > 1:
            dim = evidence.headline.get("dimension", "region")
            label = "product" if dim == "product" else dim
            return ChartSpec(type="bar", title=f"{evidence.headline.get('metric', 'revenue').title()} by {dim}", x=label,
                             y=[evidence.headline.get("metric", "revenue")], data=rows[:15])
        if t == "top_products":
            return ChartSpec(type="bar", title="Top products", x="product", y=[evidence.headline["metric"]], data=rows[:15])
        if t == "growth_ranking":
            dim = evidence.headline["dimension"]
            key = "product" if dim == "product" else dim
            pts = [{key: r[key], "growth_pct": r["growth_pct"]} for r in rows if r.get("growth_pct") is not None and not r.get("small_base")]
            omitted = sum(1 for r in rows if r.get("small_base"))
            return ChartSpec(type="bar", title=f"Growth by {dim} (%)", x=key, y=["growth_pct"], data=pts[:15], y_label="%",
                             note=f"{omitted} small-base group(s) omitted from the chart (see View Data)." if omitted else None)
        if t in ("period_change", "drivers"):
            pts = [{"name": r["name"], "change": r["change"]} for r in rows if r["dimension"] in ("region", "product", "category")]
            dim_rows = [r for r in rows if r["dimension"] == ("category" if t == "drivers" else "region")]
            pts = [{"name": r["name"], "change": r["change"]} for r in dim_rows] or pts
            return ChartSpec(type="bar", title="Contribution to change", x="name", y=["change"], data=pts[:12])
        if t == "trend":
            return ChartSpec(type="area", title="Monthly trend", x="month", y=["value"], data=rows)
        if t == "forecast":
            hist = [{"day": r["day"], "actual": r["actual"]} for r in data.get("history_tail", [])]
            fc = [{"day": r["day"], "forecast": r["forecast"]} for r in data.get("forecast", [])]
            return ChartSpec(type="line", title="Daily revenue: recent history and forecast", x="day", y=["actual", "forecast"],
                             data=hist + fc, note="Zero values are days with no trading (mostly Saturdays).")
        if t == "anomaly" and data.get("series"):
            pts = [{"day": r["day"], "revenue": r["value"], "expected": r["expected"]} for r in data["series"]]
            return ChartSpec(type="line", title="Daily revenue vs rolling expected value", x="day", y=["revenue", "expected"],
                             data=pts[-MAX_POINTS:], note=f"Largest anomaly on {data.get('date')}")
        if t == "segment_value":
            return ChartSpec(type="bar", title="Revenue by customer segment", x="segment", y=["revenue"], data=rows)
        if t == "campaign_effect":
            pts = data.get("daily_series", [])
            return ChartSpec(type="line", title="Daily revenue (campaign days flagged)", x="day", y=["revenue"],
                             data=pts[-MAX_POINTS:], note="Shaded/flagged points are synthetic campaign days.")
        if t == "compare_groups":
            return ChartSpec(type="box", title="Order value distribution (whiskers at 1.5 IQR)", x="group",
                             y=["min", "q1", "median", "q3", "max"], data=rows)
        if t == "association":
            return ChartSpec(type="heatmap", title="Category share of order lines by region (%)", x="category",
                             y=["region"], data=rows)
        if t == "correlation":
            return ChartSpec(type="scatter", title="Average price vs units sold (sample of products)", x="avg_price",
                             y=["units"], data=rows, note="Axes use log scale.")
    except (KeyError, TypeError, ValueError):
        return None
    return None
