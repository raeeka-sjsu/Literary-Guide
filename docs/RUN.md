# Setup & Run Instructions

This document is the canonical reference for getting Literary Guide running on a fresh machine, running the evaluation suite, and contributing additional eval cases.

If something doesn't work, see the [Troubleshooting](#troubleshooting) section at the bottom.

---

## 1. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| **Python** | 3.9 – 3.13 | Tested with `/usr/bin/python3` (3.9) on macOS Sequoia |
| **Node.js** | 18+ | For the Express front-end |
| **macOS / Linux** | any modern | Windows works through WSL but not directly tested |
| **Disk** | ~6 GB free | 26 MB for books, 6 MB for BookSum, ~2 GB if you install Ollama with Llama 3.2 |
| **RAM** | 8 GB+ | 16 GB recommended if running Ollama locally |

### Optional but strongly recommended

| Requirement | Why | Install |
|---|---|---|
| **Ollama** | Run the open-source LLM locally — free, no API key, satisfies the rubric's "open-source primary model" requirement | `brew install --cask ollama` (macOS), then open the app once |
| **Anthropic API key** | Run Claude Haiku in the comparison eval | https://console.anthropic.com → API Keys → Create |
| **OpenAI API key** | Run GPT-4o-mini in the comparison eval | https://platform.openai.com → API Keys → Create |

---

## 2. Clone and set up the Python backend

```bash
git clone https://github.com/raeeka-sjsu/Literary-Guide.git
cd Literary-Guide
git checkout raeeka-test     # or main once merged

# Create the Python virtual environment (one-time)
cd python
python3 -m venv venv
source venv/bin/activate

# Install dependencies (one-time per machine)
pip install -r requirements.txt
```

This installs `datasets`, `sentence-transformers`, `chromadb`, `flask`, `flask-cors`, `rank-bm25`, `numpy`, plus their transitive dependencies. First-time install takes ~5 minutes.

---

## 3. Configure LLM providers

You can run the system in three modes, each requiring different setup.

### Option A — Ollama (free, local, no API key needed)

The default. Required for running the open-source LLM baseline.

```bash
# Install Ollama
brew install --cask ollama
open -a Ollama   # or just launch from Applications. The menubar llama means the service is running.

# Pull the open-source model (~2 GB download)
ollama pull llama3.2:3b
```

Verify the service is up:
```bash
curl -s http://localhost:11434/api/tags
```

### Option B — Anthropic Claude (cloud, paid)

```bash
# In repo root
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
chmod 600 .env
```

The `.env` file is git-ignored. The Flask server reads it on startup.

### Option C — OpenAI (cloud, paid)

```bash
# Append to .env (or create if it doesn't exist)
echo "OPENAI_API_KEY=sk-..." >> .env
chmod 600 .env

# Install the OpenAI SDK (not required by default install)
pip install openai
```

---

## 4. (Optional) Rebuild data indexes

The repo ships with all data indexes pre-built (in `python/data/`). You only need to rebuild them if you change source code that affects extraction or chunking.

```bash
# Re-fetch books from Project Gutenberg (slow, ~5 min)
python scripts/fetch_library.py

# Re-pull BookSum entries for the catalog (~1 min)
python scripts/fetch_booksum.py

# Rebuild the per-book character knowledge index (~10 sec)
python scripts/build_character_index.py
```

---

## 5. Run the application

Two processes — start them in two separate terminals.

### Terminal 1 — Python backend (Flask)

```bash
cd python
source venv/bin/activate
python scripts/api_server.py
```

Expected output:
```
Literary Guide API listening on http://localhost:5050
 * Running on http://127.0.0.1:5050
```

The first time you ask a question for a given book, the Flask process will lazily build the per-book Chroma collection — that takes 2-5 seconds. Subsequent questions reuse the cached collection.

### Terminal 2 — Express front-end

```bash
cd js
npm install        # one-time
node server.js
```

Expected output:
```
Literary Guide viewer running at http://localhost:3000
Proxying agent calls to http://localhost:5050
```

### Open the app

Navigate to **http://localhost:3000**

You'll see:
1. **Library page** — 33 book cards. Search and filter by genre.
2. **Reader page** (after clicking a book) — chapter dropdown + paginated reader on the left, chat pane on the right.
3. **Chat** — agent answers your questions. Pick the LLM provider and toggle agent mode.

---

## 6. Run the evaluation suite

```bash
cd python
source venv/bin/activate

# Run all 60 cases against one provider, output to a named file
python eval/run_eval.py --provider ollama --out-prefix my_run

# Run multiple providers back-to-back
python eval/run_eval.py --provider ollama,anthropic,openai --out-prefix three_way

# Smoke test — first 5 cases only
python eval/run_eval.py --provider ollama --limit 5

# Single case by id
python eval/run_eval.py --provider anthropic --case st-pp-1

# Filter to one category
python eval/run_eval.py --provider ollama --category spoiler_trap
```

