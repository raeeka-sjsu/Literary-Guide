"""
Spoiler-boundary evaluation.

For each test case, retrieve top-k chunks at the given chapter limit and verify
that NO chunk has metadata.chapter > the limit. This is the foundational
correctness check for our spoiler safety guarantee.

Usage:
    python eval/run_spoiler_eval.py
"""

import json
import sys
from pathlib import Path

# Add scripts/ to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from rag_pipeline import build_collection, query_up_to_chapter  # noqa: E402


def main():
    cases_path = Path(__file__).resolve().parent / "spoiler_boundary_cases.json"
    with open(cases_path) as f:
        cases = json.load(f)

    print("Building Chroma collection...")
    build_collection()
    print(f"Running {len(cases)} spoiler-boundary cases.\n")

    passed = 0
    failed = []
    for case in cases:
        cid = case["id"]
        q = case["question"]
        limit = case["current_chapter"]
        chunks = query_up_to_chapter(q, chapter_limit=limit, top_k=4)

        violations = [c for c in chunks if int(c["metadata"].get("chapter", 0) or 0) > limit]
        ok = len(violations) == 0
        if ok:
            passed += 1
            print(f"  [PASS] {cid}: chapter<={limit}, retrieved={len(chunks)} chunks")
        else:
            failed.append((cid, violations))
            print(f"  [FAIL] {cid}: {len(violations)} chunks beyond chapter {limit}!")

    print(f"\n=== Results: {passed}/{len(cases)} passed ===")
    if failed:
        print("Failures:")
        for cid, vs in failed:
            for v in vs:
                print(f"  {cid}: chapter={v['metadata'].get('chapter')} doc='{v['document'][:80]}...'")
        sys.exit(1)


if __name__ == "__main__":
    main()
