"""OCR fallback for scanned PDF pages with confidence scoring and vision fallback."""

from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass

import httpx
import pymupdf
import pytesseract
from PIL import Image

from core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OcrResult:
    text: str
    mean_confidence: float
    used_vision_fallback: bool = False


def is_scanned_pdf(data: bytes, mime_type: str, min_text_chars: int = 40) -> bool:
    """Fast heuristic: returns True if a PDF has at least one low-text page."""
    if mime_type != "application/pdf":
        return False
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        return False
    try:
        if doc.page_count == 0:
            return False
        for page in doc:
            if len((page.get_text("text") or "").strip()) < min_text_chars:
                return True
        return False
    finally:
        doc.close()


def _tesseract_with_confidence(image: Image.Image, language: str) -> tuple[str, float]:
    """Run Tesseract OCR and compute mean word confidence in [0, 100]."""
    try:
        data = pytesseract.image_to_data(
            image, lang=language, output_type=pytesseract.Output.DICT
        )
        words: list[str] = []
        confs: list[float] = []
        texts = data.get("text") or []
        raw_confs = data.get("conf") or []
        for word, conf in zip(texts, raw_confs, strict=False):
            cleaned = (word or "").strip()
            try:
                conf_val = float(conf)
            except (TypeError, ValueError):
                conf_val = -1.0
            if cleaned:
                words.append(cleaned)
                if conf_val >= 0:
                    confs.append(conf_val)
        mean_conf = (sum(confs) / len(confs)) if confs else 0.0
        text = " ".join(words)
        if not text:
            text = pytesseract.image_to_string(image, lang=language)
        return text, round(mean_conf, 2)
    except Exception:
        # Fallback if image_to_data is unavailable/mocked in tests.
        text = pytesseract.image_to_string(image, lang=language)
        return text, 100.0 if text.strip() else 0.0


def _vision_extract_markdown(png_bytes: bytes, model: str) -> str | None:
    """Call configured vision-capable LLM (OpenAI-compat or Ollama) for Markdown OCR."""
    settings = get_settings()
    encoded = base64.b64encode(png_bytes).decode("ascii")
    prompt = (
        "Extract all text, tables, and chart labels from this document page "
        "into clean GitHub-Flavored Markdown. Preserve numbers and table columns "
        "accurately. Output only the extracted Markdown."
    )
    try:
        if settings.openai_api_key:
            url = f"{settings.openai_base_url.rstrip('/')}/chat/completions"
            headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{encoded}"
                                },
                            },
                        ],
                    }
                ],
                "max_tokens": 2048,
                "temperature": 0.0,
            }
            with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                choices = resp.json().get("choices") or []
                if choices:
                    return str(choices[0]["message"]["content"]).strip()
        elif settings.ollama_base_url:
            url = f"{settings.ollama_base_url.rstrip('/')}/api/generate"
            payload = {
                "model": model,
                "prompt": prompt,
                "images": [encoded],
                "stream": False,
            }
            with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                text = str(resp.json().get("response") or "").strip()
                if text:
                    return text
    except Exception as exc:
        logger.warning("Vision OCR fallback failed (%s): %s", model, exc)
    return None


def ocr_page_detailed(
    page: pymupdf.Page,
    language: str = "eng",
    dpi: int = 200,
    min_confidence: float | None = None,
    vision_model: str | None = None,
) -> OcrResult:
    """Render one page, run Tesseract with confidence, and fall back to vision LLM."""
    settings = get_settings()
    threshold = (
        settings.ocr_min_confidence if min_confidence is None else min_confidence
    )
    model = settings.ocr_vision_model if vision_model is None else vision_model

    scale = max(1.0, dpi / 72.0)
    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(scale, scale),
        colorspace=pymupdf.csGRAY,
        alpha=False,
    )
    png_bytes = pixmap.tobytes("png")
    image = Image.open(io.BytesIO(png_bytes))
    text, mean_conf = _tesseract_with_confidence(image, language)

    if mean_conf < threshold and model:
        vision_md = _vision_extract_markdown(png_bytes, model)
        if vision_md:
            return OcrResult(
                text=vision_md,
                mean_confidence=mean_conf,
                used_vision_fallback=True,
            )
    return OcrResult(
        text=text, mean_confidence=mean_conf, used_vision_fallback=False
    )


def ocr_page(page: pymupdf.Page, language: str = "eng", dpi: int = 200) -> str:
    """Render one page and recognise its text (with optional vision fallback)."""
    return ocr_page_detailed(page, language=language, dpi=dpi).text
