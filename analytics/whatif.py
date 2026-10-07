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


def annual_budget(transactions: list[dict[str, Any]], budgets: dict[str, float] | None) -> tuple[float | None, str]:
    """Total yearly expense budget: configured, else last 12 months' spend + 5%."""
    if budgets:
        return round(sum(float(v) for v in budgets.values()), 2), "configured"
    series = monthly_series(transactions)
    if not series["months"]:
        return None, "none"
    last_year = series["expense"][-12:]
    return round(sum(last_year) * 12 / len(last_year) * 1.05, 2), "last 12 months + 5%"


def _cash_path(cash: float | None, profits: list[float]) -> dict[str, Any] | None:
    """Ending cash and months until cash hits zero, for one profit path."""
    if cash is None:
        return None
    balance, out_month = float(cash), None
    for index, profit in enumerate(profits, start=1):
        balance += profit
        if out_month is None and balance <= 0:
            out_month = index
    average = sum(profits) / len(profits) if profits else 0.0
    if out_month is None and average < 0:
        out_month = round(len(profits) + balance / -average, 1)
    return {"ending_cash": round(balance, 2), "runway_months": out_month, "burning_cash": average < 0}


def simulate(
    transactions: list[dict[str, Any]],
    scenario: Scenario,
    *,
    budgets: dict[str, float] | None = None,
    finance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    series = monthly_series(transactions)
    months = series["months"]
    if len(months) < 3:
        return {"error": "At least 3 months of verified data are needed for scenarios."}
    horizon = max(1, min(int(scenario.horizon), 24))
    def baseline(values: list[float]) -> list[float]:
        # revenue and costs cannot go below zero, whatever the trend says
        return [max(0.0, v) for v in ensemble(linear_forecast(values, horizon), arima_forecast(values, horizon))["point"]]

    base_revenue = baseline(series["revenue"])
    base_expense = baseline(series["expense"])

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

    yearly, budget_source = annual_budget(transactions, budgets)
    window_budget = round(yearly / 12 * horizon, 2) if yearly else None
    budget = {
        "annual_budget": yearly,
        "budget_source": budget_source,
        "window_budget": window_budget,
        **{f"{kind}_consumption": round(totals[kind]["expense"] / window_budget, 4) if window_budget else None
           for kind in ("baseline", "scenario")},
    }
    cash = (finance or {}).get("cash_balance")
    cash = float(cash) if cash not in (None, "") else None
    runway = {
        "configured": cash is not None,
        "starting_cash": cash,
        "baseline": _cash_path(cash, [row["baseline"]["profit"] for row in rows]),
        "scenario": _cash_path(cash, [row["scenario"]["profit"] for row in rows]),
    }
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
        "budget": budget,
        "runway": runway,
    }
