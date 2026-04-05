"""Tests for ImpactProfile and ImpactEntry models — AC traceability: Story 1.1."""

import uuid
from datetime import datetime, timezone

import yaml
from pydantic import ValidationError
import pytest

from apriori.models.impact import ImpactEntry, ImpactProfile


# ---------------------------------------------------------------------------
# AC: Given valid ImpactProfile and ImpactEntry data, when instantiated and
#     serialized to JSON/YAML, they round-trip without loss.
# ---------------------------------------------------------------------------
class TestImpactModelsRoundTrip:
    def _make_impact_profile(self) -> ImpactProfile:
        entry1 = ImpactEntry(
            target_concept_id=uuid.uuid4(),
            confidence=1.0,
            relationship_path=[str(uuid.uuid4()), str(uuid.uuid4())],
            depth=2,
            rationale="Direct structural dependency via function call.",
        )
        entry2 = ImpactEntry(
            target_concept_id=uuid.uuid4(),
            confidence=0.72,
            relationship_path=[str(uuid.uuid4())],
            depth=1,
            rationale="Semantic coupling inferred from similar domain vocabulary.",
        )
        entry3 = ImpactEntry(
            target_concept_id=uuid.uuid4(),
            confidence=0.55,
            relationship_path=[str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())],
            depth=3,
            rationale="Empirically co-changed in 7 of last 10 commits.",
        )
        return ImpactProfile(
            structural_impact=[entry1],
            semantic_impact=[entry2],
            historical_impact=[entry3],
            last_computed=datetime.now(timezone.utc),
        )

    def test_json_round_trip(self):
        original = self._make_impact_profile()
        json_str = original.model_dump_json()
        restored = ImpactProfile.model_validate_json(json_str)
        assert restored == original

    def test_yaml_round_trip(self):
        original = self._make_impact_profile()
        data = original.model_dump(mode="json")
        yaml_str = yaml.dump(data)
        loaded = yaml.safe_load(yaml_str)
        restored = ImpactProfile.model_validate(loaded)
        assert restored == original

    def test_empty_impact_lists_valid(self):
        profile = ImpactProfile(
            structural_impact=[],
            semantic_impact=[],
            historical_impact=[],
            last_computed=datetime.now(timezone.utc),
        )
        assert profile.structural_impact == []

    def test_impact_entry_confidence_bounds(self):
        with pytest.raises(ValidationError):
            ImpactEntry(
                target_concept_id=uuid.uuid4(),
                confidence=1.1,
                relationship_path=[],
                depth=0,
                rationale="bad",
            )

        with pytest.raises(ValidationError):
            ImpactEntry(
                target_concept_id=uuid.uuid4(),
                confidence=-0.01,
                relationship_path=[],
                depth=0,
                rationale="bad",
            )
