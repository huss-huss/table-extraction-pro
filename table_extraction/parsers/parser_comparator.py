"""
Parser comparator: run every available backend and keep the best copy of each table.

Selection works in three steps:

1. Collect candidate tables from TATR (if given), Camelot and Tabula.
2. Group candidates that describe the same physical table: same page and
   either overlapping bounding boxes (IoU >= 0.5, PDF points) or largely the
   same cell text (multiset overlap >= 0.6). A candidate joins a group if it
   matches any member.
3. Score each candidate and keep the best of each group. The score is a
   weighted sum of the parser's confidence, the share of non-empty cells
   (completeness), the share of rows that fill at least half the columns
   (consistency; penalizes captions or prose swept into the table), a small
   size term and a small parser preference (TATR > Camelot > Tabula) that
   mostly acts as a tie-breaker.
"""

import logging
from collections import Counter
from typing import Any, Dict, List, Optional

from .._deps import MissingDependencyError, is_available
from .camelot_parser import CamelotParser
from .tabula_parser import TabulaParser

logger = logging.getLogger(__name__)

IOU_THRESHOLD = 0.5
CONTENT_THRESHOLD = 0.6
PARSER_PREFERENCE = {"tatr": 1.0, "camelot": 0.5, "tabula": 0.0}
WEIGHTS = {"confidence": 0.2, "completeness": 0.35, "consistency": 0.35, "size": 0.05, "parser": 0.05}


def bbox_iou(a: Optional[List[float]], b: Optional[List[float]]) -> Optional[float]:
    """IoU of two ``[x0, y0, x1, y1]`` boxes, or None if either is unknown."""
    if not a or not b or not any(a) or not any(b):
        return None
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _cells(table: Dict[str, Any]) -> Counter:
    return Counter(str(c).strip().lower() for row in table.get("data") or [] for c in row if str(c).strip())


def content_overlap(t1: Dict[str, Any], t2: Dict[str, Any]) -> float:
    """Share of non-empty cell texts the two tables have in common (0..1)."""
    a, b = _cells(t1), _cells(t2)
    if not a or not b:
        return 0.0
    return sum((a & b).values()) / max(sum(a.values()), sum(b.values()))


class ParserComparator:
    """Compares results from different table extraction parsers and selects the best ones."""

    def __init__(self):
        self.camelot_parser = CamelotParser()
        self.tabula_parser = TabulaParser()

    def compare_parsers(
        self, pdf_path: str, tatr_tables: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Run the available fallback parsers on ``pdf_path`` and return the best tables.

        Args:
            pdf_path: Path to PDF file
            tatr_tables: Tables already extracted by TATR (optional)

        Raises:
            MissingDependencyError: if no fallback parser is installed and no
                TATR tables were supplied.
        """
        logger.info(f"Comparing parsers for: {pdf_path}")
        candidates: List[Dict[str, Any]] = []
        for table in tatr_tables or []:
            table["metadata"]["parser"] = "tatr"
            candidates.append(table)

        ran_any = False
        for name, run in (
            ("camelot", self.camelot_parser.extract_tables_with_multiple_flavors),
            ("tabula", self.tabula_parser.extract_tables_with_different_methods),
        ):
            if not is_available(name):
                logger.warning(
                    f"{name} not installed; skipping (pip install 'table-extraction-pro[fallback]')"
                )
                continue
            ran_any = True
            try:
                found = run(pdf_path)
                logger.info(f"{name} extracted {len(found)} table(s)")
                candidates.extend(found)
            except Exception as e:
                logger.warning(f"{name} extraction failed: {e}")

        if not ran_any and not tatr_tables:
            raise MissingDependencyError("camelot", "fallback", "fallback parsing")

        best = self._select_best_tables(candidates)
        logger.info(f"Selected {len(best)} table(s) from {len(candidates)} candidate(s)")
        return best

    def _select_best_tables(self, all_tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not all_tables:
            return []
        best = []
        for group in self._group_similar_tables(all_tables):
            winner = self._select_best_from_group(group)
            winner["metadata"]["candidates"] = [g["metadata"].get("parser", "unknown") for g in group]
            winner["metadata"]["selection_score"] = round(self._calculate_table_score(winner), 4)
            best.append(winner)
        best.sort(key=lambda t: (t["page_number"], (t["detection"].get("page_bbox") or [0, 0])[1]))
        for i, table in enumerate(best, start=1):
            table["table_id"] = i
        return best

    def _group_similar_tables(self, tables: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        groups: List[List[Dict[str, Any]]] = []
        for table in tables:
            for group in groups:
                if any(self._are_tables_similar(table, member) for member in group):
                    group.append(table)
                    break
            else:
                groups.append([table])
        return groups

    def _are_tables_similar(self, table1: Dict[str, Any], table2: Dict[str, Any]) -> bool:
        if int(table1["page_number"]) != int(table2["page_number"]):
            return False
        iou = bbox_iou(table1["detection"].get("page_bbox"), table2["detection"].get("page_bbox"))
        if iou is not None and iou >= IOU_THRESHOLD:
            return True
        return content_overlap(table1, table2) >= CONTENT_THRESHOLD

    def _calculate_content_similarity(self, table1: Dict[str, Any], table2: Dict[str, Any]) -> float:
        return content_overlap(table1, table2)

    def _select_best_from_group(self, group: List[Dict[str, Any]]) -> Dict[str, Any]:
        # max() keeps the first maximum, so order by parser preference to break ties.
        ordered = sorted(group, key=lambda t: -PARSER_PREFERENCE.get(t["metadata"].get("parser", ""), 0.0))
        return max(ordered, key=self._calculate_table_score)

    def _calculate_table_score(self, table: Dict[str, Any]) -> float:
        data = table.get("data") or []
        total = sum(len(r) for r in data)
        filled = sum(1 for r in data for c in r if str(c).strip())
        completeness = filled / total if total else 0.0
        width = max((len(r) for r in data), default=0)
        dense_rows = sum(1 for r in data if 2 * sum(1 for c in r if str(c).strip()) >= width)
        consistency = dense_rows / len(data) if data and width else 0.0
        size = min(1.0, total / 100.0)
        confidence = float(table["detection"].get("confidence") or 0.0)
        parser = PARSER_PREFERENCE.get(table["metadata"].get("parser", ""), 0.0)
        return (
            WEIGHTS["confidence"] * confidence
            + WEIGHTS["completeness"] * completeness
            + WEIGHTS["consistency"] * consistency
            + WEIGHTS["size"] * size
            + WEIGHTS["parser"] * parser
        )
