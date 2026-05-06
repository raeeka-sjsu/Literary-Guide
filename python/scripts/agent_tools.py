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
CHARS_DIR = ROOT / "data" / "characters"


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


# ---------------- Character-index helpers (shared by tools 5 & 6) ----------------

def _load_char_index(book_id: str) -> List[Dict[str, Any]]:
    p = CHARS_DIR / f"{book_id}.json"
    if not p.exists():
        return []
    with open(p) as f:
        return json.load(f)


def _filter_to_chapter(entries: List[Dict[str, Any]], chapter_limit: int) -> List[Dict[str, Any]]:
    """Drop characters whose first_chapter > chapter_limit. For each kept
    entry, also drop per_chapter buckets beyond chapter_limit and recompute
    total mentions to reflect only what the reader has actually encountered."""
    out = []
    for e in entries:
        if int(e.get("first_chapter") or 0) > chapter_limit:
            continue
        per_ch = {int(k): v for k, v in (e.get("per_chapter") or {}).items() if int(k) <= chapter_limit}
        if not per_ch:
            continue
        total = sum(v.get("mentions", 0) for v in per_ch.values())
        co_filtered = {k: v for k, v in (e.get("co_occurs_with") or {}).items()
                       if any(int(c.get("first_chapter") or 0) <= chapter_limit
                              and c.get("canonical_name") == k for c in entries)}
        out.append({
            "canonical_name": e["canonical_name"],
            "aliases": e.get("aliases", []),
            "first_chapter": int(e.get("first_chapter") or 0),
            "total_mentions_so_far": total,
            "per_chapter": per_ch,
            "co_occurs_with": co_filtered,
        })
    out.sort(key=lambda x: -x["total_mentions_so_far"])
    return out


# ---------------- Tool 4: retrieve_expert_analysis (BookSum) ----------------

def retrieve_expert_analysis(
    query: str,
    book_id: str,
    chapter_limit: int,
    k: int = 3,
) -> Dict[str, Any]:
    """Retrieve scholarly literary-analysis snippets from BookSum (CliffsNotes /
    SparkNotes / Shmoop chapter analyses), spoiler-boundary enforced.

    Use when the question is interpretive ("what does X symbolize?", "why
    does the narrator use Y?") and the original-text retrieval might benefit
    from professional critical context as additional grounding.
    Returns [] if no BookSum data exists for this book."""
    from book_index import ensure_booksum_index, query_booksum
    ensure_booksum_index(book_id)
    chunks = query_booksum(book_id, query, chapter_limit, top_k=k)
    return {
        "output": [
            {
                "id": c["id"],
                "chapter": (c.get("metadata") or {}).get("chapter"),
                "score": c["score"],
                "text": c["document"],
                "source": (c.get("metadata") or {}).get("source"),
            }
            for c in chunks
        ],
        "meta": {
            "tool": "retrieve_expert_analysis",
            "args": {"query": query, "book_id": book_id, "chapter_limit": chapter_limit, "k": k},
            "n_results": len(chunks),
        },
    }


# ---------------- Tool 5: list_known_characters ----------------

def list_known_characters(
    book_id: str,
    chapter_limit: int,
    top_k: int = 10,
) -> Dict[str, Any]:
    """Kindle-X-Ray-style structured character list.

    Returns the most-mentioned characters introduced by chapter <= chapter_limit,
    each with a one-line snippet from the chapter where they first appear.
    Spoiler-safe by construction: characters whose first_chapter is later than
    chapter_limit are excluded.
    """
    entries = _load_char_index(book_id)
    if not entries:
        return {
            "output": [],
            "meta": {
                "tool": "list_known_characters",
                "args": {"book_id": book_id, "chapter_limit": chapter_limit, "top_k": top_k},
                "n_results": 0,
                "note": "no character index for this book",
            },
        }
    filtered = _filter_to_chapter(entries, chapter_limit)
    top = filtered[:top_k]
    out = []
    for e in top:
        first_ch = e["first_chapter"]
        intro_snippet = (e["per_chapter"].get(first_ch) or {}).get("snippet")
        out.append({
            "name": e["canonical_name"],
            "aliases": e["aliases"],
            "first_chapter": first_ch,
            "mentions_so_far": e["total_mentions_so_far"],
            "intro_snippet": intro_snippet,
        })
    return {
        "output": out,
        "meta": {
            "tool": "list_known_characters",
            "args": {"book_id": book_id, "chapter_limit": chapter_limit, "top_k": top_k},
            "n_results": len(out),
            "n_known_total": len(filtered),
        },
    }


# ---------------- Tool 6: get_character_profile ----------------

