"""
Generates evaluation figures for the report from python/eval/comparison.json.

Outputs (docs/figures/):
    fig_cost_vs_accuracy.png   — latency/cost vs accuracy tradeoff scatter
    fig_provider_metrics.png   — grouped bars: pass rate, leak rate, refusal F1

Reads the real aggregated eval data so the figures always match the tables
in the report. Run:
    cd python && source venv/bin/activate
    python ../docs/figures/make_eval_figures.py
"""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
COMPARISON = ROOT / "python" / "eval" / "comparison.json"
OUT = Path(__file__).resolve().parent

with open(COMPARISON) as f:
    data = json.load(f)

pp = data["per_provider"]
# Stable display order: open-source first, then commercial
order = ["ollama", "anthropic", "openai"]
labels = {
    "ollama": "Llama 3.2:3b\n(Ollama, local)",
    "anthropic": "Claude Haiku 4.5\n(Anthropic)",
    "openai": "GPT-4o-mini\n(OpenAI)",
}
colors = {"ollama": "#C2774B", "anthropic": "#4F6D9A", "openai": "#4F8A6A"}

prov = [p for p in order if p in pp]

# ---------- Figure 1: cost / latency vs accuracy tradeoff ----------
fig, ax = plt.subplots(figsize=(8, 5.5))
for p in prov:
    d = pp[p]
    acc = d["overall"]["rate"] * 100
    latency_s = d["overall"]["latency_mean_ms"] / 1000.0
    cost = d["cost"]["avg_per_query_usd"]
    # marker size encodes cost per query (free model gets a clear minimum size)
    size = 220 + cost * 90000
    ax.scatter(latency_s, acc, s=size, color=colors[p], alpha=0.75,
               edgecolor="white", linewidth=1.8, zorder=3)
    cost_lbl = "free" if cost == 0 else f"${cost*1000:.2f}/1k queries"
    ax.annotate(
        f"{labels[p].splitlines()[0]}\n{acc:.1f}% · {latency_s:.1f}s · {cost_lbl}",
        (latency_s, acc),
        textcoords="offset points", xytext=(0, -42 if p == "ollama" else 26),
        ha="center", fontsize=9, color="#1E2430",
    )

ax.set_xlabel("Mean latency per query (seconds)  →  slower", fontsize=11)
ax.set_ylabel("Overall pass rate (%)  →  more accurate", fontsize=11)
ax.set_title("Accuracy vs. latency vs. cost across three language models\n"
             "(marker size ∝ cost per query; 60-case suite)",
             fontsize=12, fontweight="bold")
ax.grid(True, linestyle=":", alpha=0.5, zorder=0)
ax.set_ylim(75, 102)
ax.set_xlim(2, 9)
fig.tight_layout()
fig.savefig(OUT / "fig_cost_vs_accuracy.png", dpi=200, bbox_inches="tight",
            facecolor="white")
print("wrote", OUT / "fig_cost_vs_accuracy.png")

# ---------- Figure 2: grouped bars — pass rate, leak rate, refusal F1 ----------
fig, ax = plt.subplots(figsize=(9, 5.5))
metrics = ["Overall\npass rate", "Spoiler-leak\nrate (lower=better)", "Refusal-task\nF1"]
x = range(len(metrics))
n = len(prov)
width = 0.78 / n

for j, p in enumerate(prov):
    d = pp[p]
    vals = [
        d["overall"]["rate"] * 100,
        d["spoiler_leak_rate"] * 100,
        d["classification_metrics"]["f1"] * 100,
    ]
    offs = [xi + (j - (n - 1) / 2) * width for xi in x]
    bars = ax.bar(offs, vals, width=width, color=colors[p],
                  label=labels[p].replace("\n", " "), edgecolor="white", linewidth=1)
    for rect, v in zip(bars, vals):
        ax.text(rect.get_x() + rect.get_width() / 2, v + 1.2, f"{v:.1f}",
                ha="center", va="bottom", fontsize=8.5, color="#1E2430")

ax.set_xticks(list(x))
ax.set_xticklabels(metrics, fontsize=10.5)
ax.set_ylabel("Percent", fontsize=11)
ax.set_ylim(0, 110)
ax.set_title("Per-provider evaluation metrics (60-case suite)",
             fontsize=12, fontweight="bold")
ax.legend(fontsize=9, loc="upper center", ncol=3, frameon=False,
          bbox_to_anchor=(0.5, -0.08))
ax.grid(True, axis="y", linestyle=":", alpha=0.5)
fig.tight_layout()
fig.savefig(OUT / "fig_provider_metrics.png", dpi=200, bbox_inches="tight",
            facecolor="white")
print("wrote", OUT / "fig_provider_metrics.png")
