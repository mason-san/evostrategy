"""Parse the output of ocr into something that is very useful."""

from ingestion.schemas.invoice_schema import Invoice

def parse_invoice(text: str) -> dict:
    """Convert OCR into structured invoice data

    Args:
        text (str): Give the OCR output text to this function to parse as json files
    """
    
    lines = text.splitlines()
    invoice_data = {}
    
    for line in lines:
        line = line.strip() 
        
        if line.startswith("Invoice Number"):
            invoice_data["invoice_number"] =  line.split(":")[-1].strip()
        
        elif line.startswith("Invoice Date"):
            invoice_data["invoice_date"] = line.split(":")[-1].strip()
            
        elif line.startswith("Total Amount"):
            amount = line.split(":")[-1].strip()
            amount = amount.replace("£","")
            amount = amount.replace("%", "")
            amount = amount.replace("INR", "")
            amount = amount.replace(",", "")
            invoice_data["total_amount"] = int(amount)
            
    return invoice_data
    
if __name__ == "__main__":
    test = """ABC Technologies Pvt Ltd

INVOICE

Invoice Number: INV-2026-001
Invoice Date: 01-07-2026

Bill To:
CloudNova Solutions Pvt Ltd
Mangalore, Karnataka

Description:
Custom Software Development Services

Quantity: 1

Rate: £25,000
Subtotal: %25,000
GST (18%): %4,500
Total Amount: £29,500

Payment Terms:
Net 30 Days

Bank Reference:
ABC-REF-001

Authorized Signatory
ABC Technologies Pvt Ltd
    """
    
    invoice_data = parse_invoice(test)

    invoice = Invoice(**invoice_data)

    print(invoice)