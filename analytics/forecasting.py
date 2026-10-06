"""Stage 4 forecasting on verified monthly series.

Models
- Linear regression trend with a prediction interval (t-distribution)
- ARIMA / seasonal ARIMA (statsmodels), order chosen by AIC from a small grid
- Ensemble: mean of the two, as the implementation plan prescribes

Every forecast reports a holdout backtest: the last ``holdout`` months are
hidden, each model forecasts them, and MAPE is measured against the actuals
(target: <= 15%).
"""

from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np
from scipy import stats

from utils.config import FORECAST_CONFIDENCE_LEVEL

MAPE_TARGET = 15.0


def _next_months(last: str, horizon: int) -> list[str]:
    year, month = int(last[:4]), int(last[5:7])
    months = []
    for _ in range(horizon):
        month += 1
        if month == 13:
            year, month = year + 1, 1
        months.append(f"{year:04d}-{month:02d}")
    return months


def linear_forecast(values: list[float], horizon: int, level: float = FORECAST_CONFIDENCE_LEVEL) -> dict[str, Any]:
    """OLS trend y = a + b t with a prediction interval for each future month."""
    y = np.asarray(values, dtype=float)
    n = len(y)
    t = np.arange(n, dtype=float)
    slope, intercept = np.polyfit(t, y, 1)
    fitted = intercept + slope * t
    dof = max(n - 2, 1)
    residual_se = math.sqrt(float(np.sum((y - fitted) ** 2)) / dof)
    t_mean = t.mean()
    sxx = float(np.sum((t - t_mean) ** 2)) or 1.0
    critical = stats.t.ppf(0.5 + level / 2, dof)
    future = np.arange(n, n + horizon, dtype=float)
    point = intercept + slope * future
    margin = critical * residual_se * np.sqrt(1 + 1 / n + (future - t_mean) ** 2 / sxx)
    return {
        "model": "linear_regression",
        "point": point.round(2).tolist(),
        "lower": (point - margin).round(2).tolist(),
        "upper": (point + margin).round(2).tolist(),
        "params": {"slope_per_month": round(float(slope), 2), "intercept": round(float(intercept), 2)},
    }


def _arima_candidates(n: int) -> list[tuple[tuple[int, int, int], tuple[int, int, int, int]]]:
    candidates = [((1, 1, 1), (0, 0, 0, 0)), ((0, 1, 1), (0, 0, 0, 0)),
                  ((1, 1, 0), (0, 0, 0, 0)), ((2, 1, 0), (0, 0, 0, 0))]
    if n >= 24:
        candidates += [((1, 1, 0), (1, 0, 0, 12)), ((0, 1, 1), (1, 0, 0, 12))]
    return candidates


def arima_forecast(values: list[float], horizon: int, level: float = FORECAST_CONFIDENCE_LEVEL) -> dict[str, Any]:
    """Seasonal ARIMA chosen by AIC; falls back to linear if the series is too short."""
    if len(values) < 8:
        result = linear_forecast(values, horizon, level)
        return {**result, "model": "arima_unavailable_linear_fallback"}
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    best = None
    y = np.asarray(values, dtype=float)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for order, seasonal in _arima_candidates(len(y)):
            try:
                fit = SARIMAX(y, order=order, seasonal_order=seasonal, trend="t",
                              enforce_stationarity=False, enforce_invertibility=False).fit(disp=False)
            except Exception:  # noqa: BLE001 - try the next candidate
                continue
            if not np.isfinite(fit.aic):
                continue
            if best is None or fit.aic < best[0]:
                best = (fit.aic, fit, order, seasonal)
        if best is None:
            result = linear_forecast(values, horizon, level)
            return {**result, "model": "arima_failed_linear_fallback"}
        _, fit, order, seasonal = best
        prediction = fit.get_forecast(horizon)
        point = np.asarray(prediction.predicted_mean)
        interval = np.asarray(prediction.conf_int(alpha=1 - level))
    return {
        "model": "arima",
        "point": point.round(2).tolist(),
        "lower": interval[:, 0].round(2).tolist(),
        "upper": interval[:, 1].round(2).tolist(),
        "params": {"order": list(order), "seasonal_order": list(seasonal), "aic": round(float(best[0]), 1)},
    }


def ensemble(linear: dict[str, Any], arima: dict[str, Any]) -> dict[str, Any]:
    def mean(key: str) -> list[float]:
        return [round((a + b) / 2, 2) for a, b in zip(linear[key], arima[key])]

    return {"model": "ensemble", "point": mean("point"), "lower": mean("lower"), "upper": mean("upper")}


def mape(actual: list[float], predicted: list[float]) -> float | None:
    pairs = [(a, p) for a, p in zip(actual, predicted) if a]
    if not pairs:
        return None
    return round(100 * sum(abs(a - p) / abs(a) for a, p in pairs) / len(pairs), 2)


def backtest(values: list[float], holdout: int, level: float = FORECAST_CONFIDENCE_LEVEL) -> dict[str, Any] | None:
    """Hide the last ``holdout`` points, forecast them, and score each model."""
    if len(values) < holdout + 8:
        return None
    train, actual = values[:-holdout], values[-holdout:]
    linear = linear_forecast(train, holdout, level)
    arima = arima_forecast(train, holdout, level)
    combined = ensemble(linear, arima)
    covered = sum(lo <= a <= hi for a, lo, hi in zip(actual, combined["lower"], combined["upper"]))
    return {
        "holdout_months": holdout,
        "actual": [round(v, 2) for v in actual],
        "mape": {
            "linear_regression": mape(actual, linear["point"]),
            "arima": mape(actual, arima["point"]),
            "ensemble": mape(actual, combined["point"]),
        },
        "interval_coverage": round(covered / holdout, 2),
        "target_mape": MAPE_TARGET,
    }


def forecast_series(
    months: list[str],
    values: list[float],
    *,
    horizon: int,
    level: float = FORECAST_CONFIDENCE_LEVEL,
    holdout: int = 6,
) -> dict[str, Any]:
    """Forecast one monthly series and report how trustworthy it is."""
    if len(values) < 3:
        return {"error": "At least 3 months of verified data are needed to forecast.", "history": len(values)}
    linear = linear_forecast(values, horizon, level)
    arima = arima_forecast(values, horizon, level)
    combined = ensemble(linear, arima)
    test = backtest(values, holdout, level)
    return {
        "history": {"months": months, "values": [round(v, 2) for v in values]},
        "forecast_months": _next_months(months[-1], horizon),
        "confidence_level": level,
        "models": {"linear_regression": linear, "arima": arima, "ensemble": combined},
        "backtest": test,
        "meets_target": bool(test and test["mape"]["ensemble"] is not None and test["mape"]["ensemble"] <= MAPE_TARGET),
    }


def forecast_all(series: dict[str, list], horizon: int, level: float = FORECAST_CONFIDENCE_LEVEL) -> dict[str, Any]:
    """Forecast revenue, expense and profit from a ``monthly_series`` result."""
    months = series["months"]
    return {
        metric: forecast_series(months, series[metric], horizon=horizon, level=level)
        for metric in ("revenue", "expense", "profit")
    }
