"""Three chunking strategies: fixed windows, paragraph/sentence aware, heading aware."""

import re
from dataclasses import dataclass
from typing import Literal

from workers.extraction import ExtractedSection, ExtractionResult
from workers.tokenization import count_tokens

Strategy = Literal["auto", "fixed", "paragraph", "heading"]

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。！？])\s+")


@dataclass(frozen=True)
class Chunk:
    page_number: int | None
    index: int
    text: str
    heading_path: tuple[str, ...] = ()
    token_count: int = 0


@dataclass(frozen=True)
class _Unit:
    start: int
    end: int
    tokens: int


def _units(text: str) -> list[_Unit]:
    """Whitespace-delimited units with their token counts and offsets."""
    return [
        _Unit(match.start(), match.end(), count_tokens(match.group()))
        for match in re.finditer(r"\S+", text)
    ]


def _hard_split(text: str, target: int, overlap: int) -> list[tuple[str, int]]:
    """Split a single oversized token (e.g. a long URL) by character budget."""
    total = count_tokens(text)
    if total <= target:
        return [(text, total)]
    density = max(1, len(text) // total)
    max_chars = max(1, target * density)
    step = max(1, max_chars - overlap * density)
    pieces: list[tuple[str, int]] = []
    for start in range(0, len(text), step):
        piece = text[start : start + max_chars]
        pieces.append((piece, count_tokens(piece)))
        if start + max_chars >= len(text):
            break
    if len(pieces) > 1 and len(pieces[-1][0]) < overlap * density:
        previous, previous_tokens = pieces[-2]
        last, last_tokens = pieces[-1]
        pieces[-2] = (previous + last, previous_tokens + last_tokens)
        pieces.pop()
    return pieces


def _window_units(text: str, target: int, overlap: int) -> list[tuple[str, int]]:
    """Version 1: fixed-size token windows with overlap, sliced from the source."""
    units = _units(text)
    pieces: list[tuple[str, int]] = []
    index = 0
    while index < len(units):
        total = units[index].tokens
        end = index + 1
        while end < len(units) and total + units[end].tokens <= target:
            total += units[end].tokens
            end += 1

        if total > target:  # one unit larger than the whole window
            pieces.extend(
                _hard_split(
                    text[units[index].start : units[index].end], target, overlap
                )
            )
            index += 1
            continue

        pieces.append((text[units[index].start : units[end - 1].end].strip(), total))

        # Walk back from the last unit to find where the overlap starts.
        back = 0
        cursor = end - 1
        while cursor > index and back + units[cursor].tokens <= overlap:
            back += units[cursor].tokens
            cursor -= 1
        next_index = cursor + 1
        index = max(next_index, index + 1)
    return pieces


def _tail_tokens(text: str, count: int) -> str:
    """Trailing text containing roughly ``count`` tokens."""
    if count <= 0:
        return ""
    words = list(re.finditer(r"\S+", text))
    total = 0
    index = len(words)
    while index > 0 and total + count_tokens(words[index - 1].group()) <= count:
        total += count_tokens(words[index - 1].group())
        index -= 1
    if index == len(words):  # the last word alone is larger than the budget
        return words[-1].group() if words else ""
    return text[words[index].start() :].strip()


def _atoms(text: str, target: int) -> list[str]:
    """Paragraphs, then sentences, then hard-split oversized sentences."""
    atoms: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if count_tokens(paragraph) <= target:
            atoms.append(paragraph)
            continue
        for sentence in _SENTENCE_SPLIT.split(paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            if count_tokens(sentence) <= target:
                atoms.append(sentence)
            else:
                atoms.extend(piece for piece, _ in _window_units(sentence, target, 0))
    return atoms


def _pack(atoms: list[str], target: int, overlap: int) -> list[tuple[str, int]]:
    """Pack whole atoms into windows, carrying a token-sized tail as overlap."""
    pieces: list[tuple[str, int]] = []
    buffer: list[str] = []
    count = 0
    for atom in atoms:
        tokens = count_tokens(atom)
        if buffer and count + tokens > target:
            text = " ".join(buffer)
            pieces.append((text, count))
            carry = _tail_tokens(text, overlap)
            # Only carry the overlap if it still fits alongside the next atom;
            # otherwise a chunk could silently exceed the target size.
            if carry and count_tokens(carry) + tokens <= target:
                buffer = [carry]
                count = count_tokens(carry)
            else:
                buffer = []
                count = 0
        buffer.append(atom)
        count += tokens
    if buffer:
        pieces.append((" ".join(buffer), count))
    return pieces


def chunk_document(
    result: ExtractionResult,
    strategy: Strategy = "auto",
    target_tokens: int = 500,
    overlap_tokens: int = 50,
) -> list[Chunk]:
    """Chunk an extracted document; ``auto`` picks heading-aware when possible."""
    if strategy not in ("auto", "fixed", "paragraph", "heading"):
        raise ValueError(f"unknown chunking strategy: {strategy}")
    if target_tokens < 1 or overlap_tokens < 0 or overlap_tokens >= target_tokens:
        raise ValueError("overlap must be non-negative and smaller than target")
    if strategy == "auto":
        strategy = (
            "heading"
            if any(section.heading_path for section in result.sections)
            else "paragraph"
        )

    sources = result.sections or [
        ExtractedSection(page.page_number, (), page.text) for page in result.pages
    ]
    chunks: list[Chunk] = []
    for section in sources:
        if strategy == "fixed":
            pieces = _window_units(section.text, target_tokens, overlap_tokens)
        else:
            # Version 2 and 3 share the paragraph/sentence packer; version 3
            # additionally carries the heading path as metadata.
            pieces = _pack(
                _atoms(section.text, target_tokens), target_tokens, overlap_tokens
            )
        for text, tokens in pieces:
            if not text:
                continue
            chunks.append(
                Chunk(
                    page_number=section.page_number,
                    index=len(chunks),
                    text=text,
                    heading_path=section.heading_path,
                    token_count=tokens,
                )
            )
    return chunks
