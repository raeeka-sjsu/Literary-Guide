# Literary Guide — Final Report Outline

For the May 19 final submission. This is the structure the report should follow, mapped to the CMPE 258 Option 2 rubric. Source content for each section is already present in the codebase or in `python/eval/comparison.md`.

---

## 1. Problem Formulation

> Maps to rubric A.

- One paragraph describing the problem (large language models pre-trained on public-domain books are likely to leak plot information when asked literary questions about those books) and the use case (chapter-aware reading companion for readers, book clubs, and literature students).
- Inputs: book identifier, current chapter, user question.
- Outputs: a grounded, citation-backed answer that respects the chapter boundary.
- Success criteria: at least 80% pass rate on the 128-case evaluation suite, low spoiler-leak rate as measured by recall on the binary refusal task, and 100% retrieval-boundary compliance.

## 2. Data and Evaluation Set

> Maps to rubric B.

- Three datasets, faithful to the project proposal:
  - Project Gutenberg — 52 public-domain novels, primary text source. Report total chapter count, word-count distribution, and genre breakdown.
  - BookSum — 3,813 human-written chapter analyses across 34 of those books, used as the agent's `retrieve_expert_analysis` tool.
  - NarrativeQA — 68 human-written question-answer pairs across 13 books, used as evaluation expansion.
- Few-shot examples in the synthesizer prompt: three worked examples covering analytical-in-bounds, spoiler-trap-refuse, and no-evidence-refuse cases. Include the prompt verbatim in the appendix.
- Evaluation set composition:
  - 30 hand-written spoiler-trap cases
  - 20 hand-written analytical cases
  - 10 hand-written refusal-or-edge cases
  - 68 NarrativeQA-derived cases (treated as spoiler-trap with auto-extracted forbidden keywords)
  - **Total: 128 cases**
- Scoring rules per category, paraphrased from `python/eval/run_eval.py`.

## 3. Models Compared

> Maps to rubric C.

- Llama 3.2:3b via Ollama — open-source primary model, runs locally without an API key.
- Claude Haiku 4.5 via Anthropic API — cloud comparison.
- GPT-4o-mini via OpenAI API — cloud comparison.
- All three were evaluated on the same 60 hand-written cases. Claude and GPT-4o-mini were additionally evaluated on the full 128-case suite.
- Pre-trained models only; no fine-tuning was performed (the rubric explicitly permits prompting).
- Reproducibility: temperatures pinned, prompts checked into git, per-case JSONL logs included.

## 4. Retrieval Architecture

> Maps to rubric D1 (Advanced RAG).

- Hybrid retrieval combining MiniLM dense embeddings and BM25 sparse keyword scoring, fused via Reciprocal Rank Fusion.
- Include a retrieval-flow diagram.
- Chunking strategy: approximately 400-word paragraph chunks tagged with `(book_id, chapter, chunk_in_chapter, chapter_title)` metadata.
- Spoiler boundary: the chapter filter is applied at the database level before ranking, ensuring that no chunk from a chapter beyond the reader's current chapter can be returned.
- Per-book index: a ChromaDB collection is lazily built on first query for each book and cached in memory.
- Knowledge-graph-style character index: per-book entity registry containing first-chapter, alias resolution, mention timeline, and co-occurrences. Used by the `list_known_characters` and `get_character_profile` tools.

## 5. Agent Architecture

> Maps to rubric D2 (Tool-using Agent).

- Four-stage Planner-Executor-Synthesizer-Critic loop:
  1. Planner LLM classifies the question and emits a structured JSON tool plan.
  2. Executor invokes tools sequentially and logs each call to the SQLite `tool_call` table.
  3. Synthesizer LLM produces a draft answer with `[n]` citations.
  4. Critic LLM verifies the draft. A deterministic name-grounding check overrides the verdict to FAIL when the answer contains a proper noun absent from the cited passages.
  5. On failure, up to one retry is performed with a hint from the Critic.
- Six tools:
  1. `retrieve_passages` — hybrid retrieval over the original Gutenberg text.
  2. `lookup_character` — passage retrieval centered on a character name.
  3. `summarize_chapter` — full chapter text on demand.
  4. `retrieve_expert_analysis` — BookSum scholarly analysis retrieval.
  5. `list_known_characters` — structured character lookup.
  6. `get_character_profile` — single-character profile with timeline and co-occurrences.
- Include a screenshot of the agent strip in the UI.

## 6. Memory Architecture

> Maps to rubric D3 (Long-Horizon Memory).

- SQLite store with three tables:
  - `reading_position` — per (user, book), the reader's current chapter.
  - `chat_turn` — every Q&A turn with retrieved chunk IDs, latency, model, and provider.
  - `book_memory` — per (user, book), an LLM-summarized rolling memory.
- Written → summarized → retrieved flow:
  - Each agent turn writes to `chat_turn`.
  - User-triggered or scheduled summarization compresses recent turns plus the prior summary into an updated memory.
  - On the next session, the summary is injected into the synthesizer system prompt as background context.
- This is the "written, summarized, retrieved" pattern the rubric specifies for D3.

## 7. Safety and Guardrails

> Maps to rubric E (safety and guardrails portion).

