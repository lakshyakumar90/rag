"""Text extraction and cleaning for uploaded documents."""

import io
import logging
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from math import ceil

import pymupdf
from docx import Document as DocxDocument

logger = logging.getLogger(__name__)


# Permanent failures: retrying will not help, so the worker records them on the
# document immediately instead of burning through ARQ retries.
class ExtractionError(Exception):
    """The file cannot be extracted (permanent failure)."""


class EmptyDocumentError(ExtractionError):
    """No usable text was found (e.g. an image-only PDF; OCR is not available)."""


class EncryptedDocumentError(ExtractionError):
    """The PDF is password protected."""


@dataclass(frozen=True)
class ExtractedPage:
    page_number: int | None
    text: str


@dataclass(frozen=True)
class ExtractedSection:
    """A region of a document with its heading hierarchy (empty for PDF/TXT)."""

    page_number: int | None
    heading_path: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class ExtractionResult:
    pages: list[ExtractedPage]
    page_count: int | None  # real page count for PDFs; None for other formats
    sections: list[ExtractedSection] = field(default_factory=list)
    ocr_pages_total: int = 0
    unreadable_pages: list[int] = field(default_factory=list)


_MIN_TEXT_CHARS = 20
_REPEAT_RATIO = 0.6


def _clean_text(text: str) -> str:
    """Normalize whitespace and repair words hyphenated across line breaks."""
    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in text.splitlines()]
    joined = "\n".join(lines)
    # "inter-\n  national" -> "international"; keep genuine standalone hyphens.
    joined = re.sub(r"(\w)-\s*\n\s*([a-z])", r"\1\2", joined)
    return re.sub(r"\n{3,}", "\n\n", joined).strip()


def _strip_running_lines(pages: list[ExtractedPage]) -> list[ExtractedPage]:
    """Remove headers/footers repeated on most pages, plus numeric page labels."""
    if len(pages) < 3:
        return pages

    first_lines: Counter[str] = Counter()
    last_lines: Counter[str] = Counter()
    for page in pages:
        lines = [line.strip() for line in page.text.splitlines() if line.strip()]
        if lines:
            first_lines[lines[0]] += 1
            last_lines[lines[-1]] += 1

    threshold = max(2, ceil(len(pages) * _REPEAT_RATIO))

    def repeated(counter: Counter[str]) -> set[str]:
        return {
            line
            for line, count in counter.items()
            if count >= threshold and len(line) >= 4 and not line.isdigit()
        }

    headers, footers = repeated(first_lines), repeated(last_lines)

    cleaned: list[ExtractedPage] = []
    for page in pages:
        lines = [
            line
            for line in (raw.strip() for raw in page.text.splitlines())
            if line
            and line not in headers
            and line not in footers
            and not line.isdigit()
        ]
        cleaned.append(ExtractedPage(page.page_number, "\n".join(lines)))
    return cleaned


def extract_pdf(
    data: bytes,
    on_progress: Callable[[int, int], None] | None = None,
    on_ocr: Callable[[int, int], None] | None = None,
    *,
    ocr_enabled: bool = True,
    ocr_language: str = "eng",
    ocr_min_text_chars: int = 40,
    ocr_dpi: int = 200,
) -> ExtractionResult:
    """Read selectable text, then OCR only the pages that need it.

    Original page numbers are preserved: a page is replaced in place with its
    OCR text, never appended. Unreadable pages are reported, not silently
    dropped, so the UI can offer a retry.
    """
    from workers.ocr import ocr_page

    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except (pymupdf.FileDataError, ValueError) as exc:
        raise ExtractionError("The PDF is corrupt or unreadable") from exc
    try:
        if document.is_encrypted and not document.authenticate(""):
            raise EncryptedDocumentError(
                "PDF is password protected; decrypt it before uploading"
            )
        page_count = document.page_count
        texts = [document[index].get_text("text") for index in range(page_count)]
        for index, _text in enumerate(texts, start=1):
            if on_progress is not None:
                on_progress(index, page_count)

        needs_ocr = [
            index
            for index, text in enumerate(texts)
            if len(text.strip()) < ocr_min_text_chars
        ]
        ocr_total = len(needs_ocr)
        if ocr_enabled and ocr_total:
            if on_ocr is not None:
                on_ocr(0, ocr_total)
            unreadable: list[int] = []
            for done, index in enumerate(needs_ocr, start=1):
                try:
                    recognised = ocr_page(
                        document[index], language=ocr_language, dpi=ocr_dpi
                    )
                except Exception as exc:  # noqa: BLE001 - surface as unreadable
                    logger.warning("OCR failed for page %d: %s", index + 1, exc)
                    recognised = ""
                if len(recognised.strip()) < ocr_min_text_chars:
                    unreadable.append(index + 1)
                    # Keep the page in order with an explicit marker so other
                    # pages remain searchable and the UI can offer a retry.
                    texts[index] = (
                        recognised.strip()
                        or "[Unreadable page: OCR could not recover text]"
                    )
                else:
                    texts[index] = recognised
                if on_ocr is not None:
                    on_ocr(done, ocr_total)
        else:
            unreadable = [index + 1 for index in needs_ocr]
            for index in needs_ocr:
                texts[index] = texts[index] or "[Unreadable page: no selectable text]"
        pages = [ExtractedPage(index + 1, text) for index, text in enumerate(texts)]
    finally:
        document.close()

    all_unreadable = bool(unreadable) and len(unreadable) == len(pages)
    if (
        all_unreadable
        or not pages
        or sum(len(page.text.strip()) for page in pages) < _MIN_TEXT_CHARS
    ):
        raise EmptyDocumentError(
            "No selectable text found in PDF; it may be a scan "
            "(OCR is not available or could not recover text)"
        )
    return ExtractionResult(
        pages=pages,
        page_count=page_count,
        ocr_pages_total=ocr_total,
        unreadable_pages=unreadable,
    )


