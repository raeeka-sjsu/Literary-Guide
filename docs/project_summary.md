# Literary Guide — Project Summary

CMPE 258 Spring 2026, Option 2 (LLMs + AI Agent System). This document summarizes the project for reference and slide preparation.

## Description

A spoiler-aware literary reading companion. The user opens one of 52 public-domain novels, sets a current chapter, and submits questions about themes, character motives, symbolism, or character lists. The system returns a grounded, citation-backed answer that does not reference events from chapters the reader has not yet reached. Spoiler enforcement operates at three independent layers: retrieval-side filtering at the database layer, prompt-side rules in the synthesizer system prompt, and a deterministic post-hoc grounding verifier.

## Mapping to Option 2 requirements

| Requirement | Implementation |
|---|---|
| **A. Problem formulation** | Vertical use case: chapter-aware literary analysis without future-plot disclosure. |
| **B. Data + ≥50 evaluation cases + few-shot examples** | Three datasets (Project Gutenberg full text, BookSum scholarly analyses, NarrativeQA QA pairs); 128 evaluation cases (60 hand-written, 68 NarrativeQA-derived); three few-shot examples in the synthesizer system prompt. |
| **C. ≥3 LLMs including ≥1 open-source** | Llama 3.2:3b (open-source primary, served locally via Ollama), Claude Haiku 4.5, GPT-4o-mini. All three were evaluated on the same 60-case suite. Performance, cost, and latency are reported in `python/eval/comparison.md`. |
| **D1. Advanced RAG** | Hybrid retrieval: BM25 sparse + sentence-transformer dense, fused via Reciprocal Rank Fusion. A structured per-book character knowledge index supports name-centered queries. |
| **D2. Tool-using agent** | Four-stage Planner → Executor → Synthesizer → Critic loop with six tools. Every tool call is logged to a SQLite `tool_call` table. |
| **D3. Long-horizon memory** | SQLite-backed reading position, chat-turn log, and an LLM-summarized rolling memory that is written, compressed, and retrieved into the next session's prompt. |
| **E. UI + state + safety + structured logging + tests** | Express front-end with library, reader, chat, and memory panel; SQLite session persistence and reading-position auto-restore; three-layer spoiler safety; per-case JSONL evaluation logs and SQLite tool-call logs; programmatically scored 128-case evaluation suite. |
| Course rules: no commercial-only model as primary | Llama is the demonstration default; Claude and GPT are used for comparison only. |

## Approach

Pre-trained language models are likely to leak plot details from their training data when asked literary questions about well-known books. Literary Guide constrains the model's available context to the chapters the reader has already read. Each passage in the per-book retrieval index is tagged with its chapter number; queries filter to chapters at or before the reader's current chapter before ranking. A four-stage agent then routes each question to an appropriate tool — structured character lookup, vector retrieval, scholarly analysis retrieval, or full-chapter access — drafts an answer with inline citations, and runs a critic step that fails any answer mentioning a proper noun or fact not present in the cited passages. The result is a system that supports literary discussion at chapter-by-chapter granularity while preventing forward-leaking content from reaching the user.

## Architecture

```
   Reader UI (Express, localhost:3000)
            │
            ▼
   Flask agent (Python, localhost:5050)
            │
   ┌────────┼────────────────────┐
   ▼        ▼                    ▼
Per-book   Multi-step agent     SQLite memory
RAG        (Planner → Executor  (reading position,
(Chroma +  → Synthesizer →      chat turns,
BM25 +     → Critic, 6 tools,   LLM-summarized
character  3-layer safety)      rolling memory)
index)
            │
            ▼
   LLM (Llama 3.2:3b open-source / Claude Haiku 4.5 / GPT-4o-mini)
```

## File-by-file summary

