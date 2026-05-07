"""
Per-book RAG indexing — DENSE + BM25 HYBRID retrieval with RRF fusion.

Each book gets its own Chroma collection named "book_<id>". Each chapter is
chunked into ~400-word passages, embedded, and stored with metadata:
    {book_id, chapter, chunk_in_chapter, chapter_title}

In parallel, an in-memory BM25 index over the same chunks is built so we can
combine sparse keyword matching with dense embedding similarity. The two
ranked lists are fused with Reciprocal Rank Fusion (RRF), the standard
hybrid-retrieval blending technique.

This satisfies Option 2 / D1 ("Advanced RAG with Hybrid retrieval").

Functions:
    ensure_book_index(book_id) -> chunk_count
    query_book(book_id, query, chapter_limit, top_k, mode='hybrid') -> list[chunk dict]
    is_indexed(book_id) -> bool

`mode` accepts 'dense', 'bm25', or 'hybrid' (default).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Dict, Any

import numpy as np
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi
import chromadb

ROOT = Path(__file__).resolve().parent.parent
BOOKS_DIR = ROOT / "data" / "books"
BOOKSUM_DIR = ROOT / "data" / "booksum"

MODEL_NAME = "all-MiniLM-L6-v2"
_model: SentenceTransformer | None = None
_chroma = chromadb.Client()
_indexed: set[str] = set()
_indexed_booksum: set[str] = set()

# Per-book BM25 indexes + tokenized corpus, keyed by book_id
_bm25: Dict[str, BM25Okapi] = {}
_bm25_ids: Dict[str, List[str]] = {}  # parallel to BM25 corpus order


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'-]+")


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def _collection_name(book_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", book_id)
    return f"book_{safe}"


def chunk_chapter(text: str, target_words: int = 400) -> List[str]:
    """Split a chapter into ~target_words-sized chunks at paragraph boundaries.

    Falls back to splitting on sentence boundaries if paragraphs are too small.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: List[str] = []
    buf: List[str] = []
    word_count = 0
    for p in paragraphs:
        p_words = len(p.split())
        if word_count + p_words > target_words and buf:
            chunks.append("\n\n".join(buf))
            buf = [p]
            word_count = p_words
        else:
            buf.append(p)
            word_count += p_words
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks


def is_indexed(book_id: str) -> bool:
    if book_id in _indexed:
        return True
    try:
        col = _chroma.get_collection(_collection_name(book_id))
        if col.count() > 0:
            _indexed.add(book_id)
            return True
    except Exception:
        pass
    return False


