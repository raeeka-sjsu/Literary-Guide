"""
Agent tools (Option 2 / D2 — Tool-using agent).

Each tool is a small, well-typed function the agent's executor can invoke.
All tools enforce the spoiler boundary at the data level — they refuse
to return any chunk whose chapter > the chapter_limit passed in.

Three tools:
  - retrieve_passages(query, book_id, chapter_limit, k, mode)
        Hybrid (BM25 + dense) retrieval — our primary RAG.
  - lookup_character(name, book_id, chapter_limit, k)
        Entity-focused retrieval. Pulls passages where `name` appears,
        ranked by frequency × position in passage.
  - summarize_chapter(book_id, chapter, max_chars)
        Returns a chapter's text body (capped). Useful when the agent
        decides it needs the full local context, not embeddings.

Each tool returns a dict with `output` and `meta` keys; the meta is what
gets logged to the tool_call table for auditability.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
BOOKS_DIR = ROOT / "data" / "books"


def _load_book(book_id: str) -> Dict[str, Any]:
    p = BOOKS_DIR / f"{book_id}.json"
    if not p.exists():
        raise FileNotFoundError(f"Book not found: {book_id}")
    with open(p) as f:
        return json.load(f)


# ---------------- Tool 1: retrieve_passages ----------------

def retrieve_passages(
    query: str,
    book_id: str,
    chapter_limit: int,
    k: int = 4,
    mode: str = "hybrid",
) -> Dict[str, Any]:
    """Hybrid (BM25 + dense, RRF) retrieval over the book's chapter chunks.

    Always enforces chapter_limit BEFORE ranking — spoiler boundary.
    """
    # Local import to avoid circular dependency
    from book_index import ensure_book_index, query_book
    ensure_book_index(book_id)
    chunks = query_book(book_id, query, chapter_limit, top_k=k, mode=mode)
    return {
        "output": [
            {
                "id": c["id"],
                "chapter": (c.get("metadata") or {}).get("chapter"),
                "score": c["score"],
                "text": c["document"],
            }
            for c in chunks
        ],
        "meta": {
            "tool": "retrieve_passages",
            "args": {"query": query, "book_id": book_id, "chapter_limit": chapter_limit, "k": k, "mode": mode},
            "n_results": len(chunks),
        },
    }


# ---------------- Tool 2: lookup_character ----------------

def lookup_character(
    name: str,
    book_id: str,
    chapter_limit: int,
    k: int = 4,
) -> Dict[str, Any]:
    """Find passages where a character's name appears, up to chapter_limit.

    Ranks chunks by (a) name occurrence count and (b) earliness in the chunk.
    Useful when the question is character-centric — pure semantic search
    sometimes misses literal name matches that BM25 catches but doesn't
    weight by appearance density.
    """
    from book_index import ensure_book_index, _bm25_ids, _bm25, _chroma, _collection_name  # type: ignore
    ensure_book_index(book_id)

    name_re = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
    col = _chroma.get_collection(_collection_name(book_id))
    data = col.get(include=["documents", "metadatas"])
    ids = data["ids"]
    docs = data["documents"]
    metas = data["metadatas"]

    scored: List[tuple[int, int, int]] = []  # (idx, count, first_pos)
    for i, m in enumerate(metas):
        ch = int(m.get("chapter") or 0)
        if ch > chapter_limit:
            continue
        matches = list(name_re.finditer(docs[i]))
        if not matches:
            continue
        scored.append((i, len(matches), matches[0].start()))

    # Sort by count desc, then by earliness asc (smaller first_pos wins ties)
    scored.sort(key=lambda x: (-x[1], x[2]))
    out = []
    for i, count, first_pos in scored[:k]:
        out.append({
            "id": ids[i],
            "chapter": int(metas[i].get("chapter") or 0),
            "occurrences": count,
            "first_pos": first_pos,
            "text": docs[i],
        })

    return {
        "output": out,
        "meta": {
            "tool": "lookup_character",
            "args": {"name": name, "book_id": book_id, "chapter_limit": chapter_limit, "k": k},
            "n_results": len(out),
            "n_candidates": len(scored),
        },
    }


# ---------------- Tool 3: summarize_chapter ----------------

def summarize_chapter(
    book_id: str,
    chapter: int,
    max_chars: int = 4000,
) -> Dict[str, Any]:
    """Return the text of a specific chapter (capped). The agent uses this
    when it needs broader context than a few embedded chunks can give —
    e.g. "What overall mood does chapter 3 establish?".

    Returns null if the chapter doesn't exist (e.g. chapter > book length).
    """
    book = _load_book(book_id)
    target = None
    for ch in book["chapters"]:
        if int(ch.get("number") or 0) == chapter:
            target = ch
            break
    if target is None:
        return {
            "output": None,
            "meta": {
                "tool": "summarize_chapter",
                "args": {"book_id": book_id, "chapter": chapter},
                "found": False,
            },
        }
    text = (target.get("text") or "")
    truncated = text[:max_chars]
    return {
        "output": {
            "chapter": chapter,
            "title": target.get("title"),
            "text": truncated,
            "truncated": len(text) > max_chars,
            "full_length": len(text),
        },
        "meta": {
            "tool": "summarize_chapter",
            "args": {"book_id": book_id, "chapter": chapter, "max_chars": max_chars},
            "found": True,
            "truncated": len(text) > max_chars,
        },
    }


# ---------------- Tool registry ----------------

TOOLS: Dict[str, Any] = {
    "retrieve_passages": retrieve_passages,
    "lookup_character":  lookup_character,
    "summarize_chapter": summarize_chapter,
}

TOOL_DESCRIPTIONS = """\
Available tools (call by name with the listed args):

1. retrieve_passages(query: str, k: int = 4, mode: str = "hybrid")
   Hybrid keyword + semantic retrieval over the book's chapter chunks.
   Best for thematic, symbolic, or quote-style questions.

2. lookup_character(name: str, k: int = 4)
   Find passages where a specific character is mentioned.
   Best when the question centers on one person.

3. summarize_chapter(chapter: int, max_chars: int = 4000)
   Pull the full text of a single chapter the reader has already read.
   Best when you need broader context than a few embedded chunks.

(book_id and chapter_limit are filled in automatically — DO NOT pass them.)
"""
