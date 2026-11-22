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
