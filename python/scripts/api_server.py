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

from literary_guide_agent import answer

app = Flask(__name__)
CORS(app)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/ask")
def ask():
    payload = request.get_json(force=True) or {}
    question = (payload.get("question") or "").strip()
    chapter = payload.get("chapter")
    provider = payload.get("provider", "dry-run")
    top_k = int(payload.get("top_k", 4))

    if not question:
        return jsonify({"error": "question is required"}), 400
    try:
        chapter = int(chapter)
    except (TypeError, ValueError):
        return jsonify({"error": "chapter must be an integer"}), 400

    res = answer(question, chapter, provider=provider, top_k=top_k)

    # Strip embeddings/heavy fields for JSON response
    return jsonify({
        "question": res["question"],
        "current_chapter": res["current_chapter"],
        "provider": res["provider"],
        "model": res["model"],
        "answer": res["answer"],
        "chunks": [
            {
                "id": c["id"],
                "score": c["score"],
                "metadata": c["metadata"],
                "document": c["document"],
            }
            for c in res["chunks"]
        ],
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print(f"Literary Guide API listening on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
