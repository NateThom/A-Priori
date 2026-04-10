"""Historical impact computation from git co-change patterns — Story 12.4.

This module scans git history once (batch), computes directional co-change
confidence between files with configurable recency decay, and upserts
``co-changes-with`` historical edges in the KnowledgeStore.
"""

from __future__ import annotations

import math
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from apriori.models.edge import Edge
from apriori.storage.protocol import KnowledgeStore


GitHistoryReader = Callable[[Path, int], list[set[str]]]


@dataclass(frozen=True)
class HistoricalImpactConfig:
    """Configuration for historical impact computation."""

    max_commits: int = 200
    decay_mode: Literal["exponential", "linear", "none"] = "exponential"
    decay_window: int = 200
    decay_lambda: float = 3.0
    linear_min_weight: float = 0.2
    min_confidence: float = 0.05


@dataclass(frozen=True)
class CoChangeConfidence:
    """Computed directional confidence for a file pair."""

    confidence: float
    co_change_count: int
    total_changes: int
    recency_weight: float


def _normalize_repo_path(repo_path: str | Path) -> Path:
    return Path(repo_path).resolve()


def _normalize_file_path(file_path: str) -> str:
    return Path(file_path).as_posix().lstrip("./")


def _read_git_history(repo_path: Path, max_commits: int) -> list[set[str]]:
    """Return changed files per commit, newest first."""
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_path),
            "log",
            f"-n{max_commits}",
            "--name-only",
            "--pretty=format:__COMMIT__",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    commits: list[set[str]] = []
    current: set[str] = set()

    for line in result.stdout.splitlines():
        if line == "__COMMIT__":
            if current:
                commits.append(current)
                current = set()
            continue

        path = line.strip()
        if path:
            current.add(_normalize_file_path(path))

    if current:
        commits.append(current)

    return commits


def _recency_weight(index: int, total_commits: int, config: HistoricalImpactConfig) -> float:
    if config.decay_mode == "none":
        return 1.0

    window = max(1, min(config.decay_window, total_commits))
    age = min(index, window - 1)
    position = age / max(1, window - 1)

    if config.decay_mode == "linear":
        return max(config.linear_min_weight, 1.0 - position)

    # exponential
    return math.exp(-config.decay_lambda * position)


def compute_file_cochange_confidences(
    commits: list[set[str]],
    config: HistoricalImpactConfig,
) -> dict[tuple[str, str], CoChangeConfidence]:
    """Compute directional file-pair co-change confidence scores.

    Confidence formula: ``(co_change_count / total_changes) * recency_weight``
    where ``recency_weight`` is the mean recency weight over co-change commits.
    """
    if not commits:
        return {}

    limited = commits[: config.max_commits]
    source_change_counts: defaultdict[str, int] = defaultdict(int)
    pair_co_counts: defaultdict[tuple[str, str], int] = defaultdict(int)
    pair_weight_sums: defaultdict[tuple[str, str], float] = defaultdict(float)

    for idx, files in enumerate(limited):
        normalized = sorted({_normalize_file_path(p) for p in files if p})
        if len(normalized) < 2:
            for path in normalized:
                source_change_counts[path] += 1
            continue

        weight = _recency_weight(idx, len(limited), config)

        for source in normalized:
            source_change_counts[source] += 1

        for source in normalized:
            for target in normalized:
                if source == target:
                    continue
                key = (source, target)
                pair_co_counts[key] += 1
                pair_weight_sums[key] += weight

    output: dict[tuple[str, str], CoChangeConfidence] = {}
    for key, co_count in pair_co_counts.items():
        source, _target = key
        total_changes = source_change_counts[source]
        if total_changes <= 0:
            continue

        recency = pair_weight_sums[key] / co_count
        confidence = (co_count / total_changes) * recency
        confidence = max(0.0, min(1.0, confidence))

        if confidence < config.min_confidence:
            continue

        output[key] = CoChangeConfidence(
            confidence=confidence,
            co_change_count=co_count,
            total_changes=total_changes,
            recency_weight=recency,
        )

    return output


def compute_historical_impact_edges(
    store: KnowledgeStore,
    repo_path: str | Path,
    *,
    config: HistoricalImpactConfig | None = None,
    read_git_history: GitHistoryReader | None = None,
) -> int:
    """Batch-compute and upsert historical ``co-changes-with`` edges.

    Returns:
        Number of edges created or updated.
    """
    cfg = config or HistoricalImpactConfig()
    history_reader = read_git_history or _read_git_history
    repo = _normalize_repo_path(repo_path)

    commits = history_reader(repo, cfg.max_commits)
    file_confidences = compute_file_cochange_confidences(commits, cfg)
    if not file_confidences:
        return 0

    file_to_concepts: defaultdict[str, set] = defaultdict(set)
    for concept in store.list_concepts():
        for ref in concept.code_references:
            file_to_concepts[_normalize_file_path(ref.file_path)].add(concept.id)

    if not file_to_concepts:
        return 0

    now = datetime.now(timezone.utc)
    concept_pair_best_confidence: dict[tuple, CoChangeConfidence] = {}

    for (src_file, tgt_file), stats in file_confidences.items():
        src_ids = file_to_concepts.get(src_file, set())
        tgt_ids = file_to_concepts.get(tgt_file, set())
        if not src_ids or not tgt_ids:
            continue

        for src_id in src_ids:
            for tgt_id in tgt_ids:
                if src_id == tgt_id:
                    continue
                key = (src_id, tgt_id)
                current = concept_pair_best_confidence.get(key)
                if current is None or stats.confidence > current.confidence:
                    concept_pair_best_confidence[key] = stats

    if not concept_pair_best_confidence:
        return 0

    git_head: str | None = None
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        git_head = result.stdout.strip() or None
    except subprocess.CalledProcessError:
        git_head = None

    upserts = 0

    for (src_id, tgt_id), stats in concept_pair_best_confidence.items():
        existing = store.list_edges(
            source_id=src_id,
            target_id=tgt_id,
            edge_type="co-changes-with",
        )

        if existing:
            edge = existing[0].model_copy(
                update={
                    "evidence_type": "historical",
                    "confidence": stats.confidence,
                    "metadata": {
                        "co_change_count": stats.co_change_count,
                        "total_changes": stats.total_changes,
                        "recency_weight": stats.recency_weight,
                    },
                    "derived_from_code_version": git_head,
                    "updated_at": now,
                }
            )
            store.update_edge(edge)
            upserts += 1
            continue

        store.create_edge(
            Edge(
                source_id=src_id,
                target_id=tgt_id,
                edge_type="co-changes-with",
                evidence_type="historical",
                confidence=stats.confidence,
                metadata={
                    "co_change_count": stats.co_change_count,
                    "total_changes": stats.total_changes,
                    "recency_weight": stats.recency_weight,
                },
                derived_from_code_version=git_head,
            )
        )
        upserts += 1

    return upserts


def build_historical_impact_pre_run_hook(
    store: KnowledgeStore,
    repo_path: str | Path,
    *,
    config: HistoricalImpactConfig | None = None,
    read_git_history: GitHistoryReader | None = None,
) -> Callable[[], None]:
    """Return a zero-arg hook compatible with ``LibrarianLoop(pre_run_hook=...)``."""

    def _hook() -> None:
        compute_historical_impact_edges(
            store,
            repo_path,
            config=config,
            read_git_history=read_git_history,
        )

    return _hook
