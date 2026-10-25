"""Statistical Test Tool.

Pure functions (testable without a database) plus three data-backed analyses:
compare two regions/countries, campaign vs non-campaign days, category-by-region
association, and price/quantity correlation. Tests are chosen from checked
assumptions; the tool refuses when sample sizes are too small.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

from app.agent.schemas import Period, ToolResult
from app.database.connection import DatabaseError
from app.tools.sql import canonical_filter_values, records, run_sql
from app.tools.sql_safety import SQLValidationError

MIN_N = 8
ALPHA = 0.05


class InsufficientData(ValueError):
    pass


def cohens_d(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = len(a), len(b)
    pooled = math.sqrt(((na - 1) * a.var(ddof=1) + (nb - 1) * b.var(ddof=1)) / (na + nb - 2))
    return float((a.mean() - b.mean()) / pooled) if pooled > 0 else 0.0


def welch_ci(a: np.ndarray, b: np.ndarray, conf: float = 0.95) -> tuple[float, float]:
    va, vb = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
    se = math.sqrt(va + vb)
    df = (va + vb) ** 2 / (va**2 / (len(a) - 1) + vb**2 / (len(b) - 1))
    t = stats.t.ppf((1 + conf) / 2, df)
    diff = a.mean() - b.mean()
    return float(diff - t * se), float(diff + t * se)


def cramers_v(table: np.ndarray) -> float:
    chi2 = stats.chi2_contingency(table, correction=False)[0]
    n = table.sum()
    k = min(table.shape) - 1
    return float(math.sqrt(chi2 / (n * k))) if n and k else 0.0


def compare_samples(a: np.ndarray, b: np.ndarray, label_a: str, label_b: str) -> dict:
    """Choose and run a two-sample test based on sample size, normality and variances."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if len(a) < MIN_N or len(b) < MIN_N:
        raise InsufficientData(f"Need at least {MIN_N} observations per group (got {len(a)} and {len(b)}).")
    assumptions = []

    def normal_p(x: np.ndarray) -> float:
        x = x if len(x) <= 5000 else np.random.default_rng(0).choice(x, 5000, replace=False)
        return float(stats.shapiro(x).pvalue)

    pa, pb = normal_p(a), normal_p(b)
    normal = pa > ALPHA and pb > ALPHA
    assumptions.append(f"Shapiro-Wilk normality p-values: {label_a} {pa:.3g}, {label_b} {pb:.3g}"
                       + (" (no strong evidence against normality)." if normal else " (normality rejected for at least one group)."))
    lev_p = float(stats.levene(a, b, center="median").pvalue)
    equal_var = lev_p > ALPHA
    assumptions.append(f"Levene (median) equal-variance p-value: {lev_p:.3g}.")
    large = len(a) >= 30 and len(b) >= 30

    welch = stats.ttest_ind(a, b, equal_var=False)
    mw = stats.mannwhitneyu(a, b, alternative="two-sided")
    lo, hi = welch_ci(a, b)
    result = {
        "group_a": label_a, "group_b": label_b,
        "n_a": int(len(a)), "n_b": int(len(b)),
        "mean_a": round(float(a.mean()), 2), "mean_b": round(float(b.mean()), 2),
        "median_a": round(float(np.median(a)), 2), "median_b": round(float(np.median(b)), 2),
        "mean_difference": round(float(a.mean() - b.mean()), 2),
        "ci95_low": round(lo, 2), "ci95_high": round(hi, 2),
        "cohens_d": round(cohens_d(a, b), 3),
        "welch_t": round(float(welch.statistic), 3), "welch_p": float(f"{welch.pvalue:.4g}"),
        "mann_whitney_u": float(mw.statistic), "mann_whitney_p": float(f"{mw.pvalue:.4g}"),
    }
    if normal and equal_var:
        st = stats.ttest_ind(a, b, equal_var=True)
        result.update(primary_test="Student t-test", primary_p=float(f"{st.pvalue:.4g}"))
    elif normal or large:
        result.update(primary_test="Welch t-test", primary_p=result["welch_p"])
        if not normal:
            assumptions.append("Samples are non-normal but large (n >= 30 each), so Welch's t-test on means is "
                               "reported alongside Mann-Whitney U.")
    else:
        result.update(primary_test="Mann-Whitney U", primary_p=result["mann_whitney_p"])
        assumptions.append("Small non-normal samples: Mann-Whitney U is the primary test; the t-test is shown for reference only.")
    result["significant"] = bool(result["primary_p"] < ALPHA)
    d = abs(result["cohens_d"])
    result["effect_size_label"] = "negligible" if d < 0.2 else "small" if d < 0.5 else "medium" if d < 0.8 else "large"
    result["assumptions"] = assumptions
    return result