def ensure_book_index(book_id: str) -> int:
    """Build (or load) the Chroma collection for a book. Returns chunk count."""
    if is_indexed(book_id):
        return _chroma.get_collection(_collection_name(book_id)).count()

    book_path = BOOKS_DIR / f"{book_id}.json"
    if not book_path.exists():
        raise FileNotFoundError(f"Book not found: {book_id}")

    with open(book_path) as f:
        book = json.load(f)

    # Use the canonical title-derived chapter number so the spoiler filter
    # aligns with what the user sees in the UI. Skip pseudo-chapters (TOC,
    # intro, etc.) that don't have a real chapter number in their title.
    from chapter_numbering import parse_chapter_number  # local import

    # Some Gutenberg books have BOTH a TOC entry that parses to e.g.
    # "Chapter XXIV. Conclusion ... 315" AND the real chapter labeled the
    # same way. Dedupe heuristic: when two chapters map to the same canonical
    # number, prefer the one whose POSITION in the parsed list is closest to
    # the canonical number (real chapter N is usually around index N), with
    # a length tiebreak (real chapters have substantial body text).
    is_single = len(book["chapters"]) == 1
    canon_to_best_idx: Dict[int, int] = {}
    canon_for: Dict[int, Optional[int]] = {}
    for i, ch in enumerate(book["chapters"]):
        c = parse_chapter_number(ch.get("title", "") or "")
        if c is None:
            if is_single:
                c = 1
            else:
                canon_for[i] = None
                continue
        canon_for[i] = c
        prev = canon_to_best_idx.get(c)
        if prev is None:
            canon_to_best_idx[c] = i
            continue
        # Prefer the candidate whose position is closer to canonical c
        prev_dist = abs(prev - c)
        new_dist = abs(i - c)
        if new_dist < prev_dist:
            canon_to_best_idx[c] = i
        elif new_dist == prev_dist:
            # Tiebreak by length — real chapters have more body text
            if len(book["chapters"][prev].get("text") or "") < len(ch.get("text") or ""):
                canon_to_best_idx[c] = i
    keep_indices = set(canon_to_best_idx.values())

    docs: List[str] = []
    metadatas: List[Dict[str, Any]] = []
    ids: List[str] = []
    for i, ch in enumerate(book["chapters"]):
        if i not in keep_indices:
            continue
        ch_num = canon_for[i]
        if ch_num is None:
            continue
        ch_title = ch.get("title", "") or ""
        chunks = chunk_chapter(ch.get("text", ""))
        for ci, chunk in enumerate(chunks):
            docs.append(chunk)
            metadatas.append({
                "book_id": book_id,
                "chapter": ch_num,
                "chunk_in_chapter": ci,
                "chapter_title": ch_title,
            })
            ids.append(f"{book_id}:c{ch_num}:{ci}")

    if not docs:
        raise ValueError(f"Book {book_id} produced no chunks")

    model = _get_model()
    embeddings = model.encode(docs, show_progress_bar=False, batch_size=32)

    name = _collection_name(book_id)
    try:
        _chroma.delete_collection(name=name)
    except Exception:
        pass
    col = _chroma.create_collection(name=name)
    col.add(ids=ids, documents=docs, metadatas=metadatas, embeddings=embeddings.tolist())

    # Build BM25 index over the same chunks (sparse retrieval for hybrid search)
    tokenized = [_tokenize(d) for d in docs]
    _bm25[book_id] = BM25Okapi(tokenized)
    _bm25_ids[book_id] = ids

    _indexed.add(book_id)
    return len(docs)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _rrf_fuse(rank_lists: List[List[int]], k: int = 60) -> List[tuple[int, float]]:
    """Reciprocal Rank Fusion — combine multiple ranked lists of indices.

    Score(item) = sum_over_lists(1 / (k + rank_in_list)). Items missing from a
    list contribute 0 from that list. Returns a list of (idx, fused_score)
    sorted by fused_score descending. Standard hybrid-retrieval blending.
    """
    fused: Dict[int, float] = {}
    for ranks in rank_lists:
        for r, idx in enumerate(ranks, start=1):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + r)
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


