# Convert the images into text. OCR reading directly from images 

from pathlib import Path
from PIL import Image 
import pytesseract 

def extract_text(image_path: Path) -> str:
    """Extract text from image using Tesseract OCR.

    Args:
        image_path (Path): Give the path of the input image.

    Returns:
        str: The text scanned from inside the image.
    """
    
    image = Image.open(image_path)

    text = pytesseract.image_to_string(image)
    
    return text

if __name__ == "__main__":
    
    image_path = Path(
        "data/processed/images/invoice_002_page_1.png"
    )
    
    text = extract_text(image_path)
    
    print(text)