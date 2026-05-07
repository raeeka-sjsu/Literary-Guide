# Literary Guide — Project Summary

For pasting into another chat (e.g., to generate slides) so it has full context. CMPE 258 SP26 — Option 2.

## What it is

A **spoiler-aware reading companion**. Open any of 52 public-domain novels, set your current chapter, ask anything — themes, character motives, symbolism, "main characters so far" — get a grounded, citation-backed answer that **never leaks events from chapters you haven't read**.

Picture Kindle X-Ray + ChatGPT, but with three-layer architectural guarantees that the system can't reveal future plot.

## Why it's not a chatbot wrapper

1. **Multi-step agent (Planner → Executor → Synthesizer → Critic)** with 6 tools and per-step logging. Quantitative ablation: agent mode is +3.3 points on hard cases vs single LLM call.
2. **Three-layer spoiler safety**: retrieval bound (DB-level chapter filter), prompt rules, and a deterministic post-hoc name-grounding verifier. A leak has to defeat all three.
3. **Auto-built per-book character knowledge index** with alias resolution and co-occurrence tracking — a Knowledge-Graph-style RAG layer (no human curation, all extracted from raw text).
4. **Hybrid retrieval** (BM25 sparse + sentence-transformer dense, fused via Reciprocal Rank Fusion) over the spoiler-bounded corpus.
5. **Long-horizon memory** that's written, summarized, and retrieved across sessions (SQLite + LLM compression). Reading position auto-restores.

## The story in 1 paragraph

LLMs can spoil books because they've read them all in pre-training. Literary Guide solves this with a chapter-aware retrieval system: every passage in the database is tagged with its chapter; at query time, only chapters ≤ the user's current page are eligible for retrieval. A four-stage agent then routes the question to the right tool (structured character lookup vs vector retrieval vs scholarly analysis), drafts an answer, and runs a critic step that hard-fails any answer mentioning a name or fact not present in the cited passages. The result: a system that talks about books at literary-discussion depth without leaking the ending.

## Architecture in one picture

```
   Reader UI (Express, :3000)
            │
            ▼
   Flask agent (Python, :5050)
            │
   ┌────────┼────────────────────┐
   ▼        ▼                    ▼
Per-book   Multi-step agent     SQLite memory
RAG        (Planner → Executor  (reading pos,
(Chroma +  → Synthesizer →      chat turns,
BM25 +     → Critic, 6 tools,   LLM-summarized
character  3-layer safety)      rolling memory)
graph)
            │
            ▼
   LLM (Llama 3.2:3b open-source / Claude Haiku 4.5 / GPT-4o-mini)
```

## What connects to what — file-by-file

```
js/server.js                  Express proxy & static server. Routes /api/* to Flask.
js/public/index.html          Single-page library + reader + chat UI. Renders agent steps
                              live, displays cited passages, handles memory panel.

python/scripts/api_server.py  Flask. Endpoints: /ask, /index_book, /memory/<book>,
                              /memory/<book>/summarize, /reading_position. Hands every
                              request off to literary_guide_agent.answer().

python/scripts/literary_guide_agent.py
                              The single answer() function. In agent_mode=False, calls
                              the LLM once with retrieved passages. In agent_mode=True,
                              dispatches to agent_loop.run_agent. Returns a uniform
                              dict with: answer, chunks, agent (plan/tool_calls/critic),
                              safety report, latency.

python/scripts/agent_loop.py  The 4-stage Planner-Executor-Synthesizer-Critic loop.
                              Planner (LLM) outputs JSON tool plan. Executor invokes
                              tools, logs each call to SQLite. Synthesizer drafts
                              answer with [n] citations. Critic verifies; deterministic
                              grounding check overrides verdict to FAIL on hallucinated
                              names. Up to 1 retry on FAIL.

python/scripts/agent_tools.py 6 tools the agent can call:
                              - retrieve_passages    (hybrid Gutenberg retrieval)
                              - lookup_character     (passage retrieval focused on a name)
                              - summarize_chapter    (full chapter text)
                              - retrieve_expert_analysis  (BookSum scholarly commentary)
                              - list_known_characters     (structured character lookup)
                              - get_character_profile     (single character + timeline)

python/scripts/book_index.py  Per-book Chroma collection (vectors) + BM25 keyword index.
                              query_book() does dense + BM25 retrieval, fuses via RRF,
                              filters by chapter ≤ current. Always includes current
                              chapter as a baseline so questions about the page you're
                              reading always have that context.

python/scripts/memory_store.py
                              SQLite layer. Three tables: reading_position (per user
                              per book), chat_turn (every Q&A logged), book_memory
                              (LLM-summarized rolling memory). Exposes record_chat_turn,
                              get_memory_summary, summarize_session.

python/scripts/safety.py      Citation enforcement + name-grounding verifier. Extracts
                              proper nouns from the answer, checks each appears in at
                              least one cited chunk, flags hallucinated names.
                              is_refusal() classifier with ~25 phrasings.

python/scripts/chapter_numbering.py
                              Single source of truth for canonical chapter numbers.
                              Parses titles in Roman, Arabic, or word form ("Chapter ONE").
                              Used everywhere chapters are tagged.

python/scripts/build_character_index.py
                              Pre-builds the per-book character registry: regex+heuristic
                              NER, alias resolution, mention timeline, co-occurrences.
                              Output to python/data/characters/<book_id>.json.

python/scripts/fetch_library.py
                              Downloads books from Project Gutenberg, splits into
                              chapters, saves to python/data/books/<book_id>.json.

python/scripts/fetch_booksum.py
                              Pulls human-written chapter analyses from the BookSum
                              dataset (CliffsNotes/SparkNotes/Shmoop) for books in
                              our catalog.

python/scripts/fetch_narrativeqa.py
                              Pulls human-written QA pairs from NarrativeQA, filters
                              to books in our catalog, converts to eval cases with
                              auto-extracted spoiler keywords.

python/eval/eval_cases.json   60 hand-written test cases across 13 books, 3 categories:
                              spoiler_trap (30), analytical (20), refusal_or_edge (10).

python/eval/narrativeqa_cases.json
                              68 NarrativeQA-derived cases for additional validation.

python/eval/run_eval.py       Eval runner. Calls each provider per case, scores
                              (negation-aware spoiler detection + system-wide refusal
                              fallback + retrieval-violation check), writes JSONL +
                              summary.json. Supports --agent flag.

python/eval/build_comparison.py
                              Reads JSONL logs, computes per-provider stats: pass rate,
                              latency mean/p95, cost estimate, spoiler-leak rate, AND
                              precision/recall/F1 on the binary refusal task. Writes
                              comparison.md (slide-ready), comparison.tsv (spreadsheet),
                              comparison.json (machine-readable).
```

