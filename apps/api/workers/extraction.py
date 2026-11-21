"""Text extraction and cleaning for uploaded documents."""

import io
import re
from collections import Counter
from dataclasses import dataclass, field
from math import ceil

import pymupdf
from docx import Document as DocxDocument


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


def extract_pdf(data: bytes) -> ExtractionResult:
    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        if document.is_encrypted and not document.authenticate(""):
            raise EncryptedDocumentError(
                "PDF is password protected; decrypt it before uploading"
            )
        pages: list[ExtractedPage] = [
            ExtractedPage(index + 1, document[index].get_text("text"))
            for index in range(document.page_count)
        ]
        page_count = document.page_count
    finally:
        document.close()

    if not pages or sum(len(page.text.strip()) for page in pages) < _MIN_TEXT_CHARS:
        raise EmptyDocumentError(
            "No selectable text found in PDF; it may be a scan (OCR is not available)"
        )
    return ExtractionResult(pages=pages, page_count=page_count)


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


def extract(data: bytes, mime_type: str) -> ExtractionResult:
    """Extract raw pages according to the document's verified MIME type."""
    if mime_type == "application/pdf":
        result = extract_pdf(data)
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
        pages=cleaned_pages, page_count=result.page_count, sections=sections
    )
