# Total pipeline of the invoice processing from PDF to structured data.
from pathlib import Path
from ingestion.pdf.pdf_to_image import pdf_to_images
from ingestion.ocr.tesseract_engine import extract_text_from_images
from ingestion.extraction.regex_parser import parse_invoice_regex
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

    # print("=" * 60)
    # print(text)
    # print("=" * 60)

    #Parsing the extracted text to get structured invoice data.
    # invoice_data = parse_invoice(text)

    invoice_data = parse_invoice_regex(text)

    print("The Extracted Invoice Data is: ", invoice_data)

    #Validation and creation of the Invoice object using the parsed data.
    invoice = Invoice(**invoice_data)

    #Save the invoice
    save_invoice(invoice)

    return invoice

if __name__ == "__main__":
    pdf_path = str(Path(__file__).resolve().parent / "evaluation_dataset/invoices/invoice_012.pdf")
    invoice = process_invoice(pdf_path)

    print("The Extracted Invoice Data is: ", invoice)