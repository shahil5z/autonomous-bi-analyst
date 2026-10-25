import numpy as np
import pandas as pd
from app.tools import anomaly as an


def test_robust_anomalies_flags_spike():
    rng = np.random.default_rng(0)
    s = pd.Series(rng.normal(100, 5, 80), index=pd.date_range("2011-01-01", periods=80))
    s.iloc[60] = 300
    res = an.robust_anomalies(s)
    assert res["is_anomaly"].iloc[60] and res["iqr_flag"].iloc[60]
    assert res["is_anomaly"].sum() <= 3


def test_detect_largest_anomaly_on_fixture(fixture_db):
    r = an.detect_largest_anomaly()
    assert r.ok and r.data["date"] == "2011-05-10" and r.data["direction"] == "above"
    assert r.data["by_region"]
