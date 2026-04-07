"""Tests for the configuration system (Story 1.5 acceptance criteria)."""

import tempfile
from pathlib import Path

import pytest
import yaml

from apriori.config import (
    DEFAULT_BASE_PRIORITIES,
    DEFAULT_EDGE_TYPES,
    Config,
    load_config,
)


class TestConfigDefaults:
    """AC1: Given no apriori.config.yaml, all defaults are applied."""

    def test_load_config_with_no_file_returns_valid_config(self):
        """With no config file, load_config returns fully populated Config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = Path.cwd()
            try:
                import os
                os.chdir(tmpdir)
                config = load_config()

                # All fields should have default values
                assert config.project_name == "A-Priori"
                assert config.log_level == "INFO"
                assert config.llm.provider == "anthropic"
                assert config.llm.api_key_env == "ANTHROPIC_API_KEY"
                assert config.librarian.modulation_strength == 0.8
                assert config.quality.co_regulation.enabled is True
                assert config.work_queue.retention_days == 30
                assert config.embedding.model == "intfloat/e5-base-v2"
                assert config.embedding.dimensions == 768
            finally:
                import os
                os.chdir(old_cwd)

    def test_config_has_valid_values_for_every_setting(self):
        """All settings in default Config are valid."""
        config = Config()

        # Validate required fields exist and are non-None
        assert config.project_name is not None
        assert config.log_level is not None
        assert config.llm is not None
        assert config.librarian is not None
        assert config.quality is not None
        assert config.work_queue is not None
        assert config.embedding is not None
        assert config.storage is not None
        assert config.edge_types is not None
        assert config.base_priority_weights is not None


class TestPartialConfigOverride:
    """AC2: Partial config with defaults for missing values."""

    def test_partial_config_uses_defaults_for_missing_values(self):
        """Given only llm.provider and llm.api_key_env, other values use defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "apriori.config.yaml"
            config_path.write_text(
                yaml.dump({"llm": {"provider": "ollama", "api_key_env": "OLLAMA_API_KEY"}})
            )

            config = load_config(config_path)

            # User-provided values
            assert config.llm.provider == "ollama"
            assert config.llm.api_key_env == "OLLAMA_API_KEY"

            # Defaults for everything else
            assert config.librarian.modulation_strength == 0.8
            assert config.quality.co_regulation.enabled is True
            assert config.work_queue.retention_days == 30


class TestModulationDisabled:
    """AC3: Adaptive modulation disabled when modulation_strength = 0.0."""

    def test_modulation_strength_zero_disables_modulation(self):
        """Given modulation_strength = 0.0, modulation is disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "apriori.config.yaml"
            config_path.write_text(
                yaml.dump({"librarian": {"modulation_strength": 0.0}})
            )

            config = load_config(config_path)

            assert config.librarian.modulation_strength == 0.0


class TestCoRegulationDisabled:
    """AC4: Co-regulation disabled when co_regulation.enabled = false."""

    def test_co_regulation_disabled(self):
        """Given co_regulation.enabled = false, co-regulation is disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "apriori.config.yaml"
            config_path.write_text(
                yaml.dump({"quality": {"co_regulation": {"enabled": False}}})
            )

            config = load_config(config_path)

            assert config.quality.co_regulation.enabled is False


class TestPriorityWeightNormalization:
    """AC5: Priority weights that don't sum to 1.0 are normalized."""

    def test_weights_not_summing_to_one_are_normalized(self, caplog):
        """Given weights that don't sum to 1.0, system normalizes and logs warning."""
        weights = {
            "recency": 2.0,
            "frequency": 2.0,
            "semantic_relevance": 2.0,
            "user_interest": 1.0,
            "code_stability": 1.0,
            "cross_module_impact": 1.0,
        }  # Sum = 9.0

        config = Config(base_priority_weights=weights)

        # Should be normalized to sum to 1.0
        total = sum(config.base_priority_weights.values())
        assert abs(total - 1.0) < 0.001

        # Check normalization is proportional
        expected_factor = 1.0 / 9.0
        for key, val in config.base_priority_weights.items():
            expected = weights[key] * expected_factor
            assert abs(val - expected) < 0.01  # Allow floating point rounding

    def test_weights_summing_to_one_not_normalized(self, caplog):
        """Given weights that sum to 1.0, no normalization or warning."""
        weights = DEFAULT_BASE_PRIORITIES.copy()
        config = Config(base_priority_weights=weights)

        # Should not be modified
        for key, val in config.base_priority_weights.items():
            assert abs(val - weights[key]) < 0.0001


