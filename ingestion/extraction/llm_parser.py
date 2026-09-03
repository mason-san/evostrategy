"""LLM-based document parser using Google Gemini."""

import json
import os

from google import genai
from google.genai import types

from dotenv import load_dotenv

load_dotenv()

_INSTRUCTION = """\
You are a general-purpose document information extraction system.

Your task is to extract meaningful information from OCR text while
preserving the information as faithfully as possible.

IMPORTANT:
You are performing EXTRACTION, not INTERPRETATION.

The purpose of this stage is to produce a generic representation of
information present in the document. Business meaning, document type,
semantic field mapping, normalization, entity resolution, and
reconciliation will be handled by a later stage.

Rules:

1. DO NOT assume the document is any particular document type.

   The document may be an invoice, purchase order, payment memo,
   ledger, receipt, statement, or any other document.

2. Extract meaningful labels, headings, and fields that have corresponding
   values.

3. Preserve labels as they appear in the document.

   Do not rename labels into standardized business terminology.

   Example:
   If the document contains:

       Order ID: ABC123

   output:

       {
           "label": "Order ID:",
           "value": "ABC123"
       }

   Do NOT change it to:

       {
           "label": "Invoice Number",
           "value": "ABC123"
       }

4. DO NOT infer business meaning.

   For example:
   - "#" must not automatically become "Invoice Number".
   - "Total" must not automatically become "Transaction Total".
   - "Order ID" must not automatically become "Purchase Order ID".
   - "Bill To" must not automatically become "Customer".
   - "Amount Paid" must not automatically become "Payment Amount".

   Preserve the original label. A later stage will determine its
   semantic meaning.

5. Preserve values from the OCR as faithfully as possible.

   Do not normalize:
   - dates
   - numbers
   - currencies
   - identifiers
   - names
   - addresses
   - units

6. Do not invent missing information.

   If a value cannot be identified with reasonable confidence,
   use null rather than guessing.

7. Handle OCR fragmentation and layout issues carefully.

   OCR text may contain:
   - broken words
   - line breaks in the middle of values
   - labels and values appearing on different lines
   - multiple columns appearing in an unusual reading order
   - visually adjacent fields appearing interleaved

   Use the surrounding context and the apparent document layout to
   associate labels with their corresponding values.

   If a label or value is clearly fragmented by OCR, reconstruct the
   obvious complete text when the surrounding context makes it
   unambiguous.

   Do NOT invent a correction when the text is genuinely ambiguous.

8. Do not merge unrelated fields.

   When multiple labeled fields are present, keep each field separate
   and associate each value with the appropriate label.

9. If multiple identifiers exist, keep them as separate fields.

   Do not assume that two identifiers represent the same type of identifier.

10. If a label appears without an identifiable value, include the field
    with a null value only when the label is clearly present in the
    document.

11. Ignore ordinary prose, greetings, decorative text, and unrelated
    document text unless it represents meaningful document information.

12. Tables must be extracted separately from ordinary fields.

    When a table is present:
    - Preserve the table separately under "tables".
    - Preserve the column headers.
    - Preserve each row.
    - Preserve the values as they appear in the OCR.
    - Do not convert table columns into semantic business fields.

13. Do not create artificial hierarchical structures.

    Do not group fields under headings such as "Terms", "Billing",
    "Shipping", or "Customer" unless the document explicitly represents
    that hierarchy.

14. Every ordinary extracted field must contain:
    - field_id
    - label
    - value

15. Every extracted table must contain:
    - table_id
    - headers
    - rows

16. field_id and table_id are identifiers for the extracted elements only.
    They must NOT represent business identifiers from the document.

17. Return JSON with exactly this top-level structure:

    {
        "fields": [
            {
                "field_id": "...",
                "label": "...",
                "value": "..."
            }
        ],
        "tables": [
            {
                "table_id": "...",
                "headers": ["..."],
                "rows": [
                    {
                        "...": "..."
                    }
                ]
            }
        ]
    }

18. If there are no ordinary fields, return:

    "fields": []

    If there are no tables, return:

    "tables": []

19. Return ONLY valid JSON.
"""


def parse_document_llm(text: str) -> dict:
    """Extract structured document fields from OCR text using Google Gemini.

    Requires the GEMINI_API_KEY environment variable to be set.
    """

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable not set")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=text,
        config=types.GenerateContentConfig(
            system_instruction=_INSTRUCTION,
            response_mime_type="application/json",
            temperature=0,
        ),
    )
    return json.loads(response.text)


# Backward compatibility alias
parse_invoice_llm = parse_document_llm


if __name__ == "__main__": 
    text = """    
        superstore INVOICE

        # 36258
        Date: Mar 06 2012
        Bill To: Ship To: Shio Mod First Cl
        ode: rst Class
        Aaron Bergman 98103, Seattle,
        Washington, United Balance Due: $50.10
        States
        Item Quantity Rate Amount
        Global Push Button Manager's Chair, Indigo 1 $48.71 $48.71
        Chairs, Furniture, FUR-CH-4421
        Subtotal: $48.71
        Discount (20%) : $9.74
        Shipping: $11.13
        Total: $50.10

        Notes:
        Thanks for your business!

        Terms:
        Order ID : CA-2012-AB10015140-40974
    """

    print(parse_document_llm(text))

