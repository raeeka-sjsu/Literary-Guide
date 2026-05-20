# Literary Guide

### CMPE 258 — SP26 Final Project (Option 2: LLMs + AI Agent System)
**Raeeka Yusuf — 018233761 · Anil Kumar Bandaru — 018280223 · Cameron Lee — 014895556**

---

## Demo
> A spoiler-aware literary reading companion. Open any of 52 public-domain novels, set your current chapter, and ask anything — themes, character motives, symbolism, "main characters so far" — answered with inline citations and **strict guarantees against future-chapter spoilers**.

Brief Demonstration Video:
<video src="https://github.com/user-attachments/assets/19fa9a6d-7db5-4622-8aab-e292e6be2b69" controls width="640"></video>

Final Demonstration Video:



---

## Overview

A full-stack chapter-aware reading assistant that combines hybrid retrieval, a multi-step LLM agent, and a structured per-book character knowledge base to answer literary questions without revealing future plot events.

| Component | Details |
|-----------|---------|
| **Primary LLM** (open-source) | Llama 3.2:3b via Ollama (local, free) |
| **Comparison LLMs** | Claude Haiku 4.5 (Anthropic), GPT-4o-mini (OpenAI) |
| **Retrieval** | Hybrid: dense embeddings (`all-MiniLM-L6-v2`, 384-dim) + BM25 sparse, fused via Reciprocal Rank Fusion |
| **Vector store** | ChromaDB (in-memory, per book) |
| **Knowledge sources** | Project Gutenberg (full text, 52 books) · BookSum (scholarly analyses, 3,813 entries) · NarrativeQA (eval QA pairs) |
| **Agent** | Planner → Executor → Synthesizer → Critic, 4 LLM calls + 6 tools per question |
| **Memory** | SQLite — reading position, chat turns, LLM-summarized rolling memory |
| **Backend** | Flask (Python) on `:5050` |
| **Frontend** | Express (Node) on `:3000` — single-page library / reader / chat UI |

## Architecture

```
   Reader UI (Express, localhost:3000)
            │
            ▼
       Flask agent (Python, localhost:5050)
            │
   ┌────────┼────────────────────┐
   ▼        ▼                    ▼
Per-book   Multi-step           SQLite memory
RAG        Planner-Executor-    (reading pos,
(Chroma +  Synthesizer-Critic   chat history,
BM25 +     + 6 tools + 3-layer  LLM-summarized
character  spoiler safety       rolling memory)
graph)
            │
            ▼
   LLM (Llama 3.2:3b / Claude Haiku 4.5 / GPT-4o-mini, per-request)
```

## Repository Structure

```
├── README.md
├── docs/
│   ├── RUN.md                      # Detailed setup, run, and contribute guide
│   └── demo_script.md              # Live presentation demo walkthrough
├── python/
│   ├── requirements.txt
│   ├── scripts/
│   │   ├── api_server.py           # Flask: /ask, /memory, /index_book, /reading_position
│   │   ├── literary_guide_agent.py # Top-level answer() — wraps simple-RAG and agent modes
│   │   ├── agent_loop.py           # Planner → Executor → Synthesizer → Critic loop
│   │   ├── agent_tools.py          # 6 tools: retrieve_passages, lookup_character,
│   │   │                           #   summarize_chapter, retrieve_expert_analysis,
│   │   │                           #   list_known_characters, get_character_profile
│   │   ├── book_index.py           # Per-book hybrid retrieval (Chroma + BM25 + RRF)
│   │   ├── memory_store.py         # SQLite persistence + LLM-summarized memory
│   │   ├── safety.py               # Citation enforcement + name-grounding verifier
│   │   ├── chapter_numbering.py    # Canonical chapter-number extraction utility
│   │   ├── build_character_index.py# Pre-compute per-book character knowledge index
│   │   ├── fetch_library.py        # Pull books from Project Gutenberg
│   │   ├── fetch_booksum.py        # Pull BookSum analyses for catalog books
│   │   └── fetch_narrativeqa.py    # Convert NarrativeQA Q&A into eval cases
│   ├── eval/
│   │   ├── eval_cases.json         # 60 hand-written test cases
│   │   ├── narrativeqa_cases.json  # 68 NarrativeQA-derived cases
│   │   ├── run_eval.py             # JSONL-logging eval runner
│   │   └── runs/                   # Per-run results
│   └── data/
│       ├── books/                  # Gutenberg full texts (52 books)
│       ├── booksum/                # BookSum analyses (34 books)
│       ├── characters/             # Character knowledge index (52 books)
│       └── catalog.json            # Library metadata
└── js/
    ├── package.json
    ├── server.js                   # Express proxy + static server
    └── public/
        └── index.html              # Library + reader + chat (single-page app)
```

