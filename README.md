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
- [x] Python data loader for BookSum dataset (`python/scripts/load_booksum_sample.py`)
- [x] Chapter-aware filtering stub (`python/scripts/chapter_filter_stub.py`)
- [x] Sample dataset outputs generated (`python/outputs/booksum_samples.json`)
- [x] Express.js viewer to browse sample data (`js/`)

## How to Run

### Python — Load BookSum samples

```bash
cd python
pip install -r requirements.txt
python scripts/load_booksum_sample.py
```

This loads the BookSum dataset, prints column info, and saves 3 sample rows to `outputs/booksum_samples.json`.

**Chapter filter stub:**
```bash
python scripts/chapter_filter_stub.py --chapter 5
```

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
│   │   └── chapter_filter_stub.py
│   └── outputs/
│       └── booksum_samples.json
└── js/
    ├── package.json
    ├── server.js
    └── public/
        └── index.html
```

## Next Steps

- [ ] Build full RAG pipeline with chapter-aware retrieval and citation extraction
- [ ] Implement chapter-aware memory persisted across sessions
- [ ] Create evaluation set (50+ test cases) for spoiler boundary accuracy
- [ ] Compare 3+ LLMs (including at least 1 open-source model) on analysis quality
- [ ] Measure latency and cost per query across models
- [ ] Build full interactive UI with reading progress tracking

## References

- **BookSum paper:** https://arxiv.org/abs/2105.08209
- **BookSum dataset (Hugging Face):** https://huggingface.co/datasets/kmfoda/booksum
- **NarrativeQA repository:** https://github.com/google-deepmind/narrativeqa
