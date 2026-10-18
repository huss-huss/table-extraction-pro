"""
Stand-ins for the TATR models that need no torch and no downloads.

``RuledGridOracle`` reads the ruling lines of the fixture PDFs and answers
detection / structure queries with the exact geometry, in the same pixel
coordinates and dict format the real TATR wrappers return. This exercises
the pipeline's geometry and text-layer code without the neural networks.
"""

from typing import Dict, List

import pymupdf

from table_extraction.models.tatr_detector import TATRTableDetector
from table_extraction.models.tatr_structure import build_cell_grid


def ruled_tables(pdf_path) -> List[List[Dict]]:
    """Per page, the ruled tables as ``{"xs": [...], "ys": [...]}`` in points."""
    pages = []
    with pymupdf.open(str(pdf_path)) as doc:
        for page in doc:
            segments = []
            for drawing in page.get_drawings():
                for item in drawing["items"]:
                    if item[0] == "l":
                        p1, p2 = item[1], item[2]
                        segments.append((min(p1.x, p2.x), min(p1.y, p2.y), max(p1.x, p2.x), max(p1.y, p2.y)))
            clusters: List[List[tuple]] = []
            for seg in segments:
                touching = [c for c in clusters if any(_touch(seg, other) for other in c)]
                merged = [seg] + [s for c in touching for s in c]
                clusters = [c for c in clusters if c not in touching] + [merged]
            tables = []
            for cluster in clusters:
                xs = sorted({round(s[0], 2) for s in cluster if s[0] == s[2]})
                ys = sorted({round(s[1], 2) for s in cluster if s[1] == s[3]})
                if len(xs) >= 2 and len(ys) >= 2:
                    tables.append({"xs": xs, "ys": ys})
            tables.sort(key=lambda t: t["ys"][0])
            pages.append(tables)
    return pages


def _touch(a, b, tol=1.0):
    return not (a[2] + tol < b[0] or b[2] + tol < a[0] or a[3] + tol < b[1] or b[3] + tol < a[1])


class RuledGridOracle:
    def __init__(self, pdf_path, dpi: int = 300, confidence: float = 0.99):
        self.pages = ruled_tables(pdf_path)
        self.scale = dpi / 72.0
        self.confidence = confidence
        self.page_index = -1
        self.pending: List[Dict] = []
        self.detector = _Detector(self)
        self.structure_recognizer = _Structure(self)


class _Detector:
    def __init__(self, oracle: RuledGridOracle):
        self.oracle = oracle

    def detect_tables(self, image, confidence_threshold=0.5):
        o = self.oracle
        o.page_index += 1
        s = o.scale
        dets = []
        for t in o.pages[o.page_index]:
            bbox = [t["xs"][0] * s, t["ys"][0] * s, t["xs"][-1] * s, t["ys"][-1] * s]
            dets.append({"bbox": bbox, "confidence": o.confidence, "class": "table", "_grid": t})
        o.pending = list(dets)
        return dets

    extract_table_regions = staticmethod(TATRTableDetector.extract_table_regions)


class _Structure:
    def __init__(self, oracle: RuledGridOracle):
        self.oracle = oracle

    def recognize_structure(self, table_image, confidence_threshold=0.5):
        det = self.oracle.pending.pop(0)
        s = self.oracle.scale
        ox, oy = det["crop_offset"]
        xs = [x * s - ox for x in det["_grid"]["xs"]]
        ys = [y * s - oy for y in det["_grid"]["ys"]]
        rows = [{"bbox": [xs[0], y0, xs[-1], y1], "confidence": 0.99} for y0, y1 in zip(ys, ys[1:])]
        cols = [{"bbox": [x0, ys[0], x1, ys[-1]], "confidence": 0.99} for x0, x1 in zip(xs, xs[1:])]
        return {
            "rows": rows,
            "columns": cols,
            "column_headers": [rows[0]] if rows else [],
            "spanning_cells": [],
            "projected_row_headers": [],
            "num_rows": len(rows),
            "num_columns": len(cols),
        }

    create_cell_grid = staticmethod(build_cell_grid)
