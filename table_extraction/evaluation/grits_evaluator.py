"""
Table-level evaluation built on the GriTS implementation in ``grits.py``.
"""

import logging
from typing import Any, Dict, List, Sequence, Union

from .grits import cell_accuracy, grits_con, grits_top

logger = logging.getLogger(__name__)

TableLike = Union[Dict[str, Any], Sequence[Sequence[str]]]


def _grid(table: TableLike) -> List[List[str]]:
    if isinstance(table, dict):
        return table.get("data") or []
    return [list(r) for r in table]


class GriTSEvaluator:
    """Compare predicted tables with ground-truth grids (``data`` lists or table dicts)."""

    def evaluate_structure(self, predicted: TableLike, ground_truth: TableLike) -> Dict[str, float]:
        pred, true = _grid(predicted), _grid(ground_truth)
        con = grits_con(true, pred)
        top = grits_top(true, pred)
        return {
            "grits_con": con["f1"],
            "grits_con_precision": con["precision"],
            "grits_con_recall": con["recall"],
            "grits_top": top["f1"],
            "cell_accuracy": cell_accuracy(true, pred),
            "exact_match": float(pred == true),
            "predicted_rows": len(pred),
            "predicted_cols": max((len(r) for r in pred), default=0),
            "ground_truth_rows": len(true),
            "ground_truth_cols": max((len(r) for r in true), default=0),
        }

    def evaluate_batch(
        self, predictions: List[TableLike], ground_truths: List[TableLike]
    ) -> Dict[str, float]:
        """Average metrics over aligned prediction / ground-truth pairs."""
        if len(predictions) != len(ground_truths):
            raise ValueError(
                f"Got {len(predictions)} predictions for {len(ground_truths)} ground-truth tables"
            )
        if not predictions:
            return {"num_samples": 0}
        results = [self.evaluate_structure(p, g) for p, g in zip(predictions, ground_truths)]
        keys = [
            "grits_con",
            "grits_con_precision",
            "grits_con_recall",
            "grits_top",
            "cell_accuracy",
            "exact_match",
        ]
        out = {k: sum(r[k] for r in results) / len(results) for k in keys}
        out["num_samples"] = len(results)
        return out
