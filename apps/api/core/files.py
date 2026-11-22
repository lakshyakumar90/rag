"""Upload validation: allowed types, magic-byte checks and filename sanitizing."""

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass

# Extension -> canonical MIME type. The client-provided content type is never
# trusted; the type is derived from magic bytes and must match the extension.
ALLOWED_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    # Notion exports arrive as ZIP archives and are parsed in a bounded helper.
    ".zip": "application/zip",
}

_SAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._\- ]+")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class DetectedType:
    mime_type: str
    extension: str


def sanitize_filename(filename: str) -> str:
    """Return a safe, single-line basename; never trust a client path."""
    # Treat both separators as path separators (Windows clients send backslashes).
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = unicodedata.normalize("NFKC", name)
    name = _CONTROL_CHARS.sub("", name)
    name = _SAFE_NAME_CHARS.sub("_", name).strip(" .")
    if not name:
        name = "file"
    return name[:255]


def detect_file_type(data: bytes, extension: str) -> DetectedType:
    """Verify the payload's *real* type and that it matches the extension.

    Raises ``ValueError`` with an actionable message for disallowed or
    mismatched content. ``extension`` must include the leading dot.
    """
    if extension not in ALLOWED_TYPES:
        raise ValueError(
            f"Unsupported file type {extension or '(none)'!r}; "
            f"allowed: {', '.join(sorted(ALLOWED_TYPES))}"
        )
    expected = ALLOWED_TYPES[extension]

    if expected == "application/pdf":
        if not data.startswith(b"%PDF-"):
            raise ValueError("File content is not a PDF (missing %PDF- header)")
    elif extension == ".zip":
        if not data.startswith(b"PK\x03\x04"):
            raise ValueError("File content is not a ZIP archive")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if archive.testzip() is not None:
                    raise ValueError("ZIP archive is corrupt")
        except (zipfile.BadZipFile, OSError) as exc:
            raise ValueError("File content is not a valid ZIP archive") from exc
    elif extension == ".docx":
        if not data.startswith(b"PK\x03\x04"):
            raise ValueError("File content is not a DOCX (missing ZIP header)")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if "word/document.xml" not in archive.namelist():
                    raise ValueError(
                        "File content is not a DOCX (missing word/document.xml)"
                    )
        except (zipfile.BadZipFile, OSError) as exc:
            raise ValueError("File content is not a valid DOCX archive") from exc
    else:  # .txt / .md: plain UTF-8 text without NUL bytes
        if b"\x00" in data:
            raise ValueError("Text files must not contain NUL bytes")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Text file is not valid UTF-8") from exc

    return DetectedType(mime_type=expected, extension=extension)
