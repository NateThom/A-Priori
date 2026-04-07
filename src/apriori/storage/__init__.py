"""Storage layer for A-Priori.

All storage access goes through the KnowledgeStore protocol.
No direct SQLite calls outside this module (arch:no-raw-sql).
"""

from apriori.storage.dual_writer import DualWriter
from apriori.storage.protocol import KnowledgeStore
from apriori.storage.rebuild import rebuild_index_from_yaml
from apriori.storage.sqlite_store import SQLiteStore
from apriori.storage.yaml_store import YamlStore, slugify

__all__ = [
    "DualWriter",
    "KnowledgeStore",
    "rebuild_index_from_yaml",
    "SQLiteStore",
    "YamlStore",
    "slugify",
]
