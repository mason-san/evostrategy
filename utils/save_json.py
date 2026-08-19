#Create a json file of the received invoice object and save it with that name. 
import json
from pathlib import Path

from ingestion.schemas.invoice_schema import Invoice 

def save_invoice(invoice: Invoice) -> str:
    """
    Save validated invoice data as JSON. 

    Args:
        invoice (Invoice): Validated invoice object.

    Returns:
        str: Path to the saved file 
    
    """

    filename = f"{invoice.invoice_number}.json"

    output_dir = Path(__file__).resolve().parent.parent / "data" / "processed" / "extracted"

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    filepath = output_dir / filename

    invoice_dict = invoice.model_dump()

    with open(filepath, "w") as file:
        json.dump(invoice_dict, file)