### Outputs

After each run, two files are produced under `python/eval/runs/`:

- `<prefix>.jsonl` — one JSON object per case, with the question, retrieved chunks, answer, latency, and score
- `<prefix>.summary.json` — aggregated pass-rate by `(provider, category)`

The script also prints a summary table to stdout.

### Eval categories and scoring

| Category | Scoring rule |
|---|---|
| `spoiler_trap` | Pass if the answer contains NONE of the case's `forbidden_keywords` (case-insensitive) AND no retrieved chunk has `chapter > current_chapter` |
| `analytical` | Pass if answer is ≥ 60 words, contains at least one `[n]` citation, and all retrieved chunks respect the chapter boundary |
| `refusal_or_edge` | If `must_refuse: true`, pass if answer contains a refusal keyword. Otherwise pass if answer is non-empty + cited + retrieval-safe. |

---

## 7. Contribute additional eval cases

To add a case, edit `python/eval/eval_cases.json` and add an entry like:

```json
{
  "id": "st-yourbook-1",
  "category": "spoiler_trap",
  "book_id": "wizard-of-oz",
  "current_chapter": 3,
  "question": "Does the Wizard turn out to be a humbug?",
  "forbidden_keywords": ["humbug", "old man", "fraud", "balloon", "from Omaha"]
}
```

Field guide:
- `id`: free-form, but the convention is `<category-prefix>-<book-shortcode>-<n>`
- `category`: one of `spoiler_trap`, `analytical`, `refusal_or_edge`
- `book_id`: must match a key in `python/data/catalog.json`
- `current_chapter`: integer, the reader's current chapter (the spoiler boundary)
- For `spoiler_trap`: `forbidden_keywords` — list of strings the answer must NOT contain
- For `refusal_or_edge` with `must_refuse: true`: `refusal_keywords` — list of strings the answer must contain
- For `analytical`: no extra fields needed

After adding cases, re-run the eval to score them.

---

## 8. Troubleshooting

### "Could not reach Literary Guide agent at http://localhost:5050"
Flask isn't running. Check Terminal 1. If it crashed, look at the traceback and re-run.

### "ChromaDB error: ids in include"
Your ChromaDB version is older than 0.4.13. Upgrade: `pip install -U chromadb`.

### "Connection refused" when running Ollama eval
Ollama service isn't running. Open the Ollama app once (it adds a llama icon to your menubar). Verify with `curl localhost:11434/api/tags`.

### Llama eval is very slow / fan is loud
Llama 3.2:3b runs on your laptop GPU. ~5-15 seconds per question is normal. If you want a silent experience, use the Anthropic or OpenAI provider — those run in the cloud.

### Anthropic eval errors with "credit_balance_too_low"
Add credits to your Anthropic account at https://console.anthropic.com. The full 60-case eval costs ~$0.20.

### Chapter numbers in the dropdown look weird (e.g. "Chapter XXIV. Home Again" before "Chapter I")
This was a Gutenberg-parsing artifact in early versions. Pull the latest code — `chapter_numbering.py` now extracts canonical numbers from titles and the UI filters out front-matter pseudo-chapters.

### Memory panel says "No memory yet" forever
Click the **Update** button in the memory panel after a few chat turns. It calls the LLM to summarize the recent turns into a rolling memory.

### Test questions from earlier sessions appear in the chat when I open a book
The chat panel auto-replays the most recent SQLite-persisted turns. Clear them with:
```bash
sqlite3 python/data/literary_guide.sqlite "DELETE FROM chat_turn; DELETE FROM book_memory;"
```

### "OPENAI_API_KEY environment variable is missing"
Either set it in `.env` or run with a different provider.

---

## 9. Common workflows

### Demo flow (live presentation)

```bash
# Terminal 1
cd python && source venv/bin/activate && python scripts/api_server.py

# Terminal 2
cd js && node server.js
```

Open http://localhost:3000. Recommended demo books with rich character + theme content:
- *Pride and Prejudice* — set chapter to 5, ask "What does Mr. Bennet's sarcasm reveal about his marriage?"
- *Frankenstein* — chapter 5, ask "What does Victor's reaction to the creature suggest about his character?"
- *Wizard of Oz* — chapter 1, ask "Who are the main characters so far?" (showcases structured character index)
- *Pride and Prejudice* — chapter 5, ask "Does Elizabeth marry Darcy?" (showcases spoiler refusal)

### Reproducing the comparison numbers

```bash
cd python && source venv/bin/activate

# Llama baseline
python eval/run_eval.py --provider ollama --out-prefix ollama_baseline

# Claude baseline (requires ANTHROPIC_API_KEY)
python eval/run_eval.py --provider anthropic --out-prefix anthropic_baseline

# OpenAI (requires OPENAI_API_KEY + `pip install openai`)
python eval/run_eval.py --provider openai --out-prefix openai_baseline
```

Then inspect `python/eval/runs/*.summary.json` for the aggregated metrics.
