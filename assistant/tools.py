"""Read-only tools that give the LLM structured access to verified EvoStrategy data.

Every tool reads from ``analytics.verified.verified_transactions()`` — the same
reconciliation gate that feeds the dashboards — so the model can never quote a
number that a reviewer has not settled. Nothing here writes to the registry.
"""

from __future__ import annotations

import inspect
import json
from dataclasses import asdict, replace
from typing import Any, Callable

from analytics.aggregates import breakdown, budget_consumption, monthly_series
from analytics.finance import data_sources, quarterly_series, runway
from analytics.forecasting import forecast_series
from analytics.verified import OPEN_CASE_STATUSES, load_transactions, verified_transactions
from analytics.whatif import Scenario, simulate
from storage import registry
from utils.config import DEMO_DATA_DIR

MAX_ROWS = 50


class DataAccess:
    """One consistent snapshot of the verified data for a single question."""

    def __init__(self) -> None:
        self.all = load_transactions()
        self.verified = verified_transactions()
        self.budgets = registry.get_setting("budgets") or None
        self.finance = registry.get_setting("finance") or {}
        self.visual: dict[str, Any] | None = None       # first series the answer drew on
        self.supporting_ids: list[str] = []               # transactions the answer cited
        self.tools_used: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ context
    def evidence(self) -> dict[str, Any]:
        dates = sorted(t["date"] for t in self.verified if t.get("date"))
        total = len(self.all)
        return {
            "verified_records": len(self.verified),
            "total_records": total,
            "verified_rate": round(len(self.verified) / total, 4) if total else None,
            "date_from": dates[0] if dates else None,
            "date_to": dates[-1] if dates else None,
            "data_source": data_sources(self.verified, registry.get_documents(), str(DEMO_DATA_DIR)),
        }

    # ------------------------------------------------------------------ tools
    def data_overview(self) -> dict[str, Any]:
        series = monthly_series(self.verified)
        revenue, expense = sum(series["revenue"]), sum(series["expense"])
        cases = registry.get_cases()
        evidence = self.evidence()
        return {
            **evidence,
            "months_covered": len(series["months"]),
            "first_month": series["months"][0] if series["months"] else None,
            "last_month": series["months"][-1] if series["months"] else None,
            "total_revenue": round(revenue, 2),
            "total_expense": round(expense, 2),
            "total_profit": round(revenue - expense, 2),
            "open_review_cases": sum(1 for c in cases if c["status"] in OPEN_CASE_STATUSES),
            "excluded_unverified_records": len(self.all) - len(self.verified),
            "revenue_categories": sorted({t["category"] for t in self.verified if t["kind"] == "revenue" and t.get("category")}),
            "expense_categories": sorted({t["category"] for t in self.verified if t["kind"] == "expense" and t.get("category")}),
            "currency_note": "Amounts are reported as stored in the source documents; no currency conversion is applied.",
        }

    def time_series(self, granularity: str = "monthly") -> dict[str, Any]:
        if granularity == "quarterly":
            q = quarterly_series(self.verified)
            self._visual("Revenue by quarter", q["quarters"], q["revenue"], q["complete"])
            return {
                "granularity": "quarterly",
                "quarters": [
                    {"quarter": quarter, "revenue": rev, "expense": exp, "profit": prof,
                     "complete": complete, **({} if complete else {"warning": "partial quarter - fewer than 3 months of data"})}
                    for quarter, rev, exp, prof, complete in zip(q["quarters"], q["revenue"], q["expense"], q["profit"], q["complete"])
                ],
            }
        m = monthly_series(self.verified)
        self._visual("Revenue by month", m["months"], m["revenue"], None)
        return {
            "granularity": "monthly",
            "months": [
                {"month": month, "revenue": rev, "expense": exp, "profit": prof}
                for month, rev, exp, prof in zip(m["months"], m["revenue"], m["expense"], m["profit"])
            ],
        }

    def breakdown_by(self, dimension: str = "category", kind: str = "revenue", top: int = 10) -> dict[str, Any]:
        rows = breakdown(self.verified, dimension, kind, top=max(1, min(top, 30)))
        total = sum(float(t["amount"]) for t in self.verified if t["kind"] == kind)
        return {
            "dimension": dimension, "kind": kind, "total": round(total, 2),
            "rows": [{**r, "share_of_total": round(r["amount"] / total, 4) if total else None,
                                    "share_display": f"{r['amount'] / total:.1%}" if total else "n/a"} for r in rows],
        }

    def find_transactions(
        self, kind: str | None = None, category: str | None = None, counterparty: str | None = None,
        date_from: str | None = None, date_to: str | None = None, min_amount: float | None = None,
        max_amount: float | None = None, sort_by: str = "date", limit: int = 20,
    ) -> dict[str, Any]:
        def keep(t: dict[str, Any]) -> bool:
            return (
                (not kind or t["kind"] == kind)
                and (not category or category.lower() in (t.get("category") or "").lower())
                and (not counterparty or counterparty.lower() in (t.get("counterparty") or "").lower())
                and (not date_from or t["date"] >= date_from)
                and (not date_to or t["date"] <= date_to)
                and (min_amount is None or float(t["amount"]) >= min_amount)
                and (max_amount is None or float(t["amount"]) <= max_amount)
            )

        rows = [t for t in self.verified if keep(t)]
        rows.sort(key=(lambda t: -float(t["amount"])) if sort_by == "amount" else (lambda t: t["date"]), reverse=sort_by != "amount")
        shown = rows[: max(1, min(limit, MAX_ROWS))]
        self.supporting_ids.extend(t["transaction_id"] for t in shown if t["transaction_id"] not in self.supporting_ids)
        return {
            "matched": len(rows),
            "matched_total_amount": round(sum(float(t["amount"]) for t in rows), 2),
            "shown": len(shown),
            "transactions": [
                {
                    "transaction_id": t["transaction_id"], "date": t["date"], "kind": t["kind"],
                    "amount": t["amount"], "category": t.get("category"), "counterparty": t.get("counterparty"),
                    "verification_status": t["verification_status"], "source_documents": t.get("document_ids", []),
                }
                for t in shown
            ],
        }

    def compare_growth(self, dimension: str = "category", kind: str = "revenue") -> dict[str, Any]:
        """Latest complete quarter vs the one before, per category or counterparty."""
        q = quarterly_series(self.verified)
        complete = [quarter for quarter, ok in zip(q["quarters"], q["complete"]) if ok]
        if len(complete) < 2:
            return {"error": "Need at least two complete quarters of verified data to compare growth."}
        current, previous = complete[-1], complete[-2]

        def quarter_of(t: dict[str, Any]) -> str:
            return f"{t['date'][:4]}-Q{(int(t['date'][5:7]) - 1) // 3 + 1}"

        totals: dict[str, dict[str, float]] = {}
        for t in self.verified:
            if t["kind"] != kind:
                continue
            label = t.get(dimension) or "Unspecified"
            bucket = totals.setdefault(label, {current: 0.0, previous: 0.0})
            if quarter_of(t) in bucket:
                bucket[quarter_of(t)] += float(t["amount"])
        rows = [
            {"label": label, current: round(v[current], 2), previous: round(v[previous], 2),
             "change": round(v[current] - v[previous], 2),
             "change_pct": round((v[current] - v[previous]) / v[previous], 4) if v[previous] else None,
             "change_percent_display": f"{(v[current] - v[previous]) / v[previous]:+.1%}" if v[previous] else "n/a (no prior revenue)"}
            for label, v in totals.items()
        ]
        rows.sort(key=lambda r: r["change"], reverse=True)
        return {"dimension": dimension, "kind": kind, "current_quarter": current, "previous_quarter": previous, "rows": rows[:15]}

    def forecast(self, metric: str = "revenue", horizon: int = 6) -> dict[str, Any]:
        series = monthly_series(self.verified)
        if not series["months"]:
            return {"error": "No verified data yet."}
        result = forecast_series(series["months"], series[metric], horizon=max(1, min(horizon, 24)), non_negative=metric != "profit")
        if "error" in result:
            return result
        ensemble = result["models"]["ensemble"]
        backtest = result.get("backtest")
        return {
            "metric": metric, "method": "ensemble of linear regression and ARIMA",
            "confidence_level": result["confidence_level"],
            "forecast": [
                {"month": month, "point": round(p, 2), "lower": round(lo, 2), "upper": round(hi, 2)}
                for month, p, lo, hi in zip(result["forecast_months"], ensemble["point"], ensemble["lower"], ensemble["upper"])
            ],
            "holdout_mape": backtest["mape"] if backtest else None,
            "meets_accuracy_target": result["meets_target"],
            "history_months": len(series["months"]),
        }

    def cash_runway(self) -> dict[str, Any]:
        result = runway(self.verified, self.finance)
        if not result.get("configured") or "error" in result:
            return result
        keep = ("cash_balance", "cash_as_of", "monthly_net_burn", "burning_cash", "runway_months",
                "runway_months_range", "cash_out_month", "confidence_level", "method", "summary")
        return {k: result[k] for k in keep}

    def what_if(
        self, horizon: int = 6, volume_change_pct: float = 0.0, pricing_adjustment_pct: float = 0.0,
        price_elasticity: float = 0.5, headcount_change: int = 0, baseline_headcount: int | None = None,
        vendor_consolidation_pct: float = 0.0, other_cost_change_pct: float = 0.0,
    ) -> dict[str, Any]:
        scenario = Scenario(
            horizon=horizon, volume_change_pct=volume_change_pct, pricing_adjustment_pct=pricing_adjustment_pct,
            price_elasticity=price_elasticity, headcount_change=headcount_change,
            baseline_headcount=baseline_headcount or int(self.finance.get("headcount") or Scenario.baseline_headcount),
            vendor_consolidation_pct=vendor_consolidation_pct, other_cost_change_pct=other_cost_change_pct,
        )
        result = simulate(self.verified, scenario, budgets=self.budgets, finance=self.finance)
        if "error" in result:
            return result
        return {"assumptions": result["assumptions"], "totals": result["totals"], "budget": result["budget"], "runway": result["runway"]}

    def budget_status(self) -> dict[str, Any]:
        return budget_consumption(self.verified, self.budgets)

    def review_queue(self, limit: int = 15) -> dict[str, Any]:
        cases = [c for c in registry.get_cases() if c["status"] in OPEN_CASE_STATUSES]
        by_type: dict[str, int] = {}
        for c in cases:
            for kind in c.get("discrepancy_types", []):
                by_type[kind] = by_type.get(kind, 0) + 1
        return {
            "open_cases": len(cases),
            "discrepancy_types": by_type,
            "note": "Transactions in open cases are excluded from every verified number until a reviewer settles them.",
            "cases": [
                {"case_id": c["case_id"], "status": c["status"], "explanation": c.get("explanation"),
                 "discrepancy_types": c.get("discrepancy_types", []), "transaction_id": c.get("transaction_id")}
                for c in cases[: max(1, min(limit, 30))]
            ],
        }

    # ------------------------------------------------------------------ helpers
    def _visual(self, title: str, labels: list[str], values: list[float], complete: list[bool] | None) -> None:
        if self.visual is None:
            self.visual = {"title": title, "labels": labels, "values": values, "complete": complete}

    def run(self, name: str, args: dict[str, Any]) -> Any:
        handler = self._dispatch().get(name)
        if handler is None:
            raise ValueError(f"Unknown tool: {name}")
        accepted = inspect.signature(handler).parameters
        args = {k: v for k, v in args.items() if k in accepted and v is not None}
        self.tools_used.append({"name": name, "input": args})
        return handler(**args)

    def _dispatch(self) -> dict[str, Callable[..., Any]]:
        return {
            "get_data_overview": self.data_overview,
            "get_time_series": self.time_series,
            "get_breakdown": self.breakdown_by,
            "find_transactions": self.find_transactions,
            "compare_growth": self.compare_growth,
            "get_forecast": self.forecast,
            "get_cash_runway": self.cash_runway,
            "run_what_if": self.what_if,
            "get_budget_status": self.budget_status,
            "get_review_queue": self.review_queue,
        }


