"""Unit tests for the three chunking strategies and their edge cases."""

import io

import pytest
from docx import Document as DocxDocument

from workers.chunking import Chunk, chunk_document
from workers.extraction import (
    ExtractedPage,
    ExtractedSection,
    ExtractionResult,
    extract,
)
from workers.tokenization import count_tokens, tokenize


def _result(text: str, *, page_number: int | None = None) -> ExtractionResult:
    return ExtractionResult(pages=[ExtractedPage(page_number, text)], page_count=None)


def test_tokenizer_handles_words_numbers_punctuation_and_unicode() -> None:
    assert tokenize("Hello, world!") == ["Hello", ",", "world", "!"]
    assert count_tokens("你好世界 hello") == 5
    assert count_tokens("foo_bar 3.14 😀") == 3


def test_fixed_windows_have_target_size_and_overlap() -> None:
    tokens = [f"word{i}" for i in range(120)]
    chunks = chunk_document(
        _result(" ".join(tokens)),
        strategy="fixed",
        target_tokens=20,
        overlap_tokens=5,
    )
    assert len(chunks) >= 2
    assert all(chunk.token_count <= 20 for chunk in chunks)
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    # Each "wordN" is one token, so a 5-token overlap is five whole words.
    assert chunks[1].text.split()[:5] == chunks[0].text.split()[-5:]


def test_fixed_windows_preserve_page_numbers() -> None:
    result = ExtractionResult(
        pages=[ExtractedPage(1, "one two three four"), ExtractedPage(2, "five six")],
        page_count=2,
    )
    chunks = chunk_document(result, strategy="fixed", target_tokens=2, overlap_tokens=0)
    assert [chunk.page_number for chunk in chunks] == [1, 1, 2]
    assert [chunk.index for chunk in chunks] == [0, 1, 2]


def test_paragraph_strategy_does_not_split_short_paragraphs() -> None:
    text = "First short paragraph.\n\nSecond short paragraph.\n\nThird one."
    chunks = chunk_document(
        _result(text), strategy="paragraph", target_tokens=50, overlap_tokens=5
    )
    assert len(chunks) == 1
    assert "First short paragraph." in chunks[0].text
    assert "Third one." in chunks[0].text


def test_paragraph_strategy_splits_huge_paragraphs_into_sentences() -> None:
    sentences = [f"This is sentence number {index}." for index in range(40)]
    chunks = chunk_document(
        _result(" ".join(sentences)),
        strategy="paragraph",
        target_tokens=25,
        overlap_tokens=5,
    )
    assert len(chunks) > 1
    assert all(chunk.token_count <= 25 for chunk in chunks)


def test_single_oversized_token_is_hard_split() -> None:
    # CJK characters each count as a token, so this is one oversized unit.
    giant = "字" * 5000
    chunks = chunk_document(
        _result(giant), strategy="paragraph", target_tokens=100, overlap_tokens=10
    )
    assert len(chunks) > 1
    assert all(chunk.token_count <= 100 for chunk in chunks)
    assert "".join(chunk.text for chunk in chunks).count("字") >= 5000 - 20


def test_tiny_file_still_produces_one_chunk() -> None:
    chunks = chunk_document(
        _result("hi"), strategy="auto", target_tokens=500, overlap_tokens=50
    )
    assert len(chunks) == 1
    assert chunks[0].text == "hi"
    assert chunks[0].token_count == 1


def test_unicode_and_cjk_are_not_lost() -> None:
    text = "你好世界 café naïve 😀 " * 20
    chunks = chunk_document(
        _result(text), strategy="paragraph", target_tokens=30, overlap_tokens=5
    )
    assert len(chunks) > 1
    assert all(chunk.token_count <= 30 for chunk in chunks)
    assert "你好世界" in " ".join(chunk.text for chunk in chunks)
    assert "😀" in " ".join(chunk.text for chunk in chunks)