## How to Run

### Prerequisites

- **Python** 3.9+ (tested with 3.9 and 3.13 on macOS)
- **Node.js** 18+
- **Ollama** *(optional, for local open-source LLM)* — `brew install --cask ollama`
- **Anthropic API key** *(optional, for Claude comparison)* — https://console.anthropic.com
- **OpenAI API key** *(optional, for GPT-4o-mini comparison)* — https://platform.openai.com
- ~6 GB disk (26 MB books, 6 MB BookSum, ~2 GB if Ollama with Llama 3.2)

### Step 1: Clone and install Python deps

```bash
git clone https://github.com/raeeka-sjsu/Literary-Guide.git
cd Literary-Guide/python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 2: (Optional) Set up the open-source LLM

```bash
brew install --cask ollama
open -a Ollama          # starts the menubar service
ollama pull llama3.2:3b # ~2 GB download
```

### Step 3: (Optional) Set API keys for cloud LLM comparison

```bash
# In repo root
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
echo "OPENAI_API_KEY=sk-..."        >> .env
chmod 600 .env
```

The `.env` file is git-ignored. Flask reads it on startup.

### Step 4: Start backend (Terminal 1)

```bash
cd python && source venv/bin/activate
python scripts/api_server.py
```

Expected: `Literary Guide API listening on http://localhost:5050`

### Step 5: Start frontend (Terminal 2)

```bash
cd js
npm install
node server.js
```

Expected: `Literary Guide viewer running at http://localhost:3000`

### Step 6: Open the app

Navigate to **http://localhost:3000**.

1. Browse the library (search by title/author or filter by genre)
2. Click any book → reader opens with chapter-paginated text
3. In the chat pane: pick the LLM, toggle agent mode, ask questions
4. The "📓 Reader memory" panel shows what's been discussed; click **Update** to refresh

## How to Evaluate

```bash
cd python && source venv/bin/activate

# Run all 128 cases against one provider (60 hand-written + 68 NarrativeQA)
python eval/run_eval.py --provider ollama --out-prefix ollama_baseline

# Run all three providers back-to-back
python eval/run_eval.py --provider ollama,anthropic,openai --out-prefix three_way

# Smoke test (first 5 cases only)
python eval/run_eval.py --provider ollama --limit 5

# Filter to one category
python eval/run_eval.py --provider ollama --category spoiler_trap
```

Outputs: `python/eval/runs/<prefix>.jsonl` (per-case detail) + `<prefix>.summary.json` (aggregated).

### Eval set composition

| Category | Count | Scoring rule |
|---|---|---|
| `spoiler_trap` | 98 (30 hand + 68 NarrativeQA) | Pass if answer contains NONE of `forbidden_keywords` (negation-aware) AND no chunk has `chapter > current_chapter` |
| `analytical` | 20 | Pass if answer ≥ 60 words, ≥ 1 `[n]` citation, retrieval-safe |
| `refusal_or_edge` | 10 | If `must_refuse: true`, pass if answer contains a refusal keyword (or matches the system-wide refusal classifier). Else require non-empty + cited + safe. |
| **Total** | **128** | |

## Results

All three models were evaluated on the same 60 hand-written test questions and scored programmatically by `python eval/run_eval.py`. The scorer is negation-aware (a denial such as "the passages do not reveal X" is not counted as leaking X) and falls back to a system-wide refusal classifier when the case-specific keyword list does not match the model's chosen refusal phrasing. Numbers below are taken directly from the per-case JSONL logs in `python/eval/runs/`.

| Provider | Pass rate | Mean latency | Cost / 1000 queries |
|---|---|---|---|
| **Llama 3.2:3b** (open-source, runs locally) | **81.7%** (49/60) | 7,366 ms | $0.00 |
| **Claude Haiku 4.5** | **96.7%** (58/60) | 4,287 ms | $2.56 |
| **GPT-4o-mini** | **98.3%** (59/60) | 3,463 ms | $0.42 |

Per-category breakdown:

| Provider | Spoiler-trap | Analytical | Refusal |
|---|---:|---:|---:|
| Llama 3.2:3b | 83% | 95% | 50% |
| Claude Haiku 4.5 | 93% | 100% | 100% |
| GPT-4o-mini | 97% | 100% | 100% |

