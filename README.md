# Literary Guide

A spoiler-aware literary companion that provides chapter-by-chapter discussion — themes, symbolism, character motives — without revealing future plot events. Powered by LLMs and an AI agent system with retrieval-augmented generation (RAG) and chapter-aware memory.

## Team

| Name | Email | Student ID |
|------|-------|------------|
| Raeeka Yusuf | raeeka.yusuf@sjsu.edu | 018233761 |
| Anil Kumar Bandaru | anilkumar.bandaru@sjsu.edu | 018280223 |
| Cameron Lee | cameron.lee@sjsu.edu | 014895556 |

**Course:** CMPE 258 — Deep Learning  
**Project Option:** Option 2 (LLMs + AI Agent System)

## Project Description

Readers often want to discuss a book as they read it — but online resources are full of spoilers. Literary Guide solves this by providing **chapter-aware analysis** that only references events up to the reader's current chapter.

**Core capabilities (planned):**
- Chapter-by-chapter thematic analysis, symbolism breakdown, and character motive discussion
- Spoiler boundary enforcement — the system never references events beyond the reader's current chapter
- Citations back to the source text
- Q&A and discussion prompts per chapter
- Reading progress tracking with chapter-aware memory

## Datasets

### BookSum (Hugging Face: `kmfoda/booksum`)

Summaries and analyses of book chapters from multiple sources.

**URL:** https://huggingface.co/datasets/kmfoda/booksum

**Fields:**
| Column | Description |
|--------|-------------|
| `is_aggregate` | Whether the entry is an aggregate summary |
| `source` | Source of the summary |
| `chapter_path` | Path to the chapter in the source |
| `summary_path` | Path to the summary |
| `book_id` | Unique book identifier |
| `chapter` | Chapter number/identifier |
| `summary_name` | Name of the summary |
| `summary_url` | URL to the summary source |
| `summary_text` | Full summary text |
| `summary_analysis` | Analysis of the chapter |
| `summary_length` | Length of the summary |
| `analysis_length` | Length of the analysis |

### NarrativeQA (DeepMind)

Question-answering pairs grounded in full narrative texts.

**URL:** https://github.com/google-deepmind/narrativeqa

**Files and fields:**

**`documents.csv`:** `document_id`, `set`, `kind`, `story_url`, `story_file_size`, `wiki_url`, `wiki_title`, `story_word_count`, `story_start`, `story_end`

**`summaries.csv`:** `document_id`, `set`, `summary`, `summary_tokenized`

**`qaps.csv`:** `document_id`, `set`, `question`, `answer1`, `answer2`, `question_tokenized`, `answer1_tokenized`, `answer2_tokenized`

## Approach

1. **Data ingestion** — Load and index BookSum chapter summaries and NarrativeQA question-answer pairs.
2. **Chapter-aware RAG** — Build a retrieval pipeline that filters context to only include content up to the reader's current chapter, preventing spoilers.
3. **LLM-powered analysis** — Use large language models to generate thematic discussion, symbolism analysis, and character motive breakdowns grounded in retrieved passages.
4. **Citation system** — Every claim the system makes links back to the source text passage.
5. **Agent orchestration** — An AI agent manages reading progress, enforces spoiler boundaries, and coordinates between retrieval and generation.

## Current Progress

- [x] Repository initialized with project structure
- [x] Python data loader for BookSum dataset (`python/scripts/load_booksum_sample.py`) — 50 sample rows
- [x] Chapter-aware filtering stub (`python/scripts/chapter_filter_stub.py`)
- [x] Sample dataset outputs generated (`python/outputs/booksum_samples.json`)
- [x] **Chapter-aware RAG pipeline** (`python/scripts/rag_pipeline.py`) — sentence-transformers embeddings + ChromaDB vector store + spoiler-safe retrieval via `query_up_to_chapter()`
- [x] **Literary Guide agent** (`python/scripts/literary_guide_agent.py`) — chapter-aware Q&A with retrieved-passage citations; pluggable LLM provider (Anthropic / OpenAI / dry-run)
- [x] **Flask HTTP API** (`python/scripts/api_server.py`) — `/ask` endpoint exposing the agent over HTTP
- [x] **Express.js Q&A UI** (`js/`) — chapter-aware question form proxied to the Python agent + sample data browser
- [x] **Spoiler-boundary eval harness** (`python/eval/`) — 6/6 test cases passing

