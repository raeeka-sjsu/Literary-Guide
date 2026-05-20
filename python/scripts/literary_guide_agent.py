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
from typing import List, Dict, Any, Optional

# Make sibling imports work when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rag_pipeline import build_collection, query_up_to_chapter  # noqa: E402
from book_index import ensure_book_index, query_book  # noqa: E402
from memory_store import (  # noqa: E402
    record_chat_turn,
    get_memory_summary,
    set_reading_position,
)
from safety import check_answer, is_refusal  # noqa: E402


SYSTEM_PROMPT = """You are Literary Guide, a spoiler-aware reading companion.

You will be given:
- The reader's current chapter (they have NOT read past this chapter)
- A question they have about the book
- A set of numbered passages [1], [2], ... drawn ONLY from up to and including that chapter
- (Optional) a SHORT rolling memory summary of past discussions about this book

Hard rules — never violate:
1. Answer ONLY using information present in the numbered passages. Do not draw on outside knowledge of this book or any other source.
2. **The passages may come from ANY chapter up to and including the reader's current chapter. All of these are fair game.** Use prior-chapter passages freely when the question requires earlier context (for example, a character's introduction, an earlier scene the question refers back to, or thematic development across chapters). Only future-chapter content is forbidden.
3. NEVER reference events, characters, identities, deaths, marriages, betrayals, twists, or revelations that are not present in the passages. Those are spoilers.
4. If the question explicitly asks about the ending, future events, or facts you can only know from later chapters, REFUSE: say "I can't see beyond chapter N yet — let's discuss what's happened so far." Do not hint, do not speculate, do not paraphrase the missing info.
5. Cite every factual claim inline using bracketed numbers of supporting passages, e.g. "The narrator emphasizes the danger of the wilderness [1][2]." Claims with no citation are not allowed.
6. If passages don't contain enough information, say so plainly. Do not invent.
7. Keep the tone thoughtful and analytical — themes, symbolism, motivations, not plot summary.

Answer style:
- Lead with the most direct, useful answer. Don't open with caveats or chapter-bookkeeping.
- For "who are the main characters" or similar overview questions, name them up front (drawing on any passages — they are all spoiler-safe by construction), then optionally note which appear in the current chapter.
- Be concise. 3–6 sentences is usually plenty unless the question genuinely needs more.
- Don't restate the question or list all passage numbers in a closing summary.

If the user's question cannot be answered without spoilers, your refusal MUST contain one of:
"I can't see beyond", "the passages do not", "haven't read that yet", "not yet visible".

EXAMPLES — follow this style:

Example 1 (analytical, in-bounds):
Current chapter: 3
Question: What does the narrator's tone reveal about her view of marriage?
Passages:
[1] (chapter 1) "It is a truth universally acknowledged, that a single man in possession of a good fortune must be in want of a wife."
[2] (chapter 1) "Mr. Bennet was so odd a mixture of quick parts, sarcastic humor, reserve, and caprice..."
ANSWER: The narrator opens with mock formality, presenting "a truth universally acknowledged" about marriage as if it were a law of nature [1]. The phrasing is satirical — it parodies the way her society treats marriage as inevitable matchmaking. Mr. Bennet's "sarcastic humor" further frames marriage as a domestic theater of mismatched temperaments [2]. The combined effect is a narrator who treats marriage as a social transaction worth gentle ridicule.

Example 2 (spoiler-trap — refuse):
Current chapter: 3
Question: Does Elizabeth end up marrying Darcy?
Passages:
[1] (chapter 1) "Mr. Darcy soon drew the attention of the room by his fine, tall person..."
[2] (chapter 3) "Elizabeth Bennet had been obliged, by the scarcity of gentlemen, to sit down for two dances..."
ANSWER: I can't see beyond chapter 3 yet — the passages do not reveal what happens between Elizabeth and Mr. Darcy later in the novel. So far we only know that Darcy makes a strong first impression in society [1] and that Elizabeth has only briefly encountered him on the dance floor [2]. Let's discuss their early dynamic instead if you'd like.

Example 3 (passage doesn't actually answer the question):
Current chapter: 4
Question: Where is the treasure hidden?
Passages:
[1] (chapter 2) "Tom whistled as he walked along the picket fence..."
[2] (chapter 4) "Tom and Huck huddled in the dark and listened..."
ANSWER: The passages do not yet describe a treasure or its location. Up to chapter 4 we see Tom's mischief along the fence [1] and the boys eavesdropping in the dark [2], but no treasure has been introduced.
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


def build_user_prompt(
    question: str,
    current_chapter: int,
    chunks: List[Dict[str, Any]],
    memory: Optional[str] = None,
    total_chapters: Optional[int] = None,
) -> str:
    if total_chapters and current_chapter >= total_chapters:
        chapter_line = (
            f"Current chapter: {current_chapter} of {total_chapters} "
            f"(this is the FINAL chapter — there is no 'later' in this book)"
        )
    elif total_chapters:
        chapter_line = (
            f"Current chapter: {current_chapter} of {total_chapters}"
        )
    else:
        chapter_line = f"Current chapter: {current_chapter}"
    parts = [chapter_line]
    if memory:
        parts.append(
            "Reader memory (a SHORT rolling summary of past discussions about this book — "
            "do not treat as new spoilers, do not cite, just use as background):\n"
            + memory
        )
    parts.append(f"Question: {question}")
    parts.append(f"Passages (cite by number):\n{format_context(chunks)}")
    return "\n\n".join(parts)


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


def _make_llm_call(provider: str, model_name: Optional[str]) -> Any:
    """Return a callable(system, user) -> str using the requested provider."""
    if provider == "anthropic":
        m = model_name or "claude-haiku-4-5"
        return lambda s, u: call_anthropic(s, u, m)
    if provider == "openai":
        m = model_name or "gpt-4o-mini"
        return lambda s, u: call_openai(s, u, m)
    if provider == "ollama":
        m = model_name or "llama3.2:3b"
        return lambda s, u: call_ollama(s, u, m)
    raise ValueError(f"agent mode requires a real provider, not {provider!r}")


def answer(
    question: str,
    current_chapter: int,
    provider: str = "dry-run",
    top_k: int = 8,
    model: str | None = None,
    book_id: str | None = None,
    user_id: str | None = None,
    retrieval_mode: str = "hybrid",
    persist: bool = False,
    agent_mode: bool = False,
) -> Dict[str, Any]:
    """Retrieve, then answer.

    Returns a dict: {answer, chunks, system_prompt, user_prompt, provider, model}.
    With provider="dry-run", `answer` is None — only the prompt + retrieved chunks
    are returned. Useful for offline development and testing the retrieval layer.

    If `book_id` is given, retrieves from that book's per-book index (preferred).
    Otherwise falls back to the legacy BookSum sample collection.
    """
    # ---- Agent mode (Option 2 / D2): Planner-Executor-Critic ----
    if agent_mode:
        if not book_id:
            raise ValueError("agent_mode requires book_id")
        if provider == "dry-run":
            raise ValueError("agent_mode requires a real LLM provider")

        from agent_loop import run_agent
        import time as _t

        # Pre-load memory so it can be passed into the synthesizer
        memory_text: Optional[str] = None
        if user_id:
            mem = get_memory_summary(user_id, book_id)
            if mem and mem.get("summary"):
                memory_text = mem["summary"]

        # Pre-create the chat_turn row so tool_calls can FK it
        turn_id: Optional[int] = None
        if persist and user_id:
            try:
                turn_id = record_chat_turn(
                    user_id=user_id, book_id=book_id, chapter=current_chapter,
                    question=question, answer=None,
                    provider=provider, model=model, retrieval_mode="agent",
                )
            except Exception:
                turn_id = None

        llm = _make_llm_call(provider, model)
        agent_started = _t.time()
        result = run_agent(
            question=question,
            current_chapter=current_chapter,
            book_id=book_id,
            llm_call=llm,
            user_id=user_id,
            turn_id=turn_id,
            memory_summary=memory_text,
        )
        agent_total_ms = int((_t.time() - agent_started) * 1000)

        # Build chunks shape compatible with the simple-RAG response
        chunks_compat = []
        for i, p in enumerate(result["passages"], 1):
            chunks_compat.append({
                "id": p.get("id"),
                "metadata": {"chapter": p.get("chapter"), "from_tool": p.get("from_tool")},
                "score": 0.0,
                "document": p.get("text"),
            })

        out: Dict[str, Any] = {
            "question": question,
            "current_chapter": current_chapter,
            "provider": provider,
            "model": model or {"anthropic": "claude-haiku-4-5", "openai": "gpt-4o-mini", "ollama": "llama3.2:3b"}[provider],
            "chunks": chunks_compat,
            "memory_used": bool(memory_text),
            "retrieval_mode": "agent",
            "system_prompt": SYSTEM_PROMPT,
            "user_prompt": "(agent mode — see plan/tool_calls)",
            "answer": result["answer"],
            "latency_ms": agent_total_ms,
            "agent": {
                "plan": result["plan"],
                "tool_calls": result["tool_calls"],
                "critic": result["critic"],
                "retried": result["retried"],
                "timings": result["timings"],
            },
        }
        out["safety"] = check_answer(out["answer"] or "", chunks_compat)
        out["is_refusal"] = is_refusal(out["answer"] or "")

        # Now write the answer back into the turn row
        if persist and user_id and turn_id is not None:
            try:
                import sqlite3
                from memory_store import _conn, _lock  # type: ignore
                with _lock, _conn() as c:
                    c.execute(
                        "UPDATE chat_turn SET answer=?, latency_ms=? WHERE id=?",
                        (out["answer"], agent_total_ms, turn_id),
                    )
                set_reading_position(user_id, book_id, current_chapter)
            except Exception as e:
                out["persist_error"] = str(e)
        return out

    # ---- Simple-RAG mode ----
    if book_id:
        ensure_book_index(book_id)
        chunks = query_book(book_id, question, chapter_limit=current_chapter,
                            top_k=top_k, mode=retrieval_mode)
    else:
        # Fallback: legacy BookSum sample retrieval
        global _COLLECTION_READY  # type: ignore
        if not globals().get("_COLLECTION_READY"):
            build_collection()
            _COLLECTION_READY = True
        chunks = query_up_to_chapter(question, chapter_limit=current_chapter, top_k=top_k)

    # Pull persisted memory summary, if any
    memory_text: Optional[str] = None
    if user_id and book_id:
        mem = get_memory_summary(user_id, book_id)
        if mem and mem.get("summary"):
            memory_text = mem["summary"]

    # Look up total chapters for this book so the LLM can recognize when the
    # reader is on the final chapter (no "later" content exists).
    total_chapters = None
    if book_id:
        try:
            import json as _json
            book_path = Path(__file__).resolve().parent.parent / "data" / "books" / f"{book_id}.json"
            with open(book_path) as _f:
                _book = _json.load(_f)
            total_chapters = len(_book.get("chapters") or [])
        except Exception:
            total_chapters = None

    user_prompt = build_user_prompt(question, current_chapter, chunks,
                                     memory=memory_text, total_chapters=total_chapters)

    out: Dict[str, Any] = {
        "question": question,
        "current_chapter": current_chapter,
        "provider": provider,
        "model": model,
        "chunks": chunks,
        "memory_used": bool(memory_text),
        "retrieval_mode": retrieval_mode,
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt": user_prompt,
        "answer": None,
    }

    if provider == "dry-run":
        return out

    import time as _t
    started = _t.time()
    if provider == "anthropic":
        out["model"] = model or "claude-haiku-4-5"
        out["answer"] = call_anthropic(SYSTEM_PROMPT, user_prompt, out["model"])
    elif provider == "openai":
        out["model"] = model or "gpt-4o-mini"
        out["answer"] = call_openai(SYSTEM_PROMPT, user_prompt, out["model"])
    elif provider == "ollama":
        out["model"] = model or "llama3.2:3b"
        out["answer"] = call_ollama(SYSTEM_PROMPT, user_prompt, out["model"])
    else:
        raise ValueError(f"Unknown provider: {provider!r}")
    out["latency_ms"] = int((_t.time() - started) * 1000)

    # Post-hoc safety/grounding check
    out["safety"] = check_answer(out["answer"] or "", chunks)
    out["is_refusal"] = is_refusal(out["answer"] or "")

    # Persist the chat turn so memory summarization has data to compress
    if persist and user_id and book_id:
        try:
            chunk_ids = [c.get("id") for c in chunks if c.get("id")]
            record_chat_turn(
                user_id=user_id,
                book_id=book_id,
                chapter=current_chapter,
                question=question,
                answer=out["answer"],
                provider=provider,
                model=out["model"],
                retrieval_mode=retrieval_mode,
                chunk_ids=chunk_ids,
                latency_ms=out["latency_ms"],
            )
            set_reading_position(user_id, book_id, current_chapter)
        except Exception as e:
            out["persist_error"] = str(e)

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