def _schema(properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False}


_KIND = {"type": "string", "enum": ["revenue", "expense"]}
_DIM = {"type": "string", "enum": ["category", "counterparty"], "description": "Group by category or by customer/vendor (counterparty)."}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {"name": "get_data_overview", "description": "Start here. Totals, date coverage, record counts, the share of records that passed reconciliation, open review cases, and the category names that exist. Use it to learn what data is available and what 'latest' means.",
     "input_schema": _schema()},
    {"name": "get_time_series", "description": "Verified revenue, expense and profit per month or per calendar quarter. Quarters flag partial ones (complete=false); never treat a partial quarter as a full one.",
     "input_schema": _schema({"granularity": {"type": "string", "enum": ["monthly", "quarterly"]}}, ["granularity"])},
    {"name": "get_breakdown", "description": "Top categories or counterparties by verified amount, with share of total.",
     "input_schema": _schema({"dimension": _DIM, "kind": _KIND, "top": {"type": "integer", "description": "Rows to return (1-30)."}}, ["dimension", "kind"])},
    {"name": "compare_growth", "description": "Latest complete quarter vs the previous complete quarter for each category or counterparty, sorted by absolute change. Use for 'who is growing fastest' or 'what drove the change'.",
     "input_schema": _schema({"dimension": _DIM, "kind": _KIND}, ["dimension", "kind"])},
    {"name": "find_transactions", "description": "Search individual verified transactions. Returns matched count and total across ALL matches plus up to `limit` rows with their source document ids. Use for specifics and to back a claim with records. Pass null for filters you do not need.",
     "input_schema": _schema({
         "kind": {"anyOf": [_KIND, {"type": "null"}]},
         "category": {"type": ["string", "null"], "description": "Case-insensitive substring."},
         "counterparty": {"type": ["string", "null"], "description": "Case-insensitive substring."},
         "date_from": {"type": ["string", "null"], "description": "YYYY-MM-DD inclusive."},
         "date_to": {"type": ["string", "null"], "description": "YYYY-MM-DD inclusive."},
         "min_amount": {"type": ["number", "null"]}, "max_amount": {"type": ["number", "null"]},
         "sort_by": {"type": "string", "enum": ["date", "amount"]},
         "limit": {"type": "integer", "description": "Rows to return (1-50)."},
     })},
    {"name": "get_forecast", "description": "Forecast of monthly revenue, expense or profit (ensemble of linear regression and ARIMA) with an interval and a holdout error (MAPE). Quote the interval and accuracy, not just the point value.",
     "input_schema": _schema({"metric": {"type": "string", "enum": ["revenue", "expense", "profit"]}, "horizon": {"type": "integer", "description": "Months ahead (1-24)."}}, ["metric"])},
    {"name": "get_cash_runway", "description": "Cash runway projection. Requires a cash balance entered in Settings; if configured=false, tell the user to add it rather than guessing.",
     "input_schema": _schema()},
    {"name": "run_what_if", "description": "Simulate a decision on top of the verified baseline forecast (nothing is saved). Percentages are whole numbers, e.g. 10 means +10%. Omit levers you do not need.",
     "input_schema": _schema({
         "horizon": {"type": "integer", "description": "Months to simulate (1-24)."},
         "volume_change_pct": {"type": "number"}, "pricing_adjustment_pct": {"type": "number"},
         "price_elasticity": {"type": "number", "description": "Volume reaction to price; 0.5 is the default assumption."},
         "headcount_change": {"type": "integer"}, "baseline_headcount": {"type": "integer"},
         "vendor_consolidation_pct": {"type": "number"}, "other_cost_change_pct": {"type": "number"},
     })},
    {"name": "get_budget_status", "description": "Spend vs budget per expense category (budgets come from Settings, or are derived and labelled as such).",
     "input_schema": _schema()},
    {"name": "get_review_queue", "description": "Open reconciliation discrepancies awaiting a human. Use to explain why a number might change or what needs attention.",
     "input_schema": _schema({"limit": {"type": "integer", "description": "Cases to return (1-30)."}})},
]