def chi_square(table: pd.DataFrame) -> dict:
    """Chi-square test of independence; drops sparse rows/cols until expected counts are adequate."""
    t = table.copy()
    for _ in range(20):
        if t.shape[0] < 2 or t.shape[1] < 2:
            raise InsufficientData("Not enough non-sparse categories for a chi-square test.")
        expected = stats.contingency.expected_freq(t.values)
        if (expected < 5).mean() <= 0.2 and expected.min() >= 1:
            break
        row_tot, col_tot = t.sum(axis=1), t.sum(axis=0)
        if row_tot.min() <= col_tot.min():
            t = t.drop(index=row_tot.idxmin())
        else:
            t = t.drop(columns=col_tot.idxmin())
    else:
        raise InsufficientData("Expected cell counts stayed too small.")
    chi2, p, dof, _ = stats.chi2_contingency(t.values, correction=False)
    return {"chi2": round(float(chi2), 2), "p_value": float(f"{p:.4g}"), "dof": int(dof),
            "cramers_v": round(cramers_v(t.values), 4), "n": int(t.values.sum()),
            "rows_used": [str(i) for i in t.index], "columns_used": [str(c) for c in t.columns],
            "table": t}


def correlation(x: np.ndarray, y: np.ndarray) -> dict:
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 10:
        raise InsufficientData("Need at least 10 pairs for a correlation.")
    r, p = stats.pearsonr(x, y)
    rho, sp = stats.spearmanr(x, y)
    z, se = np.arctanh(r), 1 / math.sqrt(len(x) - 3)
    return {"n": int(len(x)), "pearson_r": round(float(r), 3), "pearson_p": float(f"{p:.4g}"),
            "pearson_ci95": [round(float(np.tanh(z - 1.96 * se)), 3), round(float(np.tanh(z + 1.96 * se)), 3)],
            "spearman_rho": round(float(rho), 3), "spearman_p": float(f"{sp:.4g}")}


# ---------------------------------------------------------------- data-backed analyses

