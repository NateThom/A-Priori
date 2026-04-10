# Configuration Reference

A-Priori reads configuration from `apriori.config.yaml` in your project's `.apriori/` directory. All settings have sensible defaults — the file is optional, and `apriori init` generates it for you.

## Loading Order

1. `apriori init` writes `.apriori/apriori.config.yaml` with defaults
2. On every command, A-Priori loads that file (or falls back to all defaults if missing)
3. Your overrides are merged on top of the defaults

## Top-Level Settings

| Key | Type | Default | Description |
|---|---|---|---|
| `project_name` | string | `"A-Priori"` | Display name for this project |
| `log_level` | string | `"INFO"` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |

## `storage`

Controls where A-Priori persists data.

| Key | Type | Default | Description |
|---|---|---|---|
| `sqlite_path` | string | `"./apriori.db"` | Path to the SQLite knowledge graph database |
| `yaml_backup_path` | string | `"./apriori_backup.yaml"` | Directory for the human-readable YAML backup |
| `enable_dual_write` | bool | `true` | Keep SQLite and YAML in sync on every write (strongly recommended) |

> **Note:** When `enable_dual_write: true`, every write goes to both stores. Disabling it breaks the ability to rebuild the database from the YAML backup.

**Example:**
```yaml
storage:
  sqlite_path: ".apriori/graph.db"
  yaml_backup_path: ".apriori/concepts"
  enable_dual_write: true
```

## `llm`

Controls which LLM provider the librarian agent uses.

| Key | Type | Default | Valid Values | Description |
|---|---|---|---|---|
| `provider` | string | `"anthropic"` | `"anthropic"`, `"ollama"` | LLM provider backend |
| `api_key_env` | string | `"ANTHROPIC_API_KEY"` | any env var name | Environment variable that holds the API key |
| `model` | string | `"claude-opus-4-6"` | any model ID | Model to use for semantic analysis |
| `base_url` | string | `null` | any URL | Override endpoint (required for Ollama) |
| `timeout_seconds` | int | `300` | ≥ 1 | Per-request timeout in seconds |

**Example — Anthropic:**
```yaml
llm:
  provider: anthropic
  api_key_env: ANTHROPIC_API_KEY
  model: claude-sonnet-4-6
```

**Example — Ollama:**
```yaml
llm:
  provider: ollama
  model: llama3.1:70b
  base_url: http://localhost:11434
  api_key_env: OLLAMA_API_KEY  # set to any non-empty string
```

## `librarian`

Controls the autonomous librarian loop behavior.

| Key | Type | Default | Valid Range | Description |
|---|---|---|---|---|
| `modulation_strength` | float | `0.8` | [0.0, 1.0] | How aggressively adaptive modulation shifts priority weights. 0 = no modulation, 1 = full modulation. |
| `max_iterations_per_run` | int | `10` | ≥ 1 | Maximum analysis iterations per `librarian run` call |
| `context_window_tokens` | int | `200000` | ≥ 1000 | Estimated context window of the chosen model (for budget estimation) |
| `bootstrap_coverage_threshold` | float | `0.50` | [0.0, 1.0] or null | When coverage is below this fraction, enable bootstrap mode (prioritizes recent changes). Set to `null` to disable. |
| `bootstrap_developer_proximity_strength` | float | `2.0` | ≥ 0.0 | Multiplier for developer_proximity weight during bootstrap mode |

**Effect of `modulation_strength`:**
- `0.0`: Priority weights stay exactly at their configured base values regardless of graph health
- `0.8` (default): Weights shift significantly toward the most pressing need (coverage vs. freshness vs. blast radius)
- `1.0`: Maximum adaptation; effective weights may differ substantially from base weights

**Bootstrap mode** activates when coverage falls below `bootstrap_coverage_threshold`. It aggressively boosts the `developer_proximity` factor so the librarian prioritizes concepts near recent git commits — giving you the most relevant knowledge first.

**Example:**
```yaml
librarian:
  modulation_strength: 0.8
  max_iterations_per_run: 20
  bootstrap_coverage_threshold: 0.40
```

## `quality`

Controls the quality assurance pipeline that validates librarian output.

### `quality.co_regulation`

| Key | Type | Default | Valid Range | Description |
|---|---|---|---|---|
| `enabled` | bool | `true` | — | Enable co-regulation (consensus) review of librarian output |
| `min_confidence_threshold` | float | `0.7` | [0.0, 1.0] | Minimum confidence score to accept a concept without human review |
| `require_human_review_below` | float | `0.5` | [0.0, 1.0] | Concepts below this confidence are flagged `needs-review` |

### `quality` (top-level)

| Key | Type | Default | Valid Range | Description |
|---|---|---|---|---|
| `level1_consistency_checks_enabled` | bool | `true` | — | Enable Level 1 structural consistency checks on librarian output |
| `auto_reject_threshold` | float | `0.3` | [0.0, 1.0] | Concepts with quality scores below this are automatically rejected and re-queued |