# Slider ranges of the What-if tab; the desk clamps to these so the screen can always show what was set.
LEVER_LIMITS: dict[str, tuple[float, float]] = {
    "volume_change_pct": (-30, 30), "pricing_adjustment_pct": (-20, 20), "price_elasticity": (0, 2),
    "headcount_change": (-10, 10), "vendor_consolidation_pct": (0, 30), "other_cost_change_pct": (-20, 20),
}
HORIZONS = (3, 6, 12)


class WhatIfDesk(DataAccess):
    """Data access for the What-if tab's assistant: it can also move the scenario levers on screen.

    ``set_scenario`` changes only the levers it is given, re-runs the real simulation and remembers
    the final scenario so the UI can show the same sliders and numbers. Nothing is stored.
    """

    def __init__(self, scenario: Scenario) -> None:
        super().__init__()
        self.scenario = scenario
        self.simulation: dict[str, Any] | None = None

    @property
    def system_extra(self) -> str:
        return (
            "\n\nYou are embedded in the What-if tab, next to the scenario sliders, and you can move them with "
            "set_scenario. When the user describes a decision (\"hire 3 people\", \"raise prices 8%\", \"what if sales drop\"), "
            "call set_scenario with only the levers that decision changes, then report profit, revenue, expense and runway "
            "from its result. Always compare with baseline. Levers are relative to the baseline forecast, not to last month. "
            "Slider limits: volume -30..30%, pricing -20..20%, elasticity 0..2, headcount -10..10 people, vendor savings "
            "0..30%, other cost -20..20%, horizon 3/6/12 months; values beyond them are clamped and the result says so, so "
            "tell the user when a move was capped. State the assumptions you chose (e.g. default elasticity). "
            "Current scenario on screen: " + json.dumps(asdict(self.scenario)) + "."
        )

    @property
    def tool_definitions(self) -> list[dict[str, Any]]:
        return [t for t in TOOL_DEFINITIONS if t["name"] != "run_what_if"] + [SET_SCENARIO_TOOL]

    def _dispatch(self) -> dict[str, Callable[..., Any]]:
        return {**super()._dispatch(), "set_scenario": self.set_scenario}

    def set_scenario(
        self, horizon: int | None = None, volume_change_pct: float | None = None,
        pricing_adjustment_pct: float | None = None, price_elasticity: float | None = None,
        headcount_change: int | None = None, vendor_consolidation_pct: float | None = None,
        other_cost_change_pct: float | None = None, reset: bool = False,
    ) -> dict[str, Any]:
        current = self.scenario
        if reset:
            current = Scenario(horizon=current.horizon, baseline_headcount=current.baseline_headcount)
        requested = {
            "horizon": horizon, "volume_change_pct": volume_change_pct, "pricing_adjustment_pct": pricing_adjustment_pct,
            "price_elasticity": price_elasticity, "headcount_change": headcount_change,
            "vendor_consolidation_pct": vendor_consolidation_pct, "other_cost_change_pct": other_cost_change_pct,
        }
        changes: dict[str, Any] = {}
        capped: list[str] = []
        for name, value in requested.items():
            if value is None:
                continue
            if name == "horizon":
                changes[name] = min(HORIZONS, key=lambda h: abs(h - int(value)))
                continue
            low, high = LEVER_LIMITS[name]
            clamped = max(low, min(high, float(value)))
            if clamped != float(value):
                capped.append(f"{name} {value:g} capped to {clamped:g}")
            changes[name] = int(round(clamped)) if name == "headcount_change" else round(clamped, 2)
        self.scenario = replace(current, **changes)
        result = simulate(self.verified, self.scenario, budgets=self.budgets, finance=self.finance)
        if "error" in result:
            return result
        self.simulation = result
        totals, budget = result["totals"], result["budget"]

        def pct(value: float | None, signed: bool = False) -> str:
            return "n/a" if value is None else f"{value:{'+' if signed else ''}.1%}"

        base_profit = totals["baseline"]["profit"]
        return {
            "applied_scenario": asdict(self.scenario),
            "capped": capped,
            "warnings": ([] if result["assumptions"]["monthly_cost_per_head"] or not self.scenario.headcount_change else [
                "The verified expenses contain no payroll/salary category, so a headcount change adds no cost in this simulation. "
                "Tell the user this; it is not something they can fix in Settings."]),
            "assumptions": result["assumptions"],
            "totals": totals,
            "profit_change_display": pct(totals["delta"]["profit"] / abs(base_profit), True) if base_profit else "n/a (baseline profit is zero)",
            "budget": {**budget, "baseline_consumption_display": pct(budget["baseline_consumption"]),
                       "scenario_consumption_display": pct(budget["scenario_consumption"])},
            "runway": result["runway"],
            "monthly_profit": [{"month": r["month"], "baseline": r["baseline"]["profit"], "scenario": r["scenario"]["profit"]}
                               for r in result["months"]],
        }