def compare_groups(dimension: str, values: list[str], period: Period | None) -> ToolResult:
    """Compare order values (revenue per invoice) between two regions or countries."""
    from app.agent.schemas import Filter

    if len(values) != 2:
        return ToolResult(tool="statistics", ok=False, no_answer=True,
                          error="A comparison needs exactly two regions or countries.")
    try:
        a_name, b_name = canonical_filter_values(Filter(dimension=dimension, values=values))
        col = "s.region" if dimension == "region" else "s.country"
        params: list = [a_name, b_name]
        sql = (f"SELECT {col} AS grp, s.invoice_id AS invoice_id, SUM(s.revenue) AS order_value FROM sales s "
               f"WHERE {col} IN (?, ?)")
        if period:
            sql += " AND s.invoice_date >= ? AND s.invoice_date < ?"
            params += [period.start, period.end]
        sql += f" GROUP BY {col}, s.invoice_id ORDER BY s.invoice_id"
        df, rec = run_sql(f"order values for {a_name} and {b_name}", sql, params, max_rows=200000)
        a = df.loc[df["grp"] == a_name, "order_value"].to_numpy()
        b = df.loc[df["grp"] == b_name, "order_value"].to_numpy()
        res = compare_samples(a, b, a_name, b_name)
    except InsufficientData as exc:
        return ToolResult(tool="statistics", ok=False, no_answer=True, error=str(exc))
    except (SQLValidationError, DatabaseError) as exc:
        return ToolResult(tool="statistics", ok=False, error=str(exc))
    box = []
    for name, arr in [(a_name, a), (b_name, b)]:
        q1, med, q3 = np.percentile(arr, [25, 50, 75])
        iqr = q3 - q1
        box.append({"group": name, "min": round(float(max(arr.min(), q1 - 1.5 * iqr)), 2), "q1": round(float(q1), 2),
                    "median": round(float(med), 2), "q3": round(float(q3), 2),
                    "max": round(float(min(arr.max(), q3 + 1.5 * iqr)), 2), "n": int(len(arr)),
                    "total_revenue": round(float(arr.sum()), 2)})
    res["total_revenue_a"], res["total_revenue_b"] = box[0]["total_revenue"], box[1]["total_revenue"]
    return ToolResult(tool="statistics", ok=True, data=res, rows=box, sql=[rec], method="two_sample_test_order_value",
                      limitations=["Orders are treated as independent observations; repeat customers make this approximate.",
                                   "Order values are heavily right-skewed, so medians and Mann-Whitney U are more robust than means."])


def campaign_effect(campaign_id: str | None) -> ToolResult:
    """Daily revenue on campaign days vs non-campaign trading days (observational)."""
    try:
        camps, crec = run_sql("synthetic campaigns", "SELECT campaign_id, name, channel, start_date, end_date FROM campaigns ORDER BY start_date")
        if campaign_id:
            camps = camps[camps["campaign_id"] == campaign_id]
            if camps.empty:
                return ToolResult(tool="statistics", ok=False, no_answer=True, sql=[crec], error="Unknown campaign id.")
        lo = (pd.Timestamp(camps["start_date"].min()) - pd.Timedelta(days=56)).date()
        hi = (pd.Timestamp(camps["end_date"].max()) + pd.Timedelta(days=57)).date()
        sql = ("SELECT c.date AS day, c.campaign_id AS campaign_id, SUM(s.revenue) AS revenue FROM calendar c "
               "JOIN sales s ON s.invoice_date = c.date WHERE c.date >= ? AND c.date < ? GROUP BY c.date, c.campaign_id ORDER BY c.date")
        daily, rec = run_sql("daily revenue with campaign flag", sql, [lo, hi], max_rows=5000)
    except (SQLValidationError, DatabaseError) as exc:
        return ToolResult(tool="statistics", ok=False, error=str(exc))
    ids = set(camps["campaign_id"])
    in_mask = daily["campaign_id"].isin(ids)
    other_mask = daily["campaign_id"].isna()
    a = daily.loc[in_mask, "revenue"].to_numpy()
    b = daily.loc[other_mask, "revenue"].to_numpy()
    try:
        res = compare_samples(a, b, "campaign days", "non-campaign days")
    except InsufficientData as exc:
        return ToolResult(tool="statistics", ok=False, no_answer=True, error=str(exc), sql=[crec, rec])
    res["campaigns"] = records(camps)
    res["window"] = f"{lo.isoformat()} to {(pd.Timestamp(hi) - pd.Timedelta(days=1)).date().isoformat()}"
    res["higher_group"] = "campaign days" if res["mean_a"] > res["mean_b"] else "non-campaign days"
    res["relative_difference_pct"] = round((res["mean_a"] - res["mean_b"]) / res["mean_b"] * 100, 2) if res["mean_b"] else None
    rows = [{"group": "campaign days", "n_days": res["n_a"], "mean_daily_revenue": res["mean_a"], "median_daily_revenue": res["median_a"]},
            {"group": "non-campaign days", "n_days": res["n_b"], "mean_daily_revenue": res["mean_b"], "median_daily_revenue": res["median_b"]}]
    series = daily.assign(day=pd.to_datetime(daily["day"]).dt.strftime("%Y-%m-%d"),
                          in_campaign=in_mask.astype(int))[["day", "revenue", "in_campaign"]]
    res["daily_series"] = records(series)
    return ToolResult(tool="statistics", ok=True, data=res, rows=rows, sql=[crec, rec], method="campaign_vs_non_campaign_days",
                      limitations=["Campaigns are SYNTHETIC (generated with seed 42) and no effect was injected into the sales data, "
                                   "so any difference reflects timing/seasonality rather than marketing.",
                                   "Observational comparison only: this cannot show that a campaign caused a change in sales.",
                                   "Only trading days (days with sales) are compared; seasonality is not adjusted for."])


