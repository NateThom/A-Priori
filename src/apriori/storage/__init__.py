"""Storage layer for A-Priori.

All storage access goes through the KnowledgeStore protocol.
No direct SQLite calls outside this module (arch:no-raw-sql).
"""

from apriori.storage.protocol import KnowledgeStore
from apriori.storage.yaml_store import YamlStore, slugify

__all__ = ["KnowledgeStore", "YamlStore", "slugify"]
