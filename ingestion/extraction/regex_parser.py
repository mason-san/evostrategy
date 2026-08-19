import re

def parse_invoice_regex(text: str) -> dict:
    """Extract invoice fields from OCR text using regular expressions."""

    invoice_data = {}

    # --------------------------------------------------
    # Invoice Number
    # --------------------------------------------------

    invoice_number_pattern = re.compile(
        r"(?:invoice\s*(?:number|no\.?|#)|order\s*(?:id|number|no\.?))"
        r"\s*[:\-]\s*([A-Za-z0-9\-\/]+)",
        re.IGNORECASE,
    )

    match = invoice_number_pattern.search(text)

    if match:
        invoice_data["invoice_number"] = match.group(1).strip()

    # --------------------------------------------------
    # Invoice Date
    # --------------------------------------------------

    invoice_date_pattern = re.compile(
        r"(?:invoice\s*)?date"
        r"\s*[:\-]\s*"
        r"(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"
        r"|[A-Za-z]{3,9}\s+\d{1,2}\s+\d{4})",
        re.IGNORECASE,
    )

    match = invoice_date_pattern.search(text)

    if match:
        invoice_data["invoice_date"] = match.group(1).strip()

    # --------------------------------------------------
    # Total Amount
    # --------------------------------------------------

    total_amount_pattern = re.compile(
        r"(?:total\s*amount|grand\s*total|amount\s*due|balance\s*due|total)"
        r"\s*[:\-]\s*"
        r"[£$€₹%]?\s*"
        r"([\d,]+(?:\.\d{1,2})?)",
        re.IGNORECASE,
    )

    match = total_amount_pattern.search(text)

    if match:
        amount = match.group(1)

        # Remove thousands separators
        amount = amount.replace(",", "")

        invoice_data["total_amount"] = float(amount)

    return invoice_data

# if __name__ == "__main__":

#     test = """
#     Order ID: CA-2012-AB10015140-40974
#     Date: 06-03-2026
#     Total: $58.11
#     """

#     print(parse_invoice_regex(test))