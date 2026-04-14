"""
Chapter-aware filter stub for BookSum data.

Filters BookSum samples to only include rows up to a given chapter,
enforcing the spoiler boundary.

Usage:
    python scripts/chapter_filter_stub.py --chapter 5

Output:
    outputs/booksum_filtered.json
"""

import argparse
import json
from pathlib import Path


def filter_by_chapter(samples: list[dict], max_chapter: int) -> list[dict]:
    """Return only rows where the chapter field is <= max_chapter."""
    filtered = []
    for row in samples:
        ch = row.get("chapter")
        if ch is None:
            continue
        # Chapter field may be a string like "5" or an int
        try:
            ch_num = int(ch)
        except (ValueError, TypeError):
            # Non-numeric chapter identifiers — include them for now
            filtered.append(row)
            continue
        if ch_num <= max_chapter:
            filtered.append(row)
    return filtered


def main():
    parser = argparse.ArgumentParser(description="Filter BookSum by chapter")
    parser.add_argument(
        "--chapter", type=int, required=True,
        help="Maximum chapter number to include (spoiler boundary)"
    )
    args = parser.parse_args()

    samples_path = Path(__file__).resolve().parent.parent / "outputs" / "booksum_samples.json"
    if not samples_path.exists():
        print(f"Error: {samples_path} not found. Run load_booksum_sample.py first.")
        return

    with open(samples_path) as f:
        samples = json.load(f)

    filtered = filter_by_chapter(samples, args.chapter)
    print(f"Filtered to {len(filtered)} rows (chapter <= {args.chapter})")

    out_path = samples_path.parent / "booksum_filtered.json"
    with open(out_path, "w") as f:
        json.dump(filtered, f, indent=2, default=str)

    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
