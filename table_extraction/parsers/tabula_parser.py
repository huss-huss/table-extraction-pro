"""
Tabula parser wrapper for table extraction from PDFs (needs a Java runtime).
"""

import logging
from typing import Any, Dict, List, Optional

from .._deps import MissingDependencyError, require
from .base import build_table, clean_rows, dedupe_by_content, page_heights

logger = logging.getLogger(__name__)

# tabula-java has no confidence score; this constant only ranks Tabula below a
# perfect Camelot/TATR result in ParserComparator.
TABULA_CONFIDENCE = 0.8


def _parse_pages(pages: str, page_count: int) -> List[int]:
    if pages == "all":
        return list(range(1, page_count + 1))
    out: List[int] = []
    for part in str(pages).split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-")
            end_n = page_count if end == "end" else int(end)
            out.extend(range(int(start), end_n + 1))
        elif part:
            out.append(int(part))
    return [p for p in out if 1 <= p <= page_count]


class TabulaParser:
    """
    Wrapper for tabula-py.

    Tabula's JSON output does not say which page a table came from, so pages
    are read one at a time to keep page numbers correct.
    """

    METHODS = ({"lattice": True}, {"stream": True})

    def __init__(self, pages: str = "all", multiple_tables: bool = True):
        self.pages = pages
        self.multiple_tables = multiple_tables

    def extract_tables(
        self,
        pdf_path: str,
        area: Optional[List[float]] = None,
        columns: Optional[List[float]] = None,
        guess: bool = True,
        method: Optional[Dict[str, bool]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Extract tables with tabula-py.

        Args:
            pdf_path: Path to PDF file
            area: Table area ``[top, left, bottom, right]`` in points
            columns: Column x positions in points
            guess: Let Tabula guess table areas
            method: ``{"lattice": True}`` or ``{"stream": True}``; default auto

        Returns:
            Tables in the standard dict format (empty list on parser failure).
        """
        tabula = require("tabula", "the Tabula fallback parser")
        method = method or {}
        heights = page_heights(pdf_path)
        extracted: List[Dict[str, Any]] = []
        for page in _parse_pages(self.pages, len(heights)):
            try:
                raw = tabula.read_pdf(
                    str(pdf_path),
                    pages=page,
                    area=area,
                    columns=columns,
                    guess=guess,
                    multiple_tables=self.multiple_tables,
                    output_format="json",
                    silent=True,
                    **method,
                )
            except MissingDependencyError:
                raise
            except Exception as e:
                logger.error(f"Tabula extraction failed on page {page}: {e}")
                continue
            for item in raw:
                data = clean_rows([[cell.get("text", "") for cell in row] for row in item.get("data", [])])
                if not data:
                    continue
                bbox = [item["left"], item["top"], item["right"], item["bottom"]]
                extracted.append(
                    build_table(
                        data,
                        page_number=page,
                        parser="tabula",
                        confidence=TABULA_CONFIDENCE,
                        page_bbox=bbox,
                        table_id=len(extracted) + 1,
                        method=item.get("extraction_method", "auto"),
                    )
                )
        logger.info(f"Tabula {method or 'auto'} found {len(extracted)} table(s)")
        return extracted

    def extract_tables_with_different_methods(self, pdf_path: str) -> List[Dict[str, Any]]:
        """Run lattice and stream modes and keep one copy of each distinct table."""
        results: List[Dict[str, Any]] = []
        for method in self.METHODS:
            results.extend(self.extract_tables(pdf_path, method=method))
        # Prefer the copy with fewer empty cells.
        return dedupe_by_content(results, key_score=lambda t: sum(bool(c) for r in t["data"] for c in r))
