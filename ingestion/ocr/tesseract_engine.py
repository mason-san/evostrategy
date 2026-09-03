# Convert the images into text. OCR reading directly from images 

from pathlib import Path
from PIL import Image 
import pytesseract 

def extract_text_from_images(image_paths: list[Path]) -> str:
    """Extract text from images using Tesseract OCR.

    Args:
        image_paths (list[Path]): A list of paths to the input images.

    Returns:
        str: The text scanned from inside the image.
    """

    # Pretty self explanatory. Just combining different pages of the images into one text file.
    combined_text= ""
    
    for image_path in image_paths: 
        #Open the image using PIL and use pytesseract to extract text from it.
        image = Image.open(image_path)
        #Use pytesseract to extract text from the image.
        text = pytesseract.image_to_string(image)
        #Combine the text from different pages into one text file.
        combined_text += text + "\n"
    
    return combined_text