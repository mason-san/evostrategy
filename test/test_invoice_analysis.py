import pandas as pd

from src.dashboard import build_vendor_priority_queue
from src.main import DecisionRules, analyze_invoices
from src.report import build_management_report


def test_total_pending_amount():
    result = analyze_invoices()

    assert result["total_pending"] == 57150


def test_highest_pending_vendor():
    result = analyze_invoices()

    assert result["vendor"] == "ABC Supplies"


def test_decision_score():
    result = analyze_invoices()

    assert result["decision_score"] == 100


def test_risk_level():
    result = analyze_invoices()

    assert result["risk_level"] == "HIGH"


def test_recommendation():
    result = analyze_invoices()

    assert result["recommendation"] == "Review payment with this vendor immediately."


def test_low_risk_vendor(tmp_path, monkeypatch):
    data_folder = tmp_path / "data"
    data_folder.mkdir()

    invoice_file = data_folder / "invoice.csv"

    invoice_file.write_text(
        "invoice_id,vendor,amount,status\n"
        "INV001,Small Vendor,5000,Pending\n"
    )

    monkeypatch.chdir(tmp_path)

    result = analyze_invoices()

    assert result["risk_level"] == "LOW"
    assert result["recommendation"] == "Continue normal monitoring."


def test_medium_risk_vendor(tmp_path, monkeypatch):
    data_folder = tmp_path / "data"
    data_folder.mkdir()

    invoice_file = data_folder / "invoice.csv"

    invoice_file.write_text(
        "invoice_id,vendor,amount,status\n"
        "INV002,Medium Vendor,15000,Pending\n"
    )

    monkeypatch.chdir(tmp_path)

    result = analyze_invoices()

    assert result["risk_level"] == "MEDIUM"
    assert result["recommendation"] == "Schedule a payment review."


def test_high_risk_vendor(tmp_path, monkeypatch):
    data_folder = tmp_path / "data"
    data_folder.mkdir()

    invoice_file = data_folder / "invoice.csv"

    invoice_file.write_text(
        "invoice_id,vendor,amount,status\n"
        "INV003,High Risk Vendor,25000,Pending\n"
    )

    monkeypatch.chdir(tmp_path)

    result = analyze_invoices()

    assert result["risk_level"] == "HIGH"
    assert result["recommendation"] == "Review payment with this vendor immediately."


def test_no_pending_invoices(tmp_path, monkeypatch):
    data_folder = tmp_path / "data"
    data_folder.mkdir()

    invoice_file = data_folder / "invoice.csv"

    invoice_file.write_text(
        "invoice_id,vendor,amount,status\n"
        "INV004,Test Vendor,5000,Paid\n"
    )

    monkeypatch.chdir(tmp_path)

    result = analyze_invoices()

    assert result["total_pending"] == 0
    assert result["vendor"] is None
    assert result["pending_amount"] == 0
    assert result["risk_level"] == "LOW"


def test_medium_risk_boundary(tmp_path, monkeypatch):
    data_folder = tmp_path / "data"
    data_folder.mkdir()

    invoice_file = data_folder / "invoice.csv"

    invoice_file.write_text(
        "invoice_id,vendor,amount,status\n"
        "INV004,Boundary Vendor,10000,Pending\n"
    )

    monkeypatch.chdir(tmp_path)

    result = analyze_invoices()

    assert result["risk_level"] == "MEDIUM"
    assert result["recommendation"] == "Schedule a payment review."


def test_high_risk_boundary(tmp_path, monkeypatch):
    data_folder = tmp_path / "data"
    data_folder.mkdir()

    invoice_file = data_folder / "invoice.csv"

    invoice_file.write_text(
        "invoice_id,vendor,amount,status\n"
        "INV005,High Boundary Vendor,20000,Pending\n"
    )

    monkeypatch.chdir(tmp_path)

    result = analyze_invoices()

    assert result["risk_level"] == "HIGH"
    assert result["recommendation"] == "Review payment with this vendor immediately."


def test_paid_invoice_not_included(tmp_path, monkeypatch):
    data_folder = tmp_path / "data"
    data_folder.mkdir()

    invoice_file = data_folder / "invoice.csv"

    invoice_file.write_text(
        "invoice_id,vendor,amount,status\n"
        "INV006,Paid Vendor,50000,Paid\n"
    )

    monkeypatch.chdir(tmp_path)

    result = analyze_invoices()

    assert result["total_pending"] == 0
    assert result["vendor"] is None
    assert result["pending_amount"] == 0
    assert result["risk_level"] == "LOW"


