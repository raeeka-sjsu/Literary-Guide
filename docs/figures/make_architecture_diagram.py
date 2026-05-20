"""
Generates the Literary Guide architecture diagram (Figure 1 in the report).

Output: docs/figures/architecture.png  (and architecture.pdf)

Run:
    cd python && source venv/bin/activate
    python ../docs/figures/make_architecture_diagram.py
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT_DIR = Path(__file__).resolve().parent

# ---- palette (muted, print-friendly) ----
C_UI      = "#E8EEF7"; E_UI      = "#4F6D9A"
C_API     = "#E7F1EA"; E_API     = "#4F8A6A"
C_AGENT   = "#FBEEE6"; E_AGENT   = "#C2774B"
C_TOOL    = "#F3ECF7"; E_TOOL    = "#7E5A9B"
C_STORE   = "#FBF3E2"; E_STORE   = "#B08A2E"
C_LLM     = "#F7E9EC"; E_LLM     = "#9B4F62"
C_TEXT    = "#1E2430"

fig, ax = plt.subplots(figsize=(12.5, 13))
ax.set_xlim(0, 116)
ax.set_ylim(0, 130)
ax.axis("off")


def box(x, y, w, h, label, fc, ec, fs=11, bold=True, sub=None):
    p = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.6,rounding_size=2.2",
        linewidth=1.6, edgecolor=ec, facecolor=fc,
    )
    ax.add_patch(p)
    if sub:
        ax.text(x + w / 2, y + h * 0.62, label, ha="center", va="center",
                fontsize=fs, fontweight="bold" if bold else "normal", color=C_TEXT)
        ax.text(x + w / 2, y + h * 0.28, sub, ha="center", va="center",
                fontsize=fs - 2.5, color="#48505E")
    else:
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
                fontsize=fs, fontweight="bold" if bold else "normal", color=C_TEXT)


def arrow(x1, y1, x2, y2, style="-|>", color="#5A6473", lw=1.6, ls="-"):
    a = FancyArrowPatch(
        (x1, y1), (x2, y2), arrowstyle=style, mutation_scale=16,
        linewidth=lw, color=color, linestyle=ls,
        shrinkA=2, shrinkB=2,
    )
    ax.add_patch(a)


def band(y, h, label, color):
    ax.text(2.6, y + h / 2, label, ha="center", va="center", fontsize=9,
            rotation=90, color=color, fontweight="bold", alpha=0.9)


CX = 47  # horizontal center of the main flow column

# ============ LAYER 1: User / Browser ============
box(CX - 13, 121, 26, 6, "Reader (Browser)", "#FFFFFF", "#8A93A3", fs=11)

# ============ LAYER 2: Express SPA ============
band(104, 12, "FRONT END", E_UI)
box(CX - 32, 104, 64, 12,
    "Express SPA  (js/server.js, js/public/)",
    C_UI, E_UI, fs=11,
    sub="library · paginated reader · chat · agent strip · memory panel")

# ============ LAYER 3: Flask API ============
band(88, 12, "API", E_API)
box(CX - 32, 88, 64, 12,
    "Flask API Gateway  (api_server.py)",
    C_API, E_API, fs=11,
    sub="/ask · /index_book · /memory · /reading_position")

# ============ LAYER 4: routing branch ============
ax.text(CX, 83.5, "routes on  agent_mode  flag", ha="center", va="center",
        fontsize=8.5, style="italic", color="#48505E")

box(6, 67, 32, 12, "Single-call RAG", "#FFFFFF", "#8A93A3", fs=10,
    sub="one LLM call over\nretrieved chunks")

band(60, 25, "AGENT CORE", E_AGENT)
box(44, 60, 40, 19,
    "Four-Stage Agent Loop  (agent_loop.py)",
    C_AGENT, E_AGENT, fs=10,
    sub="Planner → Executor →\nSynthesizer → Critic\n(name-grounding, ≤1 retry)")

# ============ LLM providers (clean right column, no overlap) ============
ax.text(102, 82.5, "LLM PROVIDERS", ha="center", va="center", fontsize=8.5,
        color=E_LLM, fontweight="bold", alpha=0.9)
prov = [
    ("Llama 3.2:3b", "Ollama · local · open-source"),
    ("Claude Haiku 4.5", "Anthropic API"),
    ("GPT-4o-mini", "OpenAI API"),
]
px, pw = 90, 24
for i, (lab, sub) in enumerate(prov):
    by = 73.5 - i * 8.0
    box(px, by, pw, 6.4, lab, C_LLM, E_LLM, fs=8.5, bold=True)
    ax.text(px + pw / 2, by - 1.6, sub, ha="center", va="center",
            fontsize=6.6, color="#7A5560")

# ============ LAYER 5: Tools ============
band(40, 14, "TOOLS", E_TOOL)
tool_labels = [
    "retrieve_passages", "list_known_characters", "retrieve_expert_analysis",
    "get_chapter_summary", "recall_memory", "write_memory",
]
tw, th, gap = 30.0, 6.2, 2.5
x0, y0 = 6, 47
for i, t in enumerate(tool_labels):
    col = i % 3
    row = i // 3
    bx = x0 + col * (tw + gap)
    by = y0 - row * (th + gap)
    box(bx, by, tw, th, t, C_TOOL, E_TOOL, fs=8.3, bold=False)

# ============ LAYER 6: Retrieval engine ============
band(30, 8, "RETRIEVAL", "#445566")
box(8, 30, 90, 8,
    "Hybrid Retriever  (book_index.py)",
    "#EEF2F6", "#5A6473", fs=10.5,
    sub="BM25  +  MiniLM dense  →  Reciprocal Rank Fusion   ·   chapter-boundary filter (pre-ranking)")

# ============ LAYER 7: Storage ============
band(8, 16, "STORAGE", E_STORE)
store_labels = [
    ("Chroma\nvector store", "chunk embeddings"),
    ("Character\nIndex (JSON)", "per-book entities"),
    ("BookSum\ncorpus", "expert analysis"),
    ("SQLite\n(memory_store)", "position · turns · log"),
]
sw, sgap = 21.0, 2.5
sx0, sy0 = 6, 8
for i, (lab, sub) in enumerate(store_labels):
    bx = sx0 + i * (sw + sgap)
    box(bx, sy0, sw, 14, lab, C_STORE, E_STORE, fs=9, sub=sub)

# ============ ARROWS (main vertical flow) ============
arrow(CX, 121, CX, 116.2)                        # browser -> SPA
arrow(CX, 104, CX, 100.2)                         # SPA -> Flask
# Flask -> branch
arrow(CX - 8, 88, 24, 79.2)                       # Flask -> single-call
arrow(CX + 8, 88, 62, 79.2)                       # Flask -> agent loop
# agent core -> tools
arrow(58, 60, 52, 53.6)
arrow(66, 60, 66, 53.6)
# single-call -> retriever
arrow(22, 67, 22, 38.4)
# tools -> retrieval
arrow(50, 40.8, 50, 38.4)
# retrieval -> storage
arrow(30, 30, 16, 22.2)
arrow(45, 30, 39, 22.2)
arrow(58, 30, 60, 22.2)
arrow(72, 30, 81, 22.2)
# agent core <-> LLM providers (bidirectional dashed)
arrow(84, 69, 90, 69, style="<|-|>", color=E_LLM, lw=1.5, ls="--")

# ============ Title ============
ax.text(CX, 129, "Figure 1.  Literary Guide — System Architecture",
        ha="center", va="center", fontsize=13.5, fontweight="bold", color=C_TEXT)

plt.tight_layout()
fig.savefig(OUT_DIR / "architecture.png", dpi=200, bbox_inches="tight",
            facecolor="white")
fig.savefig(OUT_DIR / "architecture.pdf", bbox_inches="tight",
            facecolor="white")
print("wrote", OUT_DIR / "architecture.png")
print("wrote", OUT_DIR / "architecture.pdf")
