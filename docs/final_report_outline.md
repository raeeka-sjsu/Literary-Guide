# Literary Guide — Final Report Outline

For the May 19 final submission. This is the structure the report should follow, mapped one-to-one to the CMPE 258 Option 2 rubric. Fill each section with the content noted; everything we already need is in the codebase or in `python/eval/comparison.md`.

---

## 1. Problem Formulation

> Maps to rubric A.

- One paragraph: what the problem is (LLMs spoil books because they know full plots) and who it serves (readers + book clubs + lit students)
- Inputs: book + current chapter + user question
- Outputs: grounded, citation-backed answer that respects spoiler boundary
- Success criteria: ≥80% pass on 100-case eval, ≤15% spoiler-leak rate, 100% retrieval boundary compliance

## 2. Data and Evaluation Set

> Maps to rubric B.

- **Three datasets** (faithful to proposal):
  - Project Gutenberg — 33 public-domain novels, primary text source. Show statistics: total chapters (1700+), total words (~10M), genre breakdown
  - BookSum — 2,736 human-written chapter analyses across 23 of our books, used as `retrieve_expert_analysis` tool
  - NarrativeQA — 40 human-written QA pairs across 10 books, integrated as eval expansion
- **Few-shot examples** in the synthesizer prompt: 3 worked examples (analytical-in-bounds, spoiler-trap-refuse, no-evidence-refuse). Show the prompt verbatim.
- **Eval set composition** — show the table:
  - 30 hand-written spoiler-trap cases
  - 20 hand-written analytical cases
  - 10 hand-written refusal/edge cases
  - 40 NarrativeQA-derived spoiler-trap cases
  - = 100 total
- Scoring rules per category — paste from `eval/run_eval.py` docstring

## 3. Models Compared

> Maps to rubric C.

- **Llama 3.2:3b** via Ollama — open-source primary, runs locally, no API key
- **Claude Haiku 4.5** via Anthropic API — cloud comparison
- **GPT-4o-mini** via OpenAI API — cloud comparison
- All three evaluated on the **identical 100-case eval set**
- Pre-trained models only — we do not fine-tune (rubric explicitly allows prompting)
- Reproducibility: temperatures pinned, prompts checked into git, eval JSONL logs included

## 4. Retrieval Architecture

> Maps to rubric D1 (Advanced RAG).

- **Hybrid retrieval**: dense MiniLM embeddings + BM25 lexical, fused via Reciprocal Rank Fusion
- Show the retrieval flow as a diagram
- **Chunking strategy**: ~400-word paragraph chunks, with `(book_id, chapter, chunk_in_chapter, chapter_title)` metadata
- **Spoiler boundary**: filter `chapter ≤ chapter_limit` BEFORE ranking — show the query path
- **Per-book index**: lazy-built ChromaDB collection per book; cached in memory after first query
- **Knowledge-Graph-style character index**: per-book entity registry with first-chapter, alias resolution, mention timeline, co-occurrences. Used by the agent's `list_known_characters` and `get_character_profile` tools.

## 5. Agent Architecture

> Maps to rubric D2 (Tool-using Agent).

- **Four-stage Planner-Executor-Critic loop**:
  1. Planner LLM classifies question, outputs structured JSON tool plan
  2. Executor invokes tools sequentially, logs each call to SQLite `tool_call` table
  3. Synthesizer LLM writes draft answer with `[n]` citations
  4. Critic LLM verifies; deterministic name-grounding check overrides verdict to FAIL on hallucinated entities
  5. On FAIL → up to one retry with hint
- **Six tools**:
  1. `retrieve_passages` — hybrid retrieval over Gutenberg
  2. `lookup_character` — passage retrieval focused on a name
  3. `summarize_chapter` — full chapter text on demand
  4. `retrieve_expert_analysis` — BookSum scholarly analysis
  5. `list_known_characters` — structured character lookup
  6. `get_character_profile` — single character profile with timeline + co-occurrences
- Show the agent strip from the UI as a screenshot

## 6. Memory Architecture

> Maps to rubric D3 (Long-Horizon Memory).

- SQLite store with three tables:
  - `reading_position` — per (user, book), what chapter the user is on
  - `chat_turn` — every Q&A turn, with which chunks were retrieved, latency, model
  - `book_memory` — per (user, book), an LLM-summarized rolling memory
