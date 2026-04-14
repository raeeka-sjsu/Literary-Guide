"""
Unit-ish tests for spoiler boundary using unittest assertions.

This file imports query_up_to_chapter from rag_pipeline.py and runs 10
checks (2 queries per chapter limit) verifying that no returned chunk
has metadata.chapter > chapter_limit. It prints PASS/FAIL per test and a
final summary X/10 passed.

Run:
    python scripts/tests/test_spoiler_boundary.py
"""

from __future__ import annotations

import sys
from typing import List, Tuple
import unittest

from pathlib import Path

# Make sure imports work when executed from repository root
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.rag_pipeline import query_up_to_chapter


class SpoilerBoundary(unittest.TestCase):
    def assert_results_within_limit(self, results, chapter_limit: int):
        for r in results:
            md = r.get("metadata", {})
            ch = md.get("chapter", 0)
            try:
                ch_num = int(ch)
            except Exception:
                ch_num = 0
            self.assertLessEqual(ch_num, chapter_limit, f"Found chapter {ch_num} > {chapter_limit}")


def run_checks() -> Tuple[int, int]:
    cases: List[Tuple[str, int]] = []
    limits = [1, 2, 3, 5, 10]
    # Create two different queries per limit (10 total)
    for lim in limits:
        cases.append((f"summary about chapter {lim}", lim))
        cases.append((f"spoiler safe query {lim}", lim))

    total = 0
    passed = 0
    tester = SpoilerBoundary()
    for query, lim in cases:
        total += 1
        try:
            results = query_up_to_chapter(query, chapter_limit=lim, top_k=5)
            tester.assert_results_within_limit(results, lim)
            print(f"PASS: query='{query[:40]}...' chapter_limit={lim}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL: query='{query[:40]}...' chapter_limit={lim} --> {e}")
        except Exception as e:
            print(f"FAIL (error): query='{query[:40]}...' chapter_limit={lim} --> {e}")

    return passed, total


if __name__ == "__main__":
    p, t = run_checks()
    print(f"\nSummary: {p}/{t} passed")
    # Exit non-zero if not all passed
    sys.exit(0 if p == t else 1)
