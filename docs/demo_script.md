# Literary Guide — Live Demo Script

For the May 7 in-class presentation. Approximately five minutes of live demonstration plus a short walkthrough of results. The narration below can be read verbatim or used as a guide.

---

## Pre-demo checklist (do this 10 min before presentation)

1. **Power up + plug in laptop.** Local LLM workload draws GPU; battery-only will throttle.
2. **Two terminals open**, both already in the repo:
   - Terminal A — `cd python && source venv/bin/activate && python scripts/api_server.py`
   - Terminal B — `cd js && node server.js`
3. **Ollama menubar icon visible** (the llama). If not, `open -a Ollama`.
4. **Verify both endpoints respond:**
   ```bash
   curl -s http://localhost:5050/health     # → {"ok": true}
   curl -s http://localhost:3000/api/books | head -c 200   # → JSON book list
   ```
5. **Browser tab open at http://localhost:3000** with the library page loaded. Zoom level set so the audience at the back of the room can read the chat panel.
6. **Clear previous chat history** so the demo starts on a clean slate:
   ```bash
   sqlite3 python/data/literary_guide.sqlite "DELETE FROM chat_turn; DELETE FROM book_memory; DELETE FROM tool_call;"
   ```
7. **Backup video** at `docs/demo.mp4` opened in QuickTime in case Wi-Fi or Ollama dies.

---

## Live walkthrough — ~5 min

### 0:00 — Title slide → "Let me show you the system" (10 sec)

Switch to the browser at http://localhost:3000.

### 0:10 — The library (~30 sec)

> "We've indexed 52 public-domain novels from Project Gutenberg. They're searchable by title, author, or genre."

- Type `austen` in search → three Austen novels filter in
- Click **All genres** dropdown → choose `gothic` → grid filters to gothic novels
- Click **All genres** to reset

### 0:40 — Opening a book (~20 sec)

> "When you open a book, three things happen in the background: the chapter text loads, a per-book RAG index is built lazily, and any prior reading state is restored. There's a memory panel at the top showing what we've discussed before."

- Click **Pride and Prejudice**
- Wait for the brief "Indexing… Ready — N passages indexed" notice
- Point out the chapter dropdown, the prev/next buttons, the search-this-chapter input, and the memory panel on the right.

### 1:00 — The reader + spoiler boundary (~30 sec)

> "I'm at chapter 5 right now. The chat on the right is bound to that chapter. The system can only retrieve text up to and including chapter 5 — even if I deliberately ask it to spoil."

- Use the dropdown → set chapter to **5**
- Show the "Spoiler boundary: chapter 5" pill in the chat header

### 1:30 — Question 1: Analytical (Claude) (~45 sec)

> "Here's a normal literary question. I'll route it through Claude Haiku."

- Set LLM dropdown to **Anthropic Claude**
- Toggle **agent mode (Planner→Executor→Critic)** ON
- Type: `What does Mr. Bennet's sarcasm reveal about his marriage?`
- Hit **Ask**
- Narrate while the agent strip animates:
  > "You can see the agent's plan unfolding — it picked `get_character_profile` for Mr. Bennet AND `retrieve_passages` for the thematic lookup. Each tool call is logged. Then the synthesizer drafts an answer. Then a critic verifies citations and grounding before returning."
- When the answer arrives, point at the inline `[1][2]` citations and click **N cited passages** to expand.

### 2:15 — Question 2: Spoiler trap (Claude) (~30 sec)

> "Now let's try to break it. I'll ask something that requires future-chapter information."

- Type: `Does Elizabeth end up marrying Mr. Darcy?`
- Hit **Ask**
- Expected behavior: agent refuses with something like "I can't see beyond chapter 5 yet…"
- Narrate:
  > "The system refuses cleanly. Three layers of safety prevent the leak — the retrieval database is filtered before ranking, the synthesizer prompt forbids outside knowledge, and a deterministic name-grounding check catches anything the LLM tries to make up from training data."

### 2:45 — Question 3: Memory continuity (Llama) (~30 sec)

> "Switch to the local open-source model — Llama 3.2 3-billion-param, running on this laptop with no cloud calls."

- Set LLM dropdown to **Ollama**
- Toggle agent mode OFF (faster — pure RAG)
- Type: `What about how Mr. Bennet talks to his daughters compared to his wife?`
- The answer references context from the previous question — that's memory in action.
- Click **Update** in the memory panel:
  > "We can compress the conversation into a rolling summary. The summary gets injected into the next session as background, so when I open this book tomorrow, the system already knows what we've been discussing."

### 3:15 — Citations back to source (~30 sec)

> "Every claim is cited. Every citation is a real passage from the actual novel."

- In the previous answer, point at one of the `[n]` references
- Expand the cited passages
- Read out the cited passage and trace it back to the chapter on the left

### 3:45 — Library breadth (~30 sec)

> "And this works on any book in the library — not just the demo book."

- Click ← Library
- Click any random book — *Frankenstein* or *Time Machine*
- Set chapter to 5 or so
- Quick question: `What does the time traveler discover so far?` (Time Machine) or `What is Victor's obsession with creating life?` (Frankenstein)
- Don't read the full answer — just demonstrate it works

### 4:15 — Results slide (~30 sec)

Switch to the slide deck for the results table.

> "All three LLMs were evaluated on the same 60 hand-written test questions. GPT-4o-mini reached 98.3 percent, Claude Haiku 96.7 percent, and Llama 3.2:3b 81.7 percent. Both commercial models reached 100 percent on the analytical and refusal-or-edge categories. The hardest category is spoiler-trap, where the spread is 83 to 97 percent."

### 4:45 — Closing (~15 sec)

