"""
Table structure recognition with Microsoft's Table Transformer (TATR).
"""

import logging
from typing import Any, Dict, List

from .._deps import require
from .tatr_detector import _to_pil

logger = logging.getLogger(__name__)


def build_cell_grid(structure: Dict[str, Any]) -> List[List[Dict[str, Any]]]:
    """
    Intersect detected rows and columns into a cell grid.

    Each cell's bbox is the intersection of its row bbox (vertical extent) and
    column bbox (horizontal extent), in the coordinates of the table crop.
    """
    rows = structure.get("rows", [])
    columns = structure.get("columns", [])
    headers = structure.get("column_headers", [])
    grid = []
    for r, row in enumerate(rows):
        _, ry1, _, ry2 = row["bbox"]
        is_header = any(_v_overlap(row["bbox"], h["bbox"]) > 0.5 for h in headers)
        grid_row = []
        for c, col in enumerate(columns):
            cx1, _, cx2, _ = col["bbox"]
            grid_row.append(
                {
                    "row": r,
                    "col": c,
                    "bbox": [cx1, ry1, cx2, ry2],
                    "content": "",
                    "is_header": is_header,
                }
            )
        grid.append(grid_row)
    return grid


def _v_overlap(a, b) -> float:
    """Fraction of ``a``'s height that overlaps ``b`` vertically."""
    inter = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    height = max(1e-6, a[3] - a[1])
    return inter / height


class TATRStructureRecognizer:
    """Recognize rows, columns and headers inside a cropped table image."""

    def __init__(
        self,
        model_name: str = "microsoft/table-transformer-structure-recognition",
        device: str = None,
    ):
        torch = require("torch", "TATR structure recognition")
        transformers = require("transformers", "TATR structure recognition")
        AutoImageProcessor = transformers.AutoImageProcessor
        TableTransformerForObjectDetection = transformers.TableTransformerForObjectDetection

        self._torch = torch
        self.model_name = model_name
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"Loading TATR structure model: {model_name}")
        self.processor = AutoImageProcessor.from_pretrained(model_name)
        self.model = TableTransformerForObjectDetection.from_pretrained(model_name).to(self.device)
        self.model.eval()

    def recognize_structure(self, table_image, confidence_threshold: float = 0.5) -> Dict[str, Any]:
        pil = _to_pil(table_image)
        inputs = self.processor(images=pil, return_tensors="pt").to(self.device)
        with self._torch.no_grad():
            outputs = self.model(**inputs)
        target_sizes = self._torch.tensor([pil.size[::-1]], device=self.device)
        results = self.processor.post_process_object_detection(
            outputs, threshold=confidence_threshold, target_sizes=target_sizes
        )[0]
        id2label = self.model.config.id2label
        buckets = {
            "table row": [],
            "table column": [],
            "table column header": [],
            "table spanning cell": [],
            "table projected row header": [],
        }
        for score, label, box in zip(results["scores"], results["labels"], results["boxes"]):
            name = id2label[int(label)]
            if name in buckets:
                buckets[name].append({"bbox": [float(v) for v in box.tolist()], "confidence": float(score)})
        rows = sorted(buckets["table row"], key=lambda o: o["bbox"][1])
        columns = sorted(buckets["table column"], key=lambda o: o["bbox"][0])
        return {
            "rows": rows,
            "columns": columns,
            "column_headers": buckets["table column header"],
            "spanning_cells": buckets["table spanning cell"],
            "projected_row_headers": buckets["table projected row header"],
            "num_rows": len(rows),
            "num_columns": len(columns),
        }

    @staticmethod
    def create_cell_grid(structure: Dict[str, Any]) -> List[List[Dict[str, Any]]]:
        return build_cell_grid(structure)