Claude and GPT-4o-mini were additionally evaluated on the full 128-case suite (60 hand-written plus 68 NarrativeQA-derived). Claude scored 92/100 (92%) and GPT-4o-mini scored 93/100 (93%). Llama was excluded from the extended run because local inference is bound to the laptop GPU; the 60-case suite serves as the directly comparable benchmark across all three providers. Full logs are available at `python/eval/runs/anthropic_100.jsonl` and `python/eval/runs/openai_100.jsonl`.

### Agent mode vs single-call RAG ablation

To assess whether the four-stage Planner-Executor-Synthesizer-Critic architecture improves answer quality over a single LLM call given the same retrieved chunks, 30 cases were evaluated through Claude in both modes:

| Mode | Pass rate | Mean latency |
|---|---|---|
| Simple-RAG (1 LLM call) | 29/30 (**96.7%**) | 4,712 ms |
| Agent mode (4 LLM calls) | 30/30 (**100%**) | 9,683 ms |

Agent mode achieves a 3.3-point absolute pass-rate gain over single-call RAG, at approximately twice the latency. The additional cost is attributable to structured tool routing (character-list questions are answered by the knowledge-graph lookup rather than vector search) and the Critic stage, which validates draft answers before returning them. Approximately 15–20% of agent-mode answers result in a Critic-driven rewrite. The full ablation is reported in `docs/failure_analysis.md`.

### Classification metrics — refusal task

In addition to overall pass rate, we report precision, recall, and F1 on the binary task of correctly refusing questions that require chapters the reader has not yet reached. The positive class consists of spoiler-trap cases plus refusal-or-edge cases marked `must_refuse: true` (38 of 60 cases).

| Provider | Precision | Recall | F1 | Accuracy |
|---|---:|---:|---:|---:|
| Llama 3.2:3b | 1.000 | 0.237 | 0.383 | 0.517 |
| Claude Haiku 4.5 | 0.902 | 0.974 | 0.937 | 0.917 |
| GPT-4o-mini | 0.949 | 0.974 | 0.961 | 0.950 |

Recall is the safety-critical metric in this domain: it measures the fraction of refusal-eligible questions that the model correctly declined. Llama produces an explicit refusal in only 23.7% of these cases; it engages with most spoiler-trap questions and avoids the forbidden keywords by chance, which inflates its raw pass rate. Claude and GPT-4o-mini both refuse appropriately 97.4% of the time. Llama's precision of 1.000 indicates that when it does refuse, the refusal is always warranted — its weakness is in failing to refuse, not in over-refusing. Implementation: `python/eval/build_comparison.py::classification_metrics`.

Summary observations:
- Both commercial models reach 100% on the analytical and refusal-or-edge categories. Llama's largest deficit is on refusal cases (50% vs 100%), consistent with the recall gap above.
- GPT-4o-mini achieves the highest pass rate on the 60-case suite and the lowest cost per query among the cloud providers in this evaluation.
- Spoiler-trap pass rates are 83% / 93% / 97% for Llama / Claude / GPT-4o-mini. The three-layer safety enforcement materially narrows the gap between the open-source and commercial models, but does not eliminate it.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Server status |
| `GET` | `/api/books` | Library catalog with chapter counts |
| `GET` | `/api/books/:id` | Single book with chapters |
| `POST` | `/api/index_book` | Build (or load cached) per-book RAG index |
| `POST` | `/api/ask` | Chapter-aware Q&A with citations |
| `GET` | `/api/memory/:book_id` | Reading position + chat history + memory summary |
| `POST` | `/api/memory/:book_id/summarize` | Compress recent turns into a rolling memory summary |
| `POST` | `/api/reading_position` | Update the user's current chapter for a book |
| `GET` | `/api/recent_books` | Books the user has been reading recently |

### Example: chapter-aware Q&A

```bash
curl -X POST http://localhost:3000/api/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What does Mr. Bennet'\''s sarcasm reveal about his marriage?",
    "chapter": 5,
    "book_id": "pride-and-prejudice",
    "provider": "anthropic",
    "agent_mode": true
  }'
```

