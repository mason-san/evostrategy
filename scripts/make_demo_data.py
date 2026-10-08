"""Build the EvoStrategy demo dataset in data/demo/.

Contents
- invoices/   the 19 evaluation invoices (real PDFs, OCR'd by the pipeline)
- payments/   payment advice PDFs generated here (OCR'd by the pipeline)
- ledger/general_ledger.csv  33 months of revenue and expense postings

Planted reconciliation scenarios (so every path is exercised):
- invoice_005 is posted to the ledger 4.5% higher        -> ESCALATED numerical_mismatch
- invoice_006 is posted 1% higher                        -> AUTO_RESOLVED rounding variance
- invoice_012 is posted 3 days after its invoice date    -> AUTO_RESOLVED date variance
- invoice_004, 010, 013, 020 are never posted            -> MISSING (not in ledger)
- invoice_001/002, 011/015, 016/019 share an Order ID    -> duplicate_entry
- payment for invoice_014 is 8% short                    -> ESCALATED
- payment for invoice_009 is 1% short                    -> AUTO_RESOLVED
- one payment references an order that has no invoice   -> MISSING invoice

Run:  python scripts/make_demo_data.py
"""

from __future__ import annotations

import csv
import math
import random
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import fitz  # noqa: E402  (PyMuPDF)

from utils.config import DEMO_DATA_DIR  # noqa: E402

# Order ID, invoice date, invoice total (as printed on the evaluation invoices)
INVOICES = {
    "invoice_001": ("CA-2012-AB10015140-40974", date(2012, 3, 6), 50.10),
    "invoice_002": ("CA-2012-AB10015140-40974", date(2012, 3, 6), 58.11),
    "invoice_004": ("CA-2012-AB10015140-40958", date(2012, 2, 19), 22.17),
    "invoice_005": ("MX-2012-AH1003082-41251", date(2012, 12, 8), 2724.57),
    "invoice_006": ("IN-2012-AB1006059-41060", date(2012, 5, 31), 6263.17),
    "invoice_007": ("ES-2012-AH10075139-41251", date(2012, 12, 8), 6208.84),
    "invoice_008": ("IN-2012-AH100757-41143", date(2012, 8, 22), 6637.37),
    "invoice_009": ("ID-2012-AH100757-41163", date(2012, 9, 11), 1866.95),
    "invoice_010": ("CA-2012-AH10075140-41228", date(2012, 11, 15), 11.95),
    "invoice_011": ("IN-2012-AS1028558-41221", date(2012, 11, 8), 634.89),
    "invoice_012": ("CA-2012-AG10270140-41112", date(2012, 7, 22), 222.89),
    "invoice_013": ("CA-2012-AG10270140-41041", date(2012, 5, 12), 112.82),
    "invoice_014": ("IN-2013-AG1027027-41285", date(2013, 1, 11), 19782.76),
    "invoice_015": ("IN-2012-AS1028558-41221", date(2012, 11, 8), 7115.53),
    "invoice_016": ("CA-2012-BF10975140-41121", date(2012, 7, 31), 55.96),
    "invoice_017": ("CA-2012-BB10990140-41116", date(2012, 7, 26), 584.83),
    "invoice_018": ("CA-2012-BF10975140-41103", date(2012, 7, 13), 55.63),
    "invoice_019": ("CA-2012-BF10975140-41121", date(2012, 7, 31), 132.38),
    "invoice_020": ("CA-2012-BF11005140-41176", date(2012, 9, 24), 25.21),
}
UNPOSTED = {"invoice_004", "invoice_010", "invoice_013", "invoice_020"}
# duplicates are posted once, using the first invoice
DUPLICATE_SECONDARY = {"invoice_002", "invoice_015", "invoice_016"}
LEDGER_ADJUSTMENTS = {"invoice_005": (1.045, 0), "invoice_006": (1.01, 0), "invoice_012": (1.0, 3)}

START, END = date(2011, 1, 1), date(2013, 9, 1)

EXPENSES = [
    ("Salaries & Wages", "Payroll", lambda t, r: 38000 * (1.012 ** t)),
    ("Office Rent", "Coastal Properties Ltd", lambda t, r: 8500 if t < 18 else 9350),
    ("Cloud & IT Services", "Nimbus Cloud Pvt Ltd", lambda t, r: 2600 + 55 * t),
    ("Logistics & Shipping", "SwiftShip Logistics", lambda t, r: 0.058 * r),
    ("Marketing", "Brightline Media", lambda t, r: 4200 + (3800 if t % 12 in (9, 10) else 0)),
]
REVENUE_SPLIT = [("Technology", 0.41), ("Furniture", 0.33), ("Office Supplies", 0.26)]


