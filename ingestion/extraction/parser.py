"""Parse the output of ocr into something that is very useful."""

from ingestion.schemas.invoice_schema import Invoice
from utils.save_json import save_invoice

def parse_invoice(text: str) -> dict:
    """Convert OCR into structured invoice data

    Args:
        text (str): Give the OCR output text to this function to parse as json files

    Returns:
        dict: A dictionary containing the parsed invoice data.
    """
    #Get each line from the text and split it into a list of lines.
    lines = text.splitlines()
    #Create an empty dictionary to store the invoice data.
    invoice_data = {}
    
    for line in lines:
        # OCR often introduces leading/trailing whitespace,
        # so normalize each line before matching.
        line = line.strip()
        #Checking if the line starts with the keywords. 
        if line.startswith("Invoice Number"):
            invoice_data["invoice_number"] =  line.split(":")[-1].strip()
        
        elif line.startswith("Invoice Date"):
            invoice_data["invoice_date"] = line.split(":")[-1].strip()
            
        elif line.startswith("Total Amount"):
            amount = line.split(":")[-1].strip()
            amount = amount.replace("£","").replace("$","").replace("€","").replace("₹","")
            amount = amount.replace("%", "").replace("INR", "").replace(",", "")
            invoice_data["total_amount"] = float(amount)
            
    return invoice_data