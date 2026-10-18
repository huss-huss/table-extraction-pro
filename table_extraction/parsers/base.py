"""
Shared helpers for the rule-based parsers.

All parsers return tables in the same dict shape as the TATR pipeline.
``detection["page_bbox"]`` is the table's bounding box in PDF points with a
top-left origin (``[x0, top, x1, bottom]``), which lets the comparator match
the same table across parsers.
"""

import math
from typing import Any, Dict, Iterable, List, Optional


def cell_text(value: Any) -> str:
    """Normalize a parser cell to a stripped string (NaN/None become "")."""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def clean_rows(rows: Iterable[Iterable[Any]]) -> List[List[str]]:
    """
    Convert parser output to a rectangular list of strings.

    Rows and columns that are entirely empty are dropped; short rows are
    padded so every row has the same number of cells.
    """
    data = [[cell_text(c) for c in row] for row in rows]
    data = [row for row in data if any(row)]
    if not data:
        return []
    width = max(len(r) for r in data)
    data = [r + [""] * (width - len(r)) for r in data]
    keep = [j for j in range(width) if any(r[j] for r in data)]
    return [[r[j] for j in keep] for r in data]


def build_table(
    data: List[List[str]],
    page_number: int,
    parser: str,
    confidence: float,
    page_bbox: Optional[List[float]] = None,
    table_id: int = 1,
    **metadata: Any,
) -> Dict[str, Any]:
    num_rows = len(data)
    num_cols = len(data[0]) if data else 0
    return {
        "table_id": table_id,
        "page_number": int(page_number),
        "data": data,
        "metadata": {
            "parser": parser,
            "num_rows": num_rows,
            "num_columns": num_cols,
            **metadata,
        },
        "structure": {"num_rows": num_rows, "num_columns": num_cols, "rows": [], "columns": []},
        "detection": {
            "bbox": list(page_bbox) if page_bbox else [0, 0, 0, 0],
            "page_bbox": list(page_bbox) if page_bbox else None,
            "confidence": float(confidence),
            "class": "table",
        },
    }


def page_heights(pdf_path: str) -> List[float]:
    import pymupdf

    with pymupdf.open(str(pdf_path)) as doc:
        return [page.rect.height for page in doc]


def dedupe_by_content(tables: List[Dict[str, Any]], key_score) -> List[Dict[str, Any]]:
    """Keep one table per (page, data) pair, preferring the highest ``key_score``."""
    best: Dict[Any, Dict[str, Any]] = {}
    for table in tables:
        key = (table["page_number"], tuple(tuple(r) for r in table["data"]))
        if key not in best or key_score(table) > key_score(best[key]):
            best[key] = table
    result = sorted(
        best.values(), key=lambda t: (t["page_number"], (t["detection"]["page_bbox"] or [0, 0])[1])
    )
    for i, table in enumerate(result, start=1):
        table["table_id"] = i
    return result
