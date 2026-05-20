"""
Build a deep, per-book character index — Kindle X-Ray–style, automated.

Each book becomes a JSON file at python/data/characters/<book_id>.json with
this shape:

    [
      {
        "canonical_name": "Mr. Bennet",
        "aliases": ["Mr Bennet", "Bennet"],
        "first_chapter": 1,
        "total_mentions": 89,
        "per_chapter": {
          "1": {"mentions": 12, "snippet": "One example sentence..."},
          "2": {"mentions": 8,  "snippet": "..."}
        },
        "co_occurs_with": {"Mrs. Bennet": 45, "Elizabeth": 30, ...}
      },
      ...
    ]

Process per book:
  1. Scan every chapter, extract character-name candidates from three patterns:
       a) titled (Mr./Mrs./Dr./etc.) — strongest signal
       b) multi-cap spans ("Dorothy Gale")
       c) frequent single-cap names that aren't sentence-initial
  2. Merge aliases: a single-cap name that matches a token of a multi-cap
     name in the same book → gets folded into the longer canonical form.
  3. For each (character, chapter) pair, capture a "best snippet": one
     short sentence from that chapter where the character is mentioned.
     Used in the UI / agent answers so "Dorothy" comes with the actual
     line introducing her.
  4. Compute co-occurrence: for each chapter, every pair of characters
     mentioned in the same chapter increments their pair count.
  5. Drop low-value entries (mentioned <3 times, generic words).

Output is sorted by total_mentions descending so list_known_characters
returns the most prominent characters first.

Usage:
    python scripts/build_character_index.py            # all books
    python scripts/build_character_index.py --only wizard-of-oz
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional

ROOT = Path(__file__).resolve().parent.parent
BOOKS_DIR = ROOT / "data" / "books"
CHARS_DIR = ROOT / "data" / "characters"


# ---------------- Patterns ----------------

TITLED_RE = re.compile(
    r"\b("
    r"(?:Mr|Mrs|Ms|Miss|Dr|Lady|Lord|Captain|Major|Colonel|Lieutenant|Sir|Aunt|Uncle|"
    r"Brother|Sister|Father|Mother|Madame|Monsieur|Mademoiselle|Don|Senor|Reverend|"
    r"Professor|Master|Maid)"
    r"\.?\s+"
    r"([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)"
    r")\b"
)

MULTI_CAP_RE = re.compile(
    # Use [ \t] (no newlines) between tokens so we don't accidentally bridge a
    # chapter heading to the next paragraph's first sentence (Wizard of Oz had
    # 'Tin Woodman' + blank lines + 'When Dorothy' getting concatenated).
    r"\b([A-Z][a-z]+(?:[ \t]+(?:de|van|von|le|la|du|the)?[ \t]*[A-Z][a-z]+){1,3})\b"
)

SINGLE_CAP_RE = re.compile(r"(?<![A-Za-z])([A-Z][a-z]{2,})\b")
SENTENCE_INITIAL_RE = re.compile(r"(?:^|[.!?]\s+)([A-Z][a-z]{2,})\b")

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'])")


COMMON_NON_NAMES = {
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "Christmas", "Easter", "Sabbath",
    "Heaven", "Earth", "Hell", "God", "Lord", "Almighty", "Providence", "Nature",
    "Truth", "Death", "Hope", "Fate", "Love", "Time",
    "Chapter", "Book", "Volume", "Letter", "Part", "Preface",
    "Illustration", "Contents", "Introduction",
    "Yes", "No", "Why", "What", "When", "Where", "Who", "How", "If",
    "And", "But", "For", "Now", "Then", "Thus", "Yet", "So", "As",
    "I", "You", "We", "They", "He", "She", "It", "Me",
    "Their", "Our", "Your", "His", "Her", "My", "His",
    "Mr.", "Mrs.", "Ms.", "Sir", "Madam", "Mister",
    "Mr", "Mrs", "Ms",  # bare honorifics without surname
    "Well", "That", "This", "Says", "Told", "Asked",  # dialogue artifacts
    "Sure", "Just", "Like", "Even", "Way", "Way Back",
    "Project", "Gutenberg", "Author", "English",
    "London", "Paris", "America", "England", "France", "Europe",
    "American", "French", "British", "Italian", "German", "Russian",
    "Christian", "Christianity",
    # Common one-word place/people artifacts that survived earlier filters
    "Indian",
}
LOWERED_BLOCKLIST = {n.lower() for n in COMMON_NON_NAMES}

# Words that commonly start a sentence and would create false-positive
# multi-cap matches like "When Dorothy" or "Suddenly Uncle Henry".
# If a multi-cap candidate's FIRST token is in this set, drop the match.
SENTENCE_STARTERS = {
    "When", "While", "Where", "Why", "What", "Who", "Whom", "Whose", "Which", "How",
    "If", "Although", "Though", "Because", "Since", "Unless", "Until", "Before", "After",
    "As", "Once", "Soon", "Often", "Sometimes", "Always", "Never", "Suddenly", "Then",
    "Now", "Indeed", "Therefore", "However", "Moreover", "Furthermore", "Hence",
    "But", "And", "So", "Yet", "Thus", "Still", "Even", "Just", "Quite", "Very",
    "Many", "Much", "Some", "Any", "All", "Most", "Each", "Every", "Both", "Either",
    "I", "We", "You", "They", "He", "She", "It", "His", "Her", "My", "Our", "Their",
    "This", "That", "These", "Those", "Such", "There", "Here",
    "He", "Last", "Next", "First", "Second", "Once",
    "Looking", "Seeing", "Hearing", "Feeling",
    "Yes", "No", "Oh", "Ah", "Well",
    "Saved", "Saw", "Said", "Heard", "Felt", "Took", "Gave", "Made", "Found",
    "Among", "Above", "Below", "Beyond", "Across", "Inside", "Outside",
}

# Verbs/words that often appear in chapter sub-titles like "How Dorothy SAVED
# the Scarecrow" and would be falsely matched as part of a multi-cap name.
TITLE_VERBS = {
    "Saved", "Met", "Lost", "Found", "Killed", "Visited", "Returned", "Escaped",
    "Discovered", "Crossed", "Reached", "Climbed", "Sailed", "Sailed", "Faced",
}


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip(" .,;:!?")


def looks_like_name(name: str) -> bool:
    n = name.strip()
    if not n or len(n) < 3:
        return False
    if n.lower() in LOWERED_BLOCKLIST:
        return False
    if n.isupper():
        return False
    return True


def find_mentions(text: str) -> Dict[str, List[Tuple[int, int]]]:
    """Return {name: [(start, end), ...]} for all candidate names in text."""
    spans: Dict[str, List[Tuple[int, int]]] = defaultdict(list)

    # Titled — index both the full "Mr. Bennet" and the surname alone
    for m in TITLED_RE.finditer(text):
        full = normalize_name(m.group(1))
        if looks_like_name(full):
            spans[full].append(m.span())
        sur = normalize_name(m.group(2))
        if looks_like_name(sur):
            # Index surname using its OWN span (just the surname part)
            sur_start = m.start() + (m.group(0).find(m.group(2)))
            spans[sur].append((sur_start, sur_start + len(m.group(2))))

    # Multi-cap
    for m in MULTI_CAP_RE.finditer(text):
        name = normalize_name(m.group(1))
        if not looks_like_name(name):
            continue
        tokens = name.split()
        # Drop matches where the first token is a known sentence-starter
        if tokens and tokens[0] in SENTENCE_STARTERS:
            continue
        # Adverbs ending in "-ly" almost always start a sentence ("Sorrowfully Dorothy")
        if tokens and tokens[0].endswith("ly") and len(tokens[0]) > 4:
            continue
        # Drop matches that contain a chapter-sub-title verb
        if any(tok in TITLE_VERBS for tok in tokens):
            continue
        # Sentence-initial test: look at what precedes the match
        before = text[max(0, m.start() - 4):m.start()]
        prev_non_space = before.rstrip()
        if not prev_non_space or prev_non_space[-1] in '.!?"\'':
            # First token IS sentence-initial — drop the match's first token
            # since it's likely a generic word capitalized at sentence start
            if len(tokens) >= 3:
                # We can salvage the rest as a multi-cap name
                salvaged = " ".join(tokens[1:])
                if salvaged.split() and salvaged.split()[0] not in SENTENCE_STARTERS:
                    salvaged_start = m.start() + len(tokens[0]) + 1
                    spans[salvaged].append((salvaged_start, m.end()))
            continue
        # Drop matches that occur right after a newline (likely a sub-title line)
        line_start = text.rfind("\n", 0, m.start())
        if m.start() - line_start <= 3:
            line_end = text.find("\n", m.start())
            if line_end < 0:
                line_end = len(text)
            line = text[line_start:line_end].strip()
            if len(line) < 80 and len(line.split()) >= 3:
                title_caps = sum(1 for w in line.split() if w[:1].isupper())
                if title_caps / max(1, len(line.split())) >= 0.6:
                    continue
        spans[name].append(m.span())

    # Single-cap — only kept if frequent + not predominantly sentence-initial
    single_total: Counter = Counter()
    single_initial: Counter = Counter()
    single_spans: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
    for m in SINGLE_CAP_RE.finditer(text):
        w = m.group(1)
        if not looks_like_name(w):
            continue
        single_total[w] += 1
        single_spans[w].append(m.span())
    for m in SENTENCE_INITIAL_RE.finditer(text):
        single_initial[m.group(1)] += 1

    for w, total in single_total.items():
        # If already covered as part of a multi-cap entry, skip
        if any(w in k.split() for k in spans):
            continue
        # Never accept a word in SENTENCE_STARTERS as a single-cap name.
        # These (e.g. "There", "When", "Suddenly") appear capitalized
        # often enough to clear the initial-position ratio test, but they
        # are never actual character names.
        if w in SENTENCE_STARTERS:
            continue
        initial = single_initial.get(w, 0)
        # Tightened: require at least 70% non-sentence-initial usage
        # (was 50%), since the looser threshold let "There" slip through
        # in books with frequent narrator-voice paragraphs starting
        # mid-sentence after dialogue dashes.
        if total >= 3 and (total - initial) / total >= 0.7:
            spans[w] = single_spans[w]

    return spans


def best_snippet(text: str, spans: List[Tuple[int, int]], max_len: int = 220) -> Optional[str]:
    """Find a short, well-formed sentence containing one of the mention spans."""
    if not spans:
        return None
    # Pick the EARLIEST mention so we capture the introduction
    span_start, _ = min(spans, key=lambda s: s[0])
    # Walk back to start of the containing sentence
    start = span_start
    while start > 0 and text[start - 1] not in ".!?\n":
        start -= 1
    # Walk forward to end of sentence
    end = span_start
    while end < len(text) and text[end] not in ".!?\n":
        end += 1
    if end < len(text):
        end += 1
    snippet = text[start:end].strip()
    snippet = re.sub(r"\s+", " ", snippet)
    if len(snippet) > max_len:
        snippet = snippet[:max_len].rsplit(" ", 1)[0] + "…"
    return snippet or None


def merge_aliases(per_chapter: Dict[str, Dict[int, dict]]) -> Tuple[
        Dict[str, Dict[int, dict]], Dict[str, str]]:
    """Fold short names into their longer canonical form when the longer form
    is more frequent. If a single-token name has VASTLY more mentions than
    a multi-word match it appears in (>2x), the single token is canonical
    instead — this catches parser artifacts like 'Head Dorothy' where 'Head'
    is a noun, not a name modifier."""
    # Pre-compute per-name total mention count
    counts = {n: sum(info["mentions"] for info in chs.values())
              for n, chs in per_chapter.items()}

    name_to_canon: Dict[str, str] = {}
    # Process by total mention count (most-mentioned wins as canonical for ties)
    sorted_names = sorted(per_chapter.keys(),
                          key=lambda n: (-counts[n], -len(n.split())))
    for name in sorted_names:
        if name in name_to_canon:
            continue
        name_to_canon[name] = name
        tokens = name.split()
        if len(tokens) >= 2:
            # Look for short aliases that match a token of this multi-word name
            token_set = set(tokens)
            for shorter in per_chapter:
                if shorter == name or shorter in name_to_canon:
                    continue
                if len(shorter.split()) != 1 or shorter not in token_set:
                    continue
                # Only fold if the multi-word is at least roughly as common
                # as the single. If the single name has 2x+ the mentions,
                # it's clearly the canonical reference.
                if counts[shorter] > 2 * counts[name]:
                    continue
                name_to_canon[shorter] = name

    # Build canonical index by merging
    canonical: Dict[str, Dict[int, dict]] = defaultdict(lambda: defaultdict(
        lambda: {"mentions": 0, "snippet": None}
    ))
    for name, per_ch in per_chapter.items():
        canon = name_to_canon.get(name, name)
        for ch, info in per_ch.items():
            target = canonical[canon][ch]
            target["mentions"] = target["mentions"] + info["mentions"]
            # Prefer a snippet from the canonical name's own occurrences,
            # else accept the alias's snippet
            if not target["snippet"] or canon == name:
                if info.get("snippet") and (canon == name or not target["snippet"]):
                    target["snippet"] = info["snippet"]

    # Convert nested defaultdicts to plain dicts
    canonical_plain = {
        k: {int(ch): dict(v) for ch, v in chs.items()}
        for k, chs in canonical.items()
    }
    return canonical_plain, name_to_canon


def collect_aliases(name_to_canon: Dict[str, str]) -> Dict[str, List[str]]:
    aliases: Dict[str, Set[str]] = defaultdict(set)
    for name, canon in name_to_canon.items():
        if name != canon:
            aliases[canon].add(name)
    return {k: sorted(v) for k, v in aliases.items()}


def compute_cooccurrence(
    per_chapter: Dict[str, Dict[int, dict]],
) -> Dict[str, Dict[str, int]]:
    """For each pair of characters, count how many chapters they share."""
    chapter_to_chars: Dict[int, Set[str]] = defaultdict(set)
    for name, chs in per_chapter.items():
        for ch in chs:
            chapter_to_chars[int(ch)].add(name)
    co: Dict[str, Counter] = defaultdict(Counter)
    for ch, chars in chapter_to_chars.items():
        chars_list = sorted(chars)
        for i, a in enumerate(chars_list):
            for b in chars_list[i + 1:]:
                co[a][b] += 1
                co[b][a] += 1
    return {k: dict(v.most_common(8)) for k, v in co.items()}


def looks_like_toc_or_frontmatter(text: str, title: str) -> bool:
    """Detect chapters that are actually table-of-contents, dedications,
    title pages, or other Gutenberg front matter that the chapter parser
    misclassified as content. We must skip these before extraction so we
    don't leak character names from later-chapter titles."""
    if not text:
        return True
    if len(text) < 600:
        return True
    # Count chapter-heading-like lines — TOCs have many of these in close range
    chapter_line_re = re.compile(r"(?im)^\s*chapter\s+[ivxlcdm\d]", re.MULTILINE)
    chapter_lines = chapter_line_re.findall(text)
    # If the FIRST 2000 chars contain 5+ chapter listings, this is a TOC
    if len(chapter_line_re.findall(text[:2000])) >= 5:
        return True
    # "Contents" header followed soon by chapter listings
    if re.search(r"^\s*Contents\s*$", text[:800], re.IGNORECASE | re.MULTILINE):
        return True
    return False


