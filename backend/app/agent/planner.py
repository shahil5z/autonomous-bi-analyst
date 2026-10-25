"""Analysis Planner: deterministic plan from a validated ParsedQuestion."""

from __future__ import annotations

from app.agent.schemas import ParsedQuestion, Plan, PlanStep

ALL_DATA = "all data (Dec 2009 - Dec 2011)"


def _plabel(p) -> str:
    return p.label if p else ALL_DATA


def make_plan(pq: ParsedQuestion) -> Plan:
    m = pq.metrics[0]
    filters = [f.model_dump() for f in pq.filters]
    fdesc = "".join(f" for {', '.join(f.values)}" for f in pq.filters)
    period = pq.time_period.model_dump(mode="json") if pq.time_period else None
    comp = pq.comparison_period.model_dump(mode="json") if pq.comparison_period else None
    i = pq.intent

    if i == "unsupported":
        return Plan(intent=i, summary="No analysis can answer this question with the available data.", steps=[],
                    human_steps=["Check the question against the available data", "Return a no-answer response"])
    if i == "metric_total":
        step = PlanStep(tool="sql_query", action="query", description=f"Total {m}{fdesc}",
                        params={"metric": m, "group_by": [], "filters": filters, "period": period, "limit": 1})
        return Plan(intent=i, summary=f"Compute total {m} over {_plabel(pq.time_period)}{fdesc}.", steps=[step], chart=False,
                    human_steps=[f"Build a validated SELECT for total {m}", f"Restrict to {_plabel(pq.time_period)}{fdesc}",
                                 "Return the single total"])
    if i == "revenue_ranking":
        dim = (pq.dimensions or ["region"])[0]
        step = PlanStep(tool="sql_query", action="query", description=f"Query {m} by {dim}{fdesc}",
                        params={"metric": m, "group_by": [dim], "filters": filters, "period": period, "limit": pq.top_n})
        return Plan(intent=i, summary=f"Rank {dim}s by {m} over {_plabel(pq.time_period)}.", steps=[step], chart=True,
                    human_steps=[f"Build a validated SELECT for {m} grouped by {dim}", f"Restrict to {_plabel(pq.time_period)}{fdesc}",
                                 "Sort descending and return the leader", "Reconcile group totals with the overall total",
                                 "Generate a bar chart"])
    if i == "top_products":
        step = PlanStep(tool="aggregation", action="top_n", description=f"Top {pq.top_n} products by {m}",
                        params={"metric": m, "dimension": "product", "period": period, "n": pq.top_n, "filters": filters})
        return Plan(intent=i, summary=f"Find the top {pq.top_n} products by {m}.", steps=[step], chart=True,
                    human_steps=[f"Aggregate {m} per product over {_plabel(pq.time_period)}{fdesc}", f"Keep the top {pq.top_n}",
                                 "Compute each product's share of the total", "Generate a bar chart"])
    if i == "growth_ranking":
        dim = (pq.dimensions or ["region"])[0]
        step = PlanStep(tool="aggregation", action="growth", description=f"{m} growth by {dim}",
                        params={"metric": m, "dimension": dim, "current": period, "previous": comp, "filters": filters})
        return Plan(intent=i, summary=f"Compare {m} by {dim} between {pq.comparison_period.label} and {pq.time_period.label}.",
                    steps=[step], chart=True,
                    human_steps=[f"Calculate {m} by {dim} for {pq.time_period.label}", f"Calculate {m} by {dim} for {pq.comparison_period.label}",
                                 "Compute percentage growth", "Flag groups with a very small base", "Sort and return the fastest-growing group",
                                 "Generate a bar chart"])
    if i in ("period_change", "drivers"):
        dims = ["category", "product"] if i == "drivers" else ["region", "product"]
        step = PlanStep(tool="aggregation", action="change_decomposition", description=f"Decompose change in {m}{fdesc}",
                        params={"metric": m, "current": period, "previous": comp, "filters": filters, "dimensions": dims})
        return Plan(intent=i, summary=f"Explain the change in {m} from {pq.comparison_period.label} to {pq.time_period.label}{fdesc}.",
                    steps=[step], chart=True,
                    human_steps=[f"Calculate total {m} for both periods{fdesc}", "Compute absolute and percentage change",
                                 f"Break the change down by {dims[0]}", "List the largest positive and negative product contributions",
                                 "Generate a contribution bar chart"])
    if i == "trend":
        step = PlanStep(tool="timeseries", action="monthly_trend", description=f"Monthly {m}{fdesc}", params={"metric": m, "filters": filters})
        return Plan(intent=i, summary=f"Show the monthly trend of {m}{fdesc}.", steps=[step], chart=True,
                    human_steps=[f"Aggregate {m} by month{fdesc}", "Exclude the partial final month from summaries",
                                 "Find peak and low months and the linear slope", "Generate an area chart"])
    if i == "segment_value":
        step = PlanStep(tool="segmentation", action="rfm_kmeans", description="RFM + K-Means segmentation", params={})
        return Plan(intent=i, summary="Segment customers by behaviour and find the most valuable segment.", steps=[step], chart=True,
                    human_steps=["Compute recency, frequency and monetary value per customer", "Log-transform and standardise features",
                                 "Fit K-Means for k = 2..6 and pick k by silhouette score", "Label segments from their median behaviour",
                                 "Rank segments by revenue", "Generate a bar chart"])
    if i == "anomaly":
        step = PlanStep(tool="anomaly", action="largest", description="Detect largest daily revenue anomaly", params={})
        return Plan(intent=i, summary="Find the largest daily revenue anomaly and where it came from.", steps=[step], chart=True,
                    human_steps=["Build the daily revenue series (trading days)", "Estimate expected revenue with a 28-day rolling median",
                                 "Score days with a robust z-score and cross-check with IQR", "Pick the largest deviation",
                                 "Drill into regions, products and orders on that day", "Generate a line chart"])
    if i == "campaign_effect":
        cid = pq.entities[0] if pq.entities else None
        step = PlanStep(tool="statistics", action="campaign_effect", description="Compare campaign vs non-campaign days", params={"campaign_id": cid})
        return Plan(intent=i, summary=f"Compare daily revenue during {'campaign ' + cid if cid else 'all synthetic campaigns'} with other days.",
                    steps=[step], statistical_test=True, chart=True,
                    human_steps=["Load synthetic campaign windows", "Build daily revenue with a campaign flag",
                                 "Check sample sizes, normality and variances", "Run the appropriate two-sample test",
                                 "Report effect size and 95% CI using observational wording", "Generate a line chart"])
    if i == "forecast":
        step = PlanStep(tool="forecasting", action="forecast", description=f"Forecast {pq.horizon_days} days", params={"horizon": pq.horizon_days or 30})
        return Plan(intent=i, summary=f"Forecast daily revenue for the next {pq.horizon_days or 30} days.", steps=[step], chart=True,
                    human_steps=["Retrieve daily revenue", "Check calendar continuity and fill non-trading days",
                                 "Hold out the most recent days (time-aware split)", "Score seasonal naive vs two simple models (MAE/RMSE)",
                                 "Refit the best model on all data and forecast", "Generate a line chart"])
    if i == "compare_groups":
        dim = (pq.dimensions or ["region"])[0]
        step = PlanStep(tool="statistics", action="compare_groups", description=f"Compare order values: {' vs '.join(pq.entities)}",
                        params={"dimension": dim, "values": pq.entities[:2], "period": period})
        return Plan(intent=i, summary=f"Statistically compare order values between {' and '.join(pq.entities[:2])}.", steps=[step],
                    statistical_test=True, chart=True,
                    human_steps=["Collect order values (revenue per invoice) for both groups", "Check sample sizes and assumptions",
                                 "Choose Student/Welch t-test or Mann-Whitney U", "Compute 95% CI and Cohen's d", "Generate a box plot"])
    if i == "association":
        step = PlanStep(tool="statistics", action="association", description="Chi-square region x category", params={"period": period})
        return Plan(intent=i, summary="Test whether product category mix differs by region.", steps=[step], statistical_test=True, chart=True,
                    human_steps=["Count order lines by region and category", "Drop sparse rows/columns (expected counts < 5)",
                                 "Run a chi-square test of independence", "Compute Cramer's V", "Generate a heatmap"])
    if i == "correlation":
        step = PlanStep(tool="statistics", action="correlation", description="Price vs units correlation", params={})
        return Plan(intent=i, summary="Measure the correlation between product price and units sold.", steps=[step], statistical_test=True, chart=True,
                    human_steps=["Compute average price and units per product (>= 20 lines)", "Log-transform both variables",
                                 "Compute Pearson (with 95% CI) and Spearman correlation", "Generate a scatter plot"])
    raise ValueError(f"No plan for intent {i}")
