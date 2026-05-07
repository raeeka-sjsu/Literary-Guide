# Literary Guide — 3-LLM Comparison

All three models evaluated on the same 60 test questions.

## Overall pass rate

| Provider | Model | Pass | Total | Rate | Mean latency | p95 latency | Est. cost (run) |
|---|---|---:|---:|---:|---:|---:|---:|
| ollama | `llama3.2:3b` | 48 | 60 | **80.0%** | 7,366 ms | 12,398 ms | $0.0000 |
| anthropic | `claude-haiku-4-5` | 55 | 60 | **91.7%** | 4,287 ms | 6,828 ms | $0.1534 |
| openai | `gpt-4o-mini` | 56 | 60 | **93.3%** | 3,463 ms | 5,224 ms | $0.0250 |

## Pass rate by category

| Provider | analytical | refusal_or_edge | spoiler_trap |
|---|---:|---:|---:|
| ollama | 19/20 (95%) | 4/10 (40%) | 25/30 (83%) |
| anthropic | 20/20 (100%) | 10/10 (100%) | 25/30 (83%) |
| openai | 20/20 (100%) | 10/10 (100%) | 26/30 (87%) |

## Spoiler-leak rate (lower is better)

Of the spoiler-trap cases, what fraction did the model accidentally leak future-chapter information?

| Provider | Cases | Leaks | Leak rate |
|---|---:|---:|---:|
| ollama | 30 | 5 | **16.7%** |
| anthropic | 30 | 5 | **16.7%** |
| openai | 30 | 4 | **13.3%** |

## Cost & latency tradeoffs

| Provider | Avg latency | Avg cost / query | Cost / 1000 queries |
|---|---:|---:|---:|
| ollama | 7,366 ms | $0.00000 | $0.00 |
| anthropic | 4,287 ms | $0.00256 | $2.56 |
| openai | 3,463 ms | $0.00042 | $0.42 |

## Divergence across LLMs

- All providers passed: 42 cases
- All providers failed: 1 cases
- Only Llama (open-source) failed: 11 cases — these are the cases where the bigger commercial models edge out
- Only Llama passed: 1 cases
- Mixed: 5 cases
