"""Tool Router: maps plan steps to approved tool functions only."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.agent.schemas import Filter, Period, PlanStep, ToolResult
from app.tools import aggregation, anomaly, forecasting, segmentation, statistics, timeseries
from app.tools.sql import QuerySpec, query_tool


def _p(d: dict | None) -> Period | None:
    return Period(**d) if d else None


def _f(items: list[dict] | None) -> list[Filter]:
    return [Filter(**x) for x in (items or [])]


REGISTRY: dict[tuple[str, str], Callable[[dict[str, Any]], ToolResult]] = {
    ("sql_query", "query"): lambda p: query_tool(QuerySpec(metric=p["metric"], group_by=p["group_by"], filters=_f(p["filters"]),
                                                            period=_p(p["period"]), limit=p["limit"])),
    ("aggregation", "top_n"): lambda p: aggregation.top_n(p["metric"], p["dimension"], _p(p["period"]), p["n"], _f(p["filters"])),
    ("aggregation", "growth"): lambda p: aggregation.growth(p["metric"], p["dimension"], _p(p["current"]), _p(p["previous"]), _f(p["filters"])),
    ("aggregation", "change_decomposition"): lambda p: aggregation.change_decomposition(
        p["metric"], _p(p["current"]), _p(p["previous"]), _f(p["filters"]), tuple(p["dimensions"])),
    ("timeseries", "monthly_trend"): lambda p: timeseries.monthly_trend(p["metric"], _f(p["filters"])),
    ("segmentation", "rfm_kmeans"): lambda p: segmentation.segment_customers(),
    ("anomaly", "largest"): lambda p: anomaly.detect_largest_anomaly(),
    ("forecasting", "forecast"): lambda p: forecasting.forecast_revenue(int(p["horizon"])),
    ("statistics", "campaign_effect"): lambda p: statistics.campaign_effect(p.get("campaign_id")),
    ("statistics", "compare_groups"): lambda p: statistics.compare_groups(p["dimension"], p["values"], _p(p["period"])),
    ("statistics", "association"): lambda p: statistics.category_region_association(_p(p["period"])),
    ("statistics", "correlation"): lambda p: statistics.price_quantity_correlation(),
}


def run_step(step: PlanStep) -> ToolResult:
    fn = REGISTRY.get((step.tool, step.action))
    if fn is None:
        return ToolResult(tool=step.tool, ok=False, error="Tool is not on the approved list.")
    try:
        return fn(step.params)
    except (ValueError, KeyError, TypeError) as exc:
        return ToolResult(tool=step.tool, ok=False, error=f"Invalid tool input: {type(exc).__name__}")
    except Exception:  # noqa: BLE001 - tools must never crash the request
        return ToolResult(tool=step.tool, ok=False, error="The analysis tool failed unexpectedly.")
