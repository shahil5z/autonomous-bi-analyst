import numpy as np
import pandas as pd
import pytest
from app.tools import forecasting as fc


def weekly_series(n=200):
    idx = pd.date_range("2011-01-03", periods=n, freq="D")
    return pd.Series(np.tile([10, 20, 30, 40, 50, 0, 5], n // 7 + 1)[:n].astype(float), index=idx)


def test_seasonal_naive_perfect_on_weekly_pattern():
    s = weekly_series()
    pred = fc.seasonal_naive(s.iloc[:-14], 14)
    assert np.allclose(pred, s.iloc[-14:].to_numpy())


def test_prepare_daily_fills_gaps():
    df = pd.DataFrame({"day": pd.to_datetime(["2011-01-01", "2011-01-02", "2011-01-05"]), "value": [1.0, 2.0, 3.0]})
    s, info = fc.prepare_daily(df)
    assert len(s) == 5 and info["zero_filled_days"] == 2 and s.loc["2011-01-03"] == 0


def test_evaluate_and_forecast_outputs():
    res = fc.evaluate_and_forecast(weekly_series(), 30)
    assert len(res["forecast"]) == 30 and len(res["holdout"]) == 30
    assert {s["model"] for s in res["scores"]} == set(fc.MODELS)
    assert res["best_mae"] <= res["baseline_mae"]
    assert all(r["forecast"] >= 0 for r in res["forecast"])


def test_horizon_limits():
    r = fc.forecast_revenue(365)
    assert not r.ok and r.no_answer


def test_forecast_on_fixture(fixture_db):
    r = fc.forecast_revenue(14)
    assert r.ok and len(r.data["forecast"]) == 14 and r.data["continuity"]["zero_filled_saturdays"] > 0


def test_mape_skips_zero_days_and_band_brackets_forecast():
    mape = fc.mape

    assert mape(np.array([0.0, 100.0]), np.array([5.0, 110.0])) == pytest.approx(10.0)
    assert mape(np.array([0.0]), np.array([1.0])) is None
    idx = pd.date_range("2010-01-01", periods=300, freq="D")
    rng = np.random.default_rng(1)
    s = pd.Series(100 + 20 * (idx.day_of_week == 1) + rng.normal(0, 5, len(idx)), index=idx)
    out = fc.evaluate_and_forecast(s, 14)
    assert out["best_mape_pct"] is not None
    assert all(r["low_80"] <= r["forecast"] <= r["high_80"] or r["low_80"] == 0 for r in out["forecast"])
