"""
Run the full eval suite against one or more LLM providers.

For each case:
  - call the agent (retrieves passages, calls the LLM)
  - score the answer based on category-specific rules
  - log a JSONL record with prompt, retrieved chunks, answer, latency, tokens, score

Usage:
    python eval/run_eval.py --provider ollama
    python eval/run_eval.py --provider ollama,anthropic,openai
    python eval/run_eval.py --provider ollama --limit 5      # smoke test
    python eval/run_eval.py --provider ollama --category spoiler_trap
    python eval/run_eval.py --provider ollama --case st-tm-1  # single case

Outputs:
    python/eval/runs/<timestamp>.jsonl   — per-case structured log
    python/eval/runs/<timestamp>.summary.json — aggregated metrics
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from literary_guide_agent import answer  # noqa: E402

CASES_PATH = Path(__file__).resolve().parent / "eval_cases.json"
RUNS_DIR = Path(__file__).resolve().parent / "runs"


def score_spoiler_trap(case: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    """Pass if the answer does NOT contain any forbidden keyword (case-insensitive),
    AND no retrieved chunk has chapter > current_chapter (retrieval-side check)."""
    ans = (result.get("answer") or "").lower()
    forbidden = [k.lower() for k in case.get("forbidden_keywords", [])]
    leaks = [k for k in forbidden if k in ans]
    chunks = result.get("chunks", []) or []
    over_chapter = [
        c for c in chunks
        if int((c.get("metadata") or {}).get("chapter") or 0) > case["current_chapter"]
    ]
    passed = not leaks and not over_chapter
    return {
        "passed": passed,
        "leaks": leaks,
        "retrieval_violations": len(over_chapter),
        "reason": ("clean" if passed else f"leaked={leaks} retrieval_violations={len(over_chapter)}"),
    }


def score_analytical(case: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    """Pass if (a) answer >= 60 words, (b) every retrieved chunk has chapter <= current_chapter,
    (c) answer cites at least one [n] reference."""
    ans = (result.get("answer") or "")
    word_count = len(ans.split())
    chunks = result.get("chunks", []) or []
    over_chapter = [
        c for c in chunks
        if int((c.get("metadata") or {}).get("chapter") or 0) > case["current_chapter"]
    ]
    has_citation = any(f"[{i}]" in ans for i in range(1, 9))
    long_enough = word_count >= 60
    safe_retrieval = len(over_chapter) == 0
    passed = has_citation and long_enough and safe_retrieval
    reason_bits = []
    if not has_citation: reason_bits.append("no_citation")
    if not long_enough:  reason_bits.append(f"too_short({word_count}w)")
    if not safe_retrieval: reason_bits.append(f"retrieval_violations={len(over_chapter)}")
    return {
        "passed": passed,
        "word_count": word_count,
        "has_citation": has_citation,
        "retrieval_violations": len(over_chapter),
        "reason": "ok" if passed else ",".join(reason_bits),
    }


def score_refusal(case: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    """If must_refuse=True: answer must contain a refusal keyword.
    If must_refuse=False: answer must be non-empty + cite + retrieval-safe."""
    ans = (result.get("answer") or "").lower()
    must_refuse = case.get("must_refuse", False)
    chunks = result.get("chunks", []) or []
    over_chapter = [
        c for c in chunks
        if int((c.get("metadata") or {}).get("chapter") or 0) > case["current_chapter"]
    ]
    safe_retrieval = len(over_chapter) == 0

    if must_refuse:
        kws = [k.lower() for k in case.get("refusal_keywords", [])]
        refused = any(k in ans for k in kws)
        passed = refused and safe_retrieval
        return {
            "passed": passed,
            "refused": refused,
            "retrieval_violations": len(over_chapter),
            "reason": "refused_correctly" if passed else ("did_not_refuse" if not refused else "retrieval_violations"),
        }
    else:
        non_empty = len(ans.strip()) > 0
        has_citation = any(f"[{i}]" in result.get("answer", "") for i in range(1, 9))
        passed = non_empty and has_citation and safe_retrieval
        return {
            "passed": passed,
            "non_empty": non_empty,
            "has_citation": has_citation,
            "retrieval_violations": len(over_chapter),
            "reason": "ok" if passed else "answered_too_thinly",
        }


SCORERS = {
    "spoiler_trap": score_spoiler_trap,
    "analytical":   score_analytical,
    "refusal_or_edge": score_refusal,
}


def run_case(case: Dict[str, Any], provider: str) -> Dict[str, Any]:
    started = time.time()
    error = None
    try:
        result = answer(
            question=case["question"],
            current_chapter=case["current_chapter"],
            provider=provider,
            top_k=4,
            book_id=case["book_id"],
        )
    except Exception as e:
        result = {"answer": None, "chunks": [], "model": None, "provider": provider}
        error = f"{type(e).__name__}: {e}"
    latency_ms = int((time.time() - started) * 1000)

    score = SCORERS[case["category"]](case, result) if not error else {"passed": False, "reason": f"error:{error}"}

    return {
        "case_id": case["id"],
        "category": case["category"],
        "book_id": case["book_id"],
        "current_chapter": case["current_chapter"],
        "question": case["question"],
        "provider": provider,
        "model": result.get("model"),
        "answer": result.get("answer"),
        "chunks": [
            {
                "chapter": (c.get("metadata") or {}).get("chapter"),
                "score": c.get("score"),
                "doc_head": (c.get("document") or "")[:160],
            }
            for c in (result.get("chunks") or [])
        ],
        "score": score,
        "latency_ms": latency_ms,
        "error": error,
        "timestamp": _dt.datetime.utcnow().isoformat() + "Z",
    }


def aggregate(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Group records by (provider, category) and compute pass-rate + latency stats."""
    by_provider: Dict[str, Dict[str, Any]] = {}
    for r in records:
        p = r["provider"]
        c = r["category"]
        bucket = by_provider.setdefault(p, {"by_category": {}, "totals": {"runs": 0, "passes": 0, "total_latency_ms": 0}})
        cat = bucket["by_category"].setdefault(c, {"runs": 0, "passes": 0, "total_latency_ms": 0})
        cat["runs"] += 1
        cat["passes"] += int(r["score"].get("passed", False))
        cat["total_latency_ms"] += r["latency_ms"]
        bucket["totals"]["runs"] += 1
        bucket["totals"]["passes"] += int(r["score"].get("passed", False))
        bucket["totals"]["total_latency_ms"] += r["latency_ms"]

    # Compute pass rate + avg latency
    for p, bucket in by_provider.items():
        for c, cat in bucket["by_category"].items():
            cat["pass_rate"] = cat["passes"] / cat["runs"] if cat["runs"] else 0.0
            cat["avg_latency_ms"] = cat["total_latency_ms"] // cat["runs"] if cat["runs"] else 0
        t = bucket["totals"]
        t["pass_rate"] = t["passes"] / t["runs"] if t["runs"] else 0.0
        t["avg_latency_ms"] = t["total_latency_ms"] // t["runs"] if t["runs"] else 0

    return by_provider


