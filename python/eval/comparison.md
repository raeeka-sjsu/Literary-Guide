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

## Classification metrics — should-the-model-refuse task

Treating each case as a binary classification: ground truth is whether
the question requires refusal (spoiler-trap or must_refuse case) vs.
legitimate answer. Confusion matrix terms:
- **True positive (TP)**: correctly refused a spoiler-trap
- **False negative (FN)**: leaked when should have refused (safety-critical failure)
- **False positive (FP)**: over-cautiously refused a legitimate question
- **True negative (TN)**: correctly answered a legitimate question

| Provider | TP | FP | TN | FN | Precision | Recall | F1 | Accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ollama | 9 | 0 | 22 | 29 | **1.000** | **0.237** | **0.383** | 0.517 |
| anthropic | 37 | 4 | 18 | 1 | **0.902** | **0.974** | **0.937** | 0.917 |
| openai | 37 | 2 | 20 | 1 | **0.949** | **0.974** | **0.961** | 0.950 |

Recall is the metric that matters most for our domain: of questions
that SHOULD have triggered a refusal, what fraction did the model
correctly refuse? A false negative here is a real spoiler reaching the user.

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
