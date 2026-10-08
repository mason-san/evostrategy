"""One test that walks the whole system through the HTTP API, with real files:

real invoice PDFs + a payment advice PDF + a ledger CSV
  -> upload -> OCR -> extraction -> normalization -> reconciliation
  -> discrepancy in the review queue -> reviewer decision (audited, hash-chained)
  -> gate releases the transaction -> analytics / forecast / runway / what-if
     all built from verified records only.

Needs the Tesseract binary (skipped otherwise). Takes ~20 s.
"""

from __future__ import annotations

import csv
import shutil
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INVOICES = ROOT / "evaluation_dataset" / "invoices"

pytestmark = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")


def _ledger(path: Path) -> None:
    rows = []
    for i in range(24):                      # 2011-2012: background revenue/expense
        year, month = 2011 + (i // 12), i % 12 + 1
        rows.append([f"{year}-{month:02d}-28", "Ledger", "Revenue", "Retail", "Retail customers", "",
                     "Monthly sales", f"{60000 + 1500 * i:.2f}", "USD"])
        rows.append([f"{year}-{month:02d}-05", "Ledger", "Expense", "Office Rent", "Coastal Properties Ltd", "",
                     "Rent", "9000.00", "USD"])
    # invoice_005 (2,724.57) is booked 4.5% too high; invoice_007 is booked correctly
    rows.append(["2012-12-08", "Ledger", "Revenue", "B2B Orders", "Business customer",
                 "MX-2012-AH1003082-41251", "Invoice 005", f"{2724.57 * 1.045:.2f}", "USD"])
    rows.append(["2012-12-08", "Ledger", "Revenue", "B2B Orders", "Business customer",
                 "ES-2012-AH10075139-41251", "Invoice 007", "6208.84", "USD"])
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Date", "Document Type", "Entry Type", "Category", "Counterparty",
                         "Order ID", "Description", "Amount", "Currency"])
        writer.writerows(rows)


def test_document_to_dashboard(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from evostrategy_backend.main import app
    from scripts.make_demo_data import _payment_pdf
    from storage import registry
    from utils.config import REGISTRY_DB

    registry.reset_registry(REGISTRY_DB)
    client = TestClient(app)

    ledger = tmp_path / "general_ledger.csv"
    _ledger(ledger)
    payment = tmp_path / "pay-2012-0412.pdf"
    _payment_pdf(payment, "PAY-2012-0412", date(2012, 12, 29), "ES-2012-AH10075139-41251", 6208.84)
    files = [INVOICES / "invoice_005.pdf", INVOICES / "invoice_007.pdf", payment, ledger]

    # 1. upload -> Stage 1 + Stage 2 run as a background job
    upload = client.post("/api/ingestion/jobs", files=[("files", (f.name, f.read_bytes())) for f in files])
    assert upload.status_code == 202
    job = client.get(f"/api/ingestion/jobs/{upload.json()['job_id']}").json()
    assert job["status"] == "completed", job
    assert not job["failures"]

    # 2. OCR + extraction kept the source labels and values
    invoice = client.get("/api/documents/invoice_005").json()
    fields = {f["label"]: f["value"] for f in invoice["fields"]}
    assert fields["Order ID"] == "MX-2012-AH1003082-41251"
    assert fields["Total"] == "$2,724.57"
    assert all(f["confidence"] is not None for f in invoice["fields"])

    # 3. reconciliation: the 4.5% posting error is escalated, the clean pair matched
    cases = {c["case_id"]: c for c in client.get("/api/cases").json()}
    mismatch = next(c for c in cases.values() if "invoice_005" in [d["document_id"] for d in c["documents"]]
                    and c["case_type"] == "document_pair")
    assert mismatch["status"] == "ESCALATED" and "numerical_mismatch" in mismatch["discrepancy_types"]
    assert any(c["status"] == "MATCHED" and {"invoice_007", "pay-2012-0412"} <= {d["document_id"] for d in c["documents"]}
               for c in cases.values())

    # 4. the gate keeps the open transaction out of analytics
    before = client.get("/api/analytics/overview").json()["traceability"]
    assert before["status_counts"].get("PENDING_REVIEW", 0) >= 1

    # 5. a reviewer corrects the ledger amount, with a reason -> audited
    reviewed = client.post(f"/api/cases/{mismatch['case_id']}/review", json={
        "action": "CORRECT", "reviewer": "Ayushi", "reason": "Invoice total checked against PDF",
        "field": "amount", "corrected_value": "2724.57"})
    assert reviewed.status_code == 200 and reviewed.json()["status"] == "CORRECTED"
    audit = client.get("/api/audit").json()
    assert audit[0]["reviewer"] == "Ayushi" and audit[0]["corrected_value"] == "2724.57"
    assert client.get("/api/audit/verify").json()["intact"] is True

    # 6. the corrected transaction now reaches analytics, with the corrected amount
    after = client.get("/api/analytics/overview").json()
    assert after["traceability"]["verified_records"] == before["verified_records"] + 1
    assert after["traceability"]["status_counts"].get("CORRECTED") == 1

    # 7. forecast, runway and what-if are computed from those verified records
    forecast = client.get("/api/forecast?metric=revenue&horizon=3").json()
    assert len(forecast["models"]["ensemble"]["point"]) == 3
    assert forecast["traceability"]["verified_records"] == after["traceability"]["verified_records"]
    assert forecast["backtest"] is not None and forecast["snapshot_id"] >= 1
    client.put("/api/settings", json={"finance": {"cash_balance": 100000, "headcount": 10}})
    runway = client.get("/api/runway").json()
    assert runway["configured"] and runway["burning_cash"] is False
    whatif = client.post("/api/whatif", json={"horizon": 6, "headcount_change": 30, "baseline_headcount": 10}).json()
    assert whatif["totals"]["delta"]["expense"] == 0      # no payroll category in this ledger
    assert whatif["runway"]["scenario"]["ending_cash"] == whatif["runway"]["baseline"]["ending_cash"]
    cut = client.post("/api/whatif", json={"horizon": 6, "vendor_consolidation_pct": 20}).json()
    assert cut["totals"]["delta"]["expense"] < 0 and cut["budget"]["scenario_consumption"] < cut["budget"]["baseline_consumption"]

    # 8. live metrics are served
    metrics = client.get("/api/metrics").json()
    assert metrics["live_review_efficiency"]["documents_needing_reconciliation"] >= 4
