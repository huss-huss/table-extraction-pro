"""
Engine selection shared by the CLI and the API.

- ``tatr``: Table Transformer detection + structure, text from the PDF text
  layer (images: structure only, no OCR).
- ``fallback``: Camelot + Tabula on PDFs, best candidate per table chosen by
  :class:`~table_extraction.parsers.ParserComparator`.
- ``auto``: TATR if the ``ml`` extra is installed, plus the fallback parsers
  on PDFs when the ``fallback`` extra is installed, all candidates compared
  together. Fails with an install hint if neither is available.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ._deps import MissingDependencyError, available_backends
from .extraction.pipeline import IMAGE_EXTENSIONS, PDF_EXTENSIONS, TableExtractionPipeline
from .parsers.parser_comparator import ParserComparator

logger = logging.getLogger(__name__)

ENGINES = ("auto", "tatr", "fallback")
SUPPORTED_EXTENSIONS = PDF_EXTENSIONS + IMAGE_EXTENSIONS


def extract_tables(
    path: Union[str, Path],
    engine: str = "auto",
    confidence: float = 0.5,
    pipeline: Optional[TableExtractionPipeline] = None,
    comparator: Optional[ParserComparator] = None,
) -> List[Dict[str, Any]]:
    """Extract tables from ``path`` with the requested engine."""
    if engine not in ENGINES:
        raise ValueError(f"Unknown engine {engine!r}; choose from {', '.join(ENGINES)}")
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {path.suffix or '(none)'}")
    is_pdf = suffix in PDF_EXTENSIONS

    if pipeline is None:
        pipeline = TableExtractionPipeline(confidence_threshold=confidence)
    else:
        pipeline.confidence_threshold = confidence
    comparator = comparator or ParserComparator()

    if engine == "tatr":
        return pipeline.extract_from_file(path)
    if engine == "fallback":
        if not is_pdf:
            raise ValueError(
                "The fallback parsers (Camelot, Tabula) only read PDFs; use engine 'tatr' for images"
            )
        return comparator.compare_parsers(str(path))

    backends = available_backends()
    has_fallback = backends["camelot"] or backends["tabula"]
    if not backends["tatr"] and not (is_pdf and has_fallback):
        if is_pdf:
            raise MissingDependencyError("camelot", "fallback", "PDF extraction without the ml extra")
        raise MissingDependencyError("torch", "ml", "image input")
    tatr_tables = pipeline.extract_from_file(path) if backends["tatr"] else None
    if is_pdf and has_fallback:
        return comparator.compare_parsers(str(path), tatr_tables=tatr_tables)
    return tatr_tables or []
