"""
Planner-Executor-Critic agent loop (Option 2 / D2).

Stages:
  1. PLANNER     — LLM decides which tools to call, in what order,
                   based on the question type. Outputs strict JSON.
  2. EXECUTOR    — runs each tool call, collects outputs, logs every
                   call to the tool_call SQLite table. Spoiler boundary
                   is enforced inside each tool.
  3. SYNTHESIZER — LLM writes the answer using the gathered tool outputs
                   as numbered passages [1], [2], ...
  4. CRITIC      — LLM (or local heuristic) verifies the draft answer:
                   • does every claim cite at least one passage?
                   • does the answer mention any future-chapter content?
                   • are all citation indices valid?
                   On FAIL → executor retries with a corrective hint, max 1 retry.

Plain-text streaming of progress is supported via an `on_step` callback —
the API surfaces these so the UI can show the agent thinking.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Dict, List, Optional

from agent_tools import TOOLS, TOOL_DESCRIPTIONS
from memory_store import record_tool_call


# ---------------- Prompts ----------------

PLANNER_SYSTEM = """\
You are the PLANNER in a chapter-aware literary reading-companion agent.

Your job: read the user's question and pick which tools to call (in order)
to gather grounding evidence for the answer. You DO NOT write the answer
itself — that's the synthesizer's job.

""" + TOOL_DESCRIPTIONS + """

Rules:
- Output ONLY a JSON object with shape:
  {"reasoning": "<one short sentence>", "steps": [{"tool": "<name>", "args": {...}}, ...]}
- 1 to 3 steps. More than 3 is wasteful.
- For thematic / symbolic / "what does X reveal" questions: usually 1 retrieve_passages step.
- For questions centered on a specific character: lookup_character + retrieve_passages.
- For questions about an entire chapter's mood / structure: summarize_chapter + retrieve_passages.
- DO NOT include book_id or chapter_limit in args — those are filled automatically.
- DO NOT request information from chapters beyond the reader's current chapter.

Examples:

Q: "What does the wilderness symbolize so far?"
{"reasoning": "Thematic question — semantic retrieval is enough.",
 "steps": [{"tool":"retrieve_passages","args":{"query":"wilderness symbolism setting","k":4}}]}

Q: "What does Mr. Bennet's sarcasm reveal about his marriage?"
{"reasoning": "Character-focused question — find passages featuring Mr. Bennet, then thematic retrieve.",
 "steps": [
   {"tool":"lookup_character","args":{"name":"Bennet","k":3}},
   {"tool":"retrieve_passages","args":{"query":"sarcasm marriage Mr. and Mrs. Bennet","k":3}}
 ]}

Q: "Summarize the mood of chapter 3."
{"reasoning": "Whole-chapter mood — pull the chapter then add a thematic retrieve.",
 "steps": [
   {"tool":"summarize_chapter","args":{"chapter":3}},
   {"tool":"retrieve_passages","args":{"query":"chapter 3 mood tone atmosphere","k":2}}
 ]}
"""


SYNTHESIZER_SYSTEM = """\
You are the SYNTHESIZER. You wrote the chapter-aware reading companion's final answer.

Inputs you'll receive:
  - The user's question and current chapter
  - Numbered passages [1], [2], ... gathered by tool calls
  - (Optional) a rolling memory summary of past discussions

Hard rules:
1. Use ONLY the numbered passages. Never inject outside knowledge.
2. NEVER reference events or facts beyond the reader's current chapter.
3. Cite every factual claim inline, e.g. "The narrator emphasizes the wilderness [1][2]."
4. If the passages don't answer the question, say so ("the passages do not...") — do not speculate.
5. Lead with the direct answer. 3–6 sentences. Analytical tone, not plot summary.
6. If the question is asking for events from later in the book, REFUSE: "I can't see beyond chapter N yet."
"""


CRITIC_SYSTEM = """\
You are the CRITIC. Verify the SYNTHESIZER's draft answer.

Check these in order:
  A. Does every factual claim cite at least one passage [n]?
  B. Are all citation indices valid (within the available passages)?
  C. Does the answer mention any event, character, or revelation NOT present in the passages?
     (If you can't verify a claim from the passages, that's a hallucination.)
  D. Does the answer reference anything that would be a SPOILER for chapters > current_chapter?

