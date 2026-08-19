"""Run evaluation across all parsers and print a comparison report."""

from ingestion.extraction.parser import parse_invoice
from ingestion.extraction.regex_parser import parse_invoice_regex
from evaluation.evaluator import INVOICES_DIR, evaluate_multiple_invoices

PARSERS = {
    "keyword_parser": parse_invoice,
    "regex_parser": parse_invoice_regex,
}


def print_report(name: str, results: dict) -> None:
    """Print a formatted accuracy report for one parser."""
    print(f"\n{'=' * 50}")
    print(f"  Parser: {name}")
    print(f"{'=' * 50}")
    print(f"  Documents evaluated : {results['documents_evaluated']}")
    print(f"  Invoice Number      : {results['invoice_number_accuracy']}%")
    print(f"  Invoice Date        : {results['invoice_date_accuracy']}%")
    print(f"  Total Amount        : {results['total_amount_accuracy']}%")
    print(f"  ─────────────────────────────────")
    print(f"  Overall Accuracy    : {results['overall_accuracy']}%")
    print()


def main() -> None:
    all_results = {}
    for name, parser_fn in PARSERS.items():
        print(f"Evaluating {name}...")
        results = evaluate_multiple_invoices(INVOICES_DIR, parser_fn)
        all_results[name] = results
        print_report(name, results)

    if len(all_results) > 1:
        print(f"\n{'=' * 50}")
        print("  COMPARISON SUMMARY")
        print(f"{'=' * 50}")
        header = f"{'Metric':<25}"
        for name in all_results:
            header += f"{name:>20}"
        print(header)
        print("  " + "─" * (25 + 20 * len(all_results)))

        for metric in [
            "invoice_number_accuracy",
            "invoice_date_accuracy",
            "total_amount_accuracy",
            "overall_accuracy",
        ]:
            row = f"  {metric:<23}"
            for name in all_results:
                row += f"{all_results[name][metric]:>19}%"
            print(row)
        print()


if __name__ == "__main__":
    main()
