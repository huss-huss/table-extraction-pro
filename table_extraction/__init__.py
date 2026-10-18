"""
Table Extraction Pro - table extraction from PDFs and images.

Microsoft's Table Transformer (TATR) handles detection and structure
recognition (``ml`` extra); Camelot and Tabula act as rule-based fallbacks
(``fallback`` extra). The base install provides the CLI, API, exporters and
evaluation without any heavy dependency.
"""

__version__ = "0.2.0"

from ._deps import MissingDependencyError, available_backends
from .export.formats import export_to_csv, export_to_html, export_to_json
from .extraction.pipeline import TableExtractionPipeline

__all__ = [
    "MissingDependencyError",
    "TableExtractionPipeline",
    "available_backends",
    "export_to_csv",
    "export_to_json",
    "export_to_html",
]
