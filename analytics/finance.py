"""Quarterly trends, cash runway and the data-source label for Stage 4.

Runway (implementation plan, week 11): a linear-regression projection of the
cash balance with an 85% confidence interval.

How it works, in plain terms
1. The user states one cash balance and the month it applies to (settings).
2. Verified monthly profit (revenue - expense) rebuilds the balance history
   backwards and forwards from that anchor.
3. A straight line is fitted to the recent balance history and projected
   forward with an 85% prediction interval (``linear_forecast``).
4. Runway = months until the projected balance reaches zero. The interval
   gives an optimistic and a pessimistic date as well.

If the business is cash-positive (the line goes up) the runway is reported as
"not burning cash" rather than inventing a date.
"""

from __future__ import annotations

from typing import Any

from analytics.aggregates import monthly_series
from analytics.forecasting import _next_months, linear_forecast
from utils.config import FORECAST_CONFIDENCE_LEVEL

RUNWAY_HISTORY_MONTHS = 12
RUNWAY_MAX_HORIZON = 36


def quarterly_series(transactions: list[dict[str, Any]]) -> dict[str, list]:
    """Revenue, expense and profit per calendar quarter (from verified records)."""
    monthly = monthly_series(transactions)
    quarters: list[str] = []
    totals: dict[str, dict[str, float]] = {}
    months_in: dict[str, int] = {}
    for month, revenue, expense in zip(monthly["months"], monthly["revenue"], monthly["expense"]):
        quarter = f"{month[:4]}-Q{(int(month[5:7]) - 1) // 3 + 1}"
        if quarter not in totals:
            quarters.append(quarter)
            totals[quarter] = {"revenue": 0.0, "expense": 0.0}
            months_in[quarter] = 0
        totals[quarter]["revenue"] += revenue
        totals[quarter]["expense"] += expense
        months_in[quarter] += 1
    revenue = [round(totals[q]["revenue"], 2) for q in quarters]
    expense = [round(totals[q]["expense"], 2) for q in quarters]
    return {
        "quarters": quarters,
        "revenue": revenue,
        "expense": expense,
        "profit": [round(r - e, 2) for r, e in zip(revenue, expense)],
        "complete": [months_in[q] == 3 for q in quarters],
    }


def cash_history(months: list[str], profit: list[float], cash_balance: float, as_of: str | None) -> list[float]:
    """Month-end cash balance implied by monthly profit and one known balance."""
    anchor = months.index(as_of) if as_of in months else len(months) - 1
    balances = [0.0] * len(months)
    balances[anchor] = float(cash_balance)
    for i in range(anchor + 1, len(months)):
        balances[i] = balances[i - 1] + profit[i]
    for i in range(anchor - 1, -1, -1):
        balances[i] = balances[i + 1] - profit[i + 1]
    return [round(b, 2) for b in balances]


def _first_below_zero(values: list[float]) -> int | None:
    return next((i + 1 for i, value in enumerate(values) if value <= 0), None)


def runway(
    transactions: list[dict[str, Any]],
    finance: dict[str, Any] | None,
    *,
    profit_override: list[float] | None = None,
    level: float = FORECAST_CONFIDENCE_LEVEL,
) -> dict[str, Any]:
    """Cash runway from verified data and the configured cash balance."""
    finance = finance or {}
    if finance.get("cash_balance") in (None, ""):
        return {"configured": False,
                "message": "Enter the current cash balance in Settings to project runway."}
    series = monthly_series(transactions)
    months = series["months"]
    if len(months) < 3:
        return {"configured": True, "error": "At least 3 months of verified data are needed for runway."}
    as_of = finance.get("cash_as_of") or months[-1]
    profit = profit_override or series["profit"]
    history = cash_history(months, profit, float(finance["cash_balance"]), as_of)
    window = history[-RUNWAY_HISTORY_MONTHS:]
    window_months = months[-len(window):]
    projection = linear_forecast(window, RUNWAY_MAX_HORIZON, level)
    burn = -projection["params"]["slope_per_month"]
    point_zero = _first_below_zero(projection["point"])
    pessimistic_zero = _first_below_zero(projection["lower"])
    optimistic_zero = _first_below_zero(projection["upper"])
    future = _next_months(months[-1], RUNWAY_MAX_HORIZON)
    return {
        "configured": True,
        "cash_balance": float(finance["cash_balance"]),
        "cash_as_of": as_of,
        "cash_source": finance.get("source", "entered in Settings"),
        "history": {"months": window_months, "balance": window},
        "projection": {"months": future, **{k: projection[k] for k in ("point", "lower", "upper")}},
        "monthly_net_burn": round(burn, 2),
        "burning_cash": burn > 0,
        "runway_months": point_zero,
        "runway_months_range": {"pessimistic": pessimistic_zero, "optimistic": optimistic_zero},
        "cash_out_month": future[point_zero - 1] if point_zero else None,
        "confidence_level": level,
        "method": f"linear regression on the last {len(window)} months of month-end cash, {int(level * 100)}% interval",
        "summary": (
            f"At the current trend cash runs out in about {point_zero} months ({future[point_zero - 1]})."
            if point_zero else
            "Cash is not projected to run out within 36 months on the verified trend."
            if burn <= 0 else
            f"Burning about {burn:,.0f}/month; cash lasts beyond 36 months."
        ),
    }


def data_sources(transactions: list[dict[str, Any]], documents: list[dict[str, Any]], demo_dir: str) -> dict[str, Any]:
    """Which kinds of documents (and whether demo data) a set of transactions came from."""
    paths = {d["document_id"]: str(d.get("source_path") or "") for d in documents}
    kinds: dict[str, int] = {}
    demo = real = 0
    for transaction in transactions:
        for kind in transaction.get("document_types", []):
            kinds[kind] = kinds.get(kind, 0) + 1
        for doc_id in transaction.get("document_ids", []):
            if demo_dir and demo_dir in paths.get(doc_id, ""):
                demo += 1
            else:
                real += 1
    return {
        "documents_by_type": kinds,
        "demo_documents": demo,
        "uploaded_documents": real,
        "is_demo": demo > 0 and real == 0,
        "note": (
            "Built from the generated demo company (synthetic ledger and payments, real sample invoices)."
            if demo and not real else
            "Includes generated demo documents." if demo else
            "Built from uploaded documents."
        ),
    }
