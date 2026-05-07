"""
Aggregate all 3 LLMs' eval runs into a single slide-ready comparison.

Reads the JSONL logs in python/eval/runs/, computes per-provider:
  - Pass rate (overall and per category)
  - Latency mean / median / p95
  - Token-based cost estimate (using fixed price tables)
  - Spoiler-leak rate specifically
  - Where the models diverge (which cases each passes / fails uniquely)
  - Best/worst examples

Outputs:
  - eval/comparison.md       — markdown tables for the slides
  - eval/comparison.json     — machine-readable
  - eval/comparison.tsv      — tab-separated for pasting into a spreadsheet

Usage:
  python eval/build_comparison.py \
    --llama   eval/runs/ollama_baseline.jsonl \
    --claude  eval/runs/anthropic_100.jsonl \
    --openai  eval/runs/openai_full.jsonl
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent

# Approximate $/1M tokens (input, output) — used for cost estimation.
# These are the public pricing as of 2026-05; update if changed.
PRICING = {
    # Local Ollama is free, but we still report estimated marginal cost as $0.
    "ollama":       (0.00, 0.00),
    "anthropic":    (0.80, 4.00),   # Claude Haiku 4.5
    "openai":       (0.15, 0.60),   # GPT-4o-mini
}

# Approximate token counts per case (we don't store tokens in the eval; this
# uses a rough "1 word ~ 1.3 tokens" heuristic on the prompt + answer text).
INPUT_TOKEN_HEURISTIC = 1500  # system prompt + few-shot + 4 retrieved passages + question
OUTPUT_TOKEN_HEURISTIC = 200  # average answer length


def words_to_tokens(text: str | None) -> int:
    if not text:
        return 0
    return int(len(text.split()) * 1.3)


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def classification_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute precision / recall / F1 for the binary 'should the model refuse?' task.

    Each case has a ground-truth label of refuse-required (spoiler_trap +
    refusal_or_edge with must_refuse=True) vs answer-required. The model's
    behaviour is inferred from the answer + score:
      - "refused" if answer matches refusal patterns (system-wide classifier)
        OR contained a refusal phrase from the case keywords (when applicable)
      - "answered" otherwise
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    try:
        from safety import is_refusal as _is_refusal
    except Exception:
        _is_refusal = lambda x: False  # noqa: E731

    tp = fp = tn = fn = 0
    # TP: should refuse, did refuse
    # FP: should answer, but refused (over-cautious)
    # TN: should answer, did answer
    # FN: should refuse, but answered (LEAK — the safety-critical failure)
    for r in records:
        cat = r["category"]
        sc = r.get("score", {})
        case_must_refuse = (
            cat == "spoiler_trap"
            or (cat == "refusal_or_edge" and (
                # We can't get must_refuse from the record directly, but
                # the score reason tells us — "refused_correctly" / "did_not_refuse"
                # are only present in refusal scoring with must_refuse=True
                "refused" in str(sc) or "did_not_refuse" in str(sc.get("reason", ""))
            ))
        )
        # Did the model actually refuse?
        ans = r.get("answer") or ""
        model_refused = _is_refusal(ans) or sc.get("matched_via") == "system_classifier" \
                        or sc.get("matched_via") == "keyword"

        if case_must_refuse and model_refused:
            tp += 1
        elif case_must_refuse and not model_refused:
            fn += 1
        elif not case_must_refuse and model_refused:
            fp += 1
        elif not case_must_refuse and not model_refused:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall    = tp / (tp + fn) if (tp + fn) else 0.0
    f1        = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    accuracy  = (tp + tn) / max(1, tp + fp + tn + fn)
    return {
        "task": "binary_refusal_classification",
        "true_positive": tp,    # correctly refused a spoiler-trap
        "false_positive": fp,   # over-cautiously refused a legitimate question
        "true_negative": tn,    # correctly answered a legitimate question
        "false_negative": fn,   # leaked when it should have refused (safety-critical)
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "accuracy": round(accuracy, 3),
    }


def aggregate(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not records:
        return {}
    by_cat: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        by_cat.setdefault(r["category"], []).append(r)

    def stats_for(rs: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not rs:
            return {"n": 0, "passes": 0, "rate": 0.0,
                    "latency_mean_ms": 0, "latency_median_ms": 0, "latency_p95_ms": 0}
        passes = sum(1 for r in rs if r["score"].get("passed"))
        latencies = sorted(r.get("latency_ms", 0) for r in rs)
        n = len(latencies)
        median = latencies[n // 2]
        p95 = latencies[max(0, int(n * 0.95) - 1)]
        return {
            "n": n,
            "passes": passes,
            "rate": passes / n,
            "latency_mean_ms": int(sum(latencies) / n),
            "latency_median_ms": median,
            "latency_p95_ms": p95,
        }

    overall = stats_for(records)
    by_category = {cat: stats_for(rs) for cat, rs in by_cat.items()}

    # Spoiler-leak rate specifically (spoiler_trap cases where forbidden words were found)
    spoiler_traps = [r for r in records if r["category"] == "spoiler_trap"]
    leaks = [r for r in spoiler_traps if r["score"].get("leaks")]
    spoiler_leak_rate = len(leaks) / max(1, len(spoiler_traps))

    # Cost estimate based on captured prompt + answer length where available
    # Otherwise fall back to fixed heuristic.
    provider = records[0].get("provider", "unknown")
    total_input_tokens = 0
    total_output_tokens = 0
    for r in records:
        # input = question + retrieved passage docs (we don't have the full
        # rendered prompt, but the chunk doc_heads in the log are a useful
        # proxy). Plus the system prompt itself is fixed-size (~1.5k tokens).
        question_tokens = words_to_tokens(r.get("question", ""))
        chunk_tokens = sum(words_to_tokens((c.get("doc_head") or "")) for c in r.get("chunks", []))
        # Heuristic: actual passages are ~5x the doc_head length we logged
        chunk_tokens = chunk_tokens * 5
        total_input_tokens += INPUT_TOKEN_HEURISTIC + question_tokens + chunk_tokens
        total_output_tokens += words_to_tokens(r.get("answer", ""))

    in_price, out_price = PRICING.get(provider, (0.0, 0.0))
    est_cost = (total_input_tokens / 1_000_000) * in_price + (total_output_tokens / 1_000_000) * out_price
    avg_cost_per_query = est_cost / max(1, len(records))

    classification = classification_metrics(records)

    return {
        "provider": provider,
        "model": records[0].get("model"),
        "overall": overall,
        "by_category": by_category,
        "spoiler_leak_rate": spoiler_leak_rate,
        "spoiler_leak_count": len(leaks),
        "classification_metrics": classification,
        "tokens": {
            "input_total": total_input_tokens,
            "output_total": total_output_tokens,
        },
        "cost": {
            "total_usd": round(est_cost, 4),
            "avg_per_query_usd": round(avg_cost_per_query, 6),
        },
    }


def render_markdown(per_provider: Dict[str, Dict[str, Any]]) -> str:
    """Build the slide-ready markdown comparison."""
    providers = list(per_provider.keys())
    lines: List[str] = []

    lines.append("# Literary Guide — 3-LLM Comparison")
    lines.append("")
    n_per = {p: agg["overall"]["n"] for p, agg in per_provider.items()}
    if len(set(n_per.values())) == 1:
        n = next(iter(n_per.values()))
        lines.append(f"All three models evaluated on the same {n} test questions.")
    else:
        parts = ", ".join(f"{p}: {n} cases" for p, n in n_per.items())
        lines.append(f"Per-provider case counts — {parts}.")
    lines.append("")

    # Headline overall table
    lines.append("## Overall pass rate")
    lines.append("")
    lines.append("| Provider | Model | Pass | Total | Rate | Mean latency | p95 latency | Est. cost (run) |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for p_name, agg in per_provider.items():
        ov = agg["overall"]
        lines.append(
            f"| {p_name} | `{agg.get('model') or '?'}` | {ov['passes']} | {ov['n']} | "
            f"**{ov['rate'] * 100:.1f}%** | {ov['latency_mean_ms']:,} ms | "
            f"{ov['latency_p95_ms']:,} ms | ${agg['cost']['total_usd']:.4f} |"
        )
    lines.append("")

    # Per-category breakdown
    lines.append("## Pass rate by category")
    lines.append("")
    cats = sorted({c for p in per_provider.values() for c in p["by_category"]})
    header = "| Provider |"
    align = "|---|"
    for c in cats:
        header += f" {c} |"
        align += "---:|"
    lines.append(header)
    lines.append(align)
    for p_name, agg in per_provider.items():
        row = f"| {p_name} |"
        for c in cats:
            cstats = agg["by_category"].get(c, {})
            if not cstats:
                row += " — |"
            else:
                row += f" {cstats['passes']}/{cstats['n']} ({cstats['rate'] * 100:.0f}%) |"
        lines.append(row)
    lines.append("")

    # Spoiler-leak specifically — the safety-critical metric
    lines.append("## Spoiler-leak rate (lower is better)")
    lines.append("")
    lines.append("Of the spoiler-trap cases, what fraction did the model accidentally leak future-chapter information?")
    lines.append("")
    lines.append("| Provider | Cases | Leaks | Leak rate |")
    lines.append("|---|---:|---:|---:|")
    for p_name, agg in per_provider.items():
        st = agg["by_category"].get("spoiler_trap", {})
        n_st = st.get("n", 0)
        leaks = agg.get("spoiler_leak_count", 0)
        rate = (leaks / n_st * 100) if n_st else 0
        lines.append(f"| {p_name} | {n_st} | {leaks} | **{rate:.1f}%** |")
    lines.append("")

    # Classification metrics — precision/recall/F1 for the binary refusal task
    lines.append("## Classification metrics — should-the-model-refuse task")
    lines.append("")
    lines.append("Treating each case as a binary classification: ground truth is whether")
    lines.append("the question requires refusal (spoiler-trap or must_refuse case) vs.")
    lines.append("legitimate answer. Confusion matrix terms:")
    lines.append("- **True positive (TP)**: correctly refused a spoiler-trap")
    lines.append("- **False negative (FN)**: leaked when should have refused (safety-critical failure)")
    lines.append("- **False positive (FP)**: over-cautiously refused a legitimate question")
    lines.append("- **True negative (TN)**: correctly answered a legitimate question")
    lines.append("")
    lines.append("| Provider | TP | FP | TN | FN | Precision | Recall | F1 | Accuracy |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for p_name, agg in per_provider.items():
        m = agg.get("classification_metrics", {})
        lines.append(
            f"| {p_name} | {m.get('true_positive', 0)} | {m.get('false_positive', 0)} | "
            f"{m.get('true_negative', 0)} | {m.get('false_negative', 0)} | "
            f"**{m.get('precision', 0):.3f}** | **{m.get('recall', 0):.3f}** | "
            f"**{m.get('f1', 0):.3f}** | {m.get('accuracy', 0):.3f} |"
        )
    lines.append("")
    lines.append("Recall is the metric that matters most for our domain: of questions")
    lines.append("that SHOULD have triggered a refusal, what fraction did the model")
    lines.append("correctly refuse? A false negative here is a real spoiler reaching the user.")
    lines.append("")

    # Cost & latency
    lines.append("## Cost & latency tradeoffs")
    lines.append("")
    lines.append("| Provider | Avg latency | Avg cost / query | Cost / 1000 queries |")
    lines.append("|---|---:|---:|---:|")
    for p_name, agg in per_provider.items():
        ov = agg["overall"]
        c_per = agg["cost"]["avg_per_query_usd"]
        c_per_1k = c_per * 1000
        lines.append(
            f"| {p_name} | {ov['latency_mean_ms']:,} ms | ${c_per:.5f} | ${c_per_1k:.2f} |"
        )
    lines.append("")

    return "\n".join(lines)


def render_tsv(per_provider: Dict[str, Dict[str, Any]]) -> str:
    """Tab-separated for spreadsheet pasting."""
    lines = []
    lines.append("\t".join([
        "Provider", "Model", "Total", "Passes", "Rate%",
        "Latency Mean(ms)", "Latency p95(ms)",
        "Spoiler-trap rate%", "Analytical rate%", "Refusal rate%",
        "Spoiler-leak rate%",
        "Total cost($)", "Cost/query($)",
    ]))
    for p_name, agg in per_provider.items():
        ov = agg["overall"]
        st = agg["by_category"].get("spoiler_trap", {"rate": 0})
        an = agg["by_category"].get("analytical", {"rate": 0})
        rf = agg["by_category"].get("refusal_or_edge", {"rate": 0})
        spoiler_leak = (agg.get("spoiler_leak_count", 0) / max(1, st.get("n", 0))) * 100
        lines.append("\t".join([
            p_name, str(agg.get("model") or ""),
            str(ov["n"]), str(ov["passes"]), f"{ov['rate'] * 100:.1f}",
            str(ov["latency_mean_ms"]), str(ov["latency_p95_ms"]),
            f"{st.get('rate', 0) * 100:.1f}",
            f"{an.get('rate', 0) * 100:.1f}",
            f"{rf.get('rate', 0) * 100:.1f}",
            f"{spoiler_leak:.1f}",
            f"{agg['cost']['total_usd']:.4f}",
            f"{agg['cost']['avg_per_query_usd']:.6f}",
        ]))
    return "\n".join(lines)


def divergence(per_provider_records: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """For each case_id, find providers that pass vs fail. Useful for slides."""
    by_case: Dict[str, Dict[str, bool]] = {}
    for prov, recs in per_provider_records.items():
        for r in recs:
            cid = r["case_id"]
            by_case.setdefault(cid, {})[prov] = bool(r["score"].get("passed"))

    all_pass = []
    all_fail = []
    only_open_fails = []  # cases where only Llama fails — shows the tax of small models
    only_open_passes = []
    mixed = []
    for cid, results in by_case.items():
        passes = [p for p, ok in results.items() if ok]
        fails = [p for p, ok in results.items() if not ok]
        if not fails:
            all_pass.append(cid)
        elif not passes:
            all_fail.append(cid)
        elif passes == ["ollama"]:
            only_open_passes.append(cid)
        elif fails == ["ollama"]:
            only_open_fails.append(cid)
        else:
            mixed.append(cid)
    return {
        "all_pass": all_pass,
        "all_fail": all_fail,
        "only_open_fails": only_open_fails,
        "only_open_passes": only_open_passes,
        "mixed": mixed,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llama",  default=str(ROOT / "runs" / "ollama_baseline.jsonl"))
    ap.add_argument("--claude", default=str(ROOT / "runs" / "anthropic_100.jsonl"))
    ap.add_argument("--openai", default=str(ROOT / "runs" / "openai_full.jsonl"))
    ap.add_argument("--out-md", default=str(ROOT / "comparison.md"))
    ap.add_argument("--out-json", default=str(ROOT / "comparison.json"))
    ap.add_argument("--out-tsv", default=str(ROOT / "comparison.tsv"))
    args = ap.parse_args()

    sources: Dict[str, Path] = {
        "ollama":     Path(args.llama),
        "anthropic":  Path(args.claude),
        "openai":     Path(args.openai),
    }

    per_provider: Dict[str, Dict[str, Any]] = {}
    per_provider_records: Dict[str, List[Dict[str, Any]]] = {}
    for name, path in sources.items():
        if not path.exists():
            print(f"  ! missing log for {name}: {path}")
            continue
        recs = load_jsonl(path)
        if not recs:
            print(f"  ! empty log for {name}: {path}")
            continue
        per_provider[name] = aggregate(recs)
        per_provider_records[name] = recs
        print(f"  ✓ {name}: {len(recs)} cases from {path.name}")

    if not per_provider:
        print("No logs found. Run eval/run_eval.py first.")
        return

    div = divergence(per_provider_records) if len(per_provider_records) > 1 else None

    md = render_markdown(per_provider)
    if div:
        md += "\n## Divergence across LLMs\n\n"
        md += f"- All providers passed: {len(div['all_pass'])} cases\n"
        md += f"- All providers failed: {len(div['all_fail'])} cases\n"
        md += f"- Only Llama (open-source) failed: {len(div['only_open_fails'])} cases — these are the cases where the bigger commercial models edge out\n"
        md += f"- Only Llama passed: {len(div['only_open_passes'])} cases\n"
        md += f"- Mixed: {len(div['mixed'])} cases\n"

    with open(args.out_md, "w") as f:
        f.write(md)
    with open(args.out_json, "w") as f:
        json.dump({
            "per_provider": per_provider,
            "divergence": div,
        }, f, indent=2, default=str)
    with open(args.out_tsv, "w") as f:
        f.write(render_tsv(per_provider))

    print(f"\nWrote:")
    print(f"  {args.out_md}")
    print(f"  {args.out_json}")
    print(f"  {args.out_tsv}")
    print()
    print("---")
    print(md)


if __name__ == "__main__":
    main()