- **Written → summarized → retrieved** flow:
  - Each agent turn writes to `chat_turn`
  - User-triggered (or background) summarization compresses recent turns + prior summary into an updated rolling memory
  - On next session, the summary is injected into the synthesizer prompt as background context
- This is the canonical "written, summarized, retrieved" pattern the rubric requires

## 7. Safety / Guardrails

> Maps to rubric E (safety/guardrails portion).

- **Three independent layers** of spoiler safety:
  1. Retrieval-side: filter `chapter ≤ current_chapter` at the database level
  2. Prompt-side: synthesizer system prompt forbids outside knowledge + few-shot examples of correct refusal
  3. Post-hoc grounding verifier: extract proper nouns from answer, verify each appears in a cited passage; if not, force critic FAIL and rewrite
- **Citation enforcement**: every factual claim must cite at least one `[n]` reference; absent citations trigger critic FAIL
- **Refusal pattern**: explicit phrases ("I can't see beyond chapter N", etc.) make refusals machine-detectable
- **Why three layers**: the prompt alone is not enough — LLMs trained on internet text already "know" most public-domain books and will leak from training. Architectural safety enforcement is what prevents this.

## 8. Logging

> Maps to rubric E (structured logging portion).

- **JSONL eval logs** at `python/eval/runs/*.jsonl` — one record per case with question, retrieved chunks, answer, latency, score, and category-specific scoring detail
- **SQLite `tool_call` table** — every tool call from every agent run, with arguments, results count, latency, and parent turn ID
- **SQLite `chat_turn` table** — every user-facing Q&A with model, provider, retrieval mode, latency
- All persisted; nothing transient

## 9. UI

> Maps to rubric E1.

- Library landing page with search and genre filter
- Reader page with paginated chapters, dropdown navigation, chapter-internal text search, hover-to-highlight paragraphs, click-paragraph for prompt suggestions
- Chat pane with: provider dropdown, agent-mode toggle, animated agent steps, citation expandable
- Memory panel with rolling summary + Update button
- Reading-position auto-restore on book reopen
- Screenshot of each section

## 10. Results

> Maps to rubric C3.

Drop in the comparison table directly from `python/eval/comparison.md`:

| Provider | Pass rate | Mean latency | Cost / 1000 queries | Spoiler-leak rate |
|---|---|---|---|---|
| Llama 3.2:3b (open-source) | 80.0%* | 7,366 ms | $0.00 | 16.7% |
| Claude Haiku 4.5 | 89.0% | 18,040 ms | $2.47 | 15.7% |
| GPT-4o-mini | 90.0% | 3,253 ms | $0.41 | 14.3% |

\*Currently on 60 cases; full 100-case re-run included in final submission.

Per-category breakdown table.

Divergence analysis: 76/100 all pass, 11/100 only Llama fails, etc.

Discussion paragraph: GPT-4o-mini is cost/quality sweet spot; Claude has slowest mean latency due to a tail of long responses; Llama's biggest gap is on the refusal category.

## 11. Limitations and Future Work

- **Chapter-level (not paragraph-level) spoiler boundary** — finer-grained protection would require per-paragraph chapter tagging which is brittle for older Gutenberg texts.
- **Character extraction is regex-based** — could be replaced with a fine-tuned BERT NER model. We chose regex+heuristics for transparency and zero-runtime-cost.
- **No fine-tuning** — a fine-tuned spoiler-detection classifier (training a small DistilBERT on labeled answer/future-chapter pairs) would push Llama's refusal rate up.
- **In-memory ChromaDB** — restarting the server clears the cache; rebuild on first query takes ~5s. Persistent ChromaDB would speed cold starts.
- **No multi-user support** — `user_id` is fixed at "default" for the demo.
- **Citation jump-to-source** — answers cite passages but the reader doesn't yet auto-scroll to the cited passage on click. Easy add.

## 12. References

- Lecture rubric (Option 2)
- Project proposal (signed by team May 26)
- Kryściński et al., *BookSum*. arXiv 2105.08209
- Kočiský et al., *NarrativeQA*. ACL 2018
- Cormack et al., *Reciprocal Rank Fusion*. SIGIR 2009
- `all-MiniLM-L6-v2` — Reimers & Gurevych, sentence-transformers

## 13. Appendix

- Repo structure (paste from README)
- Reproduction commands (paste from `docs/RUN.md`)
- Eval case sample (3-5 cases per category)
- Demo script (`docs/demo_script.md`)
- Failure-mode catalog: 3-5 representative cases where models failed and why
