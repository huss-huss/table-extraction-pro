"""
Main table extraction pipeline that orchestrates the entire process.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np

from .pdf_processor import PDFProcessor

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif")
PDF_EXTENSIONS = (".pdf",)


class TableExtractionPipeline:
    """
    TATR-based pipeline for table extraction from PDFs and images.

    1. Render PDF pages to images (PyMuPDF).
    2. Detect table regions (TATR detection model).
    3. Recognize rows/columns inside each region (TATR structure model).
    4. Build a cell grid and fill it with text.

    The TATR models are loaded lazily on first use, so constructing a
    pipeline is cheap and does not require the ``ml`` extra until a TATR
    extraction is actually run. ``detector`` and ``structure_recognizer``
    can be injected (used by tests to run without torch).
    """

    def __init__(
        self,
        detection_model: str = "microsoft/table-transformer-detection",
        structure_model: str = "microsoft/table-transformer-structure-recognition",
        confidence_threshold: float = 0.5,
        dpi: int = 300,
        detector=None,
        structure_recognizer=None,
    ):
        self.detection_model = detection_model
        self.structure_model = structure_model
        self.confidence_threshold = confidence_threshold
        self.dpi = dpi
        self._detector = detector
        self._structure_recognizer = structure_recognizer
        self.pdf_processor = PDFProcessor(dpi)

    @property
    def detector(self):
        if self._detector is None:
            from ..models.tatr_detector import TATRTableDetector

            self._detector = TATRTableDetector(self.detection_model)
        return self._detector

    @property
    def structure_recognizer(self):
        if self._structure_recognizer is None:
            from ..models.tatr_structure import TATRStructureRecognizer

            self._structure_recognizer = TATRStructureRecognizer(self.structure_model)
        return self._structure_recognizer

    def _process_page(
        self,
        image: np.ndarray,
        page_number: int,
        source: Dict[str, Any],
        first_table_id: int = 1,
    ) -> List[Dict[str, Any]]:
        detections = self.detector.detect_tables(image, self.confidence_threshold)
        logger.info(f"Found {len(detections)} table(s) on page {page_number}")
        if not detections:
            return []
        regions = self.detector.extract_table_regions(image, detections)
        tables = []
        for i, (detection, region) in enumerate(zip(detections, regions)):
            structure = self.structure_recognizer.recognize_structure(region, self.confidence_threshold)
            cell_grid = self.structure_recognizer.create_cell_grid(structure)
            data = self._extract_table_data(region, cell_grid)
            tables.append(
                {
                    "table_id": first_table_id + i,
                    "page_number": page_number,
                    "detection": detection,
                    "structure": structure,
                    "cell_grid": cell_grid,
                    "data": data,
                    "metadata": {
                        **source,
                        "parser": "tatr",
                        "confidence": detection["confidence"],
                        "num_rows": structure["num_rows"],
                        "num_columns": structure["num_columns"],
                    },
                }
            )
        return tables

    def extract_from_image(self, image_path: Union[str, Path]) -> List[Dict[str, Any]]:
        """Extract tables from a single image file."""
        from PIL import Image

        try:
            with Image.open(image_path) as img:
                image = np.asarray(img.convert("RGB"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"Could not load image: {image_path}") from exc
        tables = self._process_page(image, 1, {"image_path": str(image_path)})
        logger.info(f"Extracted {len(tables)} table(s) from {image_path}")
        return tables

    def extract_from_pdf(self, pdf_path: Union[str, Path]) -> List[Dict[str, Any]]:
        """Extract tables from every page of a PDF."""
        images = self.pdf_processor.pdf_to_images(pdf_path)
        all_tables: List[Dict[str, Any]] = []
        for page_index, image in enumerate(images):
            all_tables.extend(
                self._process_page(
                    image,
                    page_index + 1,
                    {"pdf_path": str(pdf_path)},
                    first_table_id=len(all_tables) + 1,
                )
            )
        logger.info(f"Extracted {len(all_tables)} table(s) from {pdf_path}")
        return all_tables

    def extract_from_file(self, file_path: Union[str, Path]) -> List[Dict[str, Any]]:
        """Extract tables from a PDF or image, dispatching on the extension."""
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        suffix = file_path.suffix.lower()
        if suffix in PDF_EXTENSIONS:
            return self.extract_from_pdf(file_path)
        if suffix in IMAGE_EXTENSIONS:
            return self.extract_from_image(file_path)
        raise ValueError(f"Unsupported file type: {file_path.suffix}")

    def _extract_table_data(
        self, table_region: np.ndarray, cell_grid: List[List[Dict[str, Any]]]
    ) -> List[List[str]]:
        """Return the text of each cell (empty when no text source is available)."""
        return [["" for _ in row] for row in cell_grid]

    def batch_extract(
        self,
        input_folder: Union[str, Path],
        output_folder: Union[str, Path],
        file_extensions: Optional[List[str]] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Extract tables from every matching file in ``input_folder``.

        A JSON file per input is written to ``output_folder``.
        """
        from ..export.formats import export_to_json

        exts = {e.lower() for e in (file_extensions or PDF_EXTENSIONS + IMAGE_EXTENSIONS)}
        input_folder = Path(input_folder)
        output_folder = Path(output_folder)
        output_folder.mkdir(parents=True, exist_ok=True)
        files = sorted(p for p in input_folder.iterdir() if p.is_file() and p.suffix.lower() in exts)
        results: Dict[str, List[Dict[str, Any]]] = {}
        for file_path in files:
            try:
                tables = self.extract_from_file(file_path)
            except Exception as exc:
                logger.error(f"Failed to process {file_path}: {exc}")
                tables = []
            results[str(file_path)] = tables
            if tables:
                export_to_json(tables, output_folder / f"{file_path.stem}_tables.json")
        return results
