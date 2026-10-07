"""Stage 4 additions: quarterly trends, budgets, runway, rolling backtest,
what-if budget/runway impact, forecast snapshots, settings and the audit chain."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from analytics.aggregates import budget_consumption
from analytics.finance import cash_history, quarterly_series, runway
from analytics.forecasting import rolling_backtest
from analytics.whatif import Scenario, simulate
from storage import registry


def tx(day: str, amount: float, kind: str = "revenue", category: str = "Sales") -> dict:
    return {"date": day, "amount": amount, "kind": kind, "category": category, "counterparty": "X",
            "document_ids": ["d"], "document_types": ["LEDGER"]}


def monthly(months: int, revenue: float, expense: float, growth: float = 0.0) -> list[dict]:
    rows = []
    for i in range(months):
        year, month = 2011 + i // 12, i % 12 + 1
        rows.append(tx(f"{year}-{month:02d}-15", revenue * (1 + growth) ** i))
        rows.append(tx(f"{year}-{month:02d}-15", expense, "expense", "Salaries & Wages" if i % 2 else "Rent"))
    return rows


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    path = tmp_path / "registry.db"
    registry.init_registry(path)
    return path


def test_quarterly_series_sums_months_and_flags_partial_quarters() -> None:
    q = quarterly_series(monthly(4, 100, 40))
    assert q["quarters"] == ["2011-Q1", "2011-Q2"]
    assert q["revenue"] == [300, 100]
    assert q["complete"] == [True, False]


def test_configured_budget_is_annual() -> None:
    rows = monthly(14, 100, 50)
    result = budget_consumption(rows, {"Rent": 600})
    rent = next(r for r in result["categories"] if r["category"] == "Rent")
    assert rent["budget"] == 600 and rent["budget_period"] == "annual"


def test_cash_history_is_anchored_on_the_stated_balance() -> None:
    assert cash_history(["a", "b", "c"], [10, 20, -5], 100, "b") == [80, 100, 95]


def test_runway_needs_a_cash_balance() -> None:
    assert runway(monthly(12, 100, 50), {})["configured"] is False


def test_runway_reports_cash_out_for_a_burning_business() -> None:
    result = runway(monthly(12, 100, 150), {"cash_balance": 500})
    assert result["burning_cash"] is True
    assert result["monthly_net_burn"] == pytest.approx(50, rel=0.01)
    assert result["runway_months"] == 10                      # 500 / 50
    low, high = result["runway_months_range"]["pessimistic"], result["runway_months_range"]["optimistic"]
    assert low <= result["runway_months"] <= (high or 99)


def test_runway_for_a_profitable_business_has_no_cash_out_date() -> None:
    result = runway(monthly(12, 150, 100), {"cash_balance": 500})
    assert result["runway_months"] is None and result["burning_cash"] is False


def test_rolling_backtest_uses_several_origins() -> None:
    values = [100 + 3 * i for i in range(30)]
    result = rolling_backtest(values)
    assert result["origins"] == 4 and result["mape"]["ensemble"] < 5
    assert rolling_backtest(values[:9]) is None              # too short: no fake accuracy


def test_whatif_reports_budget_and_runway_impact() -> None:
    rows = monthly(24, 1000, 800)
    result = simulate(rows, Scenario(headcount_change=10, baseline_headcount=10),
                      budgets=None, finance={"cash_balance": 1000})
    assert result["budget"]["scenario_consumption"] > result["budget"]["baseline_consumption"]
    assert result["runway"]["scenario"]["ending_cash"] < result["runway"]["baseline"]["ending_cash"]


def test_settings_round_trip(db: Path) -> None:
    registry.set_setting("budgets", {"Rent": 1200.0}, db)
    assert registry.get_setting("budgets", db_path=db) == {"Rent": 1200.0}
    assert registry.get_setting("missing", "default", db) == "default"


def test_forecast_snapshot_is_stored_once_per_distinct_input(db: Path) -> None:
    first = registry.save_forecast_snapshot("revenue", 6, "abc", {"x": 1}, db)
    again = registry.save_forecast_snapshot("revenue", 6, "abc", {"x": 1}, db)
    other = registry.save_forecast_snapshot("revenue", 6, "def", {"x": 2}, db)
    assert first == again != other
    assert len(registry.get_forecast_snapshots(db_path=db)) == 2


def test_audit_chain_detects_edits_and_deletions(db: Path) -> None:
    registry.upsert_cases([{"case_id": "c1", "transaction_id": "t1", "status": "ESCALATED"}], db)
    for action in ("ACCEPT", "REJECT", "ACCEPT"):
        registry.log_review_action("c1", action, "ayushi", "checked", db_path=db)
    assert registry.verify_audit_chain(db)["intact"] is True

    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE review_actions SET reviewer='someone else' WHERE id=2")
    assert registry.verify_audit_chain(db)["intact"] is False

    registry.reset_registry(db)
    registry.upsert_cases([{"case_id": "c1", "transaction_id": "t1", "status": "ESCALATED"}], db)
    for action in ("ACCEPT", "REJECT", "ACCEPT"):
        registry.log_review_action("c1", action, "ayushi", "checked", db_path=db)
    with sqlite3.connect(db) as connection:
        connection.execute("DELETE FROM review_actions WHERE id=2")
    assert registry.verify_audit_chain(db)["intact"] is False


def test_reset_keeps_a_backup_instead_of_deleting(db: Path) -> None:
    registry.set_setting("budgets", {"Rent": 1.0}, db)
    backup = registry.reset_registry(db)
    assert backup is not None and backup.exists()
    assert registry.get_setting("budgets", db_path=db) is None
    assert registry.get_setting("budgets", db_path=backup) == {"Rent": 1.0}


def test_api_settings_runway_snapshots_and_audit_verify() -> None:
    from fastapi.testclient import TestClient

    from evostrategy_backend.main import app
    from utils.config import REGISTRY_DB

    registry.reset_registry(REGISTRY_DB)
    client = TestClient(app)
    assert client.get("/api/runway").json()["configured"] is False
    bad = client.put("/api/settings", json={"finance": {"cash_balance": 100, "cash_as_of": "March"}})
    assert bad.status_code == 422
    saved = client.put("/api/settings", json={"budgets": {"Rent": 5000, " ": 3}, "finance": {"cash_balance": 1000}})
    assert saved.json()["budgets"] == {"Rent": 5000}
    assert saved.json()["finance"]["cash_balance"] == 1000
    assert client.get("/api/forecast").json()["error"] == "No verified data yet."
    assert client.get("/api/audit/verify").json()["intact"] is True


def test_revenue_and_expense_forecasts_never_go_negative() -> None:
    from analytics.forecasting import forecast_series

    falling = [1000 - 90 * i for i in range(12)]
    result = forecast_series([f"2012-{m:02d}" for m in range(1, 13)], falling, horizon=6, non_negative=True)
    assert min(result["models"]["ensemble"]["point"]) == 0
    assert result["models"]["ensemble"]["clipped_at_zero"] is True
