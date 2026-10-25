import numpy as np
import pandas as pd
from app.tools import segmentation as sg


def test_cluster_finds_two_clear_groups():
    rng = np.random.default_rng(0)
    a = pd.DataFrame({"customer_id": range(100), "recency_days": rng.integers(1, 20, 100),
                      "frequency": rng.integers(20, 40, 100), "monetary": rng.uniform(5000, 9000, 100)})
    b = pd.DataFrame({"customer_id": range(100, 200), "recency_days": rng.integers(300, 400, 100),
                      "frequency": rng.integers(1, 2, 100), "monetary": rng.uniform(10, 100, 100)})
    out, info = sg.cluster(pd.concat([a, b], ignore_index=True))
    assert info["k"] == 2 and info["silhouette"] > 0.6
    assert out.iloc[:100]["cluster"].nunique() == 1


def test_label_segment():
    med = pd.Series({"recency_days": 50, "frequency": 3, "monetary": 500})
    assert sg.label_segment(pd.Series({"recency_days": 10, "frequency": 9, "monetary": 900}), med) == "Recent, frequent, high-spend"
    assert sg.label_segment(pd.Series({"recency_days": 90, "frequency": 1, "monetary": 50}), med) == "Lapsed, occasional, low-spend"


def test_segment_customers_on_fixture(fixture_db):
    r = sg.segment_customers()
    assert r.ok and sum(x["customers"] for x in r.rows) == r.data["customers"]
    assert r.rows[0]["revenue"] >= r.rows[-1]["revenue"]