## How to Run

### Python — set up venv and install deps

```bash
cd python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Load BookSum samples

```bash
python scripts/load_booksum_sample.py --n 50
```

This loads the BookSum dataset, prints column info, and saves N sample rows to `outputs/booksum_samples.json`.

**Chapter filter stub:**
```bash
python scripts/chapter_filter_stub.py --chapter 5
```

### RAG pipeline (chapter-aware retrieval)

```bash
python scripts/rag_pipeline.py
```

Builds an in-memory ChromaDB collection over the saved samples and runs an example query that respects the chapter spoiler boundary.

### Literary Guide agent — chapter-aware Q&A

Dry-run (retrieval only, no LLM call):
```bash
python scripts/literary_guide_agent.py \
    --question "What does the wilderness symbolize?" \
    --chapter 3
```

With Anthropic Claude (set `ANTHROPIC_API_KEY` and `pip install anthropic`):
```bash
python scripts/literary_guide_agent.py --question "..." --chapter 3 --provider anthropic
```

### HTTP API server

```bash
python scripts/api_server.py
# POST http://localhost:5050/ask  {question, chapter, provider, top_k}
```

### Run the full stack (Express UI + Flask agent)

```bash
# Terminal 1 — Python agent API on :5050
cd python && source venv/bin/activate && python scripts/api_server.py

# Terminal 2 — Express UI on :3000
cd js && npm start
```

Open http://localhost:3000 and use the **Ask** tab to ask chapter-aware questions.

### Spoiler-boundary evaluation

```bash
python eval/run_spoiler_eval.py
```

Runs 6 test cases verifying retrieved passages never exceed the reader's current chapter.

### JavaScript — Sample data viewer

```bash
cd js
npm install
npm start
```

Open http://localhost:3000 to browse the BookSum sample data.

## Repo Structure

```
Literary-Guide/
├── README.md
├── .gitignore
├── python/
│   ├── requirements.txt
│   ├── scripts/
│   │   ├── load_booksum_sample.py
│   │   ├── chapter_filter_stub.py
│   │   ├── rag_pipeline.py
│   │   ├── literary_guide_agent.py
│   │   └── api_server.py
│   ├── eval/
│   │   ├── spoiler_boundary_cases.json
│   │   └── run_spoiler_eval.py
│   └── outputs/
│       └── booksum_samples.json
└── js/
    ├── package.json
    ├── server.js
    └── public/
        └── index.html
```

## Next Steps

- [x] ~~Wire an LLM call on top of `query_up_to_chapter()` to produce grounded chapter analysis~~ — done in `literary_guide_agent.py`
- [x] ~~Citation extraction — surface `summary_id` / `chapter` for every retrieved passage~~ — done; numbered `[n]` citations in agent prompts
- [ ] Implement chapter-aware memory persisted across sessions
- [ ] Expand evaluation set to 50+ cases (currently 6)
- [ ] Compare 3+ LLMs (including at least 1 open-source model) on analysis quality
- [ ] Measure latency and cost per query across models
- [ ] Polish interactive UI: reading progress tracking, chapter-aware history


## Potential QA Testing Boundaries

- Chapter Information Limits (spoiler boundary correctness)
- Length + Depth of Chapter / Plot-point discussion
- Presence + Correctness of Citations
- Complexity of Analysis
- Comprehension and Description of Chapters
- Differences in Analysis based on Different Texts
  
## References

- **BookSum paper:** https://arxiv.org/abs/2105.08209
- **BookSum dataset (Hugging Face):** https://huggingface.co/datasets/kmfoda/booksum
- **NarrativeQA repository:** https://github.com/google-deepmind/narrativeqa
