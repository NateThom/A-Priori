# A-Priori

**A-Priori** is an autonomous knowledge graph for your codebase. It uses static analysis and LLM-driven enrichment to build a queryable map of concepts, relationships, and architectural decisions — and keeps it fresh as your code evolves.

---

## Quick Start

> **Goal:** Go from zero to a queryable structural graph in under 60 seconds.

### Prerequisites

- Python 3.11+
- An Anthropic API key (for semantic enrichment; not required for structural-only graph)

### Install

```bash
pip install apriori
```

### Initialize your repo

```bash
cd /path/to/your/project
apriori init
```

This command:
1. Creates `.apriori/` directory and `apriori.config.yaml`
2. Parses all Python, TypeScript, and JavaScript files with tree-sitter
3. Builds a structural knowledge graph (concepts + typed edges)
4. Generates embeddings for semantic search

Expected output:
```
A-Priori: initialising repository at /path/to/your/project
  Scanning /path/to/your/project for source files…
  Parsed 142 file(s) in 3.2s
  Built 89 concept(s) and 234 edge(s) in 1.4s
  Generating embeddings for 89 concept(s)…
  Done. Knowledge graph ready at .apriori/graph.db
```

### Query the graph

```bash
# Keyword search
apriori search "authentication"

# Check graph health
apriori status

# See blast radius of a change
apriori blast-radius UserAuthService
```

You now have a queryable structural knowledge graph. Continue reading to add semantic enrichment with the librarian agent.

---

## Semantic Enrichment (10 iterations to value)

The **librarian** is an autonomous agent that enriches your structural graph with semantic relationships. It analyzes your code in context and adds meaning: what things *do*, how they *relate*, and which concepts *depend on* each other.

### Set your API key

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### Run the librarian

```bash
apriori librarian run --iterations 10
```

After 10 iterations the librarian will have:
- Verified and enriched the highest-priority concepts
- Added semantic edges (depends-on, implements, extends, …)
- Flagged concepts that need human review

Check progress:
```bash
apriori librarian status
```

---

## Audit UI

The read-only web UI lets you browse the knowledge graph, review concepts, and monitor health.

```bash
apriori ui
```

Open `http://127.0.0.1:8000` in your browser. See the [Audit UI Guide](docs/audit-ui.md) for full details.

---

## MCP Integration

A-Priori exposes its knowledge graph as a [Model Context Protocol](https://modelcontextprotocol.io) server, so any MCP-compatible client (Claude Desktop, Cursor, etc.) can query it directly.

```bash
python -m apriori.mcp.server
```

Add to your MCP client config:
```json
{
  "mcpServers": {
    "apriori": {
      "command": "python",
      "args": ["-m", "apriori.mcp.server"],
      "cwd": "/path/to/your/project"
    }
  }
}
```

---

## Documentation

| Guide | Description |
|---|---|
| [Configuration Reference](docs/configuration.md) | All config options, defaults, and valid ranges |
| [MCP Tool Reference](docs/mcp-tools.md) | All MCP tools with schemas and examples |
| [Architecture Guide](docs/architecture.md) | Four-layer architecture, quality pipeline, adaptive priorities |
| [Model Quality Guide](docs/model-quality.md) | LLM cost/quality/speed tradeoffs and recommendations |
| [Audit UI Guide](docs/audit-ui.md) | Graph browser, review workflow, health dashboard |

---

## License

MIT
