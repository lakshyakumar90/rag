"""Text extraction and cleaning for uploaded documents."""

import io
import re
from collections import Counter
from dataclasses import dataclass
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
class ExtractionResult:
    pages: list[ExtractedPage]
    page_count: int | None  # real page count for PDFs; None for other formats


@dataclass(frozen=True)
class Chunk:
    page_number: int | None
    index: int
    content: str


_MIN_TEXT_CHARS = 20
_REPEAT_RATIO = 0.6
_DEFAULT_CHUNK_CHARS = 1000


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
    parts = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    text = "\n".join(part for part in parts if part.strip())
    if len(text.strip()) < _MIN_TEXT_CHARS:
        raise EmptyDocumentError("DOCX contains no selectable text")
    return ExtractionResult([ExtractedPage(None, text)], page_count=None)


def extract_plain(data: bytes, mime_type: str) -> ExtractionResult:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExtractionError("Text file is not valid UTF-8") from exc
    if len(text.strip()) < _MIN_TEXT_CHARS:
        raise EmptyDocumentError("Text file is empty or contains no usable text")
    return ExtractionResult([ExtractedPage(None, text)], page_count=None)


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
    return ExtractionResult(pages=cleaned_pages, page_count=result.page_count)


def chunk_pages(
    pages: list[ExtractedPage], max_chars: int = _DEFAULT_CHUNK_CHARS
) -> list[Chunk]:
    """Split cleaned pages into chunks, preserving page provenance."""
    chunks: list[Chunk] = []
    for page in pages:
        buffer: list[str] = []
        length = 0
        for word in page.text.split():
            if buffer and length + len(word) + 1 > max_chars:
                chunks.append(Chunk(page.page_number, len(chunks), " ".join(buffer)))
                buffer, length = [], 0
            buffer.append(word)
            length += len(word) + 1
        if buffer:
            chunks.append(Chunk(page.page_number, len(chunks), " ".join(buffer)))
    return chunks
