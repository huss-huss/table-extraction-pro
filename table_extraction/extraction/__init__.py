"""
Core extraction pipeline for table detection and structure recognition.
"""

from .pdf_processor import PDFProcessor
from .pipeline import TableExtractionPipeline

__all__ = ["TableExtractionPipeline", "PDFProcessor"]