def _months():
    current = START
    while current <= END:
        yield current
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)


def _write_ledger(path: Path, rng: random.Random) -> None:
    rows = []
    for t, month in enumerate(_months()):
        seasonal = 1 + 0.18 * math.sin(2 * math.pi * (month.month - 4) / 12) + (0.22 if month.month in (11, 12) else 0)
        revenue = 72000 * (1.017 ** t) * seasonal * rng.uniform(0.95, 1.05)
        month_end = (date(month.year + (month.month == 12), month.month % 12 + 1, 1) - timedelta(days=1))
        for category, share in REVENUE_SPLIT:
            rows.append([month_end.isoformat(), "Ledger", "Revenue", category, "Retail customers",
                         "", f"Monthly retail sales — {category}", f"{revenue * share:.2f}", "USD"])
        for category, vendor, amount in EXPENSES:
            posting = date(month.year, month.month, 5 if category != "Salaries & Wages" else 28)
            rows.append([posting.isoformat(), "Ledger", "Expense", category, vendor, "",
                         f"{category} — {month:%b %Y}", f"{amount(t, revenue) * rng.uniform(0.98, 1.02):.2f}", "USD"])
    for name, (order_id, invoice_date, total) in INVOICES.items():
        if name in UNPOSTED or name in DUPLICATE_SECONDARY:
            continue
        factor, delay = LEDGER_ADJUSTMENTS.get(name, (1.0, 0))
        rows.append([(invoice_date + timedelta(days=delay)).isoformat(), "Ledger", "Revenue",
                     "B2B Orders", "Business customer", order_id, f"Invoice {name.split('_')[1]}",
                     f"{total * factor:.2f}", "USD"])
    rows.sort(key=lambda row: row[0])
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Date", "Document Type", "Entry Type", "Category", "Counterparty",
                         "Order ID", "Description", "Amount", "Currency"])
        writer.writerows(rows)


def _payment_pdf(path: Path, payment_id: str, paid_on: date, order_id: str, amount: float) -> None:
    document = fitz.open()
    page = document.new_page()
    lines = [
        ("PAYMENT ADVICE", 20),
        ("", 11),
        (f"Payment ID: {payment_id}", 12),
        (f"Payment Date: {paid_on:%b %d %Y}", 12),
        (f"Order ID: {order_id}", 12),
        (f"Amount Paid: ${amount:,.2f}", 12),
        ("Method: Bank transfer", 12),
        ("", 11),
        ("Thank you. This advice confirms funds received.", 11),
    ]
    y = 90
    for text, size in lines:
        if text:
            page.insert_text((72, y), text, fontsize=size, fontname="helv")
        y += size + 14
    document.save(path)


PAYMENTS = [
    ("PAY-2012-0412", "invoice_007", 21, 1.0),
    ("PAY-2012-0388", "invoice_008", 25, 1.0),
    ("PAY-2012-0401", "invoice_009", 18, 0.99),
    ("PAY-2013-0027", "invoice_014", 30, 0.92),
    ("PAY-2012-0365", "invoice_017", 14, 1.0),
]


def main() -> None:
    rng = random.Random(42)
    if DEMO_DATA_DIR.exists():
        shutil.rmtree(DEMO_DATA_DIR)
    invoices = DEMO_DATA_DIR / "invoices"
    payments = DEMO_DATA_DIR / "payments"
    ledger = DEMO_DATA_DIR / "ledger"
    for folder in (invoices, payments, ledger):
        folder.mkdir(parents=True)

    for name in INVOICES:
        shutil.copy(ROOT / "evaluation_dataset" / "invoices" / f"{name}.pdf", invoices / f"{name}.pdf")
    for payment_id, invoice, days, factor in PAYMENTS:
        order_id, invoice_date, total = INVOICES[invoice]
        _payment_pdf(payments / f"{payment_id.lower()}.pdf", payment_id,
                     invoice_date + timedelta(days=days), order_id, round(total * factor, 2))
    _payment_pdf(payments / "pay-2012-0450.pdf", "PAY-2012-0450", date(2012, 12, 19),
                 "CA-2012-ZZ99999140-41260", 845.00)
    _write_ledger(ledger / "general_ledger.csv", rng)
    count = sum(1 for _ in DEMO_DATA_DIR.rglob("*.*"))
    print(f"Demo dataset written to {DEMO_DATA_DIR} ({count} files)")


if __name__ == "__main__":
    main()