Response (truncated):
```json
{
  "question": "...",
  "current_chapter": 5,
  "provider": "anthropic",
  "model": "claude-haiku-4-5",
  "answer": "Mr. Bennet's sarcasm reveals a husband fundamentally at odds with his wife's marital priorities [1][2]...",
  "memory_used": false,
  "retrieval_mode": "agent",
  "latency_ms": 5082,
  "safety": {"ok": true, "valid_citations": [1, 2], "ungrounded_names": []},
  "is_refusal": false,
  "agent": {
    "plan": {"reasoning": "Character + theme — profile, then thematic retrieve.", "steps": [...]},
    "tool_calls": [
      {"tool": "get_character_profile", "args": {...}, "n_results": 1, "latency_ms": 4},
      {"tool": "retrieve_passages",     "args": {...}, "n_results": 3, "latency_ms": 89}
    ],
    "critic": {"verdict": "PASS", "issues": []},
    "retried": false
  },
  "chunks": [...]
}
```

## System capabilities

The components below implement the non-trivial-capability requirement (Option 2 / D). All three D sub-options are present.

1. **Three-layer spoiler-safety architecture** — retrieval-side chapter filter at the database layer + synthesizer prompt rules + deterministic post-hoc name-grounding verifier. Implementation discussed in `docs/failure_analysis.md`.

2. **Automated structured character knowledge index per book** — regex+heuristic NER, alias resolution, mention timeline, co-occurrence tracking. Stored as queryable structured data per book under `python/data/characters/`.

3. **Hybrid RAG (D1)** — BM25 sparse + sentence-transformer dense, fused via Reciprocal Rank Fusion. Spoiler boundary applied at the database level before ranking.

4. **Planner-Executor-Synthesizer-Critic agent (D2)** — six tools, full per-step structured logging, deterministic grounding override on the Critic verdict. Quantified ablation in `docs/failure_analysis.md` (+6.7 pts on spoiler-traps vs single-call RAG with the same retrieved context).

5. **Long-horizon memory (D3)** — written (chat-turn log) + summarized (LLM compresses recent turns into a rolling memory) + retrieved (memory injected into next session's prompts). Persisted in SQLite with reading-position auto-restore.

6. **128-case eval suite** — 60 hand-written cases across 13 books + 68 NarrativeQA-derived cases. Three categories with category-specific scoring rules. JSONL per-case logs. Three LLMs evaluated: Llama 3.2:3b (open-source), Claude Haiku 4.5, GPT-4o-mini.

7. **Failure analysis** — `docs/failure_analysis.md` documents where the system breaks, why reported spoiler-leak rates are conservative (eval scorer over-counts on negation phrasing), where agent mode regresses vs simple-RAG, and what we plan to train next.

## Mapping to Option 2 rubric

| Rubric requirement | Where it's implemented |
|--------------------|------------------------|
| **A. Problem formulation** | Spoiler-aware literary reading companion (vertical: literature education) |
| **B. Few-shot examples + 50+ eval cases** | 3 worked examples in synthesizer prompt; 128-case eval suite (60 hand-written across 13 books in three categories, plus 68 NarrativeQA-derived across 13 additional books) |
| **C. ≥3 LLMs incl. ≥1 open-source** | Llama 3.2:3b (open-source primary) + Claude Haiku 4.5 + GPT-4o-mini, all run via `eval/run_eval.py --provider <name>` |
| **D1. Advanced RAG** | Hybrid retrieval (BM25 + dense + RRF) in `book_index.py`; structured character lookup (Knowledge-Graph-style) in `agent_tools.py` |
| **D2. Planner-Executor-Critic agent** | `agent_loop.py` — 4-stage pipeline; 6 tools logged to SQLite `tool_call` table |
| **D3. Long-horizon memory** | `memory_store.py` — written (chat turns) + summarized (rolling LLM summary) + retrieved (injected on next session) |
| **E. UI + state + safety + logging + tests** | Express SPA; SQLite persistence; 3-layer spoiler safety (retrieval bound + prompt rules + grounding verifier); JSONL eval logs + SQLite tool_call logs; 128-case eval suite |

## Datasets used (per proposal)

1. **Project Gutenberg** — primary book text source (52 books)
2. **BookSum** ([`kmfoda/booksum`](https://huggingface.co/datasets/kmfoda/booksum)) — scholarly chapter analyses, used as the agent's `retrieve_expert_analysis` tool
3. **NarrativeQA** ([deepmind/narrativeqa](https://github.com/google-deepmind/narrativeqa)) — human-written question-answer pairs over story texts, converted into 68 additional evaluation cases that provide externally-authored validation of the system

## References

- Kryściński et al., *BookSum: A Collection of Datasets for Long-form Narrative Summarization*. 2021. https://arxiv.org/abs/2105.08209
- Sentence-Transformers `all-MiniLM-L6-v2`: https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
- Cormack, Clarke, Buettcher, *Reciprocal rank fusion outperforms Condorcet and individual rank learning methods*. SIGIR 2009.
