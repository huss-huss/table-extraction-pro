"""
PDF processing utilities for converting PDFs to images and handling multi-page documents.
"""

import fitz  # PyMuPDF
import cv2
import numpy as np
from typing import List, Tuple, Optional
from pdf2image import convert_from_path
from PIL import Image
import io
import logging

logger = logging.getLogger(__name__)


class PDFProcessor:
    """
    Handles PDF to image conversion and multi-page processing.
    """
    
    def __init__(self, dpi: int = 300):
        """
        Initialize PDF processor.
        
        Args:
            dpi: DPI for PDF to image conversion
        """
        self.dpi = dpi
    
    def pdf_to_images(self, pdf_path: str) -> List[np.ndarray]:
        """
        Convert PDF pages to images.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            List of images as numpy arrays
        """
        try:
            logger.info(f"Converting PDF to images: {pdf_path}")
            
            # Use pdf2image for better quality
            images = convert_from_path(pdf_path, dpi=self.dpi)
            
            # Convert PIL images to numpy arrays
            np_images = []
            for i, pil_image in enumerate(images):
                # Convert PIL to numpy array (RGB)
                np_image = np.array(pil_image)
                # Convert RGB to BGR for OpenCV
                bgr_image = cv2.cvtColor(np_image, cv2.COLOR_RGB2BGR)
                np_images.append(bgr_image)
                logger.debug(f"Converted page {i+1} to image")
            
            logger.info(f"Successfully converted {len(np_images)} pages")
            return np_images
            
        except Exception as e:
            logger.error(f"Failed to convert PDF to images: {e}")
            raise
    
    def pdf_to_images_pymupdf(self, pdf_path: str) -> List[np.ndarray]:
        """
        Alternative PDF to image conversion using PyMuPDF (faster but lower quality).
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            List of images as numpy arrays
        """
        try:
            logger.info(f"Converting PDF to images using PyMuPDF: {pdf_path}")
            
            doc = fitz.open(pdf_path)
            images = []
            
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                
                # Create matrix for scaling
                mat = fitz.Matrix(self.dpi / 72, self.dpi / 72)
                
                # Render page to pixmap
                pix = page.get_pixmap(matrix=mat)
                
                # Convert to numpy array
                img_data = pix.tobytes("ppm")
                pil_image = Image.open(io.BytesIO(img_data))
                np_image = np.array(pil_image)
                
                # Convert RGB to BGR for OpenCV
                bgr_image = cv2.cvtColor(np_image, cv2.COLOR_RGB2BGR)
                images.append(bgr_image)
                
                logger.debug(f"Converted page {page_num+1} to image")
            
            doc.close()
            logger.info(f"Successfully converted {len(images)} pages")
            return images
            
        except Exception as e:
            logger.error(f"Failed to convert PDF to images with PyMuPDF: {e}")
            raise
    
    def get_page_info(self, pdf_path: str) -> List[dict]:
        """
        Get information about PDF pages.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            List of page information dictionaries
        """
        try:
            doc = fitz.open(pdf_path)
            page_info = []
            
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                rect = page.rect
                
                info = {
                    "page_number": page_num + 1,
                    "width": rect.width,
                    "height": rect.height,
                    "rotation": page.rotation
                }
                page_info.append(info)
            
            doc.close()
            return page_info
            
        except Exception as e:
            logger.error(f"Failed to get page info: {e}")
            raise
    
    def extract_text_blocks(self, pdf_path: str, page_num: int = 0) -> List[dict]:
        """
        Extract text blocks from a specific PDF page.
        
        Args:
            pdf_path: Path to PDF file
            page_num: Page number (0-indexed)
            
        Returns:
            List of text blocks with bounding boxes
        """
        try:
            doc = fitz.open(pdf_path)
            page = doc.load_page(page_num)
            
            # Get text blocks
            blocks = page.get_text("dict")
            
            text_blocks = []
            for block in blocks["blocks"]:
                if "lines" in block:  # Text block
                    bbox = block["bbox"]
                    text = ""
                    for line in block["lines"]:
                        for span in line["spans"]:
                            text += span["text"]
                    
                    if text.strip():
                        text_blocks.append({
                            "bbox": bbox,
                            "text": text.strip(),
                            "type": "text"
                        })
            
            doc.close()
            return text_blocks
            
        except Exception as e:
            logger.error(f"Failed to extract text blocks: {e}")
            raise
