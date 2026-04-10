"""Librarian loop orchestrator — autonomous knowledge graph builder (ERD §4.2)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apriori.librarian.loop import LibrarianLoop


def __getattr__(name: str):
    if name == "LibrarianLoop":
        from apriori.librarian.loop import LibrarianLoop

        return LibrarianLoop
    raise AttributeError(name)

__all__ = ["LibrarianLoop"]
