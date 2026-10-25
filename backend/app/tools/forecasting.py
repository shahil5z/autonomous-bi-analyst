"""Forecasting Tool: daily revenue, seasonal naive baseline vs two simple models.

Time-aware split: the last `horizon` days are held out; models are fitted on the
earlier data, scored with MAE/RMSE, then the best model is refitted on all data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from app.agent.schemas import ToolResult
from app.database.connection import DatabaseError
from app.tools.sql_safety import SQLValidationError
from app.tools.timeseries import daily_series

MAX_HORIZON = 90


def prepare_daily(df: pd.DataFrame) -> tuple[pd.Series, dict]:
    """Reindex to a continuous daily calendar; days without sales become 0."""
    s = df.set_index("day")["value"].astype(float)
    full_idx = pd.date_range(s.index.min(), s.index.max(), freq="D")
    missing = full_idx.difference(s.index)
    weekday_missing = pd.Series(missing.day_of_week).value_counts().to_dict() if len(missing) else {}
    s = s.reindex(full_idx, fill_value=0.0)
    s.index.name = "day"
    info = {"days": int(len(s)), "zero_filled_days": int(len(missing)),
            "zero_filled_saturdays": int(weekday_missing.get(5, 0)),
            "start": s.index.min().date().isoformat(), "end": s.index.max().date().isoformat()}
    return s, info


def _features(idx: pd.DatetimeIndex, t0: pd.Timestamp) -> np.ndarray:
    t = ((idx - t0).days.to_numpy() / 365.25).reshape(-1, 1)
    dow = np.eye(7)[idx.day_of_week.to_numpy()]
    doy = idx.day_of_year.to_numpy() / 365.25 * 2 * np.pi
    fourier = np.column_stack([np.sin(doy), np.cos(doy), np.sin(2 * doy), np.cos(2 * doy)])
    return np.hstack([t, dow, fourier])


def seasonal_naive(train: pd.Series, horizon: int, season: int = 7) -> np.ndarray:
    last = train.to_numpy()[-season:]
    return np.array([last[i % season] for i in range(horizon)])


def weekday_mean(train: pd.Series, horizon: int, weeks: int = 4) -> np.ndarray:
    recent = train.iloc[-7 * weeks:]
    prof = recent.groupby(recent.index.day_of_week).mean()
    idx = pd.date_range(train.index[-1] + pd.Timedelta(days=1), periods=horizon, freq="D")
    return np.array([prof.get(d, 0.0) for d in idx.day_of_week])


def ridge_trend(train: pd.Series, horizon: int) -> np.ndarray:
    t0 = train.index[0]
    model = Ridge(alpha=1.0).fit(_features(train.index, t0), train.to_numpy())
    idx = pd.date_range(train.index[-1] + pd.Timedelta(days=1), periods=horizon, freq="D")
    return np.clip(model.predict(_features(idx, t0)), 0, None)


MODELS = {
    "seasonal_naive_7d": ("Seasonal naive (same weekday last week)", seasonal_naive),
    "weekday_mean_4w": ("Weekday mean of the last 4 weeks", weekday_mean),
    "ridge_trend_seasonality": ("Ridge regression: trend + weekday + annual Fourier terms", ridge_trend),
}


def mae(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean(np.abs(y - p)))


def rmse(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y - p) ** 2)))


def mape(y: np.ndarray, p: np.ndarray) -> float | None:
    """MAPE over trading days only (days with zero sales would divide by zero)."""
    mask = y > 0
    return float(np.mean(np.abs((y[mask] - p[mask]) / y[mask])) * 100) if mask.any() else None


def evaluate_and_forecast(series: pd.Series, horizon: int) -> dict:
    if len(series) < horizon * 4 + 28:
        raise ValueError("History is too short for this horizon.")
    train, test = series.iloc[:-horizon], series.iloc[-horizon:]
    scores, preds = [], {}
    y = test.to_numpy()
    for key, (label, fn) in MODELS.items():
        pred = preds[key] = fn(train, horizon)
        m = mape(y, pred)
        scores.append({"model": key, "label": label, "mae": round(mae(y, pred), 2),
                       "rmse": round(rmse(y, pred), 2), "mape_pct": None if m is None else round(m, 1)})
    best = min(scores, key=lambda r: r["mae"])
    baseline = next(s for s in scores if s["model"] == "seasonal_naive_7d")
    future = MODELS[best["model"]][1](series, horizon)
    # Rough 80% band: 10th/90th percentile of the best model's holdout errors (actual - forecast).
    resid = y - preds[best["model"]]
    lo_e, hi_e = float(np.quantile(resid, 0.1)), float(np.quantile(resid, 0.9))
    idx = pd.date_range(series.index[-1] + pd.Timedelta(days=1), periods=horizon, freq="D")
    return {
        "scores": scores, "best_model": best["model"], "best_label": best["label"],
        "best_mae": best["mae"], "best_rmse": best["rmse"], "best_mape_pct": best["mape_pct"],
        "interval_level_pct": 80, "interval_error_low": round(lo_e, 2), "interval_error_high": round(hi_e, 2),
        "baseline_mae": baseline["mae"], "baseline_rmse": baseline["rmse"],
        "beats_baseline": best["model"] != "seasonal_naive_7d",
        "holdout_start": test.index[0].date().isoformat(), "holdout_end": test.index[-1].date().isoformat(),
        "forecast": [{"day": d.date().isoformat(), "forecast": round(float(v), 2),
                      "low_80": round(max(0.0, float(v) + lo_e), 2), "high_80": round(max(0.0, float(v) + hi_e), 2)}
                     for d, v in zip(idx, future, strict=True)],
        "forecast_total": round(float(np.sum(future)), 2),
        "holdout": [{"day": d.date().isoformat(), "actual": round(float(v), 2)} for d, v in test.items()],
    }


def forecast_revenue(horizon: int = 30) -> ToolResult:
    if horizon < 1 or horizon > MAX_HORIZON:
        return ToolResult(tool="forecasting", ok=False, no_answer=True,
                          error=f"Forecast horizon must be between 1 and {MAX_HORIZON} days; longer horizons are not supported by ~2 years of daily history.")
    try:
        df, rec = daily_series("revenue")
    except (SQLValidationError, DatabaseError) as exc:
        return ToolResult(tool="forecasting", ok=False, error=str(exc))
    last_day = df["day"].max()
    df = df[df["day"] < last_day]  # final day may be incomplete (data ends mid-day)
    series, info = prepare_daily(df)
    try:
        res = evaluate_and_forecast(series, horizon)
    except ValueError as exc:
        return ToolResult(tool="forecasting", ok=False, no_answer=True, error=str(exc), sql=[rec])
    res.update(horizon_days=horizon, continuity=info, excluded_last_day=last_day.date().isoformat())
    history = [{"day": d.date().isoformat(), "actual": round(float(v), 2)} for d, v in series.iloc[-90:].items()]
    res["history_tail"] = history
    return ToolResult(tool="forecasting", ok=True, data=res, rows=res["forecast"], sql=[rec], method="holdout_model_selection",
                      limitations=[
                          f"Days with no sales were filled with 0 ({info['zero_filled_days']} days, mostly Saturdays when the shop did not trade).",
                          "Only about two years of history: annual seasonality is estimated from two seasons.",
                          "The 80% band comes from the 10th/90th percentiles of errors on a single holdout window; it is a rough guide, not a calibrated prediction interval.",
                          "MAPE is computed over trading days only (days with zero sales are skipped).",
                          f"The last data day ({last_day.date().isoformat()}) was excluded as possibly incomplete.",
                          "The holdout covers the late-November peak, so errors are measured on an unusually busy period.",
                      ])