def test_vendor_pending_amount_is_aggregated(tmp_path, monkeypatch):
    data_folder = tmp_path / "data"
    data_folder.mkdir()

    invoice_file = data_folder / "invoice.csv"

    invoice_file.write_text(
        "invoice_id,vendor,amount,status\n"
        "INV007,Repeat Vendor,12000,Pending\n"
        "INV008,Repeat Vendor,9000,Pending\n"
    )

    monkeypatch.chdir(tmp_path)

    result = analyze_invoices()

    assert result["vendor"] == "Repeat Vendor"
    assert result["pending_amount"] == 21000
    assert result["total_pending"] == 21000
    assert result["risk_level"] == "HIGH"
    assert result["recommendation"] == "Review payment with this vendor immediately."


def test_custom_decision_rules_change_the_outcome(tmp_path, monkeypatch):
    data_folder = tmp_path / "data"
    data_folder.mkdir()

    invoice_file = data_folder / "invoice.csv"

    invoice_file.write_text(
        "invoice_id,vendor,amount,status\n"
        "INV009,Policy Vendor,15000,Pending\n"
    )

    monkeypatch.chdir(tmp_path)

    rules = DecisionRules(
        high_exposure_threshold=20000,
        medium_exposure_threshold=10000,
        multiple_pending_invoice_count=2,
        high_average_invoice_threshold=20000,
    )

    result = analyze_invoices(rules)

    assert result["decision_score"] == 30
    assert result["risk_level"] == "LOW"
    assert result["recommendation"] == "Continue normal monitoring."


def test_vendor_priority_queue_orders_and_explains_vendors():
    pending_invoices = pd.DataFrame(
        {
            "invoice_id": ["INV001", "INV002", "INV003", "INV004"],
            "vendor": ["ABC Supplies", "ABC Supplies", "Global Parts", "XYZ Traders"],
            "amount": [12500, 9200, 15750, 8400],
        }
    )

    queue = build_vendor_priority_queue(
        pending_invoices,
        DecisionRules(),
    )

    assert queue["Vendor"].tolist() == [
        "ABC Supplies",
        "Global Parts",
        "XYZ Traders",
    ]
    assert queue["Risk level"].tolist() == ["HIGH", "MEDIUM", "LOW"]
    assert queue.iloc[0]["Recommended action"] == "Review payment immediately"
    assert "₹20,000 high-exposure threshold" in queue.iloc[0]["Reason"]


def test_management_report_contains_decision_and_priority_queue():
    result = analyze_invoices()
    rules = DecisionRules()
    intelligence = {
        "insights": ["ABC Supplies requires immediate review."],
    }
    pending_invoices = pd.DataFrame(
        {
            "invoice_id": ["INV001", "INV002"],
            "vendor": ["ABC Supplies", "ABC Supplies"],
            "amount": [12500, 9200],
        }
    )
    priority_queue = build_vendor_priority_queue(pending_invoices, rules)

    report = build_management_report(
        result=result,
        rules=rules,
        intelligence=intelligence,
        priority_queue=priority_queue,
    )

    assert "# EvoStrategy Management Report" in report
    assert "**Decision score:** 100 / 100" in report
    assert "## Active decision rules" in report
    assert "## Vendor payment-priority queue" in report
    assert "Review payment immediately" in report


def test_generate_kpis():
    from src.main import generate_kpis

    result = {
        "total_pending": 57150,
        "pending_invoice_count": 4,
        "vendor": "ABC Supplies",
        "pending_amount": 25000,
        "risk_level": "HIGH",
    }

    kpis = generate_kpis(result)

    assert kpis["total_pending_amount"] == 57150
    assert kpis["pending_invoice_count"] == 4
    assert kpis["highest_risk_vendor"] == "ABC Supplies"
    assert kpis["highest_vendor_pending_amount"] == 25000
    assert kpis["risk_level"] == "HIGH"


def test_risk_distribution_kpi():
    from src.main import generate_risk_distribution

    risk_data = ["LOW", "MEDIUM", "HIGH", "HIGH", "LOW"]

    result = generate_risk_distribution(risk_data)

    assert result["LOW"] == 2
    assert result["MEDIUM"] == 1
    assert result["HIGH"] == 2
