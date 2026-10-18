"""
Table detection with Microsoft's Table Transformer (TATR).
"""

import logging
from typing import Any, Dict, List

import numpy as np

from .._deps import require

logger = logging.getLogger(__name__)


def _to_pil(image):
    """Accept a PIL image or an RGB ``numpy`` array and return a PIL RGB image."""
    from PIL import Image

    if isinstance(image, Image.Image):
        return image.convert("RGB")
    return Image.fromarray(np.asarray(image)).convert("RGB")


class TATRTableDetector:
    """Detect table regions on a page image."""

    def __init__(self, model_name: str = "microsoft/table-transformer-detection", device: str = None):
        torch = require("torch", "TATR table detection")
        transformers = require("transformers", "TATR table detection")
        AutoImageProcessor = transformers.AutoImageProcessor
        TableTransformerForObjectDetection = transformers.TableTransformerForObjectDetection

        self._torch = torch
        self.model_name = model_name
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"Loading TATR detection model: {model_name}")
        self.processor = AutoImageProcessor.from_pretrained(model_name)
        self.model = TableTransformerForObjectDetection.from_pretrained(model_name).to(self.device)
        self.model.eval()

    def detect_tables(self, image, confidence_threshold: float = 0.5) -> List[Dict[str, Any]]:
        """
        Run detection on a page image.

        Returns:
            List of ``{"bbox": [x1, y1, x2, y2], "confidence": float, "class": str}``
            in pixel coordinates of ``image``, sorted top to bottom.
        """
        pil = _to_pil(image)
        inputs = self.processor(images=pil, return_tensors="pt").to(self.device)
        with self._torch.no_grad():
            outputs = self.model(**inputs)
        target_sizes = self._torch.tensor([pil.size[::-1]], device=self.device)
        results = self.processor.post_process_object_detection(
            outputs, threshold=confidence_threshold, target_sizes=target_sizes
        )[0]
        id2label = self.model.config.id2label
        detections = []
        for score, label, box in zip(results["scores"], results["labels"], results["boxes"]):
            detections.append(
                {
                    "bbox": [float(v) for v in box.tolist()],
                    "confidence": float(score),
                    "class": id2label[int(label)],
                }
            )
        detections.sort(key=lambda d: (d["bbox"][1], d["bbox"][0]))
        return detections

    @staticmethod
    def extract_table_regions(image, detections: List[Dict[str, Any]], padding: int = 10) -> List[np.ndarray]:
        """Crop each detected table (with ``padding`` pixels) from ``image``."""
        arr = np.asarray(image)
        h, w = arr.shape[:2]
        regions = []
        for det in detections:
            x1, y1, x2, y2 = det["bbox"]
            x1 = max(0, int(x1) - padding)
            y1 = max(0, int(y1) - padding)
            x2 = min(w, int(x2) + padding)
            y2 = min(h, int(y2) + padding)
            det["crop_offset"] = [x1, y1]
            regions.append(arr[y1:y2, x1:x2])
        return regions
