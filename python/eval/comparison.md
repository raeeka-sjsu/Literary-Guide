# Literary Guide — 3-LLM Comparison

All three models evaluated on the same 60 test questions.

## Overall pass rate

| Provider | Model | Pass | Total | Rate | Mean latency | p95 latency | Est. cost (run) |
|---|---|---:|---:|---:|---:|---:|---:|
| ollama | `llama3.2:3b` | 49 | 60 | **81.7%** | 7,366 ms | 12,398 ms | $0.0000 |
| anthropic | `claude-haiku-4-5` | 58 | 60 | **96.7%** | 4,287 ms | 6,828 ms | $0.1534 |
| openai | `gpt-4o-mini` | 59 | 60 | **98.3%** | 3,463 ms | 5,224 ms | $0.0250 |

## Pass rate by category

| Provider | analytical | refusal_or_edge | spoiler_trap |
|---|---:|---:|---:|
| ollama | 19/20 (95%) | 5/10 (50%) | 25/30 (83%) |
| anthropic | 20/20 (100%) | 10/10 (100%) | 28/30 (93%) |
| openai | 20/20 (100%) | 10/10 (100%) | 29/30 (97%) |

## Spoiler-leak rate (lower is better)

Of the spoiler-trap cases, what fraction did the model accidentally leak future-chapter information?

| Provider | Cases | Leaks | Leak rate |
|---|---:|---:|---:|
| ollama | 30 | 5 | **16.7%** |
| anthropic | 30 | 2 | **6.7%** |
| openai | 30 | 1 | **3.3%** |

## Cost & latency tradeoffs

| Provider | Avg latency | Avg cost / query | Cost / 1000 queries |
|---|---:|---:|---:|
| ollama | 7,366 ms | $0.00000 | $0.00 |
| anthropic | 4,287 ms | $0.00256 | $2.56 |
| openai | 3,463 ms | $0.00042 | $0.42 |

## Divergence across LLMs

- All providers passed: 46 cases
- All providers failed: 0 cases
- Only Llama (open-source) failed: 11 cases — these are the cases where the bigger commercial models edge out
- Only Llama passed: 0 cases
- Mixed: 3 cases
