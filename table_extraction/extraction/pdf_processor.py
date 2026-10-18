"""
PDF processing utilities: page rendering and text-layer access via PyMuPDF.

PyMuPDF is a base dependency, so no system packages (poppler, ghostscript)
are needed to render pages.
"""

import logging
from typing import List

import numpy as np

logger = logging.getLogger(__name__)


def _open(pdf_path):
    import pymupdf

    return pymupdf.open(str(pdf_path))


class PDFProcessor:
    """Handles PDF to image conversion and multi-page processing."""

    def __init__(self, dpi: int = 300):
        self.dpi = dpi

    @property
    def scale(self) -> float:
        """Pixels per PDF point at the configured DPI."""
        return self.dpi / 72.0

    def page_count(self, pdf_path) -> int:
        with _open(pdf_path) as doc:
            return len(doc)

    def pdf_to_images(self, pdf_path) -> List[np.ndarray]:
        """Render every page to an RGB ``uint8`` array of shape (H, W, 3)."""
        import pymupdf

        images = []
        with _open(pdf_path) as doc:
            mat = pymupdf.Matrix(self.scale, self.scale)
            for page in doc:
                pix = page.get_pixmap(matrix=mat, alpha=False, colorspace=pymupdf.csRGB)
                arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                images.append(arr[:, :, :3].copy())
        logger.info(f"Rendered {len(images)} page(s) from {pdf_path} at {self.dpi} dpi")
        return images

    # Kept for backwards compatibility with 0.1.x callers.
    pdf_to_images_pymupdf = pdf_to_images

    def get_page_info(self, pdf_path) -> List[dict]:
        info = []
        with _open(pdf_path) as doc:
            for i, page in enumerate(doc):
                info.append(
                    {
                        "page_number": i + 1,
                        "width": page.rect.width,
                        "height": page.rect.height,
                        "rotation": page.rotation,
                    }
                )
        return info

    def has_text_layer(self, pdf_path, page_num: int = 0) -> bool:
        with _open(pdf_path) as doc:
            return bool(doc[page_num].get_text("text").strip())

    def page_words(self, pdf_path, page_num: int = 0) -> List[dict]:
        """
        Words on a page with bounding boxes in PDF points.

        Returns:
            ``[{"bbox": [x0, y0, x1, y1], "text": str}, ...]`` in reading order.
        """
        with _open(pdf_path) as doc:
            words = doc[page_num].get_text("words", sort=True)
        return [{"bbox": [w[0], w[1], w[2], w[3]], "text": w[4]} for w in words]

    def extract_text_blocks(self, pdf_path, page_num: int = 0) -> List[dict]:
        """Text blocks from a page with bounding boxes in PDF points."""
        with _open(pdf_path) as doc:
            blocks = doc[page_num].get_text("dict")["blocks"]
        out = []
        for block in blocks:
            if "lines" not in block:
                continue
            text = " ".join(span["text"] for line in block["lines"] for span in line["spans"]).strip()
            if text:
                out.append({"bbox": list(block["bbox"]), "text": text, "type": "text"})
        return out