- Three independent layers of spoiler safety:
  1. Retrieval-side: chapter filter applied at the database level before ranking.
  2. Prompt-side: synthesizer system prompt forbids drawing on outside knowledge of the book; includes few-shot examples of correct refusal.
  3. Post-hoc grounding verifier: extracts proper nouns from the candidate answer and verifies each appears in at least one cited passage; if any are absent, the Critic verdict is overridden to FAIL and a rewrite is triggered.
- Citation enforcement: every factual claim must cite at least one passage; missing citations cause a Critic failure.
- Refusal pattern: machine-detectable refusal phrasings recognized by `safety.is_refusal()`.
- Rationale for the three-layer design: the prompt rules alone are insufficient because pre-trained LLMs have already read most public-domain books and tend to leak from their parametric memory when the prompt context is thin. Architectural enforcement at retrieval time and post-hoc verification provide the guarantees the prompt cannot.

## 8. Logging

> Maps to rubric E (structured logging portion).

- JSONL evaluation logs in `python/eval/runs/*.jsonl` — one record per case containing the question, retrieved chunks, answer, latency, score, and category-specific scoring detail.
- SQLite `tool_call` table — every tool invocation by every agent run, with arguments, result counts, latency, and a foreign key to the parent chat turn.
- SQLite `chat_turn` table — every user-facing Q&A with model, provider, retrieval mode, and latency.
- All entries are persisted; nothing is held only in memory.

## 9. User Interface

> Maps to rubric E1.

- Library landing page with title and author search and genre filter.
- Reader page with paginated chapters, chapter-dropdown navigation, in-chapter text search, hover-to-highlight on paragraphs, and click-to-prompt suggestions.
- Chat pane: provider dropdown, agent-mode toggle, animated four-stage agent strip, expandable cited passages.
- Memory panel: rolling summary display with an Update control to recompute.
- Reading-position auto-restore on book reopen.
- Include a screenshot for each major section.

## 10. Results

> Maps to rubric C3.

Drop the comparison table from `python/eval/comparison.md`:

| Provider | Pass rate | Mean latency | Cost / 1000 queries |
|---|---|---|---|
| Llama 3.2:3b (open-source, local) | 81.7% | 7,366 ms | $0.00 |
| Claude Haiku 4.5 | 96.7% | 4,287 ms | $2.56 |
| GPT-4o-mini | 98.3% | 3,463 ms | $0.42 |

The above is the 60-case directly-comparable run. Claude and GPT-4o-mini were also evaluated on the full 128-case suite (60 hand-written plus 68 NarrativeQA), scoring 92% and 93% respectively. Llama on the full 128-case suite is the planned final-report addition.

Include a per-category breakdown table and the precision-recall-F1 confusion-matrix table for the binary refusal task.

Divergence analysis: of the 60 cases, 42 were passed by all three models, 11 were failed only by Llama, and 1 was passed only by Llama.

Discussion paragraph: GPT-4o-mini achieved the highest pass rate on this benchmark and the lowest cost per query among the cloud providers; Claude's mean latency is higher than its median latency due to occasional long responses; Llama's largest deficit is on the refusal-or-edge category, consistent with its low recall on the binary refusal task.

## 11. Limitations and Future Work

- Chapter-level (not paragraph-level) spoiler boundary. Finer-grained protection would require per-paragraph chapter tagging, which is brittle for older Gutenberg texts.
- Character extraction is regex- and heuristic-based. A fine-tuned BERT NER model would be more robust at the cost of opacity and runtime overhead. Regex was chosen for transparency and zero runtime cost.
- No fine-tuning. A fine-tuned spoiler-detection classifier — a small encoder trained on `(answer, future_chapter_text)` pairs — would close most of the recall gap on Llama.
- In-memory ChromaDB. Restarting the server clears the cache; rebuilding a per-book collection on first query takes approximately five seconds. A persistent ChromaDB instance would reduce cold-start latency.
- No multi-user support. The `user_id` field is fixed at "default" for the current demonstration.
- Citation jump-to-source: answers cite passages but the reader does not yet auto-scroll to the cited passage on click.

## 12. References

- CMPE 258 Lecture, Option 2 rubric.
- Project proposal (submitted by team).
- Kryściński, W., Rajani, N., Agarwal, D., Xiong, C., Radev, D. *BookSum: A Collection of Datasets for Long-form Narrative Summarization*. 2021. arXiv:2105.08209.
- Kočiský, T., Schwarz, J., Blunsom, P., Dyer, C., Hermann, K. M., Melis, G., Grefenstette, E. *The NarrativeQA Reading Comprehension Challenge*. ACL 2018.
- Cormack, G. V., Clarke, C. L. A., Buettcher, S. *Reciprocal rank fusion outperforms Condorcet and individual rank learning methods*. SIGIR 2009.
- Reimers, N., Gurevych, I. *Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks*. EMNLP 2019. (Underlying architecture for `all-MiniLM-L6-v2`.)

## 13. Appendix

- Repository structure (from README).
- Reproduction commands (from `docs/RUN.md`).
- Sample evaluation cases (three to five per category).
- Demonstration script (from `docs/demo_script.md`).
- Failure-mode catalog (three to five representative cases with cause analysis).
