import numpy as np
import pandas as pd
import pytest
from app.tools import statistics as st
from scipy import stats


def test_compare_samples_detects_clear_difference():
    rng = np.random.default_rng(1)
    a, b = rng.normal(110, 10, 200), rng.normal(100, 10, 200)
    r = st.compare_samples(a, b, "A", "B")
    assert r["significant"] and r["primary_test"] in ("Student t-test", "Welch t-test")
    assert r["ci95_low"] < r["mean_difference"] < r["ci95_high"]
    assert 0.6 < r["cohens_d"] < 1.4


def test_compare_samples_no_difference():
    rng = np.random.default_rng(2)
    r = st.compare_samples(rng.normal(0, 1, 100), rng.normal(0, 1, 100), "A", "B")
    assert not r["significant"]


def test_small_skewed_samples_use_mann_whitney():
    rng = np.random.default_rng(3)
    r = st.compare_samples(rng.lognormal(0, 2, 12), rng.lognormal(0, 2, 12), "A", "B")
    assert r["primary_test"] == "Mann-Whitney U"


def test_refuses_tiny_samples():
    with pytest.raises(st.InsufficientData):
        st.compare_samples(np.ones(3), np.ones(20), "A", "B")


def test_welch_ci_matches_scipy():
    rng = np.random.default_rng(4)
    a, b = rng.normal(5, 2, 50), rng.normal(4, 3, 70)
    lo, hi = st.welch_ci(a, b)
    ci = stats.ttest_ind(a, b, equal_var=False).confidence_interval(0.95)
    assert lo == pytest.approx(ci.low) and hi == pytest.approx(ci.high)


def test_chi_square_and_cramers_v():
    table = pd.DataFrame([[50, 10], [10, 50]], index=["r1", "r2"], columns=["c1", "c2"])
    r = st.chi_square(table)
    assert r["p_value"] < 0.001 and 0.5 < r["cramers_v"] <= 1
    assert r["chi2"] == pytest.approx(stats.chi2_contingency(table.values, correction=False)[0], rel=1e-3)


def test_chi_square_drops_sparse_cells():
    table = pd.DataFrame([[100, 90, 1], [95, 105, 0], [1, 0, 0]], index=["a", "b", "tiny"], columns=["x", "y", "rare"])
    r = st.chi_square(table)
    assert "tiny" not in r["rows_used"] and "rare" not in r["columns_used"]


def test_correlation():
    x = np.arange(50, dtype=float)
    r = st.correlation(x, -2 * x + 1)
    assert r["pearson_r"] == pytest.approx(-1.0) and r["spearman_rho"] == pytest.approx(-1.0)
    with pytest.raises(st.InsufficientData):
        st.correlation(x[:5], x[:5])


def test_campaign_effect_on_fixture(fixture_db):
    r = st.campaign_effect(None)
    assert r.ok and r.data["n_a"] >= 8
    assert any("observational" in lim.lower() for lim in r.limitations)
