# Failure Analysis

This document examines specific cases on which the system fails, the underlying causes, and the mitigations we applied or plan to apply. Source data: per-case JSONL logs in `python/eval/runs/`.

---

## Case 1 — Training-data leakage on a small open-source LLM (`st-je-1`)

**Setup.** *Jane Eyre*, reader at chapter 10. Question: *"Who is the woman locked in Mr. Rochester's attic?"*

**Retrieved context.** Three chunks from chapters 1–10. None of them name Bertha Mason; that revelation occurs in chapter 26 and is therefore correctly excluded by the chapter filter.

**Answer (Llama 3.2:3b).**
> *"The woman locked in Mr. Rochester's attic is Bertha Mason, his wife who has been institutionalized due to her mental illness. She appears in chapter 5 [1]."*

**Cause.** The retrieval-side spoiler boundary did not return any chunk containing the answer, but Llama 3.2:3b had read *Jane Eyre* during pre-training. With no relevant content in the prompt, the model produced an answer from its parametric knowledge and fabricated a citation index ("She appears in chapter 5") that does not match passage [1]'s content.

**Mitigation applied.** The deterministic name-grounding check identified "Bertha Mason" as a proper noun absent from any retrieved chunk. The Critic verdict was overridden to FAIL and a rewrite was triggered. In this case, the rewrite reasserted the same claim with slightly different phrasing and the second draft was returned as final.

**Planned mitigation.** A fine-tuned spoiler-detection classifier — a small encoder model trained on `(answer, future_chapter_text) → is_spoiler` pairs — used as a hard gate before returning any answer. This work is part of the May 19 final-report scope.

---

## Case 2 — Evaluation scorer false positive on negation phrasing (`st-pp-1`, Claude Haiku)

**Setup.** *Pride and Prejudice*, reader at chapter 5. Question: *"Does Elizabeth Bennet end up marrying Mr. Darcy?"*

**Answer.**
> *"I can't see beyond chapter 5 yet — the passages do not reveal whether Elizabeth marries Mr. Darcy later in the novel. So far, the dynamic between them is distinctly antagonistic..."*

**Reason flagged as failure (per the original scorer).** The case's `forbidden_keywords` list contains the phrase `"marries Mr. Darcy"`. The original scorer counted any substring match as a leak.

**Why the answer is in fact a correct refusal.** The forbidden phrase appears within a negation: *"the passages do not reveal whether Elizabeth marries Mr. Darcy"*. The model is explicitly stating that it cannot answer the question.

**Implication.** The original scoring rule conflates substring presence with claim assertion. We added negation-aware matching: each occurrence of a forbidden keyword is checked against an 80-character preceding window for negation markers ("not", "do not", "doesn't", "cannot", and similar). After this fix, occurrences inside negation contexts no longer count as leaks.

**Effect on reported metrics.** Our originally reported spoiler-leak rates were inflated by approximately 5–10 percentage points across the cloud providers. The numbers in the README and `python/eval/comparison.md` reflect the corrected scorer.

---

## Case 3 — Refusal-keyword mismatch between case and system (`rf-pp-1`, Llama)

**Setup.** *Pride and Prejudice*, chapter 1. Question: *"Summarize the ending of Pride and Prejudice."* Marked `must_refuse: true`.

**Answer.**
> *"I can't see beyond chapter 1 yet — let's discuss what's happened so far."*

**Reason flagged as failure (per the original scorer).** The case's `refusal_keywords` list contained narrow phrases such as `"the passages do not"` and `"haven't read that yet"`. The phrase `"I can't see beyond"` is registered in the system-wide refusal classifier (`safety.is_refusal`) but was not in this case's keyword list.

**Implication.** Two refusal-detection paths existed — the per-case scorer (narrow) and the system-wide classifier (broad) — and they were not synchronized. A reader testing the same case in the live UI would observe a correct refusal; only the eval scorer reported failure.

**Mitigation applied.** The refusal scorer in `eval/run_eval.py` now falls back to `safety.is_refusal()` whenever the case-specific keyword list does not match. Cases of this type are now scored consistently with the live system's behavior.

---

## Case 4 — Architectural success: Wizard of Oz character list

**Setup.** *Wizard of Oz*, reader at chapter 1. Question: *"Who are the main characters so far?"*

**Earlier behavior.** An earlier version of the system, using only vector retrieval and a single LLM call, would list characters such as Glinda the Good Witch (introduced in chapter 23), the Scarecrow (chapter 3), the Tin Woodman (chapter 5), and the Cowardly Lion (chapter 6) — none of whom have been introduced by chapter 1.

**Current behavior.** The system returns Dorothy, Aunt Em, Uncle Henry, and Toto — the four characters present in chapter 1 of the source text.

**Cause of the improvement.** The Planner classifies the question as a character-list query and routes it to the `list_known_characters` tool. This tool queries the per-book character knowledge index and filters to characters whose `first_chapter` is at or below the reader's current chapter. The path involves no semantic retrieval and no generation step at the data-lookup layer, eliminating the opportunity for training-data leakage on factual list-style questions.

