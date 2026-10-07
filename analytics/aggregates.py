"""Verified-only aggregates: monthly trends, categories, counterparties, budgets."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def month_key(value: str) -> str:
    return str(value)[:7]


def _month_range(first: str, last: str) -> list[str]:
    year, month = int(first[:4]), int(first[5:7])
    months = []
    while f"{year:04d}-{month:02d}" <= last:
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return months


def monthly_series(transactions: list[dict[str, Any]]) -> dict[str, list]:
    """Revenue, expense and profit per calendar month (gaps filled with 0)."""
    if not transactions:
        return {"months": [], "revenue": [], "expense": [], "profit": []}
    totals: dict[str, dict[str, float]] = defaultdict(lambda: {"revenue": 0.0, "expense": 0.0})
    for transaction in transactions:
        totals[month_key(transaction["date"])][transaction["kind"]] += float(transaction["amount"])
    months = _month_range(min(totals), max(totals))
    revenue = [round(totals[m]["revenue"], 2) for m in months]
    expense = [round(totals[m]["expense"], 2) for m in months]
    return {
        "months": months,
        "revenue": revenue,
        "expense": expense,
        "profit": [round(r - e, 2) for r, e in zip(revenue, expense)],
    }


def breakdown(transactions: list[dict[str, Any]], key: str, kind: str, top: int = 8) -> list[dict[str, Any]]:
    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for transaction in transactions:
        if transaction["kind"] == kind:
            label = transaction.get(key) or "Unspecified"
            totals[label] += float(transaction["amount"])
            counts[label] += 1
    ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)
    return [{"label": label, "amount": round(amount, 2), "count": counts[label]} for label, amount in ranked[:top]]


def budget_consumption(transactions: list[dict[str, Any]], budgets: dict[str, float] | None = None) -> dict[str, Any]:
    """Expense by category for the latest year vs a budget.

    A configured budget is an annual figure, so consumption is "share of the
    year's budget used so far". Without one, each category's budget is the
    previous year's spend for the same months plus 5% — a transparent default.
    """
    expenses = [t for t in transactions if t["kind"] == "expense"]
    if not expenses:
        return {"year": None, "through_month": None, "categories": []}
    latest = max(month_key(t["date"]) for t in expenses)
    year, through = int(latest[:4]), int(latest[5:7])
    current: dict[str, float] = defaultdict(float)
    previous: dict[str, float] = defaultdict(float)
    for transaction in expenses:
        month = month_key(transaction["date"])
        if int(month[5:7]) > through:
            continue
        if int(month[:4]) == year:
            current[transaction["category"]] += float(transaction["amount"])
        elif int(month[:4]) == year - 1:
            previous[transaction["category"]] += float(transaction["amount"])
    rows = []
    for category in sorted(set(current) | set(previous)):
        budget = (budgets or {}).get(category) or round(previous.get(category, 0.0) * 1.05, 2)
        spent = round(current.get(category, 0.0), 2)
        rows.append({
            "category": category,
            "spent": spent,
            "budget": budget,
            "consumption": round(spent / budget, 4) if budget else None,
            "budget_source": "configured" if budgets and category in budgets else "prior year +5%",
            "budget_period": "annual" if budgets and category in budgets else f"Jan-{through:02d} of prior year",
        })
    rows.sort(key=lambda row: row["spent"], reverse=True)
    return {"year": year, "through_month": through, "categories": rows}


def traceability(all_transactions: list[dict[str, Any]], verified: list[dict[str, Any]]) -> dict[str, Any]:
    """What every chart is built from: record counts, period, verification mix."""
    statuses: dict[str, int] = defaultdict(int)
    for transaction in all_transactions:
        statuses[transaction["verification_status"]] += 1
    dates = sorted(t["date"] for t in verified if t.get("date"))
    return {
        "verified_records": len(verified),
        "total_records": len(all_transactions),
        "source_documents": sum(t.get("source_count", 1) for t in verified),
        "date_from": dates[0] if dates else None,
        "date_to": dates[-1] if dates else None,
        "status_counts": dict(statuses),
    }


def overview(
    all_transactions: list[dict[str, Any]],
    verified: list[dict[str, Any]],
    budgets: dict[str, float] | None = None,
) -> dict[str, Any]:
    from analytics.finance import quarterly_series

    series = monthly_series(verified)
    revenue = sum(series["revenue"])
    expense = sum(series["expense"])
    return {
        "totals": {
            "revenue": round(revenue, 2),
            "expense": round(expense, 2),
            "profit": round(revenue - expense, 2),
            "margin": round((revenue - expense) / revenue, 4) if revenue else None,
        },
        "monthly": series,
        "quarterly": quarterly_series(verified),
        "revenue_by_category": breakdown(verified, "category", "revenue"),
        "expense_by_category": breakdown(verified, "category", "expense"),
        "top_counterparties": breakdown(verified, "counterparty", "expense", top=6),
        "budget": budget_consumption(verified, budgets),
        "expense_by_counterparty": breakdown(verified, "counterparty", "expense", top=12),
        "traceability": traceability(all_transactions, verified),
    }
