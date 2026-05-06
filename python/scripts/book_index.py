"""
Per-book RAG indexing.

Each book gets its own Chroma collection named "book_<id>". Each chapter is
chunked into ~400-word passages, embedded, and stored with metadata:
    {book_id, chapter, chunk_in_chapter, chapter_title}

Functions:
    ensure_book_index(book_id) -> chunk_count
    query_book(book_id, query, chapter_limit, top_k) -> list[chunk dict]
    is_indexed(book_id) -> bool
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Dict, Any

import numpy as np
from sentence_transformers import SentenceTransformer
import chromadb

ROOT = Path(__file__).resolve().parent.parent
BOOKS_DIR = ROOT / "data" / "books"

MODEL_NAME = "all-MiniLM-L6-v2"
_model: SentenceTransformer | None = None
_chroma = chromadb.Client()
_indexed: set[str] = set()


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

    docs: List[str] = []
    metadatas: List[Dict[str, Any]] = []
    ids: List[str] = []
    for ch in book["chapters"]:
        ch_num = ch.get("number", 1)
        ch_title = ch.get("title", f"Chapter {ch_num}")
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

    _indexed.add(book_id)
    return len(docs)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def query_book(
    book_id: str,
    query: str,
    chapter_limit: int,
    top_k: int = 4,
) -> List[Dict[str, Any]]:
    """Retrieve top_k chunks from `book_id` whose chapter <= chapter_limit."""
    ensure_book_index(book_id)
    col = _chroma.get_collection(_collection_name(book_id))
    data = col.get(include=["embeddings", "documents", "metadatas"])
    ids = data["ids"]
    docs = data["documents"]
    metas = data["metadatas"]
    embs = np.array(data["embeddings"])

    # Filter by chapter
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
            "score": score,
        })
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--query", required=True)
    ap.add_argument("--chapter", type=int, default=999)
    ap.add_argument("--top-k", type=int, default=4)
    args = ap.parse_args()

    print(f"Indexing {args.book}...")
    n = ensure_book_index(args.book)
    print(f"Indexed {n} chunks.")
    print(f"\nQuery: {args.query!r} (chapter <= {args.chapter})")
    res = query_book(args.book, args.query, args.chapter, args.top_k)
    for i, r in enumerate(res, 1):
        m = r["metadata"]
        print(f"\n[{i}] ch{m['chapter']} chunk{m['chunk_in_chapter']} score={r['score']:.3f}")
        print("    " + r["document"][:300].replace("\n", " ") + ("..." if len(r["document"]) > 300 else ""))