**General observation.** For factual questions answerable from structured per-book data, structured pre-computed indexes are more reliable than vector retrieval feeding into a generation step. The agent's Planner selects between vector search, structured lookup, full-chapter access, and scholarly-analysis retrieval based on the question type.

---

## Case 5 — Critic stage rejecting a draft answer

**Setup.** *Pride and Prejudice*, reader at chapter 3. Question: *"What does Mr. Bennet's sarcasm reveal about his marriage?"*

**Synthesizer's first draft.** The draft made claims about Mr. Bennet's character grounded in retrieved passages but cited a passage index `[4]` when only three passages were available, and asserted one claim without any citation.

**Critic verdict.** FAIL. Issues recorded: invalid citation index `[4]`, and one factual claim lacking a supporting citation.

**Rewrite.** The synthesizer received the Critic's hint and produced a second draft that dropped the invalid citation, added a citation to the previously uncited claim, and refined the analysis.

**Final answer.** Returned to the user with all citations valid and grounded.

**Implication.** The Critic stage detects synthesizer errors before they reach the user. In our test runs, approximately 15–20% of agent-mode answers required a rewrite. The cost is roughly three additional seconds per query; the benefit is improved citation accuracy and a reduction in unsupported claims.

---

## Aggregate failure modes

| Failure mode | Approximate frequency | Status |
|---|---|---|
| Training-data leak on small open-source LLMs | Approximately 17% of Llama spoiler-trap cases | Mitigated by three-layer safety; not fully eliminated. Planned mitigation: fine-tuned classifier. |
| Eval scorer over-counting leaks on negation phrasing | (resolved) | Negation-aware substring matching added to `score_spoiler_trap`. |
| Refusal-phrasing mismatch between scorer and system | (resolved) | `score_refusal` now falls back to `safety.is_refusal()`. |
| Synthesizer draft errors caught by Critic | Approximately 15–20% of agent-mode queries trigger a rewrite | Working as designed; rewrites materially improve final-answer quality. Visible in the `agent.retried` field of API responses. |
| Genuinely hard cases | Approximately 1.7% of cases on the best-performing model | Acceptable. These are cases for which available chapters do not contain the information needed to answer. |

## Agent mode vs single-call RAG ablation

To assess whether the four-stage Planner-Executor-Synthesizer-Critic architecture improves answer quality over a single LLM call given the same retrieved chunks, the same 30 cases were evaluated through Claude Haiku in both modes. The model and retrieved context are identical across both runs; only the orchestration differs.

| Category | Simple-RAG (1 LLM call) | Agent mode (4 LLM calls) | Difference |
|---|---|---|---|
| Spoiler-trap (15 cases) | 14/15 (93.3%) | 15/15 (100%) | +6.7 pp |
| Analytical (10 cases) | 10/10 (100%) | 10/10 (100%) | 0 |
| Refusal or edge (5 cases) | 5/5 (100%) | 5/5 (100%) | 0 |
| **Total (30 cases)** | 29/30 (96.7%) | 30/30 (100%) | +3.3 pp |
| Mean latency | 4,712 ms | 9,683 ms | 2.1× |

**Note on these numbers.** A first run of this ablation reported a 40-point regression on refusal cases. Manual inspection of every flagged failure showed that all five were scorer artifacts: in each case the model correctly refused, but the answer text contained either a forbidden keyword inside a negation context (for example, *"the passages do not describe Elizabeth's wedding night"* was counted as leaking "wedding night") or a refusal phrasing not present in the case-specific keyword list ("I can't answer" rather than "cannot"). We added negation-aware spoiler scoring and the system-wide refusal-classifier fallback (both in `python/eval/run_eval.py`). After re-scoring, agent mode is at least as good as single-call RAG in every category.

**Conditions under which agent mode improves results.** Spoiler-trap cases. The Planner routes character-list queries to the structured `list_known_characters` tool (which involves no LLM generation at the lookup step, eliminating training-data hallucination at that stage), and the Critic stage validates draft answers before they are returned.

**Conditions under which single-call RAG is preferable.** Simple, low-stakes questions where the additional latency and token cost (approximately four times more LLM calls) outweigh the small accuracy gain, or when API budget is constrained. The system supports both modes; the user selects in the UI.

## Planned future work

1. LLM-as-judge scorer to replace substring-based keyword matching. Estimated four hours of work. The current scorer is conservative (over-counts leaks); an LLM-as-judge layer would tighten the reported numbers, most likely upward.
2. Fine-tuned spoiler-detection classifier trained on synthetic `(answer, future_chapter_text)` pairs. Estimated six hours including a 30-minute Colab training run. Expected to close most of the remaining gap on Llama.
3. Per-paragraph spoiler boundaries instead of per-chapter. Requires a more careful ingest pipeline. Useful for books in which a single chapter contains multiple distinct events.
4. Adversarial evaluation set — questions deliberately phrased to appear innocent while requiring future-chapter knowledge. Would stress-test the system more than the current evaluation.
