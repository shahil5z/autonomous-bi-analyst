"""Customer Segmentation Tool: RFM features, log + standard scaling, K-Means.

k is chosen by silhouette score (k = 2..6). Segment labels are derived from each
cluster's median recency/frequency/monetary value relative to all customers.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from app.agent.schemas import ToolResult
from app.database.connection import DatabaseError
from app.tools.sql import records, run_sql
from app.tools.sql_safety import SQLValidationError

SEED = 42


def rfm_table(df: pd.DataFrame, snapshot: pd.Timestamp) -> pd.DataFrame:
    out = df.copy()
    out["recency_days"] = (snapshot - pd.to_datetime(out["last_purchase"])).dt.days
    return out[["customer_id", "recency_days", "frequency", "monetary"]]


def label_segment(row: pd.Series, med: pd.Series) -> str:
    r = "Recent" if row["recency_days"] <= med["recency_days"] else "Lapsed"
    f = "frequent" if row["frequency"] > med["frequency"] else "occasional"
    m = "high-spend" if row["monetary"] > med["monetary"] else "low-spend"
    return f"{r}, {f}, {m}"


def cluster(rfm: pd.DataFrame, k_range: range = range(2, 7)) -> tuple[pd.DataFrame, dict]:
    x = np.column_stack([rfm["recency_days"], np.log1p(rfm["frequency"]), np.log1p(rfm["monetary"])])
    xs = StandardScaler().fit_transform(x)
    scores = {}
    sample = min(len(xs), 4000)
    for k in k_range:
        km = KMeans(n_clusters=k, n_init=10, random_state=SEED).fit(xs)
        scores[k] = float(silhouette_score(xs, km.labels_, sample_size=sample, random_state=SEED))
    best_k = max(scores, key=scores.get)
    km = KMeans(n_clusters=best_k, n_init=10, random_state=SEED).fit(xs)
    out = rfm.assign(cluster=km.labels_)
    return out, {"silhouette_by_k": {str(k): round(v, 4) for k, v in scores.items()}, "k": best_k,
                 "silhouette": round(scores[best_k], 4)}


def segment_customers() -> ToolResult:
    sql = ("SELECT s.customer_id AS customer_id, MAX(s.invoice_date) AS last_purchase, "
           "COUNT(DISTINCT s.invoice_id) AS frequency, SUM(s.revenue) AS monetary "
           "FROM sales s WHERE s.customer_id IS NOT NULL GROUP BY s.customer_id ORDER BY s.customer_id")
    try:
        df, rec = run_sql("RFM inputs per customer", sql, [], max_rows=20000)
        snap, rec2 = run_sql("snapshot date", "SELECT MAX(s.invoice_date) AS d FROM sales s", [])
    except (SQLValidationError, DatabaseError) as exc:
        return ToolResult(tool="segmentation", ok=False, error=str(exc))
    if len(df) < 50:
        return ToolResult(tool="segmentation", ok=False, no_answer=True, error="Too few customers to segment.")
    snapshot = pd.Timestamp(snap["d"].iloc[0]) + pd.Timedelta(days=1)
    rfm = rfm_table(df, snapshot)
    clustered, info = cluster(rfm)
    med = rfm[["recency_days", "frequency", "monetary"]].median()
    seg = (clustered.groupby("cluster").agg(customers=("customer_id", "count"), revenue=("monetary", "sum"),
                                            median_recency_days=("recency_days", "median"),
                                            median_frequency=("frequency", "median"),
                                            median_monetary=("monetary", "median")).reset_index())
    seg["label"] = seg.apply(lambda r: label_segment(pd.Series({"recency_days": r["median_recency_days"],
                                                                "frequency": r["median_frequency"],
                                                                "monetary": r["median_monetary"]}), med), axis=1)
    total = seg["revenue"].sum()
    seg["revenue_share_pct"] = seg["revenue"] / total * 100
    seg["customer_share_pct"] = seg["customers"] / seg["customers"].sum() * 100
    seg = seg.sort_values("revenue", ascending=False)
    seg["segment"] = [f"Segment {i + 1}" for i in range(len(seg))]
    cols = ["segment", "label", "customers", "revenue", "revenue_share_pct", "customer_share_pct",
            "median_recency_days", "median_frequency", "median_monetary"]
    info.update(customers=int(len(rfm)), snapshot_date=snapshot.date().isoformat(),
                overall_median_recency_days=float(med["recency_days"]), overall_median_frequency=float(med["frequency"]),
                overall_median_monetary=round(float(med["monetary"]), 2), total_revenue=round(float(total), 2))
    return ToolResult(tool="segmentation", ok=True, data=info, rows=records(seg[cols]), sql=[rec, rec2], method="rfm_kmeans",
                      limitations=["Guest orders without a customer id are excluded from segmentation.",
                                   "K-Means assumes roughly spherical clusters; silhouette scores around 0.3-0.4 indicate overlapping segments.",
                                   "Labels compare each segment's medians with the overall customer medians."])
