"""Text-only, scanned, mixed and corrupt PDF extraction."""

import pymupdf
import pytest

from workers.extraction import ExtractionError, extract

_LANG = "eng"


def _text_pdf(pages: list[str]) -> bytes:
    document = pymupdf.open()
    for text in pages:
        document.new_page().insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def _scanned_pdf(pages: list[str]) -> bytes:
    source = pymupdf.open()
    images = []
    for text in pages:
        page = source.new_page()
        page.insert_text((72, 72), text)
        images.append(page.get_pixmap(dpi=150).tobytes("png"))
    target = pymupdf.open()
    for image in images:
        page = target.new_page()
        page.insert_image(page.rect, stream=image)
    data = target.tobytes()
    source.close()
    target.close()
    return data


def _mixed_pdf() -> bytes:
    text_doc = _text_pdf(
        ["Selectable text on the first page with enough characters to count."]
    )
    image_doc = _scanned_pdf(["Scanned words on the second page."])
    first = pymupdf.open(stream=text_doc, filetype="pdf")
    second = pymupdf.open(stream=image_doc, filetype="pdf")
    first.insert_pdf(second)
    data = first.tobytes()
    first.close()
    second.close()
    return data


def test_text_only_pdf_does_not_run_ocr(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise AssertionError("OCR should not run for a text-only PDF")

    monkeypatch.setattr("workers.ocr.ocr_page", fail, raising=True)
    result = extract(
        _text_pdf(["This page has plenty of selectable text for the reader."]),
        "application/pdf",
        ocr_enabled=True,
        ocr_language=_LANG,
    )
    assert result.ocr_pages_total == 0
    assert result.unreadable_pages == []
    assert len(result.pages) == 1


def test_scanned_pdf_uses_ocr_preserving_page_numbers(monkeypatch) -> None:
    calls: list[int] = []

    def fake_ocr(page, language="eng", dpi=200) -> str:
        calls.append(page.number + 1)
        return "Recognised text from the scanned page with plenty of words."

    monkeypatch.setattr("workers.ocr.ocr_page", fake_ocr)
    result = extract(
        _scanned_pdf(["invisible to text extraction"]),
        "application/pdf",
        ocr_enabled=True,
        ocr_language=_LANG,
    )
    assert calls == [1]
    assert result.ocr_pages_total == 1
    assert result.pages[0].page_number == 1
    assert "Recognised" in result.pages[0].text
    assert result.unreadable_pages == []


def test_mixed_pdf_only_ocr_pages_without_text(monkeypatch) -> None:
    ocr_pages: list[int] = []

    def fake_ocr(page, language="eng", dpi=200) -> str:
        ocr_pages.append(page.number + 1)
        return "Recovered second page content with enough words to be usable."

    monkeypatch.setattr("workers.ocr.ocr_page", fake_ocr)
    result = extract(
        _mixed_pdf(),
        "application/pdf",
        ocr_enabled=True,
        ocr_language=_LANG,
    )
    assert ocr_pages == [2]
    assert [page.page_number for page in result.pages] == [1, 2]
    assert "Selectable" in result.pages[0].text
    assert "Recovered" in result.pages[1].text


def test_unreadable_page_is_reported(monkeypatch) -> None:
    monkeypatch.setattr(
        "workers.ocr.ocr_page", lambda page, **kwargs: "   ", raising=True
    )
    result = extract(
        _mixed_pdf(),
        "application/pdf",
        ocr_enabled=True,
        ocr_language=_LANG,
    )
    assert result.unreadable_pages == [2]
    assert len(result.pages) == 2


def test_corrupt_pdf_raises_domain_error() -> None:
    with pytest.raises(ExtractionError):
        extract(b"not a pdf at all", "application/pdf")


def test_queue_isolation_routes_scanned_pdf_to_ocr_and_markdown_to_fast() -> None:
    from providers.queue import INGEST_FAST_QUEUE, INGEST_OCR_QUEUE
    from workers.ocr import is_scanned_pdf
    from workers.settings import FastWorkerSettings, OcrWorkerSettings

    assert FastWorkerSettings.queue_name == INGEST_FAST_QUEUE
    assert OcrWorkerSettings.queue_name == INGEST_OCR_QUEUE
    assert OcrWorkerSettings.max_jobs <= FastWorkerSettings.max_jobs

    assert is_scanned_pdf(b"# Fast Markdown\nHello world", "text/markdown") is False
    assert (
        is_scanned_pdf(
            _text_pdf(["Plenty of selectable text on this page for fast ingestion."]),
            "application/pdf",
        )
        is False
    )
    assert (
        is_scanned_pdf(_scanned_pdf(["Scanned invoice table"]), "application/pdf")
        is True
    )


def test_low_confidence_ocr_triggers_vision_fallback(monkeypatch) -> None:
    from workers import ocr as ocr_mod

    monkeypatch.setattr(
        ocr_mod,
        "_tesseract_with_confidence",
        lambda image, language: ("garbled table ###", 38.5),
    )
    monkeypatch.setattr(
        ocr_mod,
        "_vision_extract_markdown",
        lambda png_bytes, model: "| Item | Amount |\n| --- | --- |\n| Widget | $42 |",
    )

    doc = pymupdf.open(stream=_scanned_pdf(["Widget $42"]), filetype="pdf")
    try:
        res = ocr_mod.ocr_page_detailed(
            doc[0],
            language="eng",
            dpi=150,
            min_confidence=65.0,
            vision_model="gpt-4o-mini",
        )
        assert res.used_vision_fallback is True
        assert res.mean_confidence == pytest.approx(38.5)
        assert "| Widget | $42 |" in res.text
    finally:
        doc.close()


def test_high_confidence_ocr_skips_vision_fallback(monkeypatch) -> None:
    from workers import ocr as ocr_mod

    monkeypatch.setattr(
        ocr_mod,
        "_tesseract_with_confidence",
        lambda image, language: ("Clean high confidence text", 91.2),
    )

    def fail_vision(*args, **kwargs):
        raise AssertionError("Vision fallback should not run on high confidence OCR")

    monkeypatch.setattr(ocr_mod, "_vision_extract_markdown", fail_vision)

    doc = pymupdf.open(stream=_scanned_pdf(["Clean text"]), filetype="pdf")
    try:
        res = ocr_mod.ocr_page_detailed(
            doc[0],
            language="eng",
            dpi=150,
            min_confidence=65.0,
            vision_model="gpt-4o-mini",
        )
        assert res.used_vision_fallback is False
        assert res.text == "Clean high confidence text"
    finally:
        doc.close()


def test_multilingual_and_code_fts_sql_uses_simple_and_trgm() -> None:
    import inspect

    from repositories.retrieval import RetrievalRepository

    source = inspect.getsource(RetrievalRepository.keyword_search)
    assert "websearch_to_tsquery('simple', :query)" in source
    assert "similarity(dc.content, :query)" in source
