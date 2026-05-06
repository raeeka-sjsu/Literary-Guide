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

# Capitalized multi-word proper nouns (e.g. "Mr. Bennet", "Glinda the Good Witch").
# Skip sentence-starting single-word capitals to keep false positives down.
PROPER_NOUN_RE = re.compile(
    r"\b("
    r"(?:Mr|Mrs|Ms|Miss|Dr|Lady|Lord|Captain|Sir|Aunt|Uncle)\.?\s+[A-Z][a-zA-Z]+"
    r"|(?:[A-Z][a-z]+(?:\s+(?:the\s+)?[A-Z][a-z]+)+)"
    r")\b"
)

# Function-words / titles / weekday-month words that shouldn't be flagged
COMMON_NON_NAMES = {
    "Chapter", "Chapter One", "Chapter Two",
    "I", "You", "We", "They", "He", "She", "It",
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
}


def grounded_names(answer: str, chunks):
    """Return (grounded_names, ungrounded_names).

    Extracts likely character names from the answer (multi-word capitalized
    spans + titled names like 'Mr. Bennet') and checks whether each appears
    in at least one retrieved chunk's text. Names absent from every chunk
    are evidence of training-data hallucination — the agent's critic uses
    this signal to force a rewrite.
    """
    if not answer:
        return [], []
    candidates = []
    seen = set()
    for m in PROPER_NOUN_RE.finditer(answer):
        name = m.group(1).strip()
        if name in COMMON_NON_NAMES:
            continue
        # Drop a leading honorific token for matching ("Mr. Bennet" → also try "Bennet")
        if name in seen:
            continue
        seen.add(name)
        candidates.append(name)

    chunk_text = "\n\n".join((c.get("document") or "") for c in (chunks or []))
    chunk_text_lower = chunk_text.lower()

    grounded, ungrounded = [], []
    for name in candidates:
        # Look for the full phrase OR the last token (e.g. "Bennet" inside "Mr. Bennet")
        last = name.split()[-1].lower()
        if name.lower() in chunk_text_lower or (len(last) > 3 and last in chunk_text_lower):
            grounded.append(name)
        else:
            ungrounded.append(name)
    return grounded, ungrounded


def check_answer(answer: str, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not answer:
        return {
            "ok": False,
            "has_citation": False,
            "valid_citations": [],
            "invalid_citations": [],
            "ungrounded_names": [],
            "issues": ["empty_answer"],
        }
    cited = sorted({int(m) for m in CITATION_RE.findall(answer)})
    available = set(range(1, len(chunks) + 1))
    valid = [c for c in cited if c in available]
    invalid = [c for c in cited if c not in available]
    grounded, ungrounded = grounded_names(answer, chunks)

    issues: List[str] = []
    if not cited:
        issues.append("no_citations")
    if invalid:
        issues.append(f"invalid_citations:{invalid}")
    if ungrounded:
        issues.append(f"ungrounded_names:{ungrounded}")

    return {
        "ok": bool(cited) and not invalid and not ungrounded,
        "has_citation": bool(cited),
        "valid_citations": valid,
        "invalid_citations": invalid,
        "grounded_names": grounded,
        "ungrounded_names": ungrounded,
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