def strip_chapter_subtitle(text: str) -> str:
    """Many Gutenberg chapters have a sub-title on the first line of body text
    (e.g. 'How Dorothy Saved the Scarecrow' starting Wizard of Oz chapter 3).
    These leak character names from chapter HEADINGS into our extraction.
    We strip leading lines that look title-y: short, multi-word, no
    sentence punctuation, predominantly capitalized."""
    lines = text.split("\n")
    drop = 0
    for line in lines[:8]:  # only check up to first 8 lines
        stripped = line.strip()
        if not stripped:
            drop += 1
            continue
        # Stop at the first line that looks like prose
        words = stripped.split()
        if len(words) >= 2 and len(stripped) < 90:
            ends_punct = stripped[-1] in '.!?"\'’'
            cap_ratio = sum(1 for w in words if w[:1].isupper()) / len(words)
            if not ends_punct and cap_ratio >= 0.5:
                drop += 1
                continue
        # Bracketed Illustration markers Gutenberg sometimes inserts
        if stripped.startswith("[") and stripped.endswith("]"):
            drop += 1
            continue
        break
    return "\n".join(lines[drop:])


def build_for_book(book_id: str) -> List[dict]:
    book_path = BOOKS_DIR / f"{book_id}.json"
    if not book_path.exists():
        raise FileNotFoundError(book_path)
    with open(book_path) as f:
        book = json.load(f)

    # Use the canonical title-derived chapter number so the spoiler filter
    # matches what the UI displays.
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from chapter_numbering import parse_chapter_number

    per_chapter: Dict[str, Dict[int, dict]] = defaultdict(dict)

    is_single_chapter_book = len(book["chapters"]) == 1

    # When two chapters map to the same canonical number (Gutenberg TOC vs real
    # chapter), keep the LONGER one — the real chapter has substantially more
    # text than the TOC entry.
    canon_to_best_idx: Dict[int, int] = {}
    canon_for: Dict[int, Optional[int]] = {}
    for i, ch in enumerate(book["chapters"]):
        c = parse_chapter_number(ch.get("title") or "")
        if c is None:
            if is_single_chapter_book:
                c = 1
            else:
                canon_for[i] = None
                continue
        canon_for[i] = c
        prev = canon_to_best_idx.get(c)
        if prev is None or len(book["chapters"][prev].get("text") or "") < len(ch.get("text") or ""):
            canon_to_best_idx[c] = i
    keep_indices = set(canon_to_best_idx.values())

    for i, ch in enumerate(book["chapters"]):
        if i not in keep_indices:
            continue
        title = ch.get("title") or ""
        ch_num = canon_for[i]
        text = ch.get("text") or ""
        if not text:
            continue
        # Skip front-matter / table-of-contents detection (only when there are
        # multiple chapters — single-chapter books bypass this since the
        # whole book IS the chapter).
        if not is_single_chapter_book and looks_like_toc_or_frontmatter(text, title):
            continue
        # Strip the chapter sub-title line(s) before extraction
        text = strip_chapter_subtitle(text)
        spans_by_name = find_mentions(text)
        for name, spans in spans_by_name.items():
            snippet = best_snippet(text, spans)
            per_chapter[name][ch_num] = {
                "mentions": len(spans),
                "snippet": snippet,
            }

    # Merge aliases
    canonical, name_to_canon = merge_aliases(per_chapter)
    aliases = collect_aliases(name_to_canon)
    cooccurrence = compute_cooccurrence(canonical)

    out: List[dict] = []
    for canon_name, chs in canonical.items():
        total = sum(info["mentions"] for info in chs.values())
        if total < 3:
            continue
        first_chapter = min(chs.keys())
        out.append({
            "canonical_name": canon_name,
            "aliases": aliases.get(canon_name, []),
            "first_chapter": first_chapter,
            "total_mentions": total,
            "per_chapter": {str(k): v for k, v in sorted(chs.items())},
            "co_occurs_with": cooccurrence.get(canon_name, {}),
        })

    out.sort(key=lambda x: -x["total_mentions"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated book ids; default = all")
    args = ap.parse_args()

    CHARS_DIR.mkdir(parents=True, exist_ok=True)
    if args.only:
        books = [b.strip() for b in args.only.split(",")]
    else:
        books = sorted(p.stem for p in BOOKS_DIR.glob("*.json"))

    print(f"Building character index for {len(books)} book(s)...\n")
    for bid in books:
        try:
            entries = build_for_book(bid)
        except Exception as e:
            print(f"  {bid:30s} FAILED ({e})")
            continue
        out_path = CHARS_DIR / f"{bid}.json"
        with open(out_path, "w") as f:
            json.dump(entries, f, indent=2)
        top = ", ".join(e["canonical_name"] for e in entries[:6])
        print(f"  {bid:30s} {len(entries):3d} characters · top: {top}")


if __name__ == "__main__":
    main()
