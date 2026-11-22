"""Documented phase weights shared by the API and the Documents UI.

A document is only 100% when it is actually searchable (``status == ready``
*and* the vector index has been confirmed). Every other number is derived from
work the worker really reported; an unknown total yields ``None`` so the UI
shows an indeterminate bar instead of inventing a percentage.
"""

from __future__ import annotations

from typing import Any

PHASE_ORDER = (
    "uploading",
    "queued",
    "reading",
    "ocr",
    "chunking",
    "embedding",
    "indexing",
)
PHASE_WEIGHTS = {
    "uploading": 5,
    "queued": 2,
    "reading": 15,
    "ocr": 8,
    "chunking": 10,
    "embedding": 35,
    "indexing": 25,
}


def phase_fraction(document: Any, phase: str) -> float | None:
    """Completed fraction of one phase, or ``None`` when the total is unknown."""
    if phase == "uploading":
        total = getattr(document, "upload_total", 0) or 0
        return (
            min(1.0, (getattr(document, "upload_bytes", 0) or 0) / total)
            if total
            else None
        )
    if phase == "queued":
        return 0.0
    if phase == "reading":
        total = getattr(document, "pages_total", 0) or 0
        return (
            min(1.0, (getattr(document, "pages_done", 0) or 0) / total)
            if total
            else None
        )
    if phase == "ocr":
        total = getattr(document, "ocr_pages_total", 0) or 0
        return (
            min(1.0, (getattr(document, "ocr_pages_done", 0) or 0) / total)
            if total
            else None
        )
    if phase == "chunking":
        total = (
            getattr(document, "sections_total", 0)
            or getattr(document, "chunks_total", 0)
            or 0
        )
        done = (
            getattr(document, "sections_done", 0)
            or getattr(document, "chunks_done", 0)
            or 0
        )
        return min(1.0, done / total) if total else None
    if phase == "embedding":
        total = getattr(document, "chunks_total", 0) or 0
        return (
            min(1.0, (getattr(document, "chunks_embedded", 0) or 0) / total)
            if total
            else None
        )
    if phase == "indexing":
        total = getattr(document, "chunks_total", 0) or 0
        return (
            min(1.0, (getattr(document, "chunks_indexed", 0) or 0) / total)
            if total
            else None
        )
    return None


def progress_percent(document: Any) -> float | None:
    """Overall percentage, or ``None`` when progress cannot be measured yet."""
    status = str(getattr(document, "status", ""))
    if status == "ready":
        return 100.0
    if status == "failed":
        return None
    raw_phase = getattr(document, "ingestion_stage", None) or "queued"
    phase = str(raw_phase)
    if phase not in PHASE_WEIGHTS:
        # Legacy v1 stage name.
        phase = "reading" if phase == "extracting" else "queued"

    ocr_needed = bool(getattr(document, "ocr_pages_total", 0) or 0)
    applicable = [item for item in PHASE_ORDER if item != "ocr" or ocr_needed]
    total_weight = sum(PHASE_WEIGHTS[item] for item in applicable)
    index = applicable.index(phase) if phase in applicable else 0
    completed = sum(PHASE_WEIGHTS[item] for item in applicable[:index])
    fraction = phase_fraction(document, phase)
    if fraction is None:
        # Unknown totals mean an indeterminate bar, not a guessed number.
        return None
    return round(100 * (completed + PHASE_WEIGHTS[phase] * fraction) / total_weight, 1)
