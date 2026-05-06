"""
Fetch the curated library from Project Gutenberg, split each book into chapters,
and save to python/data/books/<book_id>.json.

Usage:
    python scripts/fetch_library.py            # all books
    python scripts/fetch_library.py --only frankenstein,dracula   # specific ids
    python scripts/fetch_library.py --limit 3  # first N (for testing)

Output per book:
    {
      "id": "...", "title": "...", "author": "...",
      "chapters": [
        {"number": 1, "title": "Chapter 1", "text": "..."},
        ...
      ]
    }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import List, Dict, Any, Optional

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "data" / "catalog.json"
BOOKS_DIR = ROOT / "data" / "books"

# Try a sequence of URLs — Gutenberg moves files around occasionally
URL_TEMPLATES = [
    "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt",
    "https://www.gutenberg.org/files/{id}/{id}-0.txt",
    "https://www.gutenberg.org/files/{id}/{id}.txt",
]


def fetch_book(gutenberg_id: int) -> str:
    last_err = None
    for tmpl in URL_TEMPLATES:
        url = tmpl.format(id=gutenberg_id)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LiteraryGuide/0.1"})
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("latin-1")
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"Could not fetch Gutenberg id={gutenberg_id}: {last_err}")


def strip_gutenberg_boilerplate(text: str) -> str:
    """Remove the Project Gutenberg header/footer."""
    start_re = re.compile(r"\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG.*?\*\*\*", re.IGNORECASE)
    end_re = re.compile(r"\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG.*?\*\*\*", re.IGNORECASE)

    m = start_re.search(text)
    if m:
        text = text[m.end():]
    m = end_re.search(text)
    if m:
        text = text[:m.start()]
    return text.strip()


# Heuristic chapter heading patterns. Try in order; first that yields >1 split wins.
CHAPTER_PATTERNS = [
    r"(?m)^\s*CHAPTER\s+[IVXLCDM]+\.?\b.*$",            # CHAPTER I., CHAPTER XII
    r"(?m)^\s*Chapter\s+[IVXLCDM]+\.?\b.*$",
    r"(?m)^\s*CHAPTER\s+\d+\.?\b.*$",                    # CHAPTER 1
    r"(?m)^\s*Chapter\s+\d+\.?\b.*$",
    r"(?m)^\s*CHAPTER\s+[A-Z][A-Z\-]+\.?\b.*$",         # CHAPTER ONE, CHAPTER TWENTY-ONE
    r"(?m)^\s*[IVXLCDM]+\.\s*[A-Z].*$",                   # I. THE BEGINNING (rare)
]

ROMAN_RE = re.compile(r"\b([IVXLCDM]+)\b")
ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def parse_roman(s: str) -> Optional[int]:
    if not s:
        return None
    s = s.upper()
    if not all(c in ROMAN_VALUES for c in s):
        return None
    total, prev = 0, 0
    for c in reversed(s):
        v = ROMAN_VALUES[c]
        total += -v if v < prev else v
        prev = v
    return total


def chapter_number_of(title: str) -> Optional[int]:
    """Try to extract a chapter integer from a heading like 'CHAPTER II.' or 'Chapter 12'."""
    m = re.search(r"\d+", title)
    if m:
        return int(m.group(0))
    m = ROMAN_RE.search(title.upper())
    if m:
        return parse_roman(m.group(1))
    return None


def split_chapters(text: str) -> List[Dict[str, Any]]:
    """Split book text into chapters. Returns list of {number, title, text}.

    Notable handling:
    - Skips short bodies (<200 chars) — these are usually TOC entries.
    - If the first kept match is NOT chapter 1 (e.g. Gutenberg's Pride and Prejudice
      hides "Chapter I." inside an [Illustration] block), synthesize a chapter 1
      from the leading text up to the first match.
    """
    for pat in CHAPTER_PATTERNS:
        regex = re.compile(pat)
        matches = list(regex.finditer(text))
        if len(matches) < 2:
            continue

        # First pass: collect candidate chapters, skipping short (TOC) bodies
        chapters_raw = []
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            title = m.group(0).strip()
            body = text[start:end].strip()
            if len(body) < 200:
                continue
            chapters_raw.append({"title": title, "text": body, "head_pos": m.start()})

        if len(chapters_raw) < 2:
            continue

        # If the first kept chapter's number is > 1, synthesize a leading chapter
        first_num = chapter_number_of(chapters_raw[0]["title"]) or 0
        if first_num > 1:
            head_text = text[: chapters_raw[0]["head_pos"]].strip()
            # Trim leading metadata: take only the LAST 30k chars to skip TOC region
            tail = head_text[-30000:] if len(head_text) > 30000 else head_text
            # Heuristic: chapter 1 starts where prose density picks up — pick the
            # last big paragraph break before the first match.
            split_marker = re.search(r"\[Illustration[^\]]*Chapter\s+I\.?\]", tail, re.IGNORECASE)
            if split_marker:
                ch1_text = tail[split_marker.end():].strip()
            else:
                # Last 5000 chars before first chapter heading is a reasonable guess
                ch1_text = tail[-5000:].strip() if len(tail) > 5000 else tail
            if len(ch1_text) > 500:
                chapters_raw.insert(0, {"title": "Chapter I.", "text": ch1_text, "head_pos": 0})

        chapters = []
        for c in chapters_raw:
            chapters.append({
                "number": len(chapters) + 1,
                "title": c["title"],
                "text": c["text"],
            })
        if len(chapters) >= 2:
            return chapters

    # Fallback: treat the whole text as one chapter
    return [{"number": 1, "title": "Full Text", "text": text.strip()}]


def process_book(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    bid = entry["id"]
    print(f"  fetching {bid} (gutenberg id {entry['gutenberg_id']})...", end=" ", flush=True)
    try:
        raw = fetch_book(entry["gutenberg_id"])
    except Exception as e:
        print(f"FAILED ({e})")
        return None
    body = strip_gutenberg_boilerplate(raw)
    chapters = split_chapters(body)
    print(f"OK ({len(chapters)} chapters, {len(body):,} chars)")
    return {
        "id": bid,
        "gutenberg_id": entry["gutenberg_id"],
        "title": entry["title"],
        "author": entry["author"],
        "year": entry.get("year"),
        "genres": entry.get("genres", []),
        "chapters": chapters,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated book ids to fetch (default: all)")
    ap.add_argument("--limit", type=int, help="only fetch first N from catalog")
    ap.add_argument("--force", action="store_true", help="re-fetch even if file exists")
    args = ap.parse_args()

    BOOKS_DIR.mkdir(parents=True, exist_ok=True)
    with open(CATALOG_PATH) as f:
        catalog = json.load(f)

    if args.only:
        wanted = set(s.strip() for s in args.only.split(","))
        catalog = [b for b in catalog if b["id"] in wanted]
    if args.limit:
        catalog = catalog[: args.limit]

    print(f"Fetching {len(catalog)} books to {BOOKS_DIR}...")

    ok = 0
    fail = 0
    for entry in catalog:
        out_path = BOOKS_DIR / f"{entry['id']}.json"
        if out_path.exists() and not args.force:
            print(f"  skipping {entry['id']} (already exists)")
            ok += 1
            continue
        book = process_book(entry)
        if book is None:
            fail += 1
            continue
        with open(out_path, "w") as f:
            json.dump(book, f, indent=2)
        ok += 1
        time.sleep(0.5)  # be polite to Gutenberg

    print(f"\nDone. {ok} ok, {fail} failed.")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
