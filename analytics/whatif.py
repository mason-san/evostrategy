"""What-if simulation on top of the verified baseline forecast.

Scenarios never modify stored data; they only transform the ensemble forecast.

Levers
- volume_change_pct         change in sales volume
- pricing_adjustment_pct    price change; volume reacts via ``price_elasticity``
- headcount_change          people added (+) or removed (-)
- vendor_consolidation_pct  savings on non-payroll vendor spend
- other_cost_change_pct     any other across-the-board cost change
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from analytics.aggregates import month_key, monthly_series
from analytics.forecasting import ensemble, linear_forecast, arima_forecast, _next_months

_PAYROLL_WORDS = ("salar", "payroll", "wage")


@dataclass
class Scenario:
    horizon: int = 6
    volume_change_pct: float = 0.0
    pricing_adjustment_pct: float = 0.0
    price_elasticity: float = 0.5
    headcount_change: int = 0
    baseline_headcount: int = 15
    vendor_consolidation_pct: float = 0.0
    other_cost_change_pct: float = 0.0


def _payroll_profile(transactions: list[dict[str, Any]], months: list[str]) -> tuple[float, float]:
    """(payroll share of expenses, monthly payroll) over the last 3 months."""
    recent = set(months[-3:])
    payroll = total = 0.0
    for transaction in transactions:
        if transaction["kind"] != "expense" or month_key(transaction["date"]) not in recent:
            continue
        amount = float(transaction["amount"])
        total += amount
        if any(word in str(transaction.get("category", "")).casefold() for word in _PAYROLL_WORDS):
            payroll += amount
    share = payroll / total if total else 0.0
    return share, payroll / max(len(recent), 1)


def simulate(transactions: list[dict[str, Any]], scenario: Scenario) -> dict[str, Any]:
    series = monthly_series(transactions)
    months = series["months"]
    if len(months) < 3:
        return {"error": "At least 3 months of verified data are needed for scenarios."}
    horizon = max(1, min(int(scenario.horizon), 24))
    base_revenue = ensemble(linear_forecast(series["revenue"], horizon), arima_forecast(series["revenue"], horizon))["point"]
    base_expense = ensemble(linear_forecast(series["expense"], horizon), arima_forecast(series["expense"], horizon))["point"]

    payroll_share, monthly_payroll = _payroll_profile(transactions, months)
    cost_per_head = monthly_payroll / scenario.baseline_headcount if scenario.baseline_headcount else 0.0

    price = scenario.pricing_adjustment_pct / 100
    revenue_factor = (1 + scenario.volume_change_pct / 100) * (1 + price) * (1 - scenario.price_elasticity * price)
    vendor_factor = (1 - scenario.vendor_consolidation_pct / 100) * (1 + scenario.other_cost_change_pct / 100)

    rows = []
    for month, revenue, expense in zip(_next_months(months[-1], horizon), base_revenue, base_expense):
        scenario_revenue = revenue * revenue_factor
        scenario_expense = (
            expense * payroll_share
            + scenario.headcount_change * cost_per_head
            + expense * (1 - payroll_share) * vendor_factor
        )
        rows.append({
            "month": month,
            "baseline": {"revenue": round(revenue, 2), "expense": round(expense, 2), "profit": round(revenue - expense, 2)},
            "scenario": {"revenue": round(scenario_revenue, 2), "expense": round(scenario_expense, 2),
                         "profit": round(scenario_revenue - scenario_expense, 2)},
        })

    def total(kind: str, metric: str) -> float:
        return round(sum(row[kind][metric] for row in rows), 2)

    totals = {
        kind: {metric: total(kind, metric) for metric in ("revenue", "expense", "profit")}
        for kind in ("baseline", "scenario")
    }
    totals["delta"] = {metric: round(totals["scenario"][metric] - totals["baseline"][metric], 2)
                       for metric in ("revenue", "expense", "profit")}
    return {
        "scenario": asdict(scenario),
        "assumptions": {
            "payroll_share_of_expense": round(payroll_share, 4),
            "monthly_cost_per_head": round(cost_per_head, 2),
            "revenue_factor": round(revenue_factor, 4),
            "non_payroll_cost_factor": round(vendor_factor, 4),
            "baseline_model": "ensemble (linear regression + ARIMA)",
        },
        "months": rows,
        "totals": totals,
    }