def test_markdown_heading_paths_become_metadata() -> None:
    markdown = (
        "# Guide\n\nIntro paragraph long enough to keep.\n\n"
        "## Install\n\nInstall steps long enough to keep.\n\n"
        "### Options\n\nOption details long enough to keep.\n\n"
        "## Usage\n\nUsage details long enough to keep."
    )
    result = extract(markdown.encode(), "text/markdown")
    chunks = chunk_document(result, strategy="auto")
    assert chunks
    assert all(
        chunk.heading_path and chunk.heading_path[0] == "Guide" for chunk in chunks
    )
    assert any(chunk.heading_path[-1] == "Install" for chunk in chunks)
    assert any(chunk.heading_path[-1] == "Options" for chunk in chunks)
    assert any(len(chunk.heading_path) == 3 for chunk in chunks)
    assert all(chunk.page_number is None for chunk in chunks)


def test_docx_heading_paths_become_metadata() -> None:
    document = DocxDocument()
    document.add_heading("Guide", level=1)
    document.add_paragraph("Intro paragraph long enough to keep.")
    document.add_heading("Install", level=2)
    document.add_paragraph("Install steps long enough to keep.")
    buffer = io.BytesIO()
    document.save(buffer)

    result = extract(
        buffer.getvalue(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    chunks = chunk_document(result, strategy="auto")
    assert chunks
    assert any(chunk.heading_path == ("Guide",) for chunk in chunks)
    assert any(chunk.heading_path == ("Guide", "Install") for chunk in chunks)


def test_heading_strategy_keeps_paths_per_section() -> None:
    result = ExtractionResult(
        pages=[ExtractedPage(None, "a")],
        sections=[
            ExtractedSection(None, ("Chapter", "One"), "alpha beta gamma delta"),
            ExtractedSection(None, ("Chapter", "Two"), "epsilon zeta eta theta"),
        ],
        page_count=None,
    )
    chunks = chunk_document(
        result, strategy="heading", target_tokens=4, overlap_tokens=1
    )
    assert {chunk.heading_path for chunk in chunks} == {
        ("Chapter", "One"),
        ("Chapter", "Two"),
    }
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))


def test_chunk_dataclass_fields_are_complete() -> None:
    chunk = Chunk(1, 0, "text", ("Head",), 1)
    assert (
        chunk.page_number,
        chunk.index,
        chunk.text,
        chunk.heading_path,
        chunk.token_count,
    ) == (1, 0, "text", ("Head",), 1)


def test_invalid_settings_are_rejected() -> None:
    with pytest.raises(ValueError, match="unknown chunking strategy"):
        chunk_document(_result("text"), strategy="bogus")
    with pytest.raises(ValueError, match="overlap"):
        chunk_document(_result("text"), target_tokens=10, overlap_tokens=10)
    with pytest.raises(ValueError, match="overlap"):
        chunk_document(_result("text"), target_tokens=10, overlap_tokens=-1)
    with pytest.raises(ValueError, match="target"):
        chunk_document(_result("text"), target_tokens=0, overlap_tokens=0)


def test_empty_and_whitespace_only_documents_produce_no_chunks() -> None:
    assert chunk_document(_result(""), strategy="fixed") == []
    assert chunk_document(_result("   \n\n\t "), strategy="paragraph") == []
    assert chunk_document(_result(""), strategy="heading") == []


def test_auto_prefers_heading_only_when_sections_have_headings() -> None:
    without = ExtractionResult(
        pages=[ExtractedPage(None, "plain text")],
        sections=[ExtractedSection(None, (), "plain text")],
        page_count=None,
    )
    with_headings = ExtractionResult(
        pages=[ExtractedPage(None, "text")],
        sections=[ExtractedSection(1, ("Title",), "text")],
        page_count=None,
    )
    assert {chunk.heading_path for chunk in chunk_document(without)} == {()}
    assert {chunk.heading_path for chunk in chunk_document(with_headings)} == {
        ("Title",)
    }


def test_exact_target_boundary_does_not_create_an_empty_chunk() -> None:
    tokens = [f"w{i}" for i in range(20)]
    chunks = chunk_document(
        _result(" ".join(tokens)),
        strategy="fixed",
        target_tokens=20,
        overlap_tokens=0,
    )
    assert len(chunks) == 1
    assert chunks[0].token_count == 20
