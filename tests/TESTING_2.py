"""TESTING_2: tests for reconciliation, storage, and utility modules."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ingestion.schemas.invoice_schema import DocumentExtraction
from reconciliation.comparator import compare_exact, compare_numeric
from reconciliation.config import get_tolerance
from reconciliation.engine import reconcile_transactions
from reconciliation.model import ReconciliationStatus
from storage.registry import init_registry, upsert_cases
from utils import save_json
from utils.config import DEFAULT_TOLERANCE_PERCENT, PROJECT_ROOT
from utils.save_json import save_document


class ReconciliationTesting2(unittest.TestCase):
    """Verify current reconciliation decisions and result serialization."""

    def test_numeric_comparison_statuses(self) -> None:
        """Numeric values use matching, tolerance, and escalation statuses."""
        self.assertEqual(
            compare_numeric("amount", 100, 100).status,
            ReconciliationStatus.MATCHED,
        )
        self.assertEqual(
            compare_numeric("amount", 100, 101).status,
            ReconciliationStatus.AUTO_RESOLVED,
        )
        self.assertEqual(
            compare_numeric("amount", 100, 110).status,
            ReconciliationStatus.ESCALATED,
        )

    def test_numeric_comparison_handles_missing_and_invalid_values(self) -> None:
        """Missing values are classified and invalid values fail explicitly."""
        missing = compare_numeric("amount", 100, None)
        self.assertEqual(missing.status, ReconciliationStatus.MISSING)
        self.assertEqual(missing.discrepancy_type, "missing_value")

        with self.assertRaises(TypeError):
            compare_numeric("amount", "100", 100)  # type: ignore[arg-type]

    def test_exact_comparison_is_case_and_whitespace_insensitive(self) -> None:
        """Exact comparisons normalize only casing and surrounding whitespace."""
        result = compare_exact("vendor", "  ACME LTD ", "acme ltd")
        self.assertEqual(result.status, ReconciliationStatus.MATCHED)

        mismatch = compare_exact("vendor", "ACME", "OTHER")
        self.assertEqual(mismatch.status, ReconciliationStatus.ESCALATED)
        self.assertEqual(mismatch.discrepancy_type, "exact_mismatch")

    def test_tolerance_configuration_and_result_serialization(self) -> None:
        """Defaults, overrides, and JSON-friendly result dictionaries work."""
        self.assertEqual(get_tolerance("amount"), DEFAULT_TOLERANCE_PERCENT)
        result = compare_numeric("amount", 100, 100)
        serialized = result.as_dict()
        self.assertEqual(serialized["status"], "MATCHED")
        self.assertEqual(serialized["field"], "amount")


class EngineTesting2(unittest.TestCase):
    """Verify the transaction-level reconciliation orchestration."""

    def _transaction(self, transaction_id: str, amount: float = 100) -> object:
        from ingestion.schemas.contracts import CanonicalTransaction

        return CanonicalTransaction(
            transaction_id=transaction_id,
            document_id=transaction_id,
            vendor="Acme Ltd",
            identifier="INV-001",
            date="2026-01-01",
            amount=amount,
            mapping_confidence=1.0,
        )

    def test_reconcile_transactions_returns_field_results(self) -> None:
        """Linked transactions produce vendor, ID, date, and amount results."""
        results = reconcile_transactions(self._transaction("invoice"), self._transaction("ledger"))
        self.assertEqual(len(results), 4)
        self.assertTrue(all(result["confidence"] == 1.0 for result in results))
        self.assertTrue(all(result["status"] == "MATCHED" for result in results))

    def test_unlinked_transactions_escalate(self) -> None:
        """Transactions with insufficient linking evidence are escalated."""
        left = self._transaction("invoice")
        right = self._transaction("ledger")
        right.vendor = "Different Vendor"
        right.identifier = None
        right.date = "2027-01-01"
        right.amount = 500

        result = reconcile_transactions(left, right)
        self.assertEqual(result[0]["field"], "document_link")
        self.assertEqual(result[0]["status"], "ESCALATED")
        self.assertEqual(result[0]["discrepancy_type"], "entity_mismatch")


class StorageAndUtilityTesting2(unittest.TestCase):
    """Verify local SQLite persistence, JSON output, and project paths."""

    def setUp(self) -> None:
        """Create an isolated temporary database and extraction directory."""
        self.workspace = Path(tempfile.mkdtemp(prefix="evostrategy-testing-2-"))
        self.database = self.workspace / "registry.db"
        self.extraction_dir = self.workspace / "extracted"

    def tearDown(self) -> None:
        """Remove temporary test artifacts."""
        shutil.rmtree(self.workspace)

    def test_registry_creates_tables_and_upserts_idempotently(self) -> None:
        """Repeated case writes update one row instead of creating duplicates."""
        init_registry(self.database)
        case = {
            "case_id": "case-1",
            "transaction_id": "transaction-1",
            "status": "ESCALATED",
            "reason": "amount mismatch",
        }
        upsert_cases([case], self.database)
        upsert_cases([{**case, "status": "AUTO_RESOLVED"}], self.database)

        import sqlite3

        with sqlite3.connect(self.database) as connection:
            row_count = connection.execute(
                "SELECT COUNT(*) FROM reconciliation_cases"
            ).fetchone()[0]
            status = connection.execute(
                "SELECT status FROM reconciliation_cases WHERE case_id = ?",
                ("case-1",),
            ).fetchone()[0]

        self.assertEqual(row_count, 1)
        self.assertEqual(status, "AUTO_RESOLVED")

    def test_save_document_writes_json_to_configured_output(self) -> None:
        """Document JSON is written to the configured extraction directory."""
        document = DocumentExtraction(fields=[], tables=[])
        with patch.object(save_json, "EXTRACTION_DIR", self.extraction_dir):
            output_path = save_document(document, "invoice-001.pdf")

        saved_file = Path(output_path)
        self.assertEqual(saved_file, self.extraction_dir / "invoice-001.json")
        self.assertEqual(json.loads(saved_file.read_text()), {"fields": [], "tables": []})

    def test_project_paths_are_rooted_at_repository(self) -> None:
        """Central configuration resolves paths from the repository root."""
        self.assertTrue(PROJECT_ROOT.exists())
        # the clone may live in any folder name (e.g. evostrategy-backup)
        self.assertTrue((PROJECT_ROOT / "pipeline.py").is_file())


if __name__ == "__main__":
    unittest.main()
