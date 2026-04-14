"""
Load the BookSum dataset from Hugging Face and save sample rows.

Usage:
    python scripts/load_booksum_sample.py

Output:
    outputs/booksum_samples.json  — 3 sample rows from the train split
"""

import json
import os
from pathlib import Path

from datasets import load_dataset


def main():
    print("Loading BookSum dataset (kmfoda/booksum) ...")
    ds = load_dataset("kmfoda/booksum", split="train", streaming=True)

    # Print column names
    print("\nDataset columns:")
    sample_iter = iter(ds)
    first = next(sample_iter)
    for col in sorted(first.keys()):
        print(f"  - {col}")

    # Collect 3 sample rows
    samples = [first]
    for _, row in zip(range(2), sample_iter):
        samples.append(row)

    print(f"\nCollected {len(samples)} sample rows.")

    # Save to outputs/
    out_dir = Path(__file__).resolve().parent.parent / "outputs"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "booksum_samples.json"

    with open(out_path, "w") as f:
        json.dump(samples, f, indent=2, default=str)

    print(f"Saved samples to {out_path}")


if __name__ == "__main__":
    main()
