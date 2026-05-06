"""
Stateful / Long-Horizon Memory for Literary Guide (Option 2 / D3).

Uses SQLite. Three kinds of memory:

1. ReadingPosition  — per (user_id, book_id): which chapter the user is on,
   when they last opened the book.
2. ChatTurn         — per (user_id, book_id): every Q&A exchange, with the
   chapter it happened in. This is the raw episodic log.
3. BookMemory       — per (user_id, book_id): a SHORT, evolving SUMMARY
   of what the reader has discussed about the book so far. Written by the
   LLM after each session (or on demand), retrieved at the start of a new
   session and folded into the system prompt as background context.

The summary path is what makes this "memory that is written, summarized,
and retrieved" — not just chat history.

API:
    set_reading_position(user_id, book_id, chapter)
    get_reading_position(user_id, book_id) -> int|None
    record_chat_turn(user_id, book_id, chapter, question, answer, ...)
    list_chat_turns(user_id, book_id, limit=20) -> list[dict]
    get_memory_summary(user_id, book_id) -> str|None
    set_memory_summary(user_id, book_id, summary)
    summarize_session(user_id, book_id, llm_callable) -> str
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "literary_guide.sqlite"

_lock = threading.RLock()


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _lock, _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS reading_position (
          user_id    TEXT NOT NULL,
          book_id    TEXT NOT NULL,
          chapter    INTEGER NOT NULL,
          updated_at TEXT NOT NULL DEFAULT (datetime('now')),
          PRIMARY KEY (user_id, book_id)
        );
        CREATE TABLE IF NOT EXISTS chat_turn (
          id           INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id      TEXT NOT NULL,
          book_id      TEXT NOT NULL,
          chapter      INTEGER NOT NULL,
          question     TEXT NOT NULL,
          answer       TEXT,
          provider     TEXT,
          model        TEXT,
          retrieval_mode TEXT,
          chunk_ids    TEXT,
          latency_ms   INTEGER,
          created_at   TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS chat_turn_user_book
          ON chat_turn (user_id, book_id, created_at);

        CREATE TABLE IF NOT EXISTS book_memory (
          user_id      TEXT NOT NULL,
          book_id      TEXT NOT NULL,
          summary      TEXT NOT NULL,
          highest_chapter INTEGER NOT NULL DEFAULT 0,
          turn_count   INTEGER NOT NULL DEFAULT 0,
          updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
          PRIMARY KEY (user_id, book_id)
        );
        CREATE TABLE IF NOT EXISTS tool_call (
          id           INTEGER PRIMARY KEY AUTOINCREMENT,
          turn_id      INTEGER,
          step_index   INTEGER NOT NULL,
          tool_name    TEXT NOT NULL,
          args_json    TEXT NOT NULL,
          meta_json    TEXT,
          n_results    INTEGER,
          latency_ms   INTEGER,
          created_at   TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY (turn_id) REFERENCES chat_turn(id)
        );
        CREATE INDEX IF NOT EXISTS tool_call_turn ON tool_call(turn_id);
        """)


# ----- Reading position -----

def set_reading_position(user_id: str, book_id: str, chapter: int):
    with _lock, _conn() as c:
        c.execute("""
            INSERT INTO reading_position (user_id, book_id, chapter)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, book_id) DO UPDATE SET
              chapter = excluded.chapter,
              updated_at = datetime('now')
        """, (user_id, book_id, chapter))


def get_reading_position(user_id: str, book_id: str) -> Optional[int]:
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT chapter FROM reading_position WHERE user_id=? AND book_id=?",
            (user_id, book_id),
        ).fetchone()
        return int(row["chapter"]) if row else None


def list_recent_books(user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT book_id, chapter, updated_at FROM reading_position "
            "WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ----- Chat turns -----

def record_chat_turn(
    user_id: str,
    book_id: str,
    chapter: int,
    question: str,
    answer: Optional[str],
    provider: Optional[str] = None,
    model: Optional[str] = None,
    retrieval_mode: Optional[str] = None,
    chunk_ids: Optional[List[str]] = None,
    latency_ms: Optional[int] = None,
) -> int:
    with _lock, _conn() as c:
        cur = c.execute("""
            INSERT INTO chat_turn
              (user_id, book_id, chapter, question, answer, provider, model,
               retrieval_mode, chunk_ids, latency_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, book_id, chapter, question, answer, provider, model,
            retrieval_mode, json.dumps(chunk_ids or []), latency_ms,
        ))
        return cur.lastrowid


def record_tool_call(
    turn_id: Optional[int],
    step_index: int,
    tool_name: str,
    args: Dict[str, Any],
    meta: Optional[Dict[str, Any]] = None,
    n_results: Optional[int] = None,
    latency_ms: Optional[int] = None,
) -> int:
    with _lock, _conn() as c:
        cur = c.execute("""
            INSERT INTO tool_call (turn_id, step_index, tool_name, args_json, meta_json, n_results, latency_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            turn_id, step_index, tool_name,
            json.dumps(args), json.dumps(meta or {}), n_results, latency_ms,
        ))
        return cur.lastrowid


def list_tool_calls_for_turn(turn_id: int) -> List[Dict[str, Any]]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM tool_call WHERE turn_id=? ORDER BY step_index ASC",
            (turn_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_chat_turns(user_id: str, book_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT id, chapter, question, answer, provider, model, created_at "
            "FROM chat_turn WHERE user_id=? AND book_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (user_id, book_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ----- Memory summary -----

def get_memory_summary(user_id: str, book_id: str) -> Optional[Dict[str, Any]]:
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT summary, highest_chapter, turn_count, updated_at "
            "FROM book_memory WHERE user_id=? AND book_id=?",
            (user_id, book_id),
        ).fetchone()
        return dict(row) if row else None


def set_memory_summary(user_id: str, book_id: str, summary: str,
                       highest_chapter: int = 0, turn_count: int = 0):
    with _lock, _conn() as c:
        c.execute("""
            INSERT INTO book_memory (user_id, book_id, summary, highest_chapter, turn_count)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, book_id) DO UPDATE SET
              summary = excluded.summary,
              highest_chapter = excluded.highest_chapter,
              turn_count = excluded.turn_count,
              updated_at = datetime('now')
        """, (user_id, book_id, summary, highest_chapter, turn_count))


def summarize_session(
    user_id: str,
    book_id: str,
    llm_callable: Callable[[str, str], str],
    max_turns: int = 30,
) -> str:
    """Compute a fresh memory summary by feeding the recent turns + the existing
    summary back to an LLM. The result is stored and returned.

    `llm_callable(system_prompt, user_prompt)` must be a callable that returns
    a string. We pass it the prior summary + recent turns and ask for a
    concise, spoiler-safe rolling summary of what the reader has discussed.
    """
    prior = get_memory_summary(user_id, book_id)
    turns = list_chat_turns(user_id, book_id, limit=max_turns)
    if not turns:
        return prior["summary"] if prior else ""

    highest_chapter = max(int(t["chapter"]) for t in turns)
    if prior and prior.get("highest_chapter", 0) > highest_chapter:
        highest_chapter = int(prior["highest_chapter"])

    formatted_turns = "\n\n".join(
        f"[ch {t['chapter']}] Q: {t['question']}\n   A: {(t['answer'] or '').strip()[:600]}"
        for t in reversed(turns)  # chronological
    )

    sys_prompt = (
        "You maintain a SHORT rolling memory for a literary reading-companion app. "
        "Given the prior memory and recent Q&A turns, produce an updated memory "
        "summary in 4-8 short bullets covering: (a) which chapters/themes the reader "
        "has explored, (b) characters or symbols they've focused on, (c) any open "
        "questions they keep returning to. Stay strictly within events at or before "
        f"chapter {highest_chapter}. Do not introduce facts not in the conversation. "
        "Keep it under 180 words. Output bullets only — no preamble."
    )
    user_prompt = (
        f"Prior memory:\n{(prior['summary'] if prior else '(none)')}\n\n"
        f"Recent turns (oldest first):\n{formatted_turns}\n\n"
        "Updated memory bullets:"
    )

    new_summary = llm_callable(sys_prompt, user_prompt).strip()
    set_memory_summary(user_id, book_id, new_summary,
                       highest_chapter=highest_chapter,
                       turn_count=(prior["turn_count"] if prior else 0) + len(turns))
    return new_summary


# Initialize on import
init_db()