def get_character_profile(
    name: str,
    book_id: str,
    chapter_limit: int,
) -> Dict[str, Any]:
    """Look up a single character (by canonical name OR alias). Returns
    first_chapter, per-chapter mention timeline up to chapter_limit, top
    co-occurring characters, and snippets from key chapters."""
    entries = _load_char_index(book_id)
    if not entries:
        return {
            "output": None,
            "meta": {
                "tool": "get_character_profile",
                "args": {"name": name, "book_id": book_id, "chapter_limit": chapter_limit},
                "found": False,
                "reason": "no character index for this book",
            },
        }
    name_norm = name.strip().lower()
    match = None
    for e in entries:
        if e["canonical_name"].lower() == name_norm or any(
            a.lower() == name_norm for a in e.get("aliases", [])
        ):
            match = e
            break
    if match is None:
        # Fuzzy: substring match on canonical or aliases
        for e in entries:
            haystack = [e["canonical_name"].lower()] + [a.lower() for a in e.get("aliases", [])]
            if any(name_norm in h or h in name_norm for h in haystack):
                match = e
                break
    if match is None:
        return {
            "output": None,
            "meta": {
                "tool": "get_character_profile",
                "args": {"name": name, "book_id": book_id, "chapter_limit": chapter_limit},
                "found": False,
                "reason": f"no character matching {name!r} in this book's index",
            },
        }

    first_chapter = int(match.get("first_chapter") or 0)
    if first_chapter > chapter_limit:
        return {
            "output": None,
            "meta": {
                "tool": "get_character_profile",
                "args": {"name": name, "book_id": book_id, "chapter_limit": chapter_limit},
                "found": False,
                "reason": (
                    f"{match['canonical_name']} is not introduced until chapter "
                    f"{first_chapter}, beyond the spoiler boundary."
                ),
            },
        }
    per_ch = {int(k): v for k, v in (match.get("per_chapter") or {}).items()
              if int(k) <= chapter_limit}
    timeline = sorted(per_ch.items())
    snippets = [
        {"chapter": ch, "snippet": info.get("snippet"), "mentions": info.get("mentions", 0)}
        for ch, info in timeline if info.get("snippet")
    ][:5]
    co = match.get("co_occurs_with") or {}
    # Filter co-occurrences to only characters also introduced by chapter_limit
    name_to_first = {e["canonical_name"]: int(e.get("first_chapter") or 0) for e in entries}
    co_filtered = sorted(
        ((k, v) for k, v in co.items() if name_to_first.get(k, 99999) <= chapter_limit),
        key=lambda x: -x[1],
    )[:5]

    return {
        "output": {
            "name": match["canonical_name"],
            "aliases": match.get("aliases", []),
            "first_chapter": first_chapter,
            "total_mentions_so_far": sum(v.get("mentions", 0) for v in per_ch.values()),
            "chapter_timeline": [
                {"chapter": ch, "mentions": info.get("mentions", 0)} for ch, info in timeline
            ],
            "snippets": snippets,
            "co_occurs_with": [{"name": n, "shared_chapters": v} for n, v in co_filtered],
        },
        "meta": {
            "tool": "get_character_profile",
            "args": {"name": name, "book_id": book_id, "chapter_limit": chapter_limit},
            "found": True,
            "matched_name": match["canonical_name"],
        },
    }


# ---------------- Tool registry ----------------

TOOLS: Dict[str, Any] = {
    "retrieve_passages": retrieve_passages,
    "lookup_character":  lookup_character,
    "summarize_chapter": summarize_chapter,
    "retrieve_expert_analysis": retrieve_expert_analysis,
    "list_known_characters": list_known_characters,
    "get_character_profile": get_character_profile,
}

TOOL_DESCRIPTIONS = """\
Available tools (call by name with the listed args):

1. retrieve_passages(query: str, k: int = 4, mode: str = "hybrid")
   Hybrid keyword + semantic retrieval over the book's ORIGINAL text.
   Best for thematic, symbolic, or quote-style questions.

2. lookup_character(name: str, k: int = 4)
   Vector retrieval of passages mentioning a character — returns full passages.
   Use AFTER list_known_characters/get_character_profile when you need quotes.

3. summarize_chapter(chapter: int, max_chars: int = 4000)
   Pull the full text of a single chapter the reader has already read.
   Best when you need broader context than a few embedded chunks.

4. retrieve_expert_analysis(query: str, k: int = 3)
   Retrieve scholarly literary-analysis snippets from BookSum (CliffsNotes /
   SparkNotes / Shmoop chapter analyses) about this book. Use as SECONDARY
   grounding alongside tool 1 for interpretive / symbolic questions.

5. list_known_characters(top_k: int = 10)
   STRUCTURED character lookup. Returns the most-mentioned characters
   introduced by the reader's current chapter, each with their first-appearance
   chapter and an intro snippet. Spoiler-safe by construction. Use this for
   ANY "main characters" / "who is in the book" / "list characters" question
   instead of relying on retrieve_passages.

6. get_character_profile(name: str)
   STRUCTURED character profile. Returns first_chapter, per-chapter mention
   timeline, intro snippets, and top co-occurring characters — all filtered
   to the spoiler boundary. Use for "tell me about X" / "who is X" / "what
   role does X play" questions.

(book_id and chapter_limit are filled in automatically — DO NOT pass them.)
"""