```
js/server.js                  Express proxy and static file server. Routes /api/*
                              requests to Flask, serves the front-end at :3000.

js/public/index.html          Single-page application with library grid, paginated
                              chapter reader, and chat panel. Renders agent steps
                              live, displays cited passages, manages the memory panel.

python/scripts/api_server.py  Flask application. Endpoints: /ask, /index_book,
                              /memory/<book_id>, /memory/<book_id>/summarize,
                              /reading_position, /recent_books. All requests
                              dispatch to literary_guide_agent.answer().

python/scripts/literary_guide_agent.py
                              Top-level answer() function. With agent_mode=False,
                              calls the LLM once with retrieved passages. With
                              agent_mode=True, dispatches to agent_loop.run_agent.
                              Returns a uniform response containing the answer,
                              chunks, agent trace (plan, tool calls, critic verdict),
                              safety report, and latency.

python/scripts/agent_loop.py  The four-stage Planner-Executor-Synthesizer-Critic
                              loop. The Planner LLM emits a structured JSON tool
                              plan; the Executor invokes tools in order and records
                              each call; the Synthesizer drafts the answer with [n]
                              citations; the Critic verifies. A deterministic
                              grounding override forces a Critic FAIL whenever the
                              answer contains a proper noun absent from the cited
                              passages. Up to one retry is performed on failure.

python/scripts/agent_tools.py Implementations of the six tools the agent can call:
                              retrieve_passages (hybrid retrieval over Gutenberg
                              text), lookup_character (passage retrieval centered
                              on a character name), summarize_chapter (full chapter
                              text on demand), retrieve_expert_analysis (BookSum
                              scholarly commentary), list_known_characters
                              (structured character lookup), and
                              get_character_profile (single-character timeline
                              and co-occurrences).

python/scripts/book_index.py  Per-book retrieval layer. Builds a Chroma collection
                              of chunk embeddings and a parallel BM25 index. The
                              query function performs both dense and sparse
                              retrieval, fuses results via Reciprocal Rank Fusion,
                              and applies the chapter-limit filter before ranking.
                              Always prepends one or more chunks from the reader's
                              current chapter so that page-local questions remain
                              answerable.

python/scripts/memory_store.py
                              SQLite persistence layer. Three tables:
                              reading_position (per user, per book), chat_turn
                              (full Q&A log including provider, model, latency,
                              and chunk IDs), and book_memory (rolling LLM-
                              summarized memory). A tool_call table logs each
                              agent tool invocation with foreign-key linkage to
                              chat_turn.

python/scripts/safety.py      Citation enforcement and grounding verification.
                              Extracts proper nouns from a candidate answer and
                              checks each one against the retrieved chunks.
                              Provides a system-wide is_refusal classifier
                              recognizing approximately 25 refusal phrasings.

python/scripts/chapter_numbering.py
                              Canonical chapter-number extraction utility.
                              Parses chapter titles in Roman, Arabic, or word
                              form (for example, "CHAPTER ONE"). Used wherever
                              a chunk or character mention is tagged with a
                              chapter number, ensuring the user-visible chapter,
                              the chunk metadata, and the spoiler filter agree.

python/scripts/build_character_index.py
                              Pre-computes the per-book character registry from
                              the parsed Gutenberg text. Performs regex- and
                              heuristic-based named entity extraction, alias
                              resolution (for example, "Mr. Bennet" and "Bennet"
                              are merged), mention timeline construction, and
                              co-occurrence tracking. Output is written to
                              python/data/characters/<book_id>.json.

python/scripts/fetch_library.py
                              Downloads books from Project Gutenberg by ID,
                              splits each into chapters using a multi-pattern
                              regex, and saves to python/data/books/<book_id>.json.

python/scripts/fetch_booksum.py
                              Streams the BookSum dataset from Hugging Face and
                              filters to the books in our catalog. Saves matching
                              entries (chapter summary plus scholarly analysis)
                              to python/data/booksum/<book_id>.json.

python/scripts/fetch_narrativeqa.py
                              Streams the NarrativeQA dataset across all splits
                              and filters to books in our catalog. Converts each
                              human-written question into an evaluation case with
                              forbidden-keyword spoiler markers automatically
                              extracted from the human reference answer.

python/eval/eval_cases.json   60 hand-written test cases across 13 books in three
                              categories: spoiler_trap (30 cases), analytical
                              (20 cases), and refusal_or_edge (10 cases).

python/eval/narrativeqa_cases.json
                              68 NarrativeQA-derived test cases across 13
                              additional books, used as externally-authored
                              validation.

python/eval/run_eval.py       Evaluation runner. For each case, calls the chosen
                              provider, scores the answer against category-
                              specific rules (negation-aware spoiler-keyword
                              matching, citation presence, retrieval-boundary
                              compliance, refusal detection with system-wide
                              fallback), and writes a per-case JSONL log.
                              Supports the --agent flag for evaluating agent mode.

python/eval/build_comparison.py
                              Aggregates per-provider statistics from the JSONL
                              logs: pass rate by category, latency mean and p95,
                              estimated token cost, spoiler-leak rate, and
                              precision, recall, F1, and accuracy on the binary
                              refusal classification task. Outputs comparison.md
                              (formatted tables), comparison.tsv (spreadsheet),
                              and comparison.json (machine-readable).
```

