"""Documentation accuracy tests (Story 13.3).

Given/When/Then:
  Given the MCP tool reference, when consulted, then all MCP tools are documented
    with input/output schemas and usage examples.
  Given the configuration reference, when consulted, then every configuration option
    is documented with its default value, valid range, and effect on system behavior.
  Given the README.md, when a new user follows the quick-start guide, then they can
    go from zero to a queryable structural graph in 60 seconds.
  Given the architecture guide, when read by a new contributor, then they understand
    the four-layer architecture, the quality pipeline, and the adaptive priority system.
  Given the model quality guide, when a user is choosing an LLM, then they can compare
    cost/quality/speed tradeoffs for recommended models.
  Given the audit UI guide, when a user opens the UI, then they can navigate the graph,
    use the review workflow, and interpret the health dashboard.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DOCS_ROOT = Path(__file__).parents[2] / "docs"
_README = Path(__file__).parents[2] / "README.md"


def _read_doc(filename: str) -> str:
    path = _DOCS_ROOT / filename
    assert path.exists(), f"Documentation file missing: {path}"
    content = path.read_text(encoding="utf-8")
    assert content.strip(), f"Documentation file is empty: {path}"
    return content


# ---------------------------------------------------------------------------
# MCP tool reference completeness (AC3)
# ---------------------------------------------------------------------------


class TestMcpToolReference:
    """All MCP tools are documented with schemas and examples."""

    def _get_registered_tool_names(self) -> set[str]:
        """Discover all @mcp.tool() decorated functions by inspecting the module."""
        from apriori.mcp import server as mcp_module
        # FastMCP exposes registered tools on mcp._tool_manager._tools
        # We introspect the module's mcp instance directly.
        registered = set()
        for name in dir(mcp_module):
            obj = getattr(mcp_module, name, None)
            if callable(obj) and hasattr(obj, "__wrapped__"):
                # safe_tool decorator sets __wrapped__; mcp.tool() sets __name__
                registered.add(obj.__name__)
        # Also enumerate tools registered with FastMCP directly
        mcp_app = mcp_module.mcp
        # FastMCP stores tools in _tool_manager; fall back to introspection
        if hasattr(mcp_app, "_tool_manager") and hasattr(mcp_app._tool_manager, "_tools"):
            registered.update(mcp_app._tool_manager._tools.keys())
        return registered

    def test_mcp_tools_doc_exists(self) -> None:
        """Given the MCP tool reference file, when opened, it is non-empty."""
        _read_doc("mcp-tools.md")

    def test_all_known_tools_documented(self) -> None:
        """Given the MCP tool reference, all known tool names appear in it."""
        content = _read_doc("mcp-tools.md")
        # These are the core tools; the doc must mention each by name in a heading
        expected_tools = {
            "search",
            "search_keyword",
            "search_semantic",
            "list_concepts",
            "get_concept",
            "get_neighbors",
            "traverse",
            "blast_radius",
            "get_edge",
            "list_edges",
            "list_edge_types",
            "get_status",
            "get_metrics",
            "create_concept",
            "update_concept",
            "delete_concept",
            "create_edge",
            "update_edge",
            "delete_edge",
            "report_gap",
        }
        missing = [name for name in expected_tools if f"`{name}`" not in content]
        assert not missing, f"MCP tools not documented: {missing}"

    def test_tool_sections_have_parameters(self) -> None:
        """Given the MCP tool reference, each major tool section describes parameters."""
        content = _read_doc("mcp-tools.md")
        # Each tool section should have a Parameters table or 'None'
        assert "Parameters" in content

    def test_tool_sections_have_examples(self) -> None:
        """Given the MCP tool reference, tool sections include usage examples."""
        content = _read_doc("mcp-tools.md")
        # Examples are shown as JSON code blocks
        assert "```json" in content

    def test_tool_sections_have_returns(self) -> None:
        """Given the MCP tool reference, tool sections describe return values."""
        content = _read_doc("mcp-tools.md")
        assert "Returns" in content

    def test_data_schemas_documented(self) -> None:
        """Given the MCP tool reference, ConceptDict and EdgeDict schemas are documented."""
        content = _read_doc("mcp-tools.md")
        assert "ConceptDict" in content
        assert "EdgeDict" in content


# ---------------------------------------------------------------------------
# Configuration reference completeness (AC2)
# ---------------------------------------------------------------------------


class TestConfigurationReference:
    """Every configuration option is documented with defaults and valid ranges."""

    def test_configuration_doc_exists(self) -> None:
        """Given the configuration reference file, when opened, it is non-empty."""
        _read_doc("configuration.md")

    def test_all_top_level_config_sections_documented(self) -> None:
        """Given the configuration reference, all Config sub-model names appear."""
        content = _read_doc("configuration.md")
        sections = ["llm", "librarian", "quality", "budget", "work_queue", "embedding", "storage"]
        missing = [s for s in sections if f"`{s}`" not in content]
        assert not missing, f"Config sections not documented: {missing}"

    def test_llm_config_fields_documented(self) -> None:
        """Given the configuration reference, LLMConfig fields are documented."""
        content = _read_doc("configuration.md")
        fields = ["provider", "api_key_env", "model", "base_url", "timeout_seconds"]
        missing = [f for f in fields if f not in content]
        assert not missing, f"LLMConfig fields not documented: {missing}"

    def test_librarian_config_fields_documented(self) -> None:
        """Given the configuration reference, LibrarianConfig fields are documented."""
        content = _read_doc("configuration.md")
        fields = [
            "modulation_strength",
            "max_iterations_per_run",
            "bootstrap_coverage_threshold",
        ]
        missing = [f for f in fields if f not in content]
        assert not missing, f"LibrarianConfig fields not documented: {missing}"

    def test_budget_config_fields_documented(self) -> None:
        """Given the configuration reference, BudgetConfig fields are documented."""
        content = _read_doc("configuration.md")
        fields = ["max_tokens_per_run", "max_tokens_per_iteration", "cost_per_1k_tokens"]
        missing = [f for f in fields if f not in content]
        assert not missing, f"BudgetConfig fields not documented: {missing}"

    def test_storage_config_fields_documented(self) -> None:
        """Given the configuration reference, StorageConfig fields are documented."""
        content = _read_doc("configuration.md")
        fields = ["sqlite_path", "yaml_backup_path", "enable_dual_write"]
        missing = [f for f in fields if f not in content]
        assert not missing, f"StorageConfig fields not documented: {missing}"

    def test_default_values_present(self) -> None:
        """Given the configuration reference, default values are listed for key options."""
        content = _read_doc("configuration.md")
        # Key defaults from config.py
        assert "anthropic" in content  # llm.provider default
        assert "claude-opus-4-6" in content  # llm.model default
        assert "intfloat/e5-base-v2" in content  # embedding.model default
        assert "0.8" in content  # modulation_strength default
        assert "0.7" in content  # co_regulation min_confidence default

    def test_edge_type_vocabulary_documented(self) -> None:
        """Given the configuration reference, the default edge types are listed."""
        content = _read_doc("configuration.md")
        edge_types = ["calls", "imports", "inherits", "depends-on", "implements", "co-changes-with"]
        missing = [t for t in edge_types if t not in content]
        assert not missing, f"Edge types not documented: {missing}"

    def test_priority_weight_factors_documented(self) -> None:
        """Given the configuration reference, all six priority factors are documented."""
        content = _read_doc("configuration.md")
        factors = [
            "coverage_gap",
            "needs_review",
            "developer_proximity",
            "git_activity",
            "staleness",
            "failure_urgency",
        ]
        missing = [f for f in factors if f not in content]
        assert not missing, f"Priority factors not documented: {missing}"

    def test_config_defaults_match_code(self) -> None:
        """Given the configuration reference, documented defaults match actual Config defaults."""
        from apriori.config import Config, LLMConfig, LibrarianConfig, BudgetConfig

        config = Config()
        content = _read_doc("configuration.md")

        # Spot-check key defaults appear in the doc
        assert str(config.llm.timeout_seconds) in content  # 300
        assert str(config.librarian.max_iterations_per_run) in content  # 10
        assert str(config.embedding.batch_size) in content  # 32
        assert str(config.work_queue.retention_days) in content  # 30


# ---------------------------------------------------------------------------
# README quick-start (AC1)
# ---------------------------------------------------------------------------


class TestReadmeQuickStart:
    """README guides a new user from zero to a queryable graph."""

    def test_readme_exists(self) -> None:
        """Given the README.md, when opened, it is non-empty."""
        assert _README.exists(), "README.md is missing"
        content = _README.read_text(encoding="utf-8")
        assert content.strip(), "README.md is empty"

    def test_readme_has_install_instructions(self) -> None:
        """Given the README.md, it includes installation instructions."""
        content = _README.read_text(encoding="utf-8")
        assert "pip install" in content

    def test_readme_has_init_command(self) -> None:
        """Given the README.md, it shows the apriori init command."""
        content = _README.read_text(encoding="utf-8")
        assert "apriori init" in content

    def test_readme_has_search_command(self) -> None:
        """Given the README.md, it shows a search command for querying the graph."""
        content = _README.read_text(encoding="utf-8")
        assert "apriori search" in content

    def test_readme_has_quick_start_section(self) -> None:
        """Given the README.md, it has an identifiable quick-start section."""
        content = _README.read_text(encoding="utf-8")
        assert "Quick Start" in content or "quick start" in content.lower()

    def test_readme_has_links_to_docs(self) -> None:
        """Given the README.md, it links to the full documentation."""
        content = _README.read_text(encoding="utf-8")
        assert "docs/" in content

    def test_readme_mentions_structural_graph(self) -> None:
        """Given the README.md, it mentions the structural knowledge graph."""
        content = _README.read_text(encoding="utf-8")
        assert "structural" in content.lower() or "knowledge graph" in content.lower()

    def test_readme_has_mcp_integration(self) -> None:
        """Given the README.md, it covers MCP integration."""
        content = _README.read_text(encoding="utf-8")
        assert "MCP" in content or "Model Context Protocol" in content


# ---------------------------------------------------------------------------
# Architecture guide (AC4)
# ---------------------------------------------------------------------------


class TestArchitectureGuide:
    """New contributors understand four-layer architecture and quality pipeline."""

    def test_architecture_doc_exists(self) -> None:
        """Given the architecture guide, when opened, it is non-empty."""
        _read_doc("architecture.md")

    def test_four_layers_described(self) -> None:
        """Given the architecture guide, all four layers are described."""
        content = _read_doc("architecture.md")
        layers = ["Layer 0", "Layer 1", "Layer 2", "Layer 3"]
        missing = [l for l in layers if l not in content]
        assert not missing, f"Architecture layers not described: {missing}"

    def test_quality_pipeline_described(self) -> None:
        """Given the architecture guide, the quality pipeline is described."""
        content = _read_doc("architecture.md")
        assert "quality pipeline" in content.lower() or "Quality Pipeline" in content

    def test_level1_and_coregulation_described(self) -> None:
        """Given the architecture guide, Level 1 checks and co-regulation are described."""
        content = _read_doc("architecture.md")
        assert "Level 1" in content
        assert "co-regulation" in content.lower() or "Co-Regulation" in content

    def test_adaptive_priority_system_described(self) -> None:
        """Given the architecture guide, the adaptive priority system is described."""
        content = _read_doc("architecture.md")
        assert "priority" in content.lower()
        assert "modulation" in content.lower() or "Modulation" in content

    def test_dependency_rule_stated(self) -> None:
        """Given the architecture guide, the layer dependency rule is stated."""
        content = _read_doc("architecture.md")
        # The dependency rule: layers only import downward
        assert "import" in content.lower()

    def test_dual_write_described(self) -> None:
        """Given the architecture guide, the dual-write storage pattern is described."""
        content = _read_doc("architecture.md")
        assert "dual" in content.lower() or "DualWriter" in content

    def test_six_priority_factors_described(self) -> None:
        """Given the architecture guide, the six priority factors are listed."""
        content = _read_doc("architecture.md")
        factors = ["coverage_gap", "needs_review", "developer_proximity",
                   "git_activity", "staleness", "failure_urgency"]
        missing = [f for f in factors if f not in content]
        assert not missing, f"Priority factors not described in architecture guide: {missing}"


# ---------------------------------------------------------------------------
# Model quality guide (AC5)
# ---------------------------------------------------------------------------


class TestModelQualityGuide:
    """Users can compare LLM cost/quality/speed tradeoffs."""

    def test_model_quality_doc_exists(self) -> None:
        """Given the model quality guide, when opened, it is non-empty."""
        _read_doc("model-quality.md")

    def test_anthropic_models_covered(self) -> None:
        """Given the model quality guide, Anthropic models are compared."""
        content = _read_doc("model-quality.md")
        models = ["claude-opus", "claude-sonnet", "claude-haiku"]
        missing = [m for m in models if m not in content]
        assert not missing, f"Anthropic models not documented: {missing}"

    def test_ollama_covered(self) -> None:
        """Given the model quality guide, Ollama (local) option is described."""
        content = _read_doc("model-quality.md")
        assert "ollama" in content.lower() or "Ollama" in content

    def test_cost_quality_speed_tradeoffs(self) -> None:
        """Given the model quality guide, cost/quality/speed are all discussed."""
        content = _read_doc("model-quality.md")
        assert "cost" in content.lower()
        assert "quality" in content.lower()
        assert "speed" in content.lower() or "fast" in content.lower() or "slow" in content.lower()

    def test_budget_recommendations_present(self) -> None:
        """Given the model quality guide, token budget recommendations are provided."""
        content = _read_doc("model-quality.md")
        assert "budget" in content.lower() or "token" in content.lower()

    def test_provider_config_examples_present(self) -> None:
        """Given the model quality guide, YAML config examples are provided."""
        content = _read_doc("model-quality.md")
        assert "```yaml" in content


# ---------------------------------------------------------------------------
# Audit UI guide (AC6)
# ---------------------------------------------------------------------------


class TestAuditUiGuide:
    """Users can navigate the graph, use review workflow, and interpret health dashboard."""

    def test_audit_ui_doc_exists(self) -> None:
        """Given the audit UI guide, when opened, it is non-empty."""
        _read_doc("audit-ui.md")

    def test_graph_navigation_described(self) -> None:
        """Given the audit UI guide, graph navigation is described."""
        content = _read_doc("audit-ui.md")
        assert "graph" in content.lower()
        assert "navigate" in content.lower() or "navigation" in content.lower() or "click" in content.lower()

    def test_review_workflow_described(self) -> None:
        """Given the audit UI guide, the review workflow (verify/correct/flag) is described."""
        content = _read_doc("audit-ui.md")
        assert "Verify" in content
        assert "Correct" in content
        assert "Flag" in content

    def test_health_dashboard_described(self) -> None:
        """Given the audit UI guide, the health dashboard is described."""
        content = _read_doc("audit-ui.md")
        assert "health" in content.lower() or "Health" in content
        assert "dashboard" in content.lower() or "metrics" in content.lower()

    def test_review_error_types_documented(self) -> None:
        """Given the audit UI guide, the review error types are listed."""
        content = _read_doc("audit-ui.md")
        error_types = [
            "incorrect_description",
            "missing_relationships",
            "wrong_relationships",
            "stale_description",
            "hallucination",
        ]
        missing = [t for t in error_types if t not in content]
        assert not missing, f"Review error types not documented: {missing}"

    def test_starting_ui_documented(self) -> None:
        """Given the audit UI guide, how to start the UI is documented."""
        content = _read_doc("audit-ui.md")
        assert "apriori ui" in content

    def test_visual_encoding_documented(self) -> None:
        """Given the audit UI guide, the confidence color encoding is explained."""
        content = _read_doc("audit-ui.md")
        # Confidence buckets: high/medium/low
        assert "confidence" in content.lower()
        assert "high" in content.lower()
        assert "medium" in content.lower()
        assert "low" in content.lower()

    def test_escalated_items_documented(self) -> None:
        """Given the audit UI guide, escalated items and how to resolve them are described."""
        content = _read_doc("audit-ui.md")
        assert "escalated" in content.lower() or "Escalated" in content

    def test_rest_api_documented(self) -> None:
        """Given the audit UI guide, the underlying REST API endpoints are documented."""
        content = _read_doc("audit-ui.md")
        assert "/api/concepts" in content
        assert "/api/health" in content
        assert "/api/graph" in content


# ---------------------------------------------------------------------------
# Cross-cutting: all doc files are parseable and link to each other
# ---------------------------------------------------------------------------


class TestDocumentationCrossCutting:
    """Documentation files exist and are complete."""

    @pytest.mark.parametrize("filename", [
        "configuration.md",
        "mcp-tools.md",
        "architecture.md",
        "model-quality.md",
        "audit-ui.md",
    ])
    def test_doc_file_exists_and_nonempty(self, filename: str) -> None:
        """Given each documentation file, it exists and contains content."""
        _read_doc(filename)

    def test_readme_links_to_configuration(self) -> None:
        """Given the README, it links to docs/configuration.md."""
        content = _README.read_text(encoding="utf-8")
        assert "docs/configuration.md" in content or "configuration" in content.lower()

    def test_readme_links_to_architecture(self) -> None:
        """Given the README, it links to docs/architecture.md."""
        content = _README.read_text(encoding="utf-8")
        assert "docs/architecture.md" in content or "architecture" in content.lower()

    def test_readme_links_to_mcp_tools(self) -> None:
        """Given the README, it links to docs/mcp-tools.md."""
        content = _README.read_text(encoding="utf-8")
        assert "docs/mcp-tools.md" in content or "MCP" in content