def extract_docx(data: bytes) -> ExtractionResult:
    document = DocxDocument(io.BytesIO(data))
    heading_stack: list[str] = []
    buffer: list[str] = []
    sections: list[ExtractedSection] = []

    def flush() -> None:
        if buffer:
            sections.append(
                ExtractedSection(None, tuple(heading_stack), "\n".join(buffer))
            )
            buffer.clear()

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        style = paragraph.style
        match = re.match(r"^Heading\s+(\d+)$", style.name if style else "")
        if match:
            flush()
            level = int(match.group(1))
            heading_stack = heading_stack[: level - 1] + [text]
        elif text:
            buffer.append(text)
    flush()

    for table in document.tables:
        for row in table.rows:
            values = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if values:
                sections.append(
                    ExtractedSection(None, tuple(heading_stack), " | ".join(values))
                )

    if not sections:
        raise EmptyDocumentError("DOCX contains no selectable text")
    text = "\n".join(section.text for section in sections)
    return ExtractionResult(
        pages=[ExtractedPage(None, text)], page_count=None, sections=sections
    )


def _markdown_sections(text: str) -> list[ExtractedSection]:
    """Turn ATX headings into a heading path per section."""
    heading_stack: list[str] = []
    buffer: list[str] = []
    sections: list[ExtractedSection] = []

    def flush() -> None:
        if buffer:
            sections.append(
                ExtractedSection(None, tuple(heading_stack), "\n".join(buffer))
            )
            buffer.clear()

    for line in text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if match:
            flush()
            level = len(match.group(1))
            heading_stack = heading_stack[: level - 1] + [match.group(2).strip()]
        else:
            buffer.append(line)
    flush()
    return sections or [ExtractedSection(None, (), text)]


def extract_plain(data: bytes, mime_type: str) -> ExtractionResult:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExtractionError("Text file is not valid UTF-8") from exc
    if len(text.strip()) < _MIN_TEXT_CHARS:
        raise EmptyDocumentError("Text file is empty or contains no usable text")

    sections = _markdown_sections(text) if mime_type == "text/markdown" else []
    return ExtractionResult(
        pages=[ExtractedPage(None, text)],
        page_count=None,
        sections=sections,
    )


def extract(
    data: bytes,
    mime_type: str,
    on_progress: Callable[[int, int], None] | None = None,
    on_ocr: Callable[[int, int], None] | None = None,
    *,
    ocr_enabled: bool | None = None,
    ocr_language: str | None = None,
    ocr_min_text_chars: int | None = None,
    ocr_dpi: int | None = None,
) -> ExtractionResult:
    """Extract raw pages according to the document's verified MIME type."""
    from core.config import get_settings

    settings = get_settings()
    if mime_type == "application/pdf":
        result = extract_pdf(
            data,
            on_progress,
            on_ocr,
            ocr_enabled=settings.ocr_enabled if ocr_enabled is None else ocr_enabled,
            ocr_language=ocr_language or settings.ocr_language,
            ocr_min_text_chars=ocr_min_text_chars or settings.ocr_min_text_chars,
            ocr_dpi=ocr_dpi or settings.ocr_dpi,
        )
    elif mime_type.endswith("wordprocessingml.document"):
        result = extract_docx(data)
    elif mime_type in ("text/plain", "text/markdown"):
        result = extract_plain(data, mime_type)
    else:
        raise ExtractionError(f"Unsupported MIME type for extraction: {mime_type}")

    cleaned_pages = _strip_running_lines(
        [
            ExtractedPage(page.page_number, _clean_text(page.text))
            for page in result.pages
        ]
    )
    cleaned_pages = [page for page in cleaned_pages if page.text]
    if not cleaned_pages:
        raise EmptyDocumentError("No usable text remained after cleaning")

    if result.sections:
        sections = [
            ExtractedSection(
                section.page_number,
                section.heading_path,
                _clean_text(section.text),
            )
            for section in result.sections
        ]
        sections = [section for section in sections if section.text]
    else:
        sections = [
            ExtractedSection(page.page_number, (), page.text) for page in cleaned_pages
        ]
    if not sections:
        raise EmptyDocumentError("No usable text remained after cleaning")

    return ExtractionResult(
        pages=cleaned_pages,
        page_count=result.page_count,
        sections=sections,
        ocr_pages_total=getattr(result, "ocr_pages_total", 0),
        unreadable_pages=getattr(result, "unreadable_pages", []),
    )