Output ONLY a JSON object:
  {"verdict": "PASS" | "FAIL", "issues": ["..."], "hint": "<one short sentence for the fixer, only if FAIL>"}

If the answer is a refusal (e.g. "I can't see beyond chapter N"), that's a PASS.
"""


# ---------------- Helper utilities ----------------

CITE_RE = re.compile(r"\[(\d+)\]")


def _safe_json(s: str) -> Optional[dict]:
    """Best-effort JSON parser — strips code fences and recovers from
    leading/trailing prose around an LLM-emitted JSON blob."""
    if not s:
        return None
    s = s.strip()
    # Strip ```json ... ``` fences
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)
    # Find first { ... matching brace } substring
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    for i, ch in enumerate(s[start:], start):
        if ch == "{": depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(s[start:i+1])
                except Exception:
                    return None
    return None


def _format_passages(tool_outputs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten tool outputs into a single numbered passage list for the synthesizer."""
    flat: List[Dict[str, Any]] = []
    for step in tool_outputs:
        out = step.get("output")
        if out is None:
            continue
        if isinstance(out, list):
            for item in out:
                flat.append({
                    "from_tool": step["meta"]["tool"],
                    "id": item.get("id"),
                    "chapter": item.get("chapter"),
                    "text": item.get("text") or "",
                })
        elif isinstance(out, dict):
            # summarize_chapter returns a single dict
            flat.append({
                "from_tool": step["meta"]["tool"],
                "id": f"chapter-{out.get('chapter')}",
                "chapter": out.get("chapter"),
                "text": out.get("text") or "",
            })
    # De-dupe by id, preserving order
    seen = set()
    deduped = []
    for p in flat:
        key = p.get("id")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)
    return deduped


def _format_passages_block(passages: List[Dict[str, Any]]) -> str:
    parts = []
    for i, p in enumerate(passages, 1):
        head = f"[{i}] (chapter {p.get('chapter')}, via {p.get('from_tool')})"
        body = (p.get("text") or "").strip()
        if len(body) > 1200:
            body = body[:1200] + "..."
        parts.append(f"{head}\n{body}")
    return "\n\n".join(parts)


# ---------------- Main agent loop ----------------