def query_book(
    book_id: str,
    query: str,
    chapter_limit: int,
    top_k: int = 4,
    mode: str = "hybrid",
) -> List[Dict[str, Any]]:
    """Retrieve top_k chunks from `book_id` whose chapter <= chapter_limit.

    mode:
      - "dense":  cosine similarity over sentence-transformer embeddings only
      - "bm25":   BM25 keyword matching only
      - "hybrid": both, fused via Reciprocal Rank Fusion (default)

    The chapter cap is enforced BEFORE ranking — this is the spoiler boundary.
    """
    ensure_book_index(book_id)
    col = _chroma.get_collection(_collection_name(book_id))
    data = col.get(include=["embeddings", "documents", "metadatas"])
    ids = data["ids"]
    docs = data["documents"]
    metas = data["metadatas"]
    embs = np.array(data["embeddings"])

    # Spoiler-boundary filter (retrieval-side, hard guarantee)
    valid = [
        i for i, m in enumerate(metas)
        if int(m.get("chapter") or 0) <= chapter_limit
    ]
    if not valid:
        return []
    valid_set = set(valid)

    # ---- Dense ranking ----
    dense_ranked: List[int] = []
    dense_scores: Dict[int, float] = {}
    if mode in ("dense", "hybrid"):
        q_emb = _get_model().encode([query])[0]
        scored = sorted(
            ((i, _cosine(embs[i], q_emb)) for i in valid),
            key=lambda x: x[1],
            reverse=True,
        )
        # Take a wider candidate pool for fusion
        pool = scored[: max(top_k * 5, 20)]
        dense_ranked = [i for i, _ in pool]
        dense_scores = {i: s for i, s in pool}

    # ---- BM25 ranking ----
    bm25_ranked: List[int] = []
    bm25_scores: Dict[int, float] = {}
    if mode in ("bm25", "hybrid"):
        bm25 = _bm25.get(book_id)
        if bm25 is not None:
            scores = bm25.get_scores(_tokenize(query))
            # Filter to valid indices, then sort
            ranked_all = sorted(
                ((i, float(scores[i])) for i in valid),
                key=lambda x: x[1],
                reverse=True,
            )
            pool = ranked_all[: max(top_k * 5, 20)]
            bm25_ranked = [i for i, _ in pool]
            bm25_scores = {i: s for i, s in pool}

    # ---- Combine ----
    if mode == "dense":
        ranked = [(i, dense_scores[i]) for i in dense_ranked]
    elif mode == "bm25":
        ranked = [(i, bm25_scores[i]) for i in bm25_ranked]
    else:
        # hybrid via RRF
        if not dense_ranked and not bm25_ranked:
            return []
        if not bm25_ranked:
            ranked = [(i, dense_scores[i]) for i in dense_ranked]
        elif not dense_ranked:
            ranked = [(i, bm25_scores[i]) for i in bm25_ranked]
        else:
            fused = _rrf_fuse([dense_ranked, bm25_ranked])
            # Use fused score directly (small numbers, but consistent ordering)
            ranked = fused

    out: List[Dict[str, Any]] = []
    for i, score in ranked[:top_k]:
        if i not in valid_set:
            continue
        out.append({
            "id": ids[i],
            "document": docs[i],
            "metadata": metas[i],
            "score": float(score),
            "retrieval_mode": mode,
            "dense_score": dense_scores.get(i),
            "bm25_score": bm25_scores.get(i),
        })

    # Always include at least one chunk from the user's CURRENT chapter so
    # questions about events on the current page can be answered even when
    # semantic similarity points elsewhere. Prepend up to 2 current-chapter
    # chunks if none are already in the top-k results.
    chapters_in_results = {int((c.get("metadata") or {}).get("chapter") or 0) for c in out}
    if chapter_limit not in chapters_in_results:
        current_chunk_indices = [
            i for i, m in enumerate(metas)
            if int(m.get("chapter") or 0) == chapter_limit
        ]
        prepend = []
        for i in current_chunk_indices[:2]:
            prepend.append({
                "id": ids[i],
                "document": docs[i],
                "metadata": metas[i],
                "score": 0.0,
                "retrieval_mode": "current_chapter_force",
                "dense_score": None,
                "bm25_score": None,
            })
        out = prepend + out[: max(0, top_k - len(prepend))]
    return out


# ---------------------------------------------------------------------------
# BookSum secondary index — "expert literary analysis" knowledge source.
#
# BookSum entries are professionally written summaries + analyses (CliffsNotes,
# SparkNotes, Shmoop, etc.) of book chapters. We embed each entry's summary +
# analysis text into a separate Chroma collection per book, named
# "booksum_<book_id>". The agent's executor can call retrieve_expert_analysis
# to get scholarly grounding alongside the original-text retrieval.
# ---------------------------------------------------------------------------

_ROMAN_VALS = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def _parse_roman(s: str) -> Optional[int]:
    s = s.upper()
    if not all(c in _ROMAN_VALS for c in s):
        return None
    total, prev = 0, 0
    for c in reversed(s):
        v = _ROMAN_VALS[c]
        total += -v if v < prev else v
        prev = v
    return total


def _booksum_chapter_number(entry: Dict[str, Any]) -> int:
    """Best-effort extraction of an integer chapter number from a BookSum row.
    Returns the FIRST chapter number when the entry covers a range
    (e.g. 'chapters 13-14' -> 13), so spoiler-boundary checks stay strict."""
    for field in ("chapter", "summary_id", "book_id"):
        s = entry.get(field) or ""
        m = re.search(r"(\d+)", str(s))
        if m:
            return int(m.group(1))
        m2 = re.search(r"\b([IVXLCDM]+)\b", str(s).upper())
        if m2:
            n = _parse_roman(m2.group(1))
            if n:
                return n
    return 0


