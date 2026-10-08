"""Tests for the integrated pipeline: Stage 1 helpers, Stage 2 orchestration,
the reconciliation gate, Stage 4 analytics and the HTTP API."""

from __future__ import annotations

import csv
import math
from pathlib import Path

import pytest

from analytics.aggregates import monthly_series
from analytics.forecasting import backtest, forecast_series, linear_forecast
from analytics.verified import load_transactions, verified_transactions
from analytics.whatif import Scenario, simulate
from ingestion.extraction.dispatcher import parse_document
from ingestion.extraction.rule_parser import parse_document_rules
from ingestion.schemas.contracts import ExtractedField, SourceDocument
from ingestion.tabular.tabular_reader import extract_rows
from reconciliation.orchestrator import reconcile_documents
from storage import registry

OCR_INVOICE = """superstore INVOICE
# 36258
Date: Mar 06 2012
Bill To: Ship To:
Washington, United Balance Due: $50.10
Subtotal: $48.71
Discount (20%) : $9.74
Total: $50.10
Order ID : CA-2012-AB10015140-40974
"""


# --------------------------------------------------------------------------- helpers

def doc(doc_id: str, fields: dict, *, ocr: str | None = None, confidence: float = 0.95, **extra) -> SourceDocument:
    return SourceDocument(
        document_id=doc_id,
        source_path=f"{doc_id}.pdf",
        fields=[
            ExtractedField(field_id=f"f{i}", label=label, value=value, source_document_id=doc_id)
            for i, (label, value) in enumerate(fields.items())
        ],
        ocr_text=ocr,
        source_name=f"{doc_id}.pdf",
        extraction_confidence=confidence,
        low_confidence=confidence < 0.85,
        **extra,
    )


def invoice(doc_id: str, order: str, amount: str, day: str = "Mar 06 2012", **kw) -> SourceDocument:
    return doc(doc_id, {"Date": day, "Total": amount, "Order ID": order}, ocr="INVOICE", **kw)


def ledger(doc_id: str, order: str, amount: str, day: str = "2012-03-06", kind: str = "Revenue",
           category: str = "B2B Orders") -> SourceDocument:
    return doc(doc_id, {"Date": day, "Document Type": "Ledger", "Entry Type": kind,
                        "Category": category, "Order ID": order, "Amount": amount}, confidence=1.0)


def payment(doc_id: str, order: str, amount: str, day: str = "Mar 20 2012") -> SourceDocument:
    return doc(doc_id, {"Payment ID": doc_id.upper(), "Payment Date": day, "Order ID": order,
                        "Amount Paid": amount}, ocr="PAYMENT ADVICE")


def by_id(cases: list[dict]) -> dict[str, dict]:
    return {case["case_id"]: case for case in cases}


# --------------------------------------------------------------------------- Stage 1

def test_rule_parser_keeps_labels_and_values_verbatim() -> None:
    fields = {f["label"]: f["value"] for f in parse_document_rules(OCR_INVOICE)["fields"]}
    assert fields["#"] == "36258"
    assert fields["Date"] == "Mar 06 2012"
    assert fields["Balance Due"] == "$50.10"
    assert fields["Discount (20%)"] == "$9.74"
    assert fields["Order ID"] == "CA-2012-AB10015140-40974"
    assert fields["Bill To"] is None and fields["Ship To"] is None


def test_dispatcher_falls_back_to_rules_and_scales_confidence(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    data, method = parse_document(OCR_INVOICE, ocr_confidence=0.9)
    assert method.startswith("rules (fallback after ollama error")
    assert all(0 < f["confidence"] <= 0.9 for f in data["fields"])


def test_spreadsheet_rows_become_source_faithful_extractions(tmp_path: Path) -> None:
    path = tmp_path / "ledger.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Date", "Amount", "Note"])
        writer.writerow(["2012-03-06", "1,250.00", ""])
    rows = extract_rows(path)
    assert len(rows) == 1
    fields = {f["label"]: f["value"] for f in rows[0]["fields"]}
    assert fields == {"Date": "2012-03-06", "Amount": "1,250.00", "Note": None}


# --------------------------------------------------------------------------- Stage 2

def test_invoice_matches_ledger_and_ocr_split_identifiers_still_link() -> None:
    result = reconcile_documents([
        invoice("inv1", "IN-2012-AH100757-41 143", "$6,637.37"),
        ledger("led1", "IN-2012-AH100757-41143", "6637.37"),
    ])
    case = by_id(result.cases)["pair:inv1|led1"]
    assert case["status"] == "MATCHED"
    assert len(result.transactions) == 1
    assert result.transactions[0]["document_ids"] == ["inv1", "led1"]


