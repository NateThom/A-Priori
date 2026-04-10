"""FQN helpers shared by structural graph components."""

from __future__ import annotations

from pathlib import Path


def module_fqn(file_path: Path) -> str:
    """Return the module-level FQN for a file."""
    return str(file_path)


def symbol_fqn(file_path: Path, *parts: str) -> str:
    """Return a symbol FQN: ``module_fqn::part1::part2``."""
    base = module_fqn(file_path)
    if not parts:
        return base
    return base + "::" + "::".join(parts)
