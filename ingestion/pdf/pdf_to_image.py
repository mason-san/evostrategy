# Convert a pdf into an image. 

import fitz
from pathlib import Path

def pdf_to_images(pdf_path: Path) -> list[Path]:
    """
    Convert a PDF file into images, one image per page.

    Args:
        pdf_path (Path): The path to the PDF file.
    
    Returns:
        list[Path]: A list of paths to the generated image files.
    """

    #Error checking if the file exists or not.
    if not pdf_path.exists():
        raise FileNotFoundError(f"The file {pdf_path} does not exist.")

    doc = fitz.open(pdf_path) # Open the PDF file as a document (Python object)
    output_dir = Path(__file__).resolve().parent.parent.parent / "data" / "processed" / "images"
    output_dir.mkdir(parents=True, exist_ok=True) #Made the directory

    image_paths = [] #List of multiple images from different pages of the pdf.

    for page_num in range(len(doc)):
        page = doc[page_num] #Each page
        pix = page.get_pixmap(matrix=fitz.Matrix(3, 3)) #Convert the page into an image with a scaling factor of 3 for better resolution 
        output_file = output_dir / f"{Path(pdf_path).stem}_page_{page_num + 1}.png" #Define the output file path
        pix.save(output_file) #Just writing to disk. 
        image_paths.append(output_file) #Images are added to the image list.
        print(f"Saved: {output_file}")
    
    print("(pdf_to_image MODULE) : PDF conversion complete")
    return image_paths