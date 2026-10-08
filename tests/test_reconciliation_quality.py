"""Reconciliation behaviours added for the plan's Stage 2 targets:
OCR-tolerant identifiers, reference-free ledger postings, duplicate folding,
and the precision/recall evaluation itself."""

from __future__ import annotations

from reconciliation.normalization import identifier_match_key
from reconciliation.orchestrator import reconcile_documents
from scripts.evaluate_reconciliation import (
    PRECISION_TARGET,
    RECALL_TARGET,
    benchmark,
    demo_truth,
    issue_key,
)
from tests.test_end_to_end import by_id, invoice, ledger


def test_identifier_key_survives_ocr_damage_but_not_different_numbers() -> None:
    clean = identifier_match_key("CA-2012-BF10975140-41121")
    assert identifier_match_key("CA-2012-BF1097514041121") == clean      # lost hyphen
    assert identifier_match_key("CA-2O12-BF10975140-41121") == clean     # O for 0
    assert identifier_match_key("CA-2012-BF109751 40-41121") == clean    # stray space
    assert identifier_match_key("CA-2012-BF10975140-41122") != clean     # a different order


def test_ocr_damaged_identifier_still_links_to_ledger() -> None:
    result = reconcile_documents([
        invoice("inv1", "CA-2O12-AB10015140-40974", "$50.10"),
        ledger("led1", "CA-2012-AB10015140-40974", "50.10"),
    ])
    assert by_id(result.cases)["pair:inv1|led1"]["status"] == "MATCHED"


def test_unreferenced_posting_links_only_when_unique() -> None:
    unique = reconcile_documents([invoice("inv1", "X-1", "$500.00"), ledger("led1", "", "500.00")])
    assert by_id(unique.cases)["pair:inv1|led1"]["status"] == "MATCHED"
    assert not any(c["case_type"] == "missing_document" for c in unique.cases)

    # two invoices could both be the posting -> no guess, both reported missing
    clash = reconcile_documents([
        invoice("inv1", "X-1", "$500.00"), invoice("inv2", "X-2", "$505.00"), ledger("led1", "", "500.00"),
    ])
    missing = {c["document_ids"][0] for c in clash.cases if c["case_type"] == "missing_document"}
    assert missing == {"inv1", "inv2"}


def test_unreferenced_posting_with_wrong_amount_is_escalated_not_matched() -> None:
    result = reconcile_documents([invoice("inv1", "X-1", "$500.00"), ledger("led1", "", "540.00")])
    case = by_id(result.cases)["pair:inv1|led1"]
    assert case["status"] == "ESCALATED"
    assert "numerical_mismatch" in case["discrepancy_types"]


def test_ledger_mismatch_against_duplicate_copy_is_folded_into_the_duplicate_case() -> None:
    result = reconcile_documents([
        invoice("inv1", "D-1", "$50.10"),
        invoice("inv2", "D-1", "$58.11"),
        ledger("led1", "D-1", "50.10"),
    ])
    cases = by_id(result.cases)
    assert "pair:inv2|led1" not in cases                      # not asked twice
    duplicate = cases["pair:inv1|inv2"]
    assert duplicate["status"] == "ESCALATED"                 # still open
    assert duplicate["related_evidence"][0]["folded_case_id"] == "pair:inv2|led1"
    assert len(result.transactions) == 1                      # whole group stays gated


def test_demo_ground_truth_comes_from_the_generator() -> None:
    truth = demo_truth()
    assert ("ledger_mismatch", "invoice_005") in truth        # 4.5% posting error
    assert ("ledger_mismatch", "invoice_006") not in truth    # 1% is within tolerance
    assert ("orphan_payment", "pay-2012-0450") in truth
    assert len(truth) == 10


def test_issue_key_maps_case_types() -> None:
    case = {"case_type": "missing_document", "document_ids": ["p1"],
            "documents": [{"document_id": "p1", "document_type": "PAYMENT"}]}
    assert issue_key(case) == ("orphan_payment", "p1")


def test_randomised_benchmark_meets_plan_targets() -> None:
    for hard in (False, True):
        report = benchmark(seeds=3, orders=30, hard=hard)
        assert report["precision"] >= PRECISION_TARGET, report
        assert report["recall"] >= RECALL_TARGET, report
