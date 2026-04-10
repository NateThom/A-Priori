# Model Quality Guide

A-Priori's librarian agent relies on an LLM for semantic analysis. This guide helps you choose the right model for your use case based on cost, quality, and speed.

---

## How the Librarian Uses the LLM

Each librarian iteration makes one structured completion call:
- **Input:** ~2,000–8,000 tokens (code context + related concepts + analysis prompt)
- **Output:** ~500–2,000 tokens (structured JSON with concepts, edges, and rationale)
- **Per-run cost** = (tokens per iteration) × (iterations) × (cost per 1K tokens)

The LLM is only called for semantic analysis. Structural parsing, embeddings, and retrieval do not use the LLM.

---

## Supported Providers

### Anthropic (Cloud)

Set in config:
```yaml
llm:
  provider: anthropic
  api_key_env: ANTHROPIC_API_KEY
  model: claude-opus-4-6  # or claude-sonnet-4-6, claude-haiku-4-5
```

Requires: `export ANTHROPIC_API_KEY=sk-ant-...`

### Ollama (Local)

Set in config:
```yaml
llm:
  provider: ollama
  model: llama3.1:70b
  base_url: http://localhost:11434
  api_key_env: OLLAMA_DUMMY_KEY  # set to any non-empty string
```

Requires: Ollama running locally with the model pulled (`ollama pull llama3.1:70b`)

---

## Model Comparison

### Anthropic Models

| Model | Quality | Speed | Cost/1M tokens (input) | Best For |
|---|---|---|---|---|
| claude-opus-4-6 | Excellent | Slow | ~$15 | Complex codebases, architectural analysis, high-stakes decisions |
| claude-sonnet-4-6 | Very Good | Moderate | ~$3 | Daily enrichment, good balance of quality and cost |
| claude-haiku-4-5 | Good | Fast | ~$0.25 | High-volume runs, simple relationships, cost-sensitive |

