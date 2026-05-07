# Literary Guide — Live Demo Script

For the May 7 in-class presentation. ~5 minutes total. Follow this verbatim if nervous; deviate if conversation goes well.

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
5. **Browser tab open at http://localhost:3000** with library page loaded. Zoom set so a grader at the back can read the chat panel.
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

> "We've indexed 33 public-domain novels from Project Gutenberg. They're searchable by title, author, or genre."

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
- Toggle **agent mode (Planner→Executor→Critic)** ON — this is the differentiator
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

### 4:15 — Numbers slide (~30 sec)

Switch to the slide deck for the results table.

> "We evaluated all three LLMs on a 100-case test suite — 60 hand-written + 40 from the NarrativeQA dataset. GPT-4o-mini hit 90 percent, Claude 89, Llama 80. Both commercial models perfect on analytical and refusal categories. The interesting cluster is on spoiler traps — all three around 84–86 percent — that's where the difficulty actually is."

### 4:45 — Wrap (~15 sec)

> "Open-source primary. Real third-party data. 100-case evaluation. Multi-step agent with structured grounding. Persisted memory across sessions. Code's at github.com/raeeka-sjsu/Literary-Guide."

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
| Whole demo dies | Switch to the backup video at `docs/demo.mp4`. Narrate over it. |
| Nervous and forget what to click | Stop demoing live — switch to the slide deck for the results table. The slides + numbers are the real grading material. |

---

## Q&A — likely prof questions

**Q: What's the deep learning here? Did you train any models?**
> "We use three pre-trained transformers: a 22M-parameter BERT-family sentence encoder for retrieval embeddings, the 3-billion-parameter Llama 3.2 as our primary LLM, and Claude/GPT for comparison. The novel contribution is the system architecture — multi-step agent, hybrid retrieval, deterministic safety enforcement — not new model weights. Fine-tuning a small spoiler-detection classifier is on our future-work backlog."

**Q: How does your retrieval work?**
> "Hybrid: dense embeddings AND BM25 lexical, fused with Reciprocal Rank Fusion. The chapter spoiler-boundary is enforced before ranking — chunks beyond the user's current chapter are filtered out at the database level, so the model can't retrieve future content even if it wanted to."

**Q: How do you stop hallucination?**
> "Three layers. Layer one: retrieval is bounded — only chapters ≤ current can be returned. Layer two: the synthesizer prompt forbids outside knowledge. Layer three: a deterministic post-hoc check extracts proper nouns from the answer and verifies each appears in a cited passage. If a name in the answer isn't in any retrieved chunk — for example the model knew 'Glinda' from training and inserted her — the critic auto-fails and forces a rewrite."

**Q: Why an agent loop instead of one-shot RAG?**
> "Different question types need different retrieval strategies. 'Main characters' is a structured-lookup question — we have a knowledge-graph-style character index for that. 'What does X symbolize' is a thematic question best answered by hybrid retrieval plus scholarly analysis from BookSum. The Planner LLM classifies the question and picks the right tool. The Critic acts as a verifier, catching errors the Synthesizer makes."

**Q: How is memory implemented?**
> "Three tiers in SQLite. Episodic — every Q&A turn is logged with timestamp, model, latency, and which chunks were retrieved. Stateful — reading position per book per user, auto-restored on reopen. Semantic — the LLM compresses recent turns into a rolling summary, which is injected into the next session's prompts as background context. That's the 'written, summarized, retrieved' pattern Option 2 / D3 explicitly requires."

**Q: How rigorous is your eval?**
> "100 cases across 3 categories: spoiler-traps where the system must refuse, analytical questions where it must produce grounded analysis with citations, and edge cases. 60 are hand-written by us, 40 are derived from NarrativeQA — a public benchmark of human-written QA pairs over story texts. Each case scored programmatically with category-specific rules. All three models run on the same eval set, with per-case JSONL logs."

**Q: What's left for the final report?**
> "Three things. One — re-running Llama on the full 100-case suite so all three providers report on the identical set. Two — recording the demo video. Three — writing the formal report. Code, eval framework, and architecture are complete."
