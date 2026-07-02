# Convert a pdf into an image. 

import fitz
from pathlib import Path

PDF_PATH = "data/raw/invoices/invoice_002.pdf"

doc = fitz.open(PDF_PATH)

print(f"Pages found: {len(doc)}")

output_dir = Path("data/processed/images")
output_dir.mkdir(parents=True, exist_ok=True)

for page_num in range(len(doc)):
    
    page = doc[page_num]
    
    pix = page.get_pixmap(
        matrix=fitz.Matrix(3, 3)
    )
    
    output_file = output_dir / f"invoice_002_page_{page_num + 1}.png"
    
    pix.save(output_file)
    
    print(f"Saved: {output_file}")
    
print("PDF conversion complete")