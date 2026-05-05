"""
RAG pipeline (embeddings -> Chroma in-memory) for BookSum samples.

Usage:
    python scripts/rag_pipeline.py

This script:
- Loads python/outputs/booksum_samples.json
- Embeds each sample.summary_text using sentence-transformers
- Stores documents, metadatas and embeddings in an in-memory ChromaDB
- Exposes query_up_to_chapter(query: str, chapter_limit: int)

Notes / assumptions:
- The source data does not always contain a numeric `chapter` field. We
  attempt to parse an integer from `summary_id` or `summary_name` (first
  integer found). If none is found, chapter defaults to 0.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
from typing import List, Dict, Any

import numpy as np

from sentence_transformers import SentenceTransformer
import chromadb

# Initialize model and chroma client at module import so tests can import
MODEL_NAME = "all-MiniLM-L6-v2"
_model = SentenceTransformer(MODEL_NAME)

# Create an in-memory Chroma client and collection
_chroma_client = chromadb.Client()
COLLECTION_NAME = "booksum_samples"
try:
    _collection = _chroma_client.get_collection(COLLECTION_NAME)
except Exception:
    _collection = _chroma_client.create_collection(name=COLLECTION_NAME)


def _extract_chapter(sample: Dict[str, Any]) -> int:
    """Try to extract a chapter integer from several fields.

    Returns 0 if no integer is found. For ranges like "1-2" this returns
    the first integer (1).
    """
    for key in ("summary_id", "summary_name", "book_id"):
        val = sample.get(key)
        if not val:
            continue
        # Find first integer
        m = re.search(r"(\d+)", str(val))
        if m:
            return int(m.group(1))
    # Fallback: look at sample.get("chapter") — sometimes numeric
    ch = sample.get("chapter")
    try:
        if isinstance(ch, (int, float)) and not math.isnan(ch):
            return int(ch)
        if isinstance(ch, str):
            m = re.search(r"(\d+)", ch)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return 0


def build_collection(samples_path: str | Path = None) -> None:
    """Load samples, embed summaries, and add to the Chroma collection.

    This is idempotent for this simple in-memory run (we clear the
    collection first).
    """
    base = Path(__file__).resolve().parent.parent
    if samples_path is None:
        samples_path = base / "outputs" / "booksum_samples.json"
    samples_path = Path(samples_path)
    if not samples_path.exists():
        raise FileNotFoundError(f"Samples not found: {samples_path}")

    with open(samples_path, "r") as f:
        samples = json.load(f)

    docs: List[str] = []
    metadatas: List[Dict[str, Any]] = []
    ids: List[str] = []

    for i, s in enumerate(samples):
        text = s.get("summary_text") or s.get("summary") or s.get("content") or ""
        chapter_num = _extract_chapter(s)
        docs.append(text)
        metadatas.append({"chapter": chapter_num, "summary_id": s.get("summary_id"), "bid": s.get("bid")})
        ids.append(str(i))

    # Compute embeddings (SentenceTransformer returns numpy array)
    embeddings = _model.encode(docs, show_progress_bar=True)

    # Clear existing collection by recreating it
    try:
        _chroma_client.delete_collection(name=COLLECTION_NAME)
    except Exception:
        pass
    col = _chroma_client.create_collection(name=COLLECTION_NAME)

    col.add(ids=ids, documents=docs, metadatas=metadatas, embeddings=embeddings.tolist())


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    if np.linalg.norm(a) == 0 or np.linalg.norm(b) == 0:
        return 0.0
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def query_up_to_chapter(query: str, chapter_limit: int, top_k: int = 3) -> List[Dict[str, Any]]:
    """Return top_k chunks whose metadata.chapter <= chapter_limit, ordered by similarity.

    Each returned item is a dict: {"id","document","metadata","score"}.
    """
    # Ensure collection is built (lazy build if empty)
    try:
        col = _chroma_client.get_collection(COLLECTION_NAME)
    except Exception:
        build_collection()
        col = _chroma_client.get_collection(COLLECTION_NAME)

    # Retrieve all data from the collection
    # Note: "ids" are always returned by Chroma; do not pass in include.
    data = col.get(include=["embeddings", "documents", "metadatas"])
    ids = data["ids"]
    docs = data["documents"]
    metadatas = data["metadatas"]
    embeddings = np.array(data["embeddings"])

    # Filter by chapter_limit
    valid_indices = []
    for idx, m in enumerate(metadatas):
        ch = m.get("chapter", 0)
        try:
            ch_num = int(ch)
        except Exception:
            ch_num = 0
        if ch_num <= chapter_limit:
            valid_indices.append(idx)

    if len(valid_indices) == 0:
        return []

    # Embed query
    q_emb = _model.encode([query])[0]

    # Compute similarities with valid embeddings
    sims = []
    for idx in valid_indices:
        emb = embeddings[idx]
        score = _cosine_sim(np.array(emb), np.array(q_emb))
        sims.append((idx, score))

    sims.sort(key=lambda x: x[1], reverse=True)

    results = []
    for idx, score in sims[:top_k]:
        results.append({
            "id": ids[idx],
            "document": docs[idx],
            "metadata": metadatas[idx],
            "score": score,
        })

    return results


if __name__ == "__main__":
    # Build collection and run an example query, printing top 3 results
    print("Building collection from python/outputs/booksum_samples.json...")
    build_collection()
    print("Collection ready. Running example query (top 3 results):")
    res = query_up_to_chapter("colonial warfare wilderness", chapter_limit=3, top_k=3)
    for i, r in enumerate(res, 1):
        print(f"\nResult {i}: id={r['id']} score={r['score']:.4f} chapter={r['metadata'].get('chapter')}")
        print(r["document"][:400].replace("\n", " ") + ("..." if len(r["document"])>400 else ""))