class TestCustomEdgeTypes:
    """AC6: Custom edge types appended to defaults."""

    def test_custom_edge_types_appended_to_defaults(self):
        """Given custom edge types in config, they're appended to defaults."""
        custom_types = {"custom_type_1", "custom_type_2"}
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "apriori.config.yaml"
            config_path.write_text(
                yaml.dump({"edge_types": list(custom_types)})
            )

            config = load_config(config_path)

            # Custom types should be present
            assert custom_types.issubset(config.edge_types)
            # Defaults should be present
            assert DEFAULT_EDGE_TYPES.issubset(config.edge_types)


class TestWorkQueueRetention:
    """AC7: Default work_queue.retention_days is 30."""

    def test_work_queue_retention_days_default_is_30(self):
        """Default config has work_queue.retention_days = 30."""
        config = Config()
        assert config.work_queue.retention_days == 30

    def test_work_queue_retention_days_can_be_overridden(self):
        """Can override work_queue.retention_days."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "apriori.config.yaml"
            config_path.write_text(yaml.dump({"work_queue": {"retention_days": 60}}))

            config = load_config(config_path)
            assert config.work_queue.retention_days == 60


class TestJSONYAMLRoundTrip:
    """Additional: JSON/YAML serialization round-trips correctly."""

    def test_config_to_dict_round_trip(self):
        """Config can be serialized to dict and reconstructed."""
        config = Config(
            llm={"provider": "ollama", "api_key_env": "OLLAMA_API_KEY"},
            work_queue={"retention_days": 45},
        )

        config_dict = config.model_dump()
        reconstructed = Config(**config_dict)

        assert reconstructed.llm.provider == "ollama"
        assert reconstructed.work_queue.retention_days == 45

    def test_config_to_json_round_trip(self):
        """Config can be serialized to JSON and reconstructed."""
        import json

        config = Config(work_queue={"retention_days": 50})
        json_str = config.model_dump_json()
        json_dict = json.loads(json_str)
        reconstructed = Config(**json_dict)

        assert reconstructed.work_queue.retention_days == 50


class TestValidation:
    """Validation errors for invalid configuration."""

    def test_invalid_log_level_raises_error(self):
        """Invalid log_level raises ValidationError."""
        with pytest.raises(ValueError):
            Config(log_level="INVALID")

    def test_invalid_llm_provider_raises_error(self):
        """Invalid LLM provider raises ValidationError."""
        with pytest.raises(ValueError):
            Config(llm={"provider": "invalid_provider"})

    def test_negative_confidence_threshold_raises_error(self):
        """Negative confidence threshold raises ValidationError."""
        with pytest.raises(ValueError):
            Config(quality={"co_regulation": {"min_confidence_threshold": -0.1}})

    def test_confidence_threshold_over_one_raises_error(self):
        """Confidence threshold > 1.0 raises ValidationError."""
        with pytest.raises(ValueError):
            Config(quality={"co_regulation": {"min_confidence_threshold": 1.5}})

    def test_empty_api_key_env_raises_error(self):
        """Empty api_key_env raises ValidationError."""
        with pytest.raises(ValueError):
            Config(llm={"api_key_env": ""})

    def test_negative_retention_days_raises_error(self):
        """Negative retention_days raises ValidationError."""
        with pytest.raises(ValueError):
            Config(work_queue={"retention_days": -1})


class TestConfigFileErrors:
    """Error handling for config file issues."""

    def test_invalid_yaml_raises_error(self):
        """Malformed YAML raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "bad.yaml"
            config_path.write_text("{ invalid yaml: [")

            with pytest.raises(ValueError, match="Failed to load config"):
                load_config(config_path)

    def test_nonexistent_file_uses_defaults(self):
        """Non-existent file path uses defaults, no error."""
        # This should use defaults and log a message, not raise an error
        config = load_config(Path("/tmp/nonexistent_config_apriori_test_12345.yaml"))
        assert config.work_queue.retention_days == 30


class TestLoadConfigFunction:
    """Tests for the load_config() function signature and behavior."""

    def test_load_config_signature(self):
        """load_config accepts Optional[Path] and returns Config."""
        # With None (defaults)
        config = load_config(None)
        assert isinstance(config, Config)

        # With explicit path
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "apriori.config.yaml"
            config_path.write_text(yaml.dump({}))
            config = load_config(config_path)
            assert isinstance(config, Config)
