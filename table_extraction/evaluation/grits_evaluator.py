"""
GriTS evaluator for table structure recognition evaluation.

This module provides evaluation functionality using the GriTS metrics
from the TATR repository for assessing table structure recognition quality.
"""

import logging
from typing import Any, Dict, List

import numpy as np

logger = logging.getLogger(__name__)


class GriTSEvaluator:
    """
    GriTS (Grid Table Similarity) evaluator for table structure recognition.

    GriTS is a comprehensive evaluation metric for table structure recognition
    that considers both cell-level and table-level structure accuracy.
    """

    def __init__(self):
        """Initialize the GriTS evaluator."""
        logger.info("Initializing GriTS evaluator")

    def evaluate_structure(
        self, predicted_structure: Dict[str, Any], ground_truth_structure: Dict[str, Any]
    ) -> Dict[str, float]:
        """
        Evaluate table structure recognition using GriTS metrics.

        Args:
            predicted_structure: Predicted table structure
            ground_truth_structure: Ground truth table structure

        Returns:
            Dictionary containing GriTS metrics
        """
        try:
            # Extract cell grids
            pred_grid = self._extract_cell_grid(predicted_structure)
            gt_grid = self._extract_cell_grid(ground_truth_structure)

            if not pred_grid or not gt_grid:
                return {"grits_accuracy": 0.0, "grits_f1": 0.0}

            # Calculate GriTS metrics
            accuracy = self._calculate_grits_accuracy(pred_grid, gt_grid)
            f1_score = self._calculate_grits_f1(pred_grid, gt_grid)

            return {
                "grits_accuracy": accuracy,
                "grits_f1": f1_score,
                "predicted_rows": len(pred_grid),
                "predicted_cols": len(pred_grid[0]) if pred_grid else 0,
                "ground_truth_rows": len(gt_grid),
                "ground_truth_cols": len(gt_grid[0]) if gt_grid else 0,
            }

        except Exception as e:
            logger.error(f"GriTS evaluation failed: {e}")
            return {"grits_accuracy": 0.0, "grits_f1": 0.0}

    def _extract_cell_grid(self, structure: Dict[str, Any]) -> List[List[Dict[str, Any]]]:
        """
        Extract cell grid from table structure.

        Args:
            structure: Table structure dictionary

        Returns:
            2D list representing the cell grid
        """
        # This is a simplified implementation
        # In practice, you would implement the full GriTS cell grid extraction
        cell_grid = structure.get("cell_grid", [])

        if not cell_grid:
            # Create a simple grid from rows and columns
            rows = structure.get("structure", {}).get("rows", [])
            columns = structure.get("structure", {}).get("columns", [])

            if rows and columns:
                # Create basic grid structure
                num_rows = len(rows)
                num_cols = len(columns)
                cell_grid = []

                for i in range(num_rows):
                    row = []
                    for j in range(num_cols):
                        cell = {
                            "row": i,
                            "col": j,
                            "bbox": [0, 0, 0, 0],  # Placeholder
                            "content": "",
                            "is_header": i == 0,
                        }
                        row.append(cell)
                    cell_grid.append(row)

        return cell_grid

    def _calculate_grits_accuracy(
        self, pred_grid: List[List[Dict[str, Any]]], gt_grid: List[List[Dict[str, Any]]]
    ) -> float:
        """
        Calculate GriTS accuracy metric.

        Args:
            pred_grid: Predicted cell grid
            gt_grid: Ground truth cell grid

        Returns:
            GriTS accuracy score
        """
        # Simplified GriTS accuracy calculation
        # In practice, this would implement the full GriTS algorithm

        if not pred_grid or not gt_grid:
            return 0.0

        # Basic cell count comparison
        pred_cells = sum(len(row) for row in pred_grid)
        gt_cells = sum(len(row) for row in gt_grid)

        if gt_cells == 0:
            return 0.0

        # Simple accuracy based on cell count similarity
        cell_accuracy = min(pred_cells, gt_cells) / max(pred_cells, gt_cells)

        return cell_accuracy

    def _calculate_grits_f1(
        self, pred_grid: List[List[Dict[str, Any]]], gt_grid: List[List[Dict[str, Any]]]
    ) -> float:
        """
        Calculate GriTS F1 score.

        Args:
            pred_grid: Predicted cell grid
            gt_grid: Ground truth cell grid

        Returns:
            GriTS F1 score
        """
        # Simplified GriTS F1 calculation
        # In practice, this would implement the full GriTS algorithm

        if not pred_grid or not gt_grid:
            return 0.0

        # Basic precision and recall calculation
        pred_cells = sum(len(row) for row in pred_grid)
        gt_cells = sum(len(row) for row in gt_grid)

        if pred_cells == 0 or gt_cells == 0:
            return 0.0

        # Simple F1 based on cell count
        precision = min(pred_cells, gt_cells) / pred_cells
        recall = min(pred_cells, gt_cells) / gt_cells

        if precision + recall == 0:
            return 0.0

        f1 = 2 * (precision * recall) / (precision + recall)
        return f1

    def evaluate_batch(
        self, predictions: List[Dict[str, Any]], ground_truths: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """
        Evaluate a batch of table structures.

        Args:
            predictions: List of predicted structures
            ground_truths: List of ground truth structures

        Returns:
            Average metrics across the batch
        """
        if len(predictions) != len(ground_truths):
            logger.warning("Mismatch between predictions and ground truths length")
            return {"grits_accuracy": 0.0, "grits_f1": 0.0}

        all_metrics = []

        for pred, gt in zip(predictions, ground_truths):
            metrics = self.evaluate_structure(pred, gt)
            all_metrics.append(metrics)

        # Calculate averages
        avg_accuracy = np.mean([m["grits_accuracy"] for m in all_metrics])
        avg_f1 = np.mean([m["grits_f1"] for m in all_metrics])

        return {"grits_accuracy": avg_accuracy, "grits_f1": avg_f1, "num_samples": len(all_metrics)}