> Prices are approximate and subject to change. Check [Anthropic's pricing](https://www.anthropic.com/pricing) for current rates.

**Quality difference in practice:**

- **Opus** produces the most nuanced descriptions and is best at identifying subtle architectural dependencies. It almost always passes the co-regulation review on the first attempt.
- **Sonnet** produces high-quality output and passes co-regulation most of the time. Recommended for most teams.
- **Haiku** is faster and cheaper but sometimes produces generic descriptions that fail co-regulation and require a retry. Better for high-volume, lower-stakes enrichment.

### Ollama (Local) Models

| Model | Quality | Speed | VRAM Required | Best For |
|---|---|---|---|---|
| llama3.1:70b | Good | Moderate | ~48GB | Air-gapped environments, cost elimination |
| llama3.1:8b | Adequate | Fast | ~6GB | Laptops, quick exploration |
| codellama:34b | Good (code) | Moderate | ~24GB | Code-heavy codebases |
| deepseek-coder-v2:16b | Very Good (code) | Moderate | ~12GB | Code-specific semantic analysis |
| qwen2.5-coder:32b | Very Good (code) | Moderate | ~20GB | Code-specific analysis with strong reasoning |

**Note on Ollama quality:** Local models generally produce shorter, less nuanced descriptions than Claude. Expect more co-regulation retries, which means more tokens per effective concept enriched. Adjust `budget.cost_per_1k_tokens` to `0.0` when using Ollama since there's no API cost.

---

## Quality-Cost Tradeoffs

### Strategy 1: Maximum Quality (Opus)

Best when: You want the richest knowledge graph and can afford the cost.

```yaml
llm:
  provider: anthropic
  model: claude-opus-4-6

budget:
  max_tokens_per_run: 500000  # ~$7.50 per run at Opus pricing
  cost_per_1k_tokens: 0.015
```

**Expected yield:** ~8–12 high-confidence concepts enriched per 10 iterations.

### Strategy 2: Balanced Quality (Sonnet — Recommended)

Best when: You want good quality with reasonable cost for daily enrichment.

```yaml
llm:
  provider: anthropic
  model: claude-sonnet-4-6

budget:
  max_tokens_per_run: 200000  # ~$0.60 per run at Sonnet pricing
  cost_per_1k_tokens: 0.003
```

**Expected yield:** ~7–11 high-confidence concepts per 10 iterations.

### Strategy 3: Cost-Optimized (Haiku)

Best when: You're enriching a very large codebase and want to minimize cost.

```yaml
llm:
  provider: anthropic
  model: claude-haiku-4-5

budget:
  max_tokens_per_run: 1000000  # ~$0.25 per run at Haiku pricing
  cost_per_1k_tokens: 0.00025
```

**Expected yield:** ~5–9 accepted concepts per 10 iterations (higher retry rate).

Consider pairing Haiku enrichment with occasional Opus passes for the highest-priority concepts.

### Strategy 4: Free (Local via Ollama)

Best when: Cost elimination is the priority or you're in an air-gapped environment.

```yaml
llm:
  provider: ollama
  model: llama3.1:70b
  base_url: http://localhost:11434
  api_key_env: OLLAMA_DUMMY_KEY

budget:
  cost_per_1k_tokens: 0.0  # no API cost

quality:
  co_regulation:
    min_confidence_threshold: 0.65  # slightly relaxed for local models
```

**Expected yield:** ~4–8 accepted concepts per 10 iterations with a 70B model.

---

## Model Selection by Codebase Type

### Large Enterprise Codebase (>500K LOC)

- Start with **Sonnet** for initial structural enrichment
- Use **Opus** for architectural concepts (services, protocols, shared abstractions)
- Use **Haiku** for utility functions and well-understood patterns

```yaml
llm:
  model: claude-sonnet-4-6
librarian:
  max_iterations_per_run: 50
  bootstrap_coverage_threshold: 0.30  # lower threshold → more iterations in bootstrap mode
```

### Small to Medium Codebase (<50K LOC)

- **Sonnet** is usually the right choice throughout
- **Opus** if architectural clarity is critical (e.g., planning a major refactor)

```yaml
llm:
  model: claude-sonnet-4-6
librarian:
  max_iterations_per_run: 20
```

### Code-Heavy / Algorithmic Codebase

Code-specialized models (DeepSeek Coder, Qwen2.5-Coder) may outperform general models for implementation-heavy concepts, but general-purpose large models still win for architectural reasoning.

```yaml
llm:
  provider: ollama
  model: deepseek-coder-v2:16b
  base_url: http://localhost:11434
```

### Air-Gapped / Privacy-Sensitive

- Ollama with 70B+ model for best local quality
- 8B models work but require more manual review

---

## Quality Metrics to Watch

After running the librarian, check these metrics to evaluate model quality:

### 1. Co-regulation pass rate

In `apriori librarian status`, look at the failure rate. A pass rate below 60% suggests the model is struggling — consider switching to a more capable model or tightening the `auto_reject_threshold`.

### 2. Concept confidence distribution

In `apriori status`, check the confidence histogram. A healthy graph has most concepts above 0.7. If many concepts cluster around 0.5–0.6, the model is producing uncertain descriptions — Opus or Sonnet will produce higher-confidence output.

### 3. Human review rate

Check what fraction of concepts get the `needs-review` label. This is set when co-regulation confidence falls in [0.5, 0.7]. A rate above 30% means the model needs more context or a better model.

---

## Prompting Considerations

A-Priori uses fixed prompt templates designed for analytical LLMs. You cannot currently customize prompts — this is intentional to ensure consistent quality pipeline behavior.

If you find the librarian consistently misses a particular type of concept in your codebase, use `report_gap` (via MCP or CLI) to create targeted work items with specific context.

---

## Token Budget Recommendations

| Scenario | Recommended Budget | Notes |
|---|---|---|
| First init on a medium codebase | 500K–1M tokens | Gets you meaningful initial coverage |
| Daily incremental run | 50K–200K tokens | Picks up recent changes |
| Deep architectural analysis | 1M+ tokens | No limit; run Opus overnight |
| Cost-capped CI run | 100K tokens | Quick freshness check |

Set budget in config:
```yaml
budget:
  max_tokens_per_run: 200000
  max_tokens_per_iteration: 20000  # prevents a single runaway iteration
```
