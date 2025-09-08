"""
Core extraction pipeline for table detection and structure recognition.
"""

from .pipeline import TableExtractionPipeline
from .pdf_processor import PDFProcessor

__all__ = ["TableExtractionPipeline", "PDFProcessor"]