## Deep learning content

| Model | Type | Use | Trained by us? |
|---|---|---|---|
| `all-MiniLM-L6-v2` | 22M-param BERT-family sentence encoder | Embed every chunk and query into 384-dim vectors for cosine retrieval | No, pre-trained via contrastive learning |
| Llama 3.2 3B | decoder-only transformer | Primary LLM, runs locally via Ollama | No, pre-trained + instruction-tuned by Meta |
| Claude Haiku 4.5 | larger commercial transformer | Comparison LLM | No, used via API |
| GPT-4o-mini | larger commercial transformer | Comparison LLM | No, used via API |

We do not fine-tune. The rubric explicitly allows prompting OR tuning. Our novel contribution is system architecture (multi-step agent, hybrid retrieval, structured grounding, three-layer safety), not new model weights. A fine-tuned spoiler-detection classifier is on the May-19 backlog as a stretch goal.

## Datasets

1. **Project Gutenberg** — full original text of 52 public-domain novels (primary text source for retrieval AND display)
2. **BookSum** ([`kmfoda/booksum`](https://huggingface.co/datasets/kmfoda/booksum)) — 3,813 human-written chapter analyses across 34 of those books (used as the agent's `retrieve_expert_analysis` tool)
3. **NarrativeQA** ([deepmind/narrativeqa](https://github.com/google-deepmind/narrativeqa)) — human-written QA pairs converted into 68 eval cases for external validation

## Evaluation

128-case suite, 3 categories, all programmatically scored.

**60-case 3-LLM comparison (apples-to-apples on the same hand-written cases):**

| Provider | Accuracy | Recall | F1 | Mean latency | Cost / 1000 queries |
|---|---|---|---|---|---|
| Llama 3.2:3b (open-source, local) | 81.7% | 0.237 | 0.383 | 7.4 s | $0.00 |
| Claude Haiku 4.5 | 96.7% | 0.974 | 0.937 | 4.3 s | $2.56 |
| GPT-4o-mini | 98.3% | 0.974 | 0.961 | 3.5 s | $0.42 |

Recall = of questions that should have triggered a refusal, what fraction did the model correctly refuse. Llama explicitly refuses 24% of the time; Claude and GPT 97%. Llama precision = 1.000 (when it does refuse, always correct) — under-detector, not sloppy.

**Agent vs simple-RAG ablation (same 30 cases through Claude):**

| Mode | Accuracy | Mean latency |
|---|---|---|
| Simple-RAG (1 LLM call) | 96.7% | 4.7 s |
| Agent mode (4 LLM calls) | 100% | 9.7 s |

+3.3 points for the multi-step architecture at 2× latency. The Critic stage triggers a rewrite on ~15-20% of agent answers — those rewrites materially improve quality.

## What graders should walk away knowing

1. **All 7 of the rubric's Option-2 requirements are met** — see README "Mapping to Option 2 rubric" section.
2. **3 LLMs evaluated on identical 60-case suite**: Llama / Claude / GPT.
3. **Option D capability requirement: ALL THREE sub-options satisfied** (advanced RAG with hybrid + GraphRAG-style character index, Planner-Executor-Critic agent, long-horizon memory).
4. **Real failure analysis** at `docs/failure_analysis.md` shows we know exactly where the system breaks and why our reported numbers are conservative (eval scorer originally over-counted leaks; we caught and fixed it).
5. **Datasets faithful to original proposal**: Gutenberg, BookSum, NarrativeQA all integrated in their proper roles.

## Slide structure suggestion

1. Title (project, team, course)
2. Problem (LLMs spoil books — why this is hard)
3. Solution (chapter-aware retrieval + multi-step agent + 3-layer safety)
4. Architecture diagram
5. Live demo (Pride and Prejudice ch 5, ask Mr. Bennet's sarcasm question; switch chapter, ask spoiler-trap, show refusal)
6. Eval set (60 hand + 68 NarrativeQA = 128 total, 3 categories)
7. 3-LLM comparison table (the headline numbers above)
8. Classification metrics: precision/recall/F1 — show the recall gap between Llama (24%) and commercial models (97%)
9. Agent ablation (+3.3 pts proves the multi-step architecture earns its compute)
10. Failure analysis 1-slide highlights
11. Roadmap to May 19 final report
12. Q&A — see `docs/demo_script.md` for prepared answers

## Repo

https://github.com/raeeka-sjsu/Literary-Guide (branch: `raeeka-test`)

Run instructions in `docs/RUN.md`. Demo script in `docs/demo_script.md`. Failure analysis in `docs/failure_analysis.md`. Final report outline in `docs/final_report_outline.md`.
