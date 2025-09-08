"""
Table Extraction Pro - Production-oriented table extraction from PDFs and images.

This package provides end-to-end table extraction using Microsoft's Table Transformer (TATR)
with fallback support for Camelot and Tabula parsers.
"""

__version__ = "0.1.0"
__author__ = "Your Name"
__email__ = "your.email@example.com"

from .extraction.pipeline import TableExtractionPipeline
from .export.formats import export_to_csv, export_to_json, export_to_html

__all__ = [
    "TableExtractionPipeline",
    "export_to_csv",
    "export_to_json", 
    "export_to_html",
]