def _booksum_collection_name(book_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", book_id)
    return f"booksum_{safe}"


def is_booksum_indexed(book_id: str) -> bool:
    if book_id in _indexed_booksum:
        return True
    try:
        col = _chroma.get_collection(_booksum_collection_name(book_id))
        if col.count() > 0:
            _indexed_booksum.add(book_id)
            return True
    except Exception:
        pass
    return False


def ensure_booksum_index(book_id: str) -> int:
    """Build/load the BookSum collection for a book. Returns chunk count.
    Returns 0 (and is a no-op) if no BookSum file exists for this book."""
    if is_booksum_indexed(book_id):
        return _chroma.get_collection(_booksum_collection_name(book_id)).count()

    src = BOOKSUM_DIR / f"{book_id}.json"
    if not src.exists():
        return 0
    with open(src) as f:
        rows = json.load(f)

    docs: List[str] = []
    metadatas: List[Dict[str, Any]] = []
    ids: List[str] = []
    for i, r in enumerate(rows):
        analysis = (r.get("summary_analysis") or "").strip()
        summary = (r.get("summary_text") or "").strip()
        # Combine analysis + summary; analysis is the more critical/scholarly content
        text = ""
        if analysis:
            text += analysis
        if summary:
            text += ("\n\n" if text else "") + summary
        if not text or len(text) < 100:
            continue
        docs.append(text[:6000])  # cap each entry
        metadatas.append({
            "book_id": book_id,
            "chapter": _booksum_chapter_number(r),
            "source": r.get("source") or "booksum",
            "summary_id": r.get("summary_id") or f"bs-{i}",
            "summary_url": r.get("summary_url") or "",
        })
        ids.append(f"bs:{book_id}:{i}")

    if not docs:
        return 0

    embeddings = _get_model().encode(docs, show_progress_bar=False, batch_size=32)
    name = _booksum_collection_name(book_id)
    try:
        _chroma.delete_collection(name=name)
    except Exception:
        pass
    col = _chroma.create_collection(name=name)
    col.add(ids=ids, documents=docs, metadatas=metadatas, embeddings=embeddings.tolist())
    _indexed_booksum.add(book_id)
    return len(docs)


def query_booksum(
    book_id: str,
    query: str,
    chapter_limit: int,
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    """Retrieve top_k expert-analysis chunks from BookSum for `book_id`,
    filtered by chapter <= chapter_limit. Dense-only (the corpus is small)."""
    n = ensure_booksum_index(book_id)
    if n == 0:
        return []
    col = _chroma.get_collection(_booksum_collection_name(book_id))
    data = col.get(include=["embeddings", "documents", "metadatas"])
    ids = data["ids"]
    docs = data["documents"]
    metas = data["metadatas"]
    embs = np.array(data["embeddings"])
    valid = [
        i for i, m in enumerate(metas)
        if int(m.get("chapter") or 0) <= chapter_limit
    ]
    if not valid:
        return []
    q = _get_model().encode([query])[0]
    scored = sorted(
        ((i, _cosine(embs[i], q)) for i in valid),
        key=lambda x: x[1],
        reverse=True,
    )
    out = []
    for i, score in scored[:top_k]:
        out.append({
            "id": ids[i],
            "document": docs[i],
            "metadata": metas[i],
            "score": float(score),
            "source_kind": "expert_analysis",
        })
    return out


# Re-export Optional for the helpers above
from typing import Optional  # noqa: E402


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--query", required=True)
    ap.add_argument("--chapter", type=int, default=999)
    ap.add_argument("--top-k", type=int, default=4)
    ap.add_argument("--mode", default="hybrid", choices=["hybrid", "dense", "bm25"])
    args = ap.parse_args()

    print(f"Indexing {args.book}...")
    n = ensure_book_index(args.book)
    print(f"Indexed {n} chunks.")
    print(f"\nQuery: {args.query!r} (chapter <= {args.chapter}, mode={args.mode})")
    res = query_book(args.book, args.query, args.chapter, args.top_k, mode=args.mode)
    for i, r in enumerate(res, 1):
        m = r["metadata"]
        ds = r.get("dense_score"); bs = r.get("bm25_score")
        ds_s = f" dense={ds:.3f}" if ds is not None else ""
        bs_s = f" bm25={bs:.3f}" if bs is not None else ""
        print(f"\n[{i}] ch{m['chapter']} chunk{m['chunk_in_chapter']} fused={r['score']:.4f}{ds_s}{bs_s}")
        print("    " + r["document"][:300].replace("\n", " ") + ("..." if len(r["document"]) > 300 else ""))
