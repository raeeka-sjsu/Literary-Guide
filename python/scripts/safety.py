"""
Safety / grounding guardrails for Literary Guide answers.

Two checks run AFTER the LLM produces an answer:

1. Citation enforcement — does the answer include at least one [n] reference?
2. Grounding verification — for every cited passage [n], does the cited
   passage actually exist in the retrieved chunks? Bare existence isn't
   strong grounding, but it catches the common failure mode where models
   make up citation indices.

Returns a structured `SafetyReport` dict the caller can attach to the
response payload (and the eval can score against).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

CITATION_RE = re.compile(r"\[(\d+)\]")


def check_answer(answer: str, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not answer:
        return {
            "ok": False,
            "has_citation": False,
            "valid_citations": [],
            "invalid_citations": [],
            "issues": ["empty_answer"],
        }
    cited = sorted({int(m) for m in CITATION_RE.findall(answer)})
    available = set(range(1, len(chunks) + 1))
    valid = [c for c in cited if c in available]
    invalid = [c for c in cited if c not in available]
    issues: List[str] = []
    if not cited:
        issues.append("no_citations")
    if invalid:
        issues.append(f"invalid_citations:{invalid}")

    return {
        "ok": bool(cited) and not invalid,
        "has_citation": bool(cited),
        "valid_citations": valid,
        "invalid_citations": invalid,
        "issues": issues,
    }


def is_refusal(answer: str) -> bool:
    """Return True if the answer looks like a spoiler-refusal."""
    if not answer:
        return False
    a = answer.lower()
    refusal_phrases = [
        "i can't see beyond",
        "i cannot see beyond",
        "the passages do not",
        "passages don't",
        "haven't read that yet",
        "not yet visible",
        "cannot answer that yet",
        "would be a spoiler",
        "has not been mentioned",
        "is not mentioned",
        "are not mentioned",
        "have not yet",
        "no information",
        "passages don’t",
    ]
    return any(p in a for p in refusal_phrases)