def category_region_association(period: Period | None) -> ToolResult:
    params: list = []
    sql = ("SELECT s.region AS region, p.category AS category, COUNT(*) AS lines FROM sales s "
           "LEFT JOIN products p ON p.product_id = s.product_id")
    if period:
        sql += " WHERE s.invoice_date >= ? AND s.invoice_date < ?"
        params += [period.start, period.end]
    sql += " GROUP BY s.region, p.category"
    try:
        df, rec = run_sql("order lines by region and category", sql, params, max_rows=1000)
        table = df.pivot_table(index="region", columns="category", values="lines", fill_value=0)
        res = chi_square(table)
    except InsufficientData as exc:
        return ToolResult(tool="statistics", ok=False, no_answer=True, error=str(exc))
    except (SQLValidationError, DatabaseError) as exc:
        return ToolResult(tool="statistics", ok=False, error=str(exc))
    t = res.pop("table")
    share = (t.div(t.sum(axis=1), axis=0) * 100).round(2)
    heat = [{"region": r, "category": c, "share_pct": float(share.loc[r, c])} for r in share.index for c in share.columns]
    res["significant"] = res["p_value"] < ALPHA
    v = res["cramers_v"]
    res["effect_size_label"] = "negligible" if v < 0.1 else "small" if v < 0.3 else "medium" if v < 0.5 else "large"
    return ToolResult(tool="statistics", ok=True, data=res, rows=heat, sql=[rec], method="chi_square_independence",
                      limitations=["Order lines are not fully independent (lines share invoices).",
                                   "With very large samples almost any difference is 'significant'; Cramer's V shows the practical size.",
                                   "Categories are keyword-derived from product descriptions."])


def price_quantity_correlation() -> ToolResult:
    sql = ("SELECT s.product_id AS product_id, AVG(s.unit_price) AS avg_price, SUM(s.quantity) AS units, COUNT(*) AS lines "
           "FROM sales s GROUP BY s.product_id HAVING COUNT(*) >= 20 ORDER BY s.product_id")
    try:
        df, rec = run_sql("average price and units per product", sql, [], max_rows=10000)
        res = correlation(np.log(df["avg_price"]), np.log(df["units"]))
    except InsufficientData as exc:
        return ToolResult(tool="statistics", ok=False, no_answer=True, error=str(exc))
    except (SQLValidationError, DatabaseError) as exc:
        return ToolResult(tool="statistics", ok=False, error=str(exc))
    sample = df.sample(min(300, len(df)), random_state=42)
    pts = [{"avg_price": round(float(r.avg_price), 2), "units": int(r.units)} for r in sample.itertuples()]
    res["products_used"] = int(len(df))
    return ToolResult(tool="statistics", ok=True, data=res, rows=pts, sql=[rec], method="pearson_spearman_log_log",
                      limitations=["Correlation is computed across products (log price vs log units); it is not a price elasticity estimate.",
                                   "Only products with at least 20 order lines are included.", "Correlation does not imply causation."])
