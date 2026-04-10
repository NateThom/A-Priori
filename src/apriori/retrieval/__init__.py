"""Retrieval layer (Layer 3) — graph queries and impact computations.

Modules in this package query the KnowledgeStore (Layer 2) and return
derived results. No writes to the store are performed here.

Layer dependency rule (arch:layer-flow): retrieval/ may import from
models/, storage/, and any lower layer. Nothing lower may import from
retrieval/.
"""
