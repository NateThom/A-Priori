"""Configuration system for A-Priori (PRD §2.3; ERD §2.3).

Loads apriori.config.yaml, merges with defaults, validates, and exposes typed Config.
API keys are never stored in config — referenced by environment variable name only.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default edge type vocabulary
# ---------------------------------------------------------------------------
DEFAULT_EDGE_TYPES: frozenset[str] = frozenset(
    {
        # Structural: derived deterministically from AST analysis (Layer 0)
        "calls",
        "imports",
        "inherits",
        "type-references",
        # Semantic: derived by librarian agents via LLM analysis (Layer 1)
        "depends-on",
        "implements",
        "relates-to",
        "shares-assumption-about",
        "extends",
        "supersedes",
        "owned-by",
        # Historical: derived from git history analysis (Layer 2)
        "co-changes-with",
    }
)

# Default base priority weights for the six-factor scoring model (PRD §6.3, ERD §4.3.1).
# Must sum to 1.0. Custom weights can be specified in apriori.config.yaml under
# base_priority_weights and will be normalized if they don't sum to 1.0.
DEFAULT_BASE_PRIORITIES = {
    "coverage_gap": 0.15,          # gap in file coverage (investigate_file items)
    "needs_review": 0.20,          # concept labeled needs-review
    "developer_proximity": 0.25,   # graph distance from recently-modified files (inverted)
    "git_activity": 0.20,          # normalized commit count over configurable window
    "staleness": 0.15,             # days since last verification, normalized
    "failure_urgency": 0.05,       # normalized prior failure count
}


# ---------------------------------------------------------------------------
# Nested Config Models (Pydantic v2)
# ---------------------------------------------------------------------------
class LLMConfig(BaseModel):
    """LLM provider configuration."""

    provider: Literal["anthropic", "ollama"] = "anthropic"
    api_key_env: str = "ANTHROPIC_API_KEY"
    model: str = "claude-opus-4-6"
    base_url: Optional[str] = None  # for Ollama or custom endpoints
    timeout_seconds: int = 300

    @field_validator("api_key_env")
    @classmethod
    def api_key_env_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("api_key_env must not be empty")
        return v


class LibrarianConfig(BaseModel):
    """Librarian loop configuration."""

    modulation_strength: float = Field(default=0.8, ge=0.0, le=1.0)
    max_iterations_per_run: int = Field(default=10, ge=1)
    context_window_tokens: int = Field(default=200000, ge=1000)


class QualityCoRegulationConfig(BaseModel):
    """Co-regulation review configuration."""

    enabled: bool = True
    min_confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    require_human_review_below: float = Field(default=0.5, ge=0.0, le=1.0)


class QualityConfig(BaseModel):
    """Quality pipeline configuration."""

    co_regulation: QualityCoRegulationConfig = Field(
        default_factory=QualityCoRegulationConfig
    )
    level1_consistency_checks_enabled: bool = True
    auto_reject_threshold: float = Field(default=0.3, ge=0.0, le=1.0)


class BudgetConfig(BaseModel):
    """Token budget configuration (ERD §4.8).

    Enforces per-run and per-iteration token limits to prevent unexpected costs.
    When unset (None), the corresponding limit is not enforced.
    """

    max_tokens_per_run: Optional[int] = Field(default=None, ge=1)
    max_tokens_per_iteration: Optional[int] = Field(default=None, ge=1)
    token_estimation_window: int = Field(
        default=5,
        ge=1,
        description="Number of recent iterations used to compute the rolling average cost estimate.",
    )


class WorkQueueConfig(BaseModel):
    """Work queue and backlog configuration."""

    retention_days: int = Field(default=30, ge=1)
    max_backlog_size: int = Field(default=10000, ge=100)
    priority_recalc_interval_hours: int = Field(default=24, ge=1)


class EmbeddingConfig(BaseModel):
    """Embedding service configuration.

    Per S-2 spike decision: intfloat/e5-base-v2 via sentence-transformers.
    Produces 768-dimensional vectors. Model is ~440MB and downloaded once.
    """

    model: str = "intfloat/e5-base-v2"
    dimensions: int = 768
    batch_size: int = Field(default=32, ge=1)


class StorageConfig(BaseModel):
    """Storage configuration."""

    sqlite_path: str = "./apriori.db"
    yaml_backup_path: str = "./apriori_backup.yaml"
    enable_dual_write: bool = True


class Config(BaseModel):
    """Complete A-Priori configuration."""

    # Core settings
    project_name: str = "A-Priori"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # Sub-configurations
    llm: LLMConfig = Field(default_factory=LLMConfig)
    librarian: LibrarianConfig = Field(default_factory=LibrarianConfig)
    quality: QualityConfig = Field(default_factory=QualityConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    work_queue: WorkQueueConfig = Field(default_factory=WorkQueueConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)

    # Edge types vocabulary (default + custom)
    edge_types: set[str] = Field(default_factory=lambda: set(DEFAULT_EDGE_TYPES))

    # Base priority weights
    base_priority_weights: dict[str, float] = Field(
        default_factory=lambda: DEFAULT_BASE_PRIORITIES.copy()
    )

    @model_validator(mode="after")
    def normalize_priority_weights(self) -> "Config":
        """Normalize priority weights to sum to 1.0 if they don't already."""
        weights = self.base_priority_weights
        total = sum(weights.values())

        if total <= 0:
            raise ValueError("base_priority_weights must have at least one positive value")

        # If not close to 1.0, normalize and warn
        if not abs(total - 1.0) < 0.001:
            logger.warning(
                f"base_priority_weights sum to {total:.4f}, not 1.0. Normalizing proportionally."
            )
            factor = 1.0 / total
            self.base_priority_weights = {k: v * factor for k, v in weights.items()}

        return self


def load_config(path: Optional[Path] = None) -> Config:
    """Load and validate A-Priori configuration.

    Load apriori.config.yaml (or custom path), merge with defaults, validate,
    and return a fully-populated typed Config object.

    Args:
        path: Path to config file. If None, searches for apriori.config.yaml
              in current working directory. If not found, uses all defaults.

    Returns:
        Validated Config object with all required fields populated.

    Raises:
        ValueError: If config file is invalid or required values are missing.
    """

    # Determine config file path
    if path is None:
        default_path = Path.cwd() / "apriori.config.yaml"
        path = default_path if default_path.exists() else None

    # Load YAML if config file exists
    user_config_dict = {}
    if path and path.exists():
        try:
            with open(path, "r") as f:
                loaded = yaml.safe_load(f)
                if loaded:  # YAML can return None for empty files
                    user_config_dict = loaded
            logger.info(f"Loaded configuration from {path}")
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to load config from {path}: {e}") from e
    elif path:
        logger.info(f"Config file not found at {path}, using defaults")
    else:
        logger.info("No config file found, using defaults")

    # Handle edge_types merging: append custom types to defaults
    if "edge_types" in user_config_dict:
        custom_types = user_config_dict.pop("edge_types")
        user_edge_types = set(DEFAULT_EDGE_TYPES) | set(custom_types)
        user_config_dict["edge_types"] = user_edge_types

    # Merge user config with defaults by creating a default Config and
    # selectively overriding with user values
    try:
        config = Config(**user_config_dict)
    except Exception as e:
        raise ValueError(f"Configuration validation failed: {e}") from e

    return config
