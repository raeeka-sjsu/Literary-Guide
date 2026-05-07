"""
Fetch BookSum entries for the books in our Project Gutenberg catalog.

BookSum is keyed by book title (e.g. "Pride and Prejudice.chapter 1"). We
match BookSum's title prefixes to our catalog ids, save per-book entries
to python/data/booksum/<book_id>.json, then book_index.py builds a separate
"expert analysis" Chroma collection per book on demand.

Usage:
    python scripts/fetch_booksum.py
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from datasets import load_dataset

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "data" / "catalog.json"
BOOKSUM_DIR = ROOT / "data" / "booksum"

# Map our catalog ids -> list of BookSum title prefixes (case-insensitive).
# BookSum's book_id field looks like:
#   "Pride and Prejudice.chapter 1"
#   "The Last of the Mohicans.chapters 13-14"
# So we match by lowercasing both sides and checking prefix.
TITLE_TO_CATALOG = {
    "pride and prejudice":                                  "pride-and-prejudice",
    "sense and sensibility":                                "sense-and-sensibility",
    "emma":                                                  "emma",
    "frankenstein; or, the modern prometheus":              "frankenstein",
    "frankenstein":                                          "frankenstein",
    "dracula":                                               "dracula",
    "jane eyre":                                             "jane-eyre",
    "wuthering heights":                                     "wuthering-heights",
    "a tale of two cities":                                  "tale-of-two-cities",
    "great expectations":                                    "great-expectations",
    "oliver twist":                                          "oliver-twist",
    "moby dick":                                             "moby-dick",
    "moby-dick":                                             "moby-dick",
    "the scarlet letter":                                    "scarlet-letter",
    "adventures of huckleberry finn":                        "huckleberry-finn",
    "huckleberry finn":                                      "huckleberry-finn",
    "the adventures of tom sawyer":                          "tom-sawyer",
    "tom sawyer":                                            "tom-sawyer",
    "treasure island":                                       "treasure-island",
    "the strange case of dr jekyll and mr hyde":            "jekyll-and-hyde",
    "jekyll and hyde":                                       "jekyll-and-hyde",
    "twenty thousand leagues under the sea":                "20000-leagues",
    "around the world in eighty days":                       "around-the-world-80",
    "the last of the mohicans":                              "last-of-mohicans",
    "crime and punishment":                                  "crime-and-punishment",
    "anna karenina":                                         "anna-karenina",
    "war and peace":                                         "war-and-peace",
    "the picture of dorian gray":                            "picture-of-dorian-gray",
    "the importance of being earnest":                       "importance-of-being-earnest",
    "heart of darkness":                                     "heart-of-darkness",
    "the age of innocence":                                  "age-of-innocence",
    "the house of mirth":                                    "house-of-mirth",
    "the secret garden":                                     "secret-garden",
    "alice's adventures in wonderland":                      "alice-in-wonderland",
    "alice in wonderland":                                   "alice-in-wonderland",
    "the wonderful wizard of oz":                            "wizard-of-oz",
    "wizard of oz":                                          "wizard-of-oz",
    "little women":                                          "little-women",
    "the adventures of sherlock holmes":                     "sherlock-adventures",
    "the time machine":                                      "time-machine",
    "the war of the worlds":                                 "war-of-the-worlds",
    "the three musketeers":                                  "three-musketeers",
    "persuasion":                                            "persuasion",
    "mansfield park":                                        "mansfield-park",
    "tess of the d'urbervilles":                             "tess-durbervilles",
    "the brothers karamazov":                                "brothers-karamazov",
    "madame bovary":                                         "madame-bovary",
    "robinson crusoe":                                       "robinson-crusoe",
    "northanger abbey":                                      "northanger-abbey",
    "the hound of the baskervilles":                         "hound-baskervilles",
    "the phantom of the opera":                              "phantom-opera",
    "the jungle book":                                       "jungle-book",
    "anne of green gables":                                  "anne-green-gables",
    "the prince and the pauper":                             "prince-pauper",
    "don quixote":                                           "don-quixote",
    "the ingenious gentleman don quixote of la mancha":      "don-quixote",
    "gulliver's travels":                                    "gullivers-travels",
    "the hunchback of notre dame":                           "hunchback-notre-dame",
    "notre-dame de paris":                                   "hunchback-notre-dame",
    "the count of monte cristo":                             "count-monte-cristo",
    "les misérables":                                        "les-miserables",
    "les miserables":                                        "les-miserables",
}


def normalize_title(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().strip().rstrip("."))


def title_part(book_id: str) -> str:
    """BookSum's book_id has form 'Title.chapter X' — extract the title part."""
    return book_id.split(".")[0] if "." in book_id else book_id


def main():
    BOOKSUM_DIR.mkdir(parents=True, exist_ok=True)
    print("Loading BookSum dataset (kmfoda/booksum) — train + test + validation splits...")

    grouped: Dict[str, List[dict]] = defaultdict(list)
    n_total = 0
    n_matched = 0

    for split in ("train", "test", "validation"):
        try:
            ds = load_dataset("kmfoda/booksum", split=split, streaming=True)
        except Exception as e:
            print(f"  could not load split={split}: {e}")
            continue
        for row in ds:
            n_total += 1
            title = normalize_title(title_part(row.get("book_id") or ""))
            cat_id = TITLE_TO_CATALOG.get(title)
            if not cat_id:
                continue
            n_matched += 1
            # Keep only fields we actually need
            grouped[cat_id].append({
                "summary_id": row.get("summary_id"),
                "book_id": row.get("book_id"),
                "chapter": row.get("chapter"),
                "summary_path": row.get("summary_path"),
                "source": row.get("source"),
                "summary_text": row.get("summary_text"),
                "summary_analysis": row.get("summary_analysis"),
                "summary_url": row.get("summary_url"),
            })

    print(f"\nScanned {n_total:,} BookSum rows; matched {n_matched:,} to our catalog.")
    print(f"\nWriting {len(grouped)} per-book files to {BOOKSUM_DIR}:")
    for cat_id, rows in sorted(grouped.items()):
        out_path = BOOKSUM_DIR / f"{cat_id}.json"
        with open(out_path, "w") as f:
            json.dump(rows, f, indent=2, default=str)
        print(f"  {cat_id:30s} {len(rows):4d} entries")


if __name__ == "__main__":
    main()