SET_SCENARIO_TOOL: dict[str, Any] = {
    "name": "set_scenario",
    "description": "Move the What-if sliders on the user's screen and run the simulation on the verified baseline forecast "
                   "(nothing is saved). Only the levers you pass are changed; the rest keep their current value. Percentages "
                   "are whole numbers (10 = +10%). Returns baseline vs scenario revenue, expense and profit, budget use and cash runway.",
    "input_schema": {"type": "object", "additionalProperties": False, "required": [], "properties": {
        "horizon": {"type": "integer", "enum": list(HORIZONS), "description": "Months to simulate."},
        "volume_change_pct": {"type": "number", "description": "Sales volume change, -30..30."},
        "pricing_adjustment_pct": {"type": "number", "description": "Price change, -20..20; volume reacts via elasticity."},
        "price_elasticity": {"type": "number", "description": "0..2; 0.5 is the default assumption."},
        "headcount_change": {"type": "integer", "description": "People added (+) or removed (-), -10..10."},
        "vendor_consolidation_pct": {"type": "number", "description": "Savings on non-payroll spend, 0..30."},
        "other_cost_change_pct": {"type": "number", "description": "Other across-the-board cost change, -20..20."},
        "reset": {"type": "boolean", "description": "Set every lever back to zero (default elasticity) before applying the others."},
    }},
}
