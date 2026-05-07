"""
Fetch NarrativeQA Q&A pairs and convert them into Literary Guide eval cases
for books that overlap with our Project Gutenberg library.

NarrativeQA contains ~46k human-written question/answer pairs over 1,572 stories
(from Gutenberg + movie scripts). We use the *gutenberg* subset and match by
Wikipedia title to our catalog.

Usage:
    python scripts/fetch_narrativeqa.py
    python scripts/fetch_narrativeqa.py --max-per-book 5

For each matched book we sample up to N questions and emit eval cases:
- The question
- Both human reference answers (we use the union of their key proper nouns
  as forbidden keywords for spoiler-traps, since human answers were written
  with full-book knowledge and may reveal late-book facts)
- Set current_chapter to a small early-book number (default 5) so the question
  acts as a spoiler-trap on average. The reader hasn't read that far yet.

Outputs: python/eval/narrativeqa_cases.json — append to eval_cases.json.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "data" / "catalog.json"
OUT_PATH = ROOT / "eval" / "narrativeqa_cases.json"

# Map our catalog ids -> case-insensitive Wikipedia title strings the
# NarrativeQA dataset uses. Some titles match across both BookSum and
# NarrativeQA, others differ slightly.
CATALOG_TO_NARRATIVEQA_TITLES: Dict[str, List[str]] = {
    "pride-and-prejudice": ["Pride and Prejudice"],
    "sense-and-sensibility": ["Sense and Sensibility"],
    "emma": ["Emma (novel)", "Emma"],
    "frankenstein": ["Frankenstein", "Frankenstein; or, The Modern Prometheus"],
    "dracula": ["Dracula"],
    "jane-eyre": ["Jane Eyre"],
    "wuthering-heights": ["Wuthering Heights"],
    "tale-of-two-cities": ["A Tale of Two Cities"],
    "great-expectations": ["Great Expectations"],
    "oliver-twist": ["Oliver Twist"],
    "moby-dick": ["Moby-Dick", "Moby Dick"],
    "scarlet-letter": ["The Scarlet Letter"],
    "huckleberry-finn": ["Adventures of Huckleberry Finn"],
    "tom-sawyer": ["The Adventures of Tom Sawyer"],
    "treasure-island": ["Treasure Island"],
    "jekyll-and-hyde": ["Strange Case of Dr Jekyll and Mr Hyde",
                         "The Strange Case of Dr. Jekyll and Mr. Hyde"],
    "20000-leagues": ["Twenty Thousand Leagues Under the Sea"],
    "around-the-world-80": ["Around the World in Eighty Days"],
    "last-of-mohicans": ["The Last of the Mohicans"],
    "crime-and-punishment": ["Crime and Punishment"],
    "anna-karenina": ["Anna Karenina"],
    "war-and-peace": ["War and Peace"],
    "picture-of-dorian-gray": ["The Picture of Dorian Gray"],
    "importance-of-being-earnest": ["The Importance of Being Earnest"],
    "heart-of-darkness": ["Heart of Darkness"],
    "age-of-innocence": ["The Age of Innocence"],
    "house-of-mirth": ["The House of Mirth"],
    "secret-garden": ["The Secret Garden"],
    "alice-in-wonderland": ["Alice's Adventures in Wonderland"],
    "wizard-of-oz": ["The Wonderful Wizard of Oz"],
    "little-women": ["Little Women"],
    "sherlock-adventures": ["The Adventures of Sherlock Holmes"],
    "time-machine": ["The Time Machine"],
    "war-of-the-worlds": ["The War of the Worlds"],
    "three-musketeers":   ["The Three Musketeers"],
    "persuasion":         ["Persuasion (novel)", "Persuasion"],
    "mansfield-park":     ["Mansfield Park"],
    "tess-durbervilles":  ["Tess of the d'Urbervilles", "Tess of the d'Urbervilles: A Pure Woman Faithfully Presented"],
    "brothers-karamazov": ["The Brothers Karamazov"],
    "madame-bovary":      ["Madame Bovary"],
    "robinson-crusoe":    ["Robinson Crusoe", "The Life and Adventures of Robinson Crusoe"],
    "northanger-abbey":   ["Northanger Abbey"],
    "hound-baskervilles": ["The Hound of the Baskervilles"],
    "phantom-opera":      ["The Phantom of the Opera"],
    "jungle-book":        ["The Jungle Book"],
    "anne-green-gables":  ["Anne of Green Gables"],
    "prince-pauper":      ["The Prince and the Pauper"],
    "don-quixote":        ["Don Quixote", "The Ingenious Gentleman Don Quixote of La Mancha"],
    "gullivers-travels":  ["Gulliver's Travels", "Travels into Several Remote Nations of the World"],
    "hunchback-notre-dame": ["Notre-Dame de Paris", "The Hunchback of Notre-Dame", "The Hunchback of Notre Dame"],
    "count-monte-cristo": ["The Count of Monte Cristo"],
    "les-miserables":     ["Les Misérables", "Les Miserables"],
}


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().strip())


def build_title_index() -> Dict[str, str]:
    """Return {normalized_title: catalog_id}."""
    out = {}
    for cat_id, titles in CATALOG_TO_NARRATIVEQA_TITLES.items():
        for t in titles:
            out[normalize(t)] = cat_id
    return out


# Extract proper-noun "spoiler hints" from a reference answer. Used as
# forbidden_keywords for the eval — if the model's answer contains any of
# these names, that's likely a spoiler leak, since the reference answer
# was written by a human who'd read the whole book.
PROPER_NOUN_RE = re.compile(
    r"\b("
    r"(?:Mr|Mrs|Ms|Dr|Lady|Lord|Captain|Sir|Aunt|Uncle)\.?\s+[A-Z][a-zA-Z]+"
    r"|(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"
    r")\b"
)
COMMON_FALSE_POSITIVES = {
    "Mr.", "Mrs.", "Dr.", "Sir", "Madame",
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "Heaven", "Earth", "God", "Lord",
    "London", "Paris", "America", "England", "France",
}


def extract_spoiler_keywords(text: str, max_n: int = 5) -> List[str]:
    if not text:
        return []
    seen = set()
    keywords = []
    for m in PROPER_NOUN_RE.finditer(text):
        name = m.group(1).strip()
        if name in COMMON_FALSE_POSITIVES:
            continue
        if name in seen:
            continue
        seen.add(name)
        keywords.append(name)
        if len(keywords) >= max_n:
            break
    return keywords


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-per-book", type=int, default=3,
                    help="Number of NarrativeQA questions to emit per matched book")
    ap.add_argument("--current-chapter", type=int, default=5,
                    help="Spoiler boundary chapter for emitted cases (default 5)")
    args = ap.parse_args()

    print("Loading NarrativeQA dataset (all splits)...")
    from datasets import load_dataset

    title_to_cat = build_title_index()

    # Collect candidates per catalog book
    by_book: Dict[str, List[dict]] = defaultdict(list)
    n_seen = 0
    n_kept = 0
    for split in ("train", "validation", "test"):
        try:
            ds = load_dataset("deepmind/narrativeqa", split=split, streaming=True)
        except Exception as e:
            print(f"  could not load split={split}: {e}")
            continue
        for row in ds:
            n_seen += 1
            # NarrativeQA's row has nested document.summary or document.kind etc.
            # Title field is at row['document']['summary']['title'] in the modern dataset,
            # or at the top level in the older one. Try both.
            doc = row.get("document") or {}
            title = (doc.get("summary") or {}).get("title") if isinstance(doc, dict) else None
            if not title:
                title = doc.get("wiki_title") if isinstance(doc, dict) else None
            if not title:
                title = row.get("wiki_title")
            if not title:
                continue
            norm = normalize(title)
            cat_id = title_to_cat.get(norm)
            if not cat_id:
                continue
            n_kept += 1
            question = (row.get("question") or {}).get("text") or row.get("question_text")
            answers_field = row.get("answers")
            if isinstance(answers_field, list):
                answer_texts = [a.get("text") if isinstance(a, dict) else str(a) for a in answers_field]
            else:
                # Older format
                answer_texts = [
                    row.get("answer1") or "",
                    row.get("answer2") or "",
                ]
            answer_texts = [a for a in answer_texts if a]
            if not question or not answer_texts:
                continue
            if len(by_book[cat_id]) >= args.max_per_book:
                continue
            by_book[cat_id].append({
                "question": question,
                "answers": answer_texts,
                "title": title,
            })

    print(f"\nScanned {n_seen:,} NarrativeQA rows; {n_kept:,} matched our catalog.")

    # Convert into eval cases
    cases = []
    for cat_id, qas in sorted(by_book.items()):
        for i, qa in enumerate(qas):
            joined_answers = " || ".join(qa["answers"])
            forbidden = extract_spoiler_keywords(joined_answers, max_n=5)
            case = {
                "id": f"nq-{cat_id}-{i + 1}",
                "category": "spoiler_trap",
                "book_id": cat_id,
                "current_chapter": args.current_chapter,
                "question": qa["question"],
                "forbidden_keywords": forbidden,
                "source": "narrativeqa",
                "reference_answers": qa["answers"][:2],
            }
            cases.append(case)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(cases, f, indent=2)

    print(f"\nWrote {len(cases)} cases across {len(by_book)} books to {OUT_PATH}")
    print("\nSample cases:")
    for c in cases[:3]:
        print(f"  - [{c['id']}] {c['question'][:80]}")
        print(f"    forbidden: {c['forbidden_keywords']}")


if __name__ == "__main__":
    main()