def print_summary(summary: Dict[str, Any]):
    print("\n" + "=" * 70)
    print(f"{'Provider':<14} {'Category':<18} {'Pass':>6} {'Total':>6} {'Rate':>8} {'AvgLat':>10}")
    print("-" * 70)
    for p, bucket in summary.items():
        for c, cat in bucket["by_category"].items():
            print(f"{p:<14} {c:<18} {cat['passes']:>6} {cat['runs']:>6} {cat['pass_rate']:>7.1%} {cat['avg_latency_ms']:>9}ms")
        t = bucket["totals"]
        print(f"{p:<14} {'TOTAL':<18} {t['passes']:>6} {t['runs']:>6} {t['pass_rate']:>7.1%} {t['avg_latency_ms']:>9}ms")
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="ollama",
                    help="Comma-separated list: ollama,anthropic,openai,dry-run")
    ap.add_argument("--limit", type=int, help="Run only first N cases")
    ap.add_argument("--category", help="Filter to one category")
    ap.add_argument("--case", help="Run only one case by id")
    ap.add_argument("--out-prefix", help="Override timestamp prefix for output files")
    args = ap.parse_args()

    with open(CASES_PATH) as f:
        cases = json.load(f)["cases"]

    # Append NarrativeQA-derived cases if the fetcher has produced any
    nqa_path = CASES_PATH.parent / "narrativeqa_cases.json"
    if nqa_path.exists():
        with open(nqa_path) as f:
            nqa_cases = json.load(f)
        cases = cases + nqa_cases

    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
    if args.category:
        cases = [c for c in cases if c["category"] == args.category]
    if args.limit:
        cases = cases[: args.limit]

    providers = [p.strip() for p in args.provider.split(",")]
    RUNS_DIR.mkdir(exist_ok=True)
    stamp = args.out_prefix or _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = RUNS_DIR / f"{stamp}.jsonl"
    summary_path = RUNS_DIR / f"{stamp}.summary.json"

    print(f"Running {len(cases)} cases × {len(providers)} provider(s) → {log_path}")

    records: List[Dict[str, Any]] = []
    with open(log_path, "w") as logf:
        for provider in providers:
            print(f"\n--- provider: {provider} ---")
            for i, case in enumerate(cases, 1):
                print(f"  [{i}/{len(cases)}] {case['id']:<10} {case['category']:<18} ", end="", flush=True)
                rec = run_case(case, provider)
                logf.write(json.dumps(rec) + "\n")
                logf.flush()
                records.append(rec)
                p = "PASS" if rec["score"].get("passed") else "FAIL"
                print(f"{p}  {rec['latency_ms']:>6}ms  {rec['score'].get('reason', '')}")

    summary = aggregate(records)
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print_summary(summary)
    print(f"\nLog:     {log_path}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
