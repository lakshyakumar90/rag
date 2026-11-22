"""OCR fallback for PDF pages with little or no selectable text."""

from __future__ import annotations

import io

import pymupdf
import pytesseract
from PIL import Image


def ocr_page(page: pymupdf.Page, language: str = "eng", dpi: int = 200) -> str:
    """Render one page and recognise its text with Tesseract."""
    scale = max(1.0, dpi / 72.0)
    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(scale, scale),
        colorspace=pymupdf.csGRAY,
        alpha=False,
    )
    image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    return pytesseract.image_to_string(image, lang=language)
