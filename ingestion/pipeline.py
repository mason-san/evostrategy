from pathlib import Path
from ingestion.pdf.pdf_to_image import pdf_to_images
from ingestion.ocr.tesseract_engine import extract_text_from_images
from ingestion.extraction.parser import parse_invoice
from ingestion.schemas.invoice_schema import Invoice
from utils.save_json import save_invoice

def process_invoice(pdf_path : str) -> Invoice:
    """
    Process the invoice PDF and extract relevant information.

    Args:
        pdf_path(str): The path to the invoice PDF file.
    
    Returns:
        Invoice: An Invoice object containing extracted invoice information.
    """
    # Converting the string file path to a Path object.
    input_pdf_path = Path(pdf_path)

    #Converting the pdf into images. 
    images = pdf_to_images(input_pdf_path)

    #Extracting text from the images using OCR.
    text = extract_text_from_images(images)

    #Parsing the extracted text to get structured invoice data.
    invoice_data = parse_invoice(text)

    #Validation and creation of the Invoice object using the parsed data.
    invoice = Invoice(**invoice_data)

    save_invoice(invoice)

    return invoice

if __name__ == "__main__":
    invoice = process_invoice("data/raw/invoices/invoice_001.pdf")
    print(invoice)    