def run_agent(
    question: str,
    current_chapter: int,
    book_id: str,
    llm_call: Callable[[str, str], str],
    user_id: Optional[str] = None,
    turn_id: Optional[int] = None,
    memory_summary: Optional[str] = None,
    on_step: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Run the Planner-Executor-Critic loop.

    `llm_call(system, user)` is the LLM gateway — same callable used for
    planner, synthesizer, and critic. Pass whichever provider you want.

    Returns:
      {answer, plan, tool_calls, passages, critic, retried, latency_ms_per_stage}
    """

    def step(name: str, **payload):
        if on_step:
            on_step({"stage": name, **payload})

    timings: Dict[str, int] = {}

    # ---- 1. Planner ----
    t0 = time.time()
    step("planner", status="running", question=question)
    planner_user = f"Current chapter: {current_chapter}\nQuestion: {question}"
    planner_raw = llm_call(PLANNER_SYSTEM, planner_user)
    plan = _safe_json(planner_raw) or {
        "reasoning": "fallback: planner output unparseable, default to retrieve_passages",
        "steps": [{"tool": "retrieve_passages", "args": {"query": question, "k": 4}}],
    }
    if not isinstance(plan.get("steps"), list) or not plan["steps"]:
        plan["steps"] = [{"tool": "retrieve_passages", "args": {"query": question, "k": 4}}]
    timings["planner_ms"] = int((time.time() - t0) * 1000)
    step("planner", status="done", plan=plan, latency_ms=timings["planner_ms"])

    # ---- 2. Executor ----
    t0 = time.time()
    tool_outputs: List[Dict[str, Any]] = []
    for i, st in enumerate(plan["steps"][:3]):  # cap at 3 steps for safety
        tool_name = st.get("tool")
        args = dict(st.get("args") or {})
        # Inject context the planner shouldn't pass
        args["book_id"] = book_id
        args["chapter_limit"] = current_chapter
        step("executor", status="running", step_index=i, tool=tool_name, args=args)
        if tool_name not in TOOLS:
            tool_outputs.append({"output": None, "meta": {"tool": tool_name, "args": args, "error": "unknown_tool"}})
            step("executor", status="error", step_index=i, error="unknown_tool", tool=tool_name)
            continue
        tool_t0 = time.time()
        try:
            result = TOOLS[tool_name](**args)
        except TypeError as e:
            # Bad arg shape — try to recover by stripping unknown args
            result = {"output": None, "meta": {"tool": tool_name, "args": args, "error": f"bad_args:{e}"}}
        except Exception as e:
            result = {"output": None, "meta": {"tool": tool_name, "args": args, "error": str(e)}}
        tool_latency = int((time.time() - tool_t0) * 1000)
        result["meta"]["latency_ms"] = tool_latency
        tool_outputs.append(result)
        try:
            record_tool_call(
                turn_id=turn_id,
                step_index=i,
                tool_name=tool_name,
                args=args,
                meta=result.get("meta", {}),
                n_results=result.get("meta", {}).get("n_results"),
                latency_ms=tool_latency,
            )
        except Exception:
            pass
        step("executor", status="done", step_index=i, tool=tool_name,
             n_results=result.get("meta", {}).get("n_results"),
             latency_ms=tool_latency)
    timings["executor_ms"] = int((time.time() - t0) * 1000)

    passages = _format_passages(tool_outputs)
    if not passages:
        # Hard refusal — no evidence
        return {
            "answer": (
                f"The tools didn't surface any passages within chapter {current_chapter}. "
                "I can't speculate without grounded evidence — try rephrasing the question "
                "or pointing to a specific scene."
            ),
            "plan": plan,
            "tool_calls": tool_outputs,
            "passages": [],
            "critic": {"verdict": "PASS", "issues": ["no_passages_returned"]},
            "retried": False,
            "timings": timings,
        }

    # ---- 3. Synthesizer ----
    t0 = time.time()
    step("synthesizer", status="running")
    synth_user_parts = [f"Current chapter: {current_chapter}"]
    if memory_summary:
        synth_user_parts.append(f"Reader memory:\n{memory_summary}")
    synth_user_parts.append(f"Question: {question}")
    synth_user_parts.append(f"Passages:\n{_format_passages_block(passages)}")
    synth_user = "\n\n".join(synth_user_parts)
    answer = llm_call(SYNTHESIZER_SYSTEM, synth_user).strip()
    timings["synthesizer_ms"] = int((time.time() - t0) * 1000)
    step("synthesizer", status="done", latency_ms=timings["synthesizer_ms"])

    # ---- 4. Critic ----
    t0 = time.time()
    step("critic", status="running")
    critic_user = (
        f"Current chapter: {current_chapter}\nQuestion: {question}\n"
        f"Available passage indices: 1..{len(passages)}\n\n"
        f"Draft answer:\n{answer}\n\n"
        f"Passages:\n{_format_passages_block(passages)}"
    )
    critic_raw = llm_call(CRITIC_SYSTEM, critic_user)
    verdict = _safe_json(critic_raw) or {"verdict": "PASS", "issues": ["critic_unparseable"]}
    timings["critic_ms"] = int((time.time() - t0) * 1000)
    step("critic", status="done", verdict=verdict.get("verdict"), latency_ms=timings["critic_ms"])

    retried = False
    if verdict.get("verdict", "").upper() == "FAIL":
        retried = True
        hint = verdict.get("hint") or "Cite every claim. Don't reference future-chapter events."
        step("synthesizer", status="retrying", hint=hint)
        t0 = time.time()
        retry_user = synth_user + f"\n\nReviewer feedback: {hint}\nRewrite the answer."
        answer = llm_call(SYNTHESIZER_SYSTEM, retry_user).strip()
        timings["synthesizer_retry_ms"] = int((time.time() - t0) * 1000)
        step("synthesizer", status="done_retry", latency_ms=timings["synthesizer_retry_ms"])

    return {
        "answer": answer,
        "plan": plan,
        "tool_calls": [
            {
                "tool": tc["meta"].get("tool"),
                "args": tc["meta"].get("args"),
                "n_results": tc["meta"].get("n_results"),
                "latency_ms": tc["meta"].get("latency_ms"),
                "error": tc["meta"].get("error"),
            }
            for tc in tool_outputs
        ],
        "passages": [{"chapter": p["chapter"], "from_tool": p["from_tool"], "id": p["id"], "text": p["text"]} for p in passages],
        "critic": verdict,
        "retried": retried,
        "timings": timings,
    }
