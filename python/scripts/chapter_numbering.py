"""
Canonical chapter-number extraction.

Used everywhere we tag content with a chapter number so that the user-visible
chapter number, the chunk metadata, the character index, and the spoiler
filter all use the SAME scale. This fixes the off-by-N bug introduced when
our Gutenberg parser created spurious TOC/front-matter chapters at the start
of some books (Wizard of Oz, Frankenstein, etc.).

Strategy:
  1. Extract a number from the chapter title — Roman numerals first, then
     Arabic. Roman numerals are more reliable because Gutenberg titles like
     "Chapter VI." appear in the body but Arabic chapter numbers can also
     appear inside paragraphs.
  2. If the title yields nothing, return None — caller should treat the
     chapter as front matter (skip in indexing) rather than fall back to
     the parser's broken `number` field.
"""

from __future__ import annotations

import re
from typing import Optional


_ROMAN_VALS = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}

# Written-out chapter numbers (Little Women uses "CHAPTER ONE", etc.)
_WORD_NUMS = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
    "SIX": 6, "SEVEN": 7, "EIGHT": 8, "NINE": 9, "TEN": 10,
    "ELEVEN": 11, "TWELVE": 12, "THIRTEEN": 13, "FOURTEEN": 14, "FIFTEEN": 15,
    "SIXTEEN": 16, "SEVENTEEN": 17, "EIGHTEEN": 18, "NINETEEN": 19, "TWENTY": 20,
    "THIRTY": 30, "FORTY": 40, "FIFTY": 50,
    "FIRST": 1, "SECOND": 2, "THIRD": 3, "FOURTH": 4, "FIFTH": 5,
    "SIXTH": 6, "SEVENTH": 7, "EIGHTH": 8, "NINTH": 9, "TENTH": 10,
}


def _parse_word_number(s: str) -> Optional[int]:
    """Parse "TWENTY-ONE", "THIRTY-FIVE", etc. — basic compound support."""
    if not s:
        return None
    s = s.upper().replace("-", " ").strip()
    parts = s.split()
    total = 0
    for p in parts:
        if p in _WORD_NUMS:
            total += _WORD_NUMS[p]
        elif p == "AND":
            continue
        else:
            return None
    return total or None


def _parse_roman(s: str) -> Optional[int]:
    s = s.upper()
    if not s or not all(c in _ROMAN_VALS for c in s):
        return None
    total, prev = 0, 0
    for c in reversed(s):
        v = _ROMAN_VALS[c]
        total += -v if v < prev else v
        prev = v
    return total


# Canonical pattern: "CHAPTER VI" / "Chapter VI." / "CHAPTER 6" / "Chapter 6"
_HEAD_ROMAN = re.compile(r"^\s*(?:CHAPTER|Chapter|CH\.|Ch\.)\s+([IVXLCDM]+)\b", re.IGNORECASE)
_HEAD_ARAB  = re.compile(r"^\s*(?:CHAPTER|Chapter|CH\.|Ch\.)\s+(\d+)\b", re.IGNORECASE)
# Word-form: "CHAPTER ONE", "CHAPTER TWENTY-FIVE"
_HEAD_WORD  = re.compile(r"^\s*(?:CHAPTER|Chapter|CH\.|Ch\.)\s+([A-Z][A-Z\-]+(?:\s[A-Z][A-Z\-]+)?)\b", re.IGNORECASE)
# Bare leading numeral with a period: "VI.", "12."
_BARE_ROMAN = re.compile(r"^\s*([IVXLCDM]+)\.\s")
_BARE_ARAB  = re.compile(r"^\s*(\d+)\.\s")


def parse_chapter_number(title: str) -> Optional[int]:
    """Return the canonical chapter number from a chapter title, or None if
    the title doesn't look like a numbered chapter heading."""
    if not title:
        return None
    t = title.strip()
    m = _HEAD_ROMAN.match(t)
    if m:
        n = _parse_roman(m.group(1))
        if n:
            return n
    m = _HEAD_ARAB.match(t)
    if m:
        return int(m.group(1))
    m = _HEAD_WORD.match(t)
    if m:
        n = _parse_word_number(m.group(1))
        if n:
            return n
    m = _BARE_ROMAN.match(t)
    if m:
        n = _parse_roman(m.group(1))
        if n:
            return n
    m = _BARE_ARAB.match(t)
    if m:
        return int(m.group(1))
    # Fallback: look anywhere in the title for "Chapter X" pattern (strict)
    m = re.search(r"\bChapter\s+(\d+|[IVXLCDM]+)\b", t, re.IGNORECASE)
    if m:
        s = m.group(1)
        if s.isdigit():
            return int(s)
        return _parse_roman(s)
    return None