> "Project summary: open-source primary model, three datasets from the proposal, 128 evaluation cases scored programmatically, multi-step agent with three-layer safety enforcement, and persisted memory across sessions. The repository is at github.com/raeeka-sjsu/Literary-Guide."

---

## Three safe questions (Plan B if you need different demo questions)

1. *Pride and Prejudice ch 3:* "What does Mr. Bennet's sarcasm reveal about his marriage?"
2. *Frankenstein ch 5:* "What does Victor's reaction to creating the creature suggest about his character?"
3. *Wizard of Oz ch 3:* "Who are the main characters so far?" — showcases the structured character index

## Three spoiler-trap questions (Plan B)

1. *Pride and Prejudice ch 5:* "Does Elizabeth marry Mr. Darcy?"
2. *Frankenstein ch 5:* "What does the creature do to William?"
3. *Wizard of Oz ch 3:* "How is the Wicked Witch of the West eventually defeated?"

## Memory demonstration (Plan B)

1. Open *Pride and Prejudice*, set chapter 5
2. Ask `What does Mrs. Bennet seem most preoccupied with?`
3. Ask `How does that contrast with Mr. Bennet?`
4. Click **Update** in the memory panel — show the rolling summary appear
5. Click ← Library, then click *Pride and Prejudice* again
6. Reading position auto-restores to chapter 5; chat replays the prior turns; memory panel still shows the summary

## Citation demonstration (Plan B)

In any answer with `[1]` `[2]` etc.:
1. Click **N cited passages** in the answer card
2. Each citation shows: chapter number, similarity score, and the actual passage text
3. Compare the cited passage's text to a chapter on the left — same words

## Fallback plan if things break

| Failure mode | Workaround |
|---|---|
| Wi-Fi dies → Anthropic / OpenAI calls fail | Switch LLM dropdown to **Ollama**. Local model. No Wi-Fi needed. |
| Ollama dies (no menubar llama) | Open Ollama app from Spotlight. Wait 5 sec. Switch LLM dropdown back. |
| Both LLMs dead | Switch dropdown to **dry-run** — shows retrieved passages without an answer. Still demonstrates the RAG layer. |
| Frontend can't reach Flask | Both terminals show real-time logs — find the error. Restart both with the commands at top of this doc. |
| Live demo cannot recover | Switch to the backup video at `docs/demo.mp4` and narrate over it. |
| Need to pause the live demo | Switch to the results slide; the slide deck contains the same evidence. |

---

## Q&A — anticipated questions

**Q: What deep-learning components does the project use, and were any models trained?**
> "Three pre-trained transformers are in use: `all-MiniLM-L6-v2`, a 22-million-parameter BERT-family sentence encoder for retrieval embeddings; Llama 3.2 3B as the open-source primary LLM, served locally via Ollama; and Claude Haiku 4.5 and GPT-4o-mini as comparison LLMs. No model weights are trained for this project. The contribution is the system around the models — the multi-step agent, hybrid retrieval, structured grounding verification, and three-layer safety enforcement. A fine-tuned spoiler-detection classifier is part of the May 19 final-report scope."

**Q: How does retrieval work?**
> "Hybrid retrieval: a sentence-transformer dense index and a BM25 sparse index, both queried per request and fused via Reciprocal Rank Fusion. The chapter spoiler-boundary is applied at the database level before ranking, so chunks from chapters beyond the reader's current chapter are excluded from the candidate set entirely."

**Q: How is hallucination prevented?**
> "Three independent layers. First, retrieval is bounded by chapter, so the LLM cannot see future content. Second, the synthesizer system prompt explicitly forbids drawing on outside knowledge of the book. Third, a deterministic post-hoc verifier extracts proper nouns from the candidate answer and confirms each appears in at least one cited passage. If a name in the answer is absent from every retrieved chunk — for example, if the model produced 'Glinda' from its training data — the Critic verdict is overridden to FAIL and the synthesizer is asked to rewrite."

**Q: Why a multi-step agent instead of single-call RAG?**
> "Different question types are best served by different retrieval strategies. Character-list questions are answered most reliably by a structured lookup against the per-book character knowledge index. Thematic questions are answered well by hybrid retrieval combined with scholarly analysis from BookSum. The Planner LLM classifies the question and selects the appropriate tools; the Critic stage validates the draft answer before it is returned. We measured the value of this architecture: agent mode improves pass rate by 3.3 percentage points over single-call RAG on the same 30 cases."

**Q: How is memory implemented?**
> "Three tiers in SQLite. Episodic memory — every question-and-answer turn is logged with the model, provider, latency, and the IDs of the chunks retrieved. Stateful — reading position per user per book, automatically restored when the user reopens the book. Semantic — the LLM compresses recent turns into a short rolling summary, which is injected into the next session's synthesizer prompt as background context. This implements the 'written, summarized, retrieved' pattern that the rubric specifies for the long-horizon-memory option (D3)."

**Q: How rigorous is the evaluation?**
> "128 test cases across three categories: 30 spoiler-trap cases where the system must avoid revealing future-chapter content, 20 analytical cases where the system must produce a grounded analysis with citations, and 10 refusal-or-edge cases that test boundary behavior. Sixty cases are hand-written by the team across 13 books. The remaining 68 are derived from NarrativeQA, a public benchmark of human-written question-answer pairs over story texts. Each case is scored programmatically with category-specific rules. All three LLMs were evaluated on the same 60 hand-written cases for the directly comparable benchmark; Claude and GPT-4o-mini were additionally evaluated on the full 128-case suite. Per-case JSONL logs are checked into the repository."

**Q: What is the remaining work for the final report?**
> "Three items. First, running Llama on the full 128-case suite so all three providers report on the identical extended set. Second, recording the final demonstration video. Third, writing the formal report. The code, evaluation framework, and architecture are complete."
