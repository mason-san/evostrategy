"""
Mock discrepancy records — stand-in for Adham's reconciliation registry
until Stage 2 produces real output (Week 7+). Same field shape as the
planned per-transaction JSON schema so swapping to real data later is
a small change, not a rewrite.
"""

MOCK_RECORDS = [
    {
        "record_id": "INV-2291",
        "status": "ESCALATED",
        "discrepancy_type": "Amount mismatch",
        "flagged_hours_ago": 2,
        "match_confidence": 0.94,
        "documents": {
            "invoice": {
                "vendor": "Sundar Traders",
                "amount": 48200,
                "date": "2026-06-12",
            },
            "ledger": {
                "vendor": "Sundar Traders Pvt Ltd",
                "amount": 46800,
                "date": "2026-06-12",
            },
        },
        "mismatch_field": "amount",
        "difference": 1400,
        "tolerance_pct": 2,
    },
    {
        "record_id": "INV-2292",
        "status": "ESCALATED",
        "discrepancy_type": "Missing document",
        "flagged_hours_ago": 5,
        "match_confidence": 0.88,
        "documents": {
            "invoice": {
                "vendor": "Kaveri Textiles",
                "amount": 21000,
                "date": "2026-06-10",
            },
            "ledger": None,
        },
        "mismatch_field": None,
        "difference": None,
        "tolerance_pct": 2,
    },
    {
        "record_id": "INV-2293",
        "status": "ESCALATED",
        "discrepancy_type": "Vendor alias",
        "flagged_hours_ago": 8,
        "match_confidence": 0.91,
        "documents": {
            "invoice": {
                "vendor": "MG Enterprises",
                "amount": 15500,
                "date": "2026-06-09",
            },
            "ledger": {
                "vendor": "M.G. Enterprises Pvt Ltd",
                "amount": 15500,
                "date": "2026-06-09",
            },
        },
        "mismatch_field": "vendor",
        "difference": None,
        "tolerance_pct": 2,
    },
]