def test_amount_tolerance_auto_resolves_then_escalates() -> None:
    result = reconcile_documents([
        invoice("inv1", "A-1", "$100.00"), ledger("led1", "A-1", "101.00"),
        invoice("inv2", "A-2", "$100.00"), ledger("led2", "A-2", "104.50"),
    ])
    cases = by_id(result.cases)
    assert cases["pair:inv1|led1"]["status"] == "AUTO_RESOLVED"
    assert cases["pair:inv2|led2"]["status"] == "ESCALATED"
    assert "numerical_mismatch" in cases["pair:inv2|led2"]["discrepancy_types"]


def test_duplicates_missing_documents_and_orphan_payments_are_flagged() -> None:
    result = reconcile_documents([
        invoice("inv1", "A-1", "$50.10"), invoice("inv2", "A-1", "$58.11"),
        ledger("led1", "A-1", "50.10"),
        invoice("inv3", "A-3", "$20.00"),               # never posted to the ledger
        payment("pay1", "Z-999", "$845.00"),            # pays an unknown order
        payment("pay2", "A-1", "$50.10", "Mar 25 2012"),  # paid 19 days later: fine
    ])
    cases = by_id(result.cases)
    assert cases["pair:inv1|inv2"]["case_type"] == "duplicate_entry"
    assert cases["pair:inv1|inv2"]["status"] == "ESCALATED"
    assert cases["doc:inv3:missing-ledger"]["status"] == "MISSING"
    assert cases["doc:pay1:missing-invoice"]["status"] == "MISSING"
    assert cases["pair:inv1|pay2"]["status"] == "MATCHED"


def test_low_confidence_extraction_is_escalated() -> None:
    result = reconcile_documents([invoice("inv1", "A-1", "$10.00", confidence=0.7)])
    case = by_id(result.cases)["doc:inv1:extraction"]
    assert case["status"] == "ESCALATED"
    assert "70.0%" in case["explanation"]


def test_document_type_falls_back_to_document_title() -> None:
    result = reconcile_documents([doc("x", {"Date": "Mar 06 2012", "Total": "$5"}, ocr="superstore INVOICE\n# 1")])
    assert result.facts["x"].document_type.value == "INVOICE"


# --------------------------------------------------------------------------- gate + registry

@pytest.fixture()
def db(tmp_path: Path) -> Path:
    return tmp_path / "registry.db"


def _store(db_path: Path, documents: list[SourceDocument]) -> None:
    registry.upsert_documents([d.model_dump() for d in documents], db_path)
    result = reconcile_documents(documents)
    registry.replace_run_results(cases=result.cases, links=result.links, transactions=result.transactions,
                                 summary=result.summary, db_path=db_path)


def test_gate_excludes_open_cases_and_applies_corrections(db: Path) -> None:
    documents = [invoice("inv1", "A-1", "$100.00"), ledger("led1", "A-1", "110.00")]
    _store(db, documents)
    assert verified_transactions(db) == []
    [transaction] = load_transactions(db)
    assert transaction["verification_status"] == "PENDING_REVIEW"

    registry.log_review_action("pair:inv1|led1", "CORRECT", "Ayushi", "ledger typo", "100.00",
                               db_path=db, field="amount")
    [verified] = verified_transactions(db)
    assert verified["verification_status"] == "CORRECTED"
    assert verified["amount"] == 100.0 and verified["original_amount"] == 100.0

    # a rerun must not overwrite the human decision
    _store(db, documents)
    assert registry.get_case("pair:inv1|led1", db)["status"] == "CORRECTED"


def test_rejected_transactions_are_quarantined(db: Path) -> None:
    _store(db, [invoice("inv1", "A-1", "$100.00"), ledger("led1", "A-1", "150.00")])
    registry.log_review_action("pair:inv1|led1", "REJECT", "Ayushi", "fraudulent", db_path=db)
    assert load_transactions(db)[0]["verification_status"] == "QUARANTINED"
    assert verified_transactions(db) == []


# --------------------------------------------------------------------------- Stage 4

