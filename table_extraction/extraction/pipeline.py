"""
Main table extraction pipeline that orchestrates the entire process.
"""

import cv2
import numpy as np
from typing import List, Dict, Any, Optional, Union
from pathlib import Path
import logging

from ..models.tatr_detector import TATRTableDetector
from ..models.tatr_structure import TATRStructureRecognizer
from .pdf_processor import PDFProcessor

logger = logging.getLogger(__name__)


class TableExtractionPipeline:
    """
    Main pipeline for table extraction from PDFs and images.
    
    This class orchestrates the entire process:
    1. Convert PDF to images (if needed)
    2. Detect table regions using TATR
    3. Recognize table structure using TATR
    4. Extract table data and export to various formats
    """
    
    def __init__(
        self,
        detection_model: str = "microsoft/table-transformer-detection",
        structure_model: str = "microsoft/table-transformer-structure-recognition",
        confidence_threshold: float = 0.5,
        dpi: int = 300
    ):
        """
        Initialize the table extraction pipeline.
        
        Args:
            detection_model: Hugging Face model name for table detection
            structure_model: Hugging Face model name for structure recognition
            confidence_threshold: Minimum confidence threshold for detections
            dpi: DPI for PDF to image conversion
        """
        self.confidence_threshold = confidence_threshold
        self.dpi = dpi
        
        # Initialize components
        self.detector = TATRTableDetector(detection_model)
        self.structure_recognizer = TATRStructureRecognizer(structure_model)
        self.pdf_processor = PDFProcessor(dpi)
        
        logger.info("Table extraction pipeline initialized")
    
    def extract_from_image(
        self, 
        image_path: Union[str, Path]
    ) -> List[Dict[str, Any]]:
        """
        Extract tables from a single image.
        
        Args:
            image_path: Path to image file
            
        Returns:
            List of extracted tables with structure and data
        """
        try:
            logger.info(f"Extracting tables from image: {image_path}")
            
            # Load image
            image = cv2.imread(str(image_path))
            if image is None:
                raise ValueError(f"Could not load image: {image_path}")
            
            # Detect tables
            detections = self.detector.detect_tables(image, self.confidence_threshold)
            logger.info(f"Found {len(detections)} table(s)")
            
            if not detections:
                return []
            
            # Extract table regions
            table_regions = self.detector.extract_table_regions(image, detections)
            
            # Process each table
            extracted_tables = []
            for i, (detection, table_region) in enumerate(zip(detections, table_regions)):
                logger.info(f"Processing table {i+1}/{len(table_regions)}")
                
                # Recognize structure
                structure = self.structure_recognizer.recognize_structure(
                    table_region, self.confidence_threshold
                )
                
                # Create cell grid
                cell_grid = self.structure_recognizer.create_cell_grid(structure)
                
                # Extract text content (placeholder for now)
                table_data = self._extract_table_data(table_region, cell_grid)
                
                extracted_table = {
                    "table_id": i + 1,
                    "page_number": 1,
                    "detection": detection,
                    "structure": structure,
                    "cell_grid": cell_grid,
                    "data": table_data,
                    "metadata": {
                        "image_path": str(image_path),
                        "confidence": detection["confidence"],
                        "num_rows": structure["num_rows"],
                        "num_columns": structure["num_columns"]
                    }
                }
                
                extracted_tables.append(extracted_table)
            
            logger.info(f"Successfully extracted {len(extracted_tables)} table(s)")
            return extracted_tables
            
        except Exception as e:
            logger.error(f"Failed to extract tables from image: {e}")
            raise
    
    def extract_from_pdf(
        self, 
        pdf_path: Union[str, Path]
    ) -> List[Dict[str, Any]]:
        """
        Extract tables from a PDF document.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            List of extracted tables with structure and data
        """
        try:
            logger.info(f"Extracting tables from PDF: {pdf_path}")
            
            # Convert PDF to images
            images = self.pdf_processor.pdf_to_images(str(pdf_path))
            logger.info(f"Converted PDF to {len(images)} page(s)")
            
            all_tables = []
            
            # Process each page
            for page_num, image in enumerate(images):
                logger.info(f"Processing page {page_num + 1}/{len(images)}")
                
                # Detect tables on this page
                detections = self.detector.detect_tables(image, self.confidence_threshold)
                logger.info(f"Found {len(detections)} table(s) on page {page_num + 1}")
                
                if not detections:
                    continue
                
                # Extract table regions
                table_regions = self.detector.extract_table_regions(image, detections)
                
                # Process each table on this page
                for i, (detection, table_region) in enumerate(zip(detections, table_regions)):
                    logger.info(f"Processing table {i+1} on page {page_num + 1}")
                    
                    # Recognize structure
                    structure = self.structure_recognizer.recognize_structure(
                        table_region, self.confidence_threshold
                    )
                    
                    # Create cell grid
                    cell_grid = self.structure_recognizer.create_cell_grid(structure)
                    
                    # Extract text content
                    table_data = self._extract_table_data(table_region, cell_grid)
                    
                    extracted_table = {
                        "table_id": len(all_tables) + 1,
                        "page_number": page_num + 1,
                        "detection": detection,
                        "structure": structure,
                        "cell_grid": cell_grid,
                        "data": table_data,
                        "metadata": {
                            "pdf_path": str(pdf_path),
                            "confidence": detection["confidence"],
                            "num_rows": structure["num_rows"],
                            "num_columns": structure["num_columns"]
                        }
                    }
                    
                    all_tables.append(extracted_table)
            
            logger.info(f"Successfully extracted {len(all_tables)} table(s) from PDF")
            return all_tables
            
        except Exception as e:
            logger.error(f"Failed to extract tables from PDF: {e}")
            raise
    
    def extract_from_file(
        self, 
        file_path: Union[str, Path]
    ) -> List[Dict[str, Any]]:
        """
        Extract tables from a file (PDF or image).
        
        Args:
            file_path: Path to file
            
        Returns:
            List of extracted tables
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Determine file type and process accordingly
        if file_path.suffix.lower() in ['.pdf']:
            return self.extract_from_pdf(file_path)
        elif file_path.suffix.lower() in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff']:
            return self.extract_from_image(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_path.suffix}")
    
    def _extract_table_data(
        self, 
        table_region: np.ndarray, 
        cell_grid: List[List[Dict[str, Any]]]
    ) -> List[List[str]]:
        """
        Extract text data from table cells using OCR.
        
        This is a placeholder implementation. In a production system,
        you would integrate with an OCR engine like Tesseract or PaddleOCR.
        
        Args:
            table_region: Cropped table image
            cell_grid: 2D grid of cell information
            
        Returns:
            2D list of cell text content
        """
        # Placeholder: return empty strings for now
        # In production, integrate with OCR engine
        data = []
        for row in cell_grid:
            data_row = []
            for cell in row:
                # TODO: Implement OCR extraction
                data_row.append("")  # Placeholder
            data.append(data_row)
        
        return data
    
    def batch_extract(
        self, 
        input_folder: Union[str, Path],
        output_folder: Union[str, Path],
        file_extensions: List[str] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Batch extract tables from multiple files.
        
        Args:
            input_folder: Folder containing input files
            output_folder: Folder to save results
            file_extensions: List of file extensions to process
            
        Returns:
            Dictionary mapping file paths to extracted tables
        """
        if file_extensions is None:
            file_extensions = ['.pdf', '.jpg', '.jpeg', '.png', '.bmp', '.tiff']
        
        input_folder = Path(input_folder)
        output_folder = Path(output_folder)
        output_folder.mkdir(parents=True, exist_ok=True)
        
        results = {}
        
        # Find all files to process
        files_to_process = []
        for ext in file_extensions:
            files_to_process.extend(input_folder.glob(f"*{ext}"))
            files_to_process.extend(input_folder.glob(f"*{ext.upper()}"))
        
        logger.info(f"Found {len(files_to_process)} files to process")
        
        # Process each file
        for file_path in files_to_process:
            try:
                logger.info(f"Processing file: {file_path}")
                tables = self.extract_from_file(file_path)
                results[str(file_path)] = tables
                
                # Save results (placeholder)
                output_file = output_folder / f"{file_path.stem}_tables.json"
                # TODO: Implement result saving
                
            except Exception as e:
                logger.error(f"Failed to process {file_path}: {e}")
                results[str(file_path)] = []
        
        return results