## Deep learning components

| Model | Architecture | Role | Trained by us |
|---|---|---|---|
| `all-MiniLM-L6-v2` | BERT-family bi-encoder, 22M parameters, contrastive pre-training | Encodes each chunk and each query into a 384-dimensional dense vector for cosine retrieval | No (pre-trained, used at inference time) |
| Llama 3.2 3B | Decoder-only transformer | Open-source primary LLM, served locally via Ollama | No (pre-trained and instruction-tuned by Meta) |
| Claude Haiku 4.5 | Decoder-only transformer | Comparison LLM, accessed via API | No |
| GPT-4o-mini | Decoder-only transformer | Comparison LLM, accessed via API | No |

We do not fine-tune. The Option 2 rubric explicitly permits "for prompting OR tuning"; our work focuses on system architecture, evaluation, and safety enforcement on top of pre-trained models. A fine-tuned spoiler-detection classifier remains an item on the May 19 final-report backlog.

## Datasets

1. **Project Gutenberg** — full original text of 52 public-domain novels. Primary text source used both for the reader UI and as the corpus for retrieval embeddings.
2. **BookSum** ([`kmfoda/booksum`](https://huggingface.co/datasets/kmfoda/booksum)) — 3,813 human-written chapter analyses across 34 of those books, used as the agent's `retrieve_expert_analysis` tool to provide critical context alongside original-text retrieval.
3. **NarrativeQA** ([deepmind/narrativeqa](https://github.com/google-deepmind/narrativeqa)) — human-written question-answer pairs over story texts, converted into 68 additional evaluation cases that provide externally-authored validation alongside the 60 internal cases.

## Evaluation results

The 128-case evaluation suite is divided into three categories. All cases are scored programmatically.

### Three-LLM comparison on 60 hand-written cases

| Provider | Pass rate | Recall | F1 | Mean latency | Cost / 1000 queries |
|---|---|---|---|---|---|
| Llama 3.2:3b (open-source, local) | 81.7% | 0.237 | 0.383 | 7,366 ms | $0.00 |
| Claude Haiku 4.5 | 96.7% | 0.974 | 0.937 | 4,287 ms | $2.56 |
| GPT-4o-mini | 98.3% | 0.974 | 0.961 | 3,463 ms | $0.42 |

Recall, computed against the binary "should this question trigger a refusal?" task, captures the safety-critical aspect of the system: it measures the fraction of refusal-eligible questions for which the model produced an explicit refusal. The two commercial models refuse appropriately approximately 97% of the time. Llama refuses approximately 24% of the time; the remainder of its passes on refusal-eligible questions are attributable to the model engaging with the question while happening to avoid the case-specific forbidden keyword.

### Agent mode vs single-call RAG ablation

Identical 30 cases evaluated through Claude Haiku in both modes:

| Mode | Pass rate | Mean latency |
|---|---|---|
| Simple-RAG (1 LLM call) | 96.7% | 4,712 ms |
| Agent mode (4 LLM calls) | 100.0% | 9,683 ms |

The four-stage architecture yields a 3.3-point absolute pass-rate gain at approximately twice the latency. Approximately 15–20% of agent-mode answers are revised by the Critic stage before being returned.

## Suggested slide structure

1. Title slide (project name, team members, course)
2. Problem statement (LLMs leaking plot details from training data)
3. Approach (chapter-aware retrieval with three-layer safety enforcement and a four-stage agent)
4. Architecture diagram
5. Live demonstration
6. Evaluation methodology (128-case suite, three categories, programmatic scoring)
7. Three-LLM comparison table
8. Classification metrics (precision, recall, F1)
9. Agent-vs-single-call ablation
10. Failure analysis highlights
11. Remaining work for the May 19 final report
12. Q&A

## Repository

https://github.com/raeeka-sjsu/Literary-Guide (branch: `raeeka-test`)

Run instructions in `docs/RUN.md`. Demonstration walkthrough in `docs/demo_script.md`. Failure analysis in `docs/failure_analysis.md`. Final-report outline in `docs/final_report_outline.md`.
