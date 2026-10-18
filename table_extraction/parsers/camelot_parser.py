"""
Camelot parser wrapper for table extraction from PDFs.
"""

import logging
from typing import Any, Dict, List, Optional

from .._deps import MissingDependencyError, require
from .base import build_table, clean_rows, dedupe_by_content, page_heights

logger = logging.getLogger(__name__)


class CamelotParser:
    """
    Wrapper for the Camelot PDF table extraction library.

    ``lattice`` works on ruled tables (cell borders drawn as lines); ``stream``
    infers columns from whitespace and suits unruled tables.
    """

    FLAVORS = ("lattice", "stream")

    def __init__(self, flavor: str = "lattice", pages: str = "all"):
        self.flavor = flavor
        self.pages = pages

    def extract_tables(
        self,
        pdf_path: str,
        table_areas: Optional[List[str]] = None,
        columns: Optional[List[str]] = None,
        flavor: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Extract tables from a PDF with one Camelot flavor.

        Args:
            pdf_path: Path to PDF file
            table_areas: Camelot table areas, e.g. ``["72,720,540,400"]``
            columns: Column separators (stream flavor only)
            flavor: Overrides the instance flavor for this call

        Returns:
            Tables in the standard dict format (empty list on parser failure).
        """
        flavor = flavor or self.flavor
        camelot = require("camelot", "the Camelot fallback parser")
        kwargs: Dict[str, Any] = {}
        # Camelot rejects `columns` (even None) for lattice, which used to
        # make every lattice extraction fail silently.
        if table_areas:
            kwargs["table_areas"] = table_areas
        if columns:
            if flavor == "lattice":
                raise ValueError("columns can only be used with the stream flavor")
            kwargs["columns"] = columns
        try:
            tables = camelot.read_pdf(str(pdf_path), flavor=flavor, pages=self.pages, **kwargs)
        except MissingDependencyError:
            raise
        except Exception as e:
            logger.error(f"Camelot ({flavor}) extraction failed: {e}")
            return []

        heights = page_heights(pdf_path)
        extracted = []
        for table in tables:
            data = clean_rows(table.df.values.tolist())
            if not data:
                continue
            page = int(table.page)
            x1, y1, x2, y2 = table._bbox  # PDF points, bottom-left origin
            height = heights[page - 1]
            extracted.append(
                build_table(
                    data,
                    page_number=page,
                    parser="camelot",
                    confidence=float(table.accuracy) / 100.0,
                    page_bbox=[x1, height - y2, x2, height - y1],
                    table_id=len(extracted) + 1,
                    flavor=flavor,
                    accuracy=float(table.accuracy),
                    whitespace=float(table.whitespace),
                    order=table.order,
                )
            )
        logger.info(f"Camelot ({flavor}) found {len(extracted)} table(s)")
        return extracted

    def extract_tables_with_multiple_flavors(self, pdf_path: str) -> List[Dict[str, Any]]:
        """Run every flavor and keep the most accurate copy of each distinct table."""
        results: List[Dict[str, Any]] = []
        for flavor in self.FLAVORS:
            results.extend(self.extract_tables(pdf_path, flavor=flavor))
        return dedupe_by_content(results, key_score=lambda t: t["metadata"]["accuracy"])

    def get_table_areas(self, pdf_path: str, page: int = 1) -> List[str]:
        """
        Suggested Camelot ``table_areas`` strings (``"x1,y1,x2,y2"``: top-left
        and bottom-right corners in PDF points, bottom-left origin).
        """
        camelot = require("camelot", "the Camelot fallback parser")
        try:
            tables = camelot.read_pdf(str(pdf_path), flavor=self.flavor, pages=str(page))
        except Exception as e:
            logger.error(f"Failed to get table areas: {e}")
            return []
        areas = []
        for table in tables:
            x1, y1, x2, y2 = table._bbox
            areas.append(f"{x1:g},{y2:g},{x2:g},{y1:g}")
        return areas