**Example:**
```yaml
quality:
  co_regulation:
    enabled: true
    min_confidence_threshold: 0.75
    require_human_review_below: 0.5
  level1_consistency_checks_enabled: true
  auto_reject_threshold: 0.3
```

## `budget`

Prevents unexpected API cost overruns.

| Key | Type | Default | Valid Range | Description |
|---|---|---|---|---|
| `max_tokens_per_run` | int | `null` | ≥ 1 or null | Hard token limit per `librarian run` call. `null` = no limit. |
| `max_tokens_per_iteration` | int | `null` | ≥ 1 or null | Hard token limit per single analysis iteration. `null` = no limit. |
| `token_estimation_window` | int | `5` | ≥ 1 | Rolling window of recent iterations used to estimate remaining cost |
| `cost_per_1k_tokens` | float | `0.015` | ≥ 0.0 | USD cost per 1,000 tokens (used for cost estimation only) |

**Example — cap at 100K tokens per run:**
```yaml
budget:
  max_tokens_per_run: 100000
  cost_per_1k_tokens: 0.015  # ~Claude Sonnet pricing
```

## `work_queue`

Controls work item lifecycle and backlog management.

| Key | Type | Default | Valid Range | Description |
|---|---|---|---|---|
| `retention_days` | int | `30` | ≥ 1 | How long completed work items are retained in history |
| `max_backlog_size` | int | `10000` | ≥ 100 | Maximum number of pending work items |
| `priority_recalc_interval_hours` | int | `24` | ≥ 1 | How often priority scores are recomputed |
| `impact_profile_staleness_hours` | int | `24` | ≥ 1 | How old an impact profile must be before the librarian re-queues it |

## `embedding`

Controls the embedding model used for semantic search.

| Key | Type | Default | Description |
|---|---|---|---|
| `model` | string | `"intfloat/e5-base-v2"` | Sentence-transformers model ID (768-dimensional) |
| `dimensions` | int | `768` | Embedding vector dimensions (must match the chosen model) |
| `batch_size` | int | `32` | Number of texts embedded per batch |

> **Warning:** Changing the embedding model requires re-embedding all existing concepts. Run `apriori rebuild-index` after changing this setting.

## `edge_types`

A list of custom edge type strings to add to the vocabulary. Custom types are merged with the defaults.

```yaml
edge_types:
  - "triggers"
  - "validates"
  - "replaces"
```

**Default vocabulary:**

| Type | Layer | Description |
|---|---|---|
| `calls` | Structural | A function calls another function |
| `imports` | Structural | A module imports another module |
| `inherits` | Structural | A class inherits from another class |
| `type-references` | Structural | A type references another type |
| `depends-on` | Semantic | Functional dependency |
| `implements` | Semantic | Implements an interface or contract |
| `relates-to` | Semantic | General semantic relationship |
| `shares-assumption-about` | Semantic | Shared architectural assumption |
| `extends` | Semantic | Extends behavior without inheriting |
| `supersedes` | Semantic | Replaces a deprecated concept |
| `owned-by` | Semantic | Ownership or responsibility |
| `co-changes-with` | Historical | Files that frequently change together |

## `base_priority_weights`

Override the six-factor priority weights used by the librarian's work queue. Values are normalized to sum to 1.0 automatically.

| Factor | Default | Description |
|---|---|---|
| `coverage_gap` | `0.15` | Under-represented files in the knowledge graph |
| `needs_review` | `0.20` | Concepts explicitly flagged for review |
| `developer_proximity` | `0.25` | Graph distance from recently-modified files (inverted) |
| `git_activity` | `0.20` | Normalized commit count |
| `staleness` | `0.15` | Days since last concept verification |
| `failure_urgency` | `0.05` | Prior analysis failure count |

**Example — emphasize freshness:**
```yaml
base_priority_weights:
  coverage_gap: 0.10
  needs_review: 0.15
  developer_proximity: 0.20
  git_activity: 0.15
  staleness: 0.35
  failure_urgency: 0.05
```

## Complete Example

```yaml
# .apriori/apriori.config.yaml

project_name: "My Project"
log_level: "INFO"

storage:
  sqlite_path: ".apriori/graph.db"
  yaml_backup_path: ".apriori/concepts"
  enable_dual_write: true

llm:
  provider: anthropic
  api_key_env: ANTHROPIC_API_KEY
  model: claude-sonnet-4-6
  timeout_seconds: 300

librarian:
  modulation_strength: 0.8
  max_iterations_per_run: 20
  bootstrap_coverage_threshold: 0.50

quality:
  co_regulation:
    enabled: true
    min_confidence_threshold: 0.70
    require_human_review_below: 0.50
  level1_consistency_checks_enabled: true
  auto_reject_threshold: 0.30

budget:
  max_tokens_per_run: 200000

work_queue:
  retention_days: 30
  impact_profile_staleness_hours: 24

embedding:
  model: "intfloat/e5-base-v2"
  dimensions: 768
  batch_size: 32
```
