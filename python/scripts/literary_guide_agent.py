"""
Literary Guide agent — chapter-aware Q&A with citations.

Pipeline:
  question + current_chapter
    -> rag_pipeline.query_up_to_chapter()  (spoiler-safe retrieval)
    -> LLM call with retrieved passages as grounded context
    -> answer + inline [n] citations mapped to source chunks

Usage:
    # Default: dry-run (no LLM call), prints retrieved context only
    python scripts/literary_guide_agent.py \
        --question "What does the wilderness symbolize?" \
        --chapter 3

    # With Anthropic Claude (set ANTHROPIC_API_KEY)
    python scripts/literary_guide_agent.py \
        --question "..." --chapter 3 --provider anthropic

    # With OpenAI (set OPENAI_API_KEY)
    python scripts/literary_guide_agent.py \
        --question "..." --chapter 3 --provider openai
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

# Make sibling imports work when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rag_pipeline import build_collection, query_up_to_chapter  # noqa: E402
from book_index import ensure_book_index, query_book  # noqa: E402


SYSTEM_PROMPT = """You are Literary Guide, a spoiler-aware reading companion.

You will be given:
- The reader's current chapter (they have NOT read past this chapter)
- A question they have about the book
- A set of numbered passages [1], [2], ... drawn ONLY from up to and including that chapter

Rules:
1. Answer ONLY using information present in the numbered passages. Do not draw on outside knowledge of the book.
2. NEVER reference events, characters, or revelations that are not present in the passages — those are spoilers.
3. Cite every claim inline using the bracketed number(s) of the passage(s) supporting it, e.g. "The narrator emphasizes the danger of the wilderness [1][2]."
4. If the passages do not contain enough information, say so plainly. Do not speculate.
5. Keep the tone thoughtful and analytical — discuss themes, symbolism, and motivations, not plot summary.

Answer style:
- Lead with the most direct, useful answer. Don't open with caveats or chapter-bookkeeping.
- For "who are the main characters" or similar overview questions, name them up front (drawing on any passages — they are all spoiler-safe by construction), then optionally note which appear in the current chapter.
- Be concise. 3–6 sentences is usually plenty unless the question genuinely needs more.
- Don't restate the question or list all passage numbers in a closing summary.
"""


def format_context(chunks: List[Dict[str, Any]]) -> str:
    """Format retrieved chunks as numbered passages for the LLM prompt."""
    parts = []
    for i, c in enumerate(chunks, 1):
        meta = c.get("metadata", {}) or {}
        ch = meta.get("chapter", "?")
        sid = meta.get("summary_id", "?")
        text = (c.get("document") or "").strip()
        parts.append(f"[{i}] (chapter {ch}, summary_id={sid})\n{text}")
    return "\n\n".join(parts)


def build_user_prompt(question: str, current_chapter: int, chunks: List[Dict[str, Any]]) -> str:
    return (
        f"Current chapter: {current_chapter}\n\n"
        f"Question: {question}\n\n"
        f"Passages (cite by number):\n{format_context(chunks)}"
    )


def call_anthropic(system: str, user: str, model: str = "claude-3-5-sonnet-latest") -> str:
    import anthropic  # type: ignore

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    # Concatenate text blocks
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def call_openai(system: str, user: str, model: str = "gpt-4o-mini") -> str:
    from openai import OpenAI  # type: ignore

    client = OpenAI()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content or ""


def call_ollama(system: str, user: str, model: str = "llama3.2:3b") -> str:
    """Call a local Ollama model via its HTTP API. No API key required."""
    import json as _json
    import urllib.request

    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {"temperature": 0.3},
    }
    req = urllib.request.Request(
        f"{host}/api/chat",
        data=_json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        body = _json.loads(r.read().decode("utf-8"))
    return body.get("message", {}).get("content", "")


def answer(
    question: str,
    current_chapter: int,
    provider: str = "dry-run",
    top_k: int = 4,
    model: str | None = None,
    book_id: str | None = None,
) -> Dict[str, Any]:
    """Retrieve, then answer.

    Returns a dict: {answer, chunks, system_prompt, user_prompt, provider, model}.
    With provider="dry-run", `answer` is None — only the prompt + retrieved chunks
    are returned. Useful for offline development and testing the retrieval layer.

    If `book_id` is given, retrieves from that book's per-book index (preferred).
    Otherwise falls back to the legacy BookSum sample collection.
    """
    if book_id:
        ensure_book_index(book_id)
        chunks = query_book(book_id, question, chapter_limit=current_chapter, top_k=top_k)
    else:
        # Fallback: legacy BookSum sample retrieval
        global _COLLECTION_READY  # type: ignore
        if not globals().get("_COLLECTION_READY"):
            build_collection()
            _COLLECTION_READY = True
        chunks = query_up_to_chapter(question, chapter_limit=current_chapter, top_k=top_k)

    user_prompt = build_user_prompt(question, current_chapter, chunks)

    out: Dict[str, Any] = {
        "question": question,
        "current_chapter": current_chapter,
        "provider": provider,
        "model": model,
        "chunks": chunks,
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt": user_prompt,
        "answer": None,
    }

    if provider == "dry-run":
        return out

    if provider == "anthropic":
        out["model"] = model or "claude-3-5-sonnet-latest"
        out["answer"] = call_anthropic(SYSTEM_PROMPT, user_prompt, out["model"])
    elif provider == "openai":
        out["model"] = model or "gpt-4o-mini"
        out["answer"] = call_openai(SYSTEM_PROMPT, user_prompt, out["model"])
    elif provider == "ollama":
        out["model"] = model or "llama3.2:3b"
        out["answer"] = call_ollama(SYSTEM_PROMPT, user_prompt, out["model"])
    else:
        raise ValueError(f"Unknown provider: {provider!r}")

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", required=True)
    ap.add_argument("--chapter", type=int, required=True,
                    help="Reader's current chapter (spoiler boundary)")
    ap.add_argument("--provider", default="dry-run",
                    choices=["dry-run", "anthropic", "openai", "ollama"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--top-k", type=int, default=4)
    args = ap.parse_args()

    print(f"\n=== Literary Guide ({args.provider}) ===")
    print(f"Chapter limit: {args.chapter}\nQuestion: {args.question}\n")

    res = answer(args.question, args.chapter, provider=args.provider,
                 top_k=args.top_k, model=args.model)

    print(f"Retrieved {len(res['chunks'])} passages (spoiler-safe, chapter <= {args.chapter}):\n")
    for i, c in enumerate(res["chunks"], 1):
        meta = c.get("metadata", {}) or {}
        snippet = (c.get("document") or "")[:200].replace("\n", " ")
        print(f"  [{i}] chapter={meta.get('chapter')} score={c['score']:.3f}")
        print(f"      {snippet}{'...' if len(c.get('document') or '') > 200 else ''}\n")

    if res["answer"] is not None:
        print("--- Answer ---")
        print(res["answer"])
    else:
        print("(dry-run — no LLM call made. Pass --provider anthropic or --provider openai.)")


if __name__ == "__main__":
    main()