def _synthetic(months: int = 30) -> list[dict]:
    rows = []
    for t in range(months):
        year, month = 2011 + t // 12, t % 12 + 1
        revenue = 1000 + 25 * t + 80 * math.sin(2 * math.pi * month / 12)
        rows.append({"date": f"{year}-{month:02d}-28", "kind": "revenue", "amount": revenue, "category": "Sales"})
        rows.append({"date": f"{year}-{month:02d}-05", "kind": "expense", "amount": 400 + 5 * t, "category": "Salaries & Wages"})
        rows.append({"date": f"{year}-{month:02d}-05", "kind": "expense", "amount": 200, "category": "Rent"})
    return rows


def test_monthly_series_fills_gaps() -> None:
    series = monthly_series([
        {"date": "2012-01-10", "kind": "revenue", "amount": 10},
        {"date": "2012-03-10", "kind": "expense", "amount": 4},
    ])
    assert series["months"] == ["2012-01", "2012-02", "2012-03"]
    assert series["revenue"] == [10, 0, 0] and series["profit"] == [10, 0, -4]


def test_linear_forecast_recovers_trend_with_widening_interval() -> None:
    result = linear_forecast([10 + 2 * t for t in range(12)], 3)
    assert result["point"] == pytest.approx([34, 36, 38], abs=1e-6)
    widths = [u - l for l, u in zip(result["lower"], result["upper"])]
    assert widths == sorted(widths)


def test_forecast_and_backtest_meet_target_on_clean_series() -> None:
    series = monthly_series(_synthetic())
    result = forecast_series(series["months"], series["revenue"], horizon=6)
    assert len(result["models"]["ensemble"]["point"]) == 6
    assert result["forecast_months"][0] == "2013-07"
    assert result["backtest"]["mape"]["ensemble"] < 15
    assert result["meets_target"] is True
    assert backtest([1.0] * 5, 6) is None


def test_whatif_levers_move_the_right_lines() -> None:
    rows = _synthetic()
    base = simulate(rows, Scenario())
    assert base["totals"]["delta"] == {"revenue": 0, "expense": 0, "profit": 0}
    hire = simulate(rows, Scenario(headcount_change=3, baseline_headcount=10))
    assert hire["totals"]["delta"]["expense"] > 0 and hire["totals"]["delta"]["revenue"] == 0
    save = simulate(rows, Scenario(vendor_consolidation_pct=20))
    assert save["totals"]["delta"]["expense"] < 0
    price = simulate(rows, Scenario(pricing_adjustment_pct=10, price_elasticity=0))
    assert price["totals"]["delta"]["revenue"] == pytest.approx(base["totals"]["baseline"]["revenue"] * 0.1, rel=1e-3)


# --------------------------------------------------------------------------- API

def test_api_review_validation_and_flow() -> None:
    from fastapi.testclient import TestClient
    from urllib.parse import quote

    from evostrategy_backend.main import app
    from utils.config import REGISTRY_DB

    registry.reset_registry(REGISTRY_DB)
    _store(REGISTRY_DB, [invoice("inv1", "A-1", "$100.00"), ledger("led1", "A-1", "110.00")])
    client = TestClient(app)
    case = quote("pair:inv1|led1", safe="")

    assert client.get("/api/summary").json()["open_cases"] == 1
    assert client.get("/api/cases?status=open").json()[0]["case_id"] == "pair:inv1|led1"
    detail = client.get(f"/api/cases/{case}/detail").json()
    assert {d["facts"]["document_id"] for d in detail["documents"]} == {"inv1", "led1"}

    assert client.post(f"/api/cases/{case}/review", json={"action": "REJECT", "reviewer": "A"}).status_code == 422
    bad = {"action": "CORRECT", "reviewer": "A", "reason": "x", "field": "amount", "corrected_value": "ten"}
    assert client.post(f"/api/cases/{case}/review", json=bad).status_code == 422
    good = {**bad, "corrected_value": "100.00"}
    response = client.post(f"/api/cases/{case}/review", json=good)
    assert response.status_code == 200 and response.json()["status"] == "CORRECTED"
    assert client.get("/api/audit").json()[0]["reviewer"] == "A"
    assert client.get("/api/analytics/overview").json()["totals"]["revenue"] == 100.0
    assert client.get("/api/forecast?metric=revenue").json()["error"]  # one month: not enough history
    assert client.get("/api/cases/nope/detail").status_code == 404
    upload = client.post("/api/ingestion/jobs", files={"files": ("notes.exe", b"x")})
    assert upload.status_code == 415
