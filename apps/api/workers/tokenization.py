"""Deterministic, offline token counting for chunk sizing.

No model-specific tokenizer is chosen yet (the embedding stack uses Ollama), so
counts are an approximation: ASCII words/numbers/punctuation and individual
CJK or emoji code points each count as one token. It is stable across machines
and needs no downloaded vocabulary files.
"""

import re

# Word-like runs first, then numbers, then single CJK/kana code points, then
# any remaining non-space character (punctuation, symbols, emoji).
_TOKEN_PATTERN = re.compile(
    r"[A-Za-z_][A-Za-z0-9_']*|\d+(?:[.,]\d+)?|[\u3040-\u30ff\u4e00-\u9fff]|[^\s]",
    re.UNICODE,
)
_UNIT_PATTERN = re.compile(r"\S+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Split text into approximate tokens."""
    return _TOKEN_PATTERN.findall(text)


def count_tokens(text: str) -> int:
    return len(tokenize(text))
