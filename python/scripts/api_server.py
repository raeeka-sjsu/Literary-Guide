"""
Flask HTTP API for the Literary Guide agent.

Endpoints:
    GET  /health
    POST /ask   {question, chapter, provider?, top_k?}  -> {answer, chunks, ...}

Usage:
    python scripts/api_server.py
    # then curl localhost:5050/ask -d ...

The Express front-end can proxy /api/ask to this server.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from flask import Flask, jsonify, request
from flask_cors import CORS

from literary_guide_agent import answer, call_ollama, call_anthropic, call_openai, SYSTEM_PROMPT
from book_index import ensure_book_index, is_indexed
from memory_store import (
    set_reading_position,
    get_reading_position,
    list_recent_books,
    list_chat_turns,
    get_memory_summary,
    summarize_session,
)

DEFAULT_USER = "default"  # single-user mode for the demo

app = Flask(__name__)
CORS(app)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/index_book")
def index_book():
    """Build (or load) the per-book index. Returns chunk count."""
    payload = request.get_json(force=True) or {}
    book_id = (payload.get("book_id") or "").strip()
    if not book_id:
        return jsonify({"error": "book_id is required"}), 400
    try:
        already = is_indexed(book_id)
        n = ensure_book_index(book_id)
        return jsonify({"book_id": book_id, "chunks": n, "cached": already})
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/ask")
def ask():
    payload = request.get_json(force=True) or {}
    question = (payload.get("question") or "").strip()
    chapter = payload.get("chapter")
    provider = payload.get("provider", "dry-run")
    # Adaptive top_k: scale with how far into the book the reader is, capped to
    # keep the LLM context manageable. A reader 40+ chapters in needs broader
    # context; a reader on chapter 2 only has 2 chapters' worth of content.
    _explicit_k = payload.get("top_k")
    if _explicit_k is None:
        try:
            ch = int(payload.get("chapter") or 1)
        except (TypeError, ValueError):
            ch = 1
        top_k = min(max(6, ch // 2), 16)
    else:
        top_k = int(_explicit_k)
    book_id = (payload.get("book_id") or "").strip() or None
    user_id = (payload.get("user_id") or DEFAULT_USER).strip() or DEFAULT_USER
    retrieval_mode = (payload.get("retrieval_mode") or "hybrid").strip()
    agent_mode = bool(payload.get("agent_mode", False))

    if not question:
        return jsonify({"error": "question is required"}), 400
    try:
        chapter = int(chapter)
    except (TypeError, ValueError):
        return jsonify({"error": "chapter must be an integer"}), 400

    try:
        res = answer(
            question, chapter,
            provider=provider, top_k=top_k, book_id=book_id,
            user_id=user_id, retrieval_mode=retrieval_mode,
            persist=bool(book_id),
            agent_mode=agent_mode,
        )
    except Exception as e:
        # Surface the underlying LLM-provider error to the UI in a clean,
        # JSON-shaped 502 response, so the user sees a useful message rather
        # than a generic "agent unreachable" or HTML 500 page.
        msg = str(e)
        kind = "provider_error"
        # Detect the common cases by message content
        m_lower = msg.lower()
        if "credit balance is too low" in m_lower or "insufficient" in m_lower:
            kind = "credit_balance_too_low"
            friendly = (
                f"The {provider} API rejected the request because your account "
                "has insufficient credits. Add credits at the provider's billing "
                "page, or switch to a different LLM in the dropdown."
            )
        elif "rate limit" in m_lower or "429" in msg:
            kind = "rate_limited"
            friendly = (
                f"The {provider} API is rate-limiting requests. Wait a few "
                "seconds and try again, or switch to a different LLM."
            )
        elif "authentication" in m_lower or "invalid api key" in m_lower or "401" in msg:
            kind = "auth_failed"
            friendly = (
                f"The {provider} API rejected the API key. Check that .env "
                "contains the correct key and restart the backend."
            )
        else:
            friendly = f"The {provider} backend returned an error: {msg}"
        return jsonify({
            "error": friendly,
            "error_kind": kind,
            "provider": provider,
            "detail": msg[:500],
        }), 502

    # Strip embeddings/heavy fields for JSON response
    return jsonify({
        "question": res["question"],
        "current_chapter": res["current_chapter"],
        "provider": res["provider"],
        "model": res["model"],
        "answer": res["answer"],
        "memory_used": res.get("memory_used", False),
        "retrieval_mode": res.get("retrieval_mode"),
        "latency_ms": res.get("latency_ms"),
        "safety": res.get("safety"),
        "is_refusal": res.get("is_refusal"),
        "agent": res.get("agent"),  # plan, tool_calls, critic, timings (None in simple-RAG mode)
        "chunks": [
            {
                "id": c["id"],
                "score": c["score"],
                "metadata": c["metadata"],
                "document": c["document"],
                "dense_score": c.get("dense_score"),
                "bm25_score": c.get("bm25_score"),
            }
            for c in res["chunks"]
        ],
    })


# ----- Memory + reading-position endpoints (Option 2 / D3) -----

@app.get("/memory/<book_id>")
def memory_for_book(book_id):
    user_id = request.args.get("user_id", DEFAULT_USER)
    return jsonify({
        "user_id": user_id,
        "book_id": book_id,
        "reading_position": get_reading_position(user_id, book_id),
        "memory": get_memory_summary(user_id, book_id),
        "recent_turns": list_chat_turns(user_id, book_id, limit=20),
    })


@app.post("/memory/<book_id>/summarize")
def summarize_for_book(book_id):
    """Compress the recent chat turns into a rolling memory summary."""
    payload = request.get_json(silent=True) or {}
    user_id = payload.get("user_id", DEFAULT_USER)
    provider = payload.get("provider", "ollama")

    def _llm(sys, usr):
        if provider == "anthropic":
            return call_anthropic(sys, usr)
        if provider == "openai":
            return call_openai(sys, usr)
        return call_ollama(sys, usr)  # default — local

    summary = summarize_session(user_id, book_id, _llm)
    return jsonify({
        "user_id": user_id,
        "book_id": book_id,
        "summary": summary,
        "memory": get_memory_summary(user_id, book_id),
    })


@app.post("/reading_position")
def update_reading_position():
    payload = request.get_json(force=True) or {}
    user_id = payload.get("user_id", DEFAULT_USER)
    book_id = payload.get("book_id")
    chapter = payload.get("chapter")
    if not book_id or chapter is None:
        return jsonify({"error": "book_id and chapter required"}), 400
    set_reading_position(user_id, book_id, int(chapter))
    return jsonify({"ok": True})


@app.get("/recent_books")
def recent_books():
    user_id = request.args.get("user_id", DEFAULT_USER)
    return jsonify({"user_id": user_id, "books": list_recent_books(user_id, limit=10)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print(f"Literary Guide API listening on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
