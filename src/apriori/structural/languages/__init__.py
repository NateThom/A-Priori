"""Language-specific parsers for the structural layer.

Each parser implements the :class:`~apriori.structural.protocol.LanguageParser`
protocol and extracts structural entities (functions, classes, interfaces,
imports, re-exports) from source files via tree-sitter.
"""

from apriori.structural.languages.typescript import TypeScriptParser

__all__ = ["TypeScriptParser"]
