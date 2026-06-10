"""Tests for Learning Candidate Engine (PR #40).

Tests proving:
- candidates generated deterministically
- duplicate candidates merged
- evidence paths preserved
- confidence ordering stable
"""

from __future__ import annotations

import json
import pathlib

import pytest
from axiom_core.learning_candidates import (
    CandidateEvidence,
    CandidateSource,
    CandidateStrength,
    CandidateType,
    LearningCandidate,
    LearningCandidateRegistry,
)


@pytest.fixture()
def db_path(tmp_path: pathlib.Path) -> str:
    return str(tmp_path / "test_candidates.db")


@pytest.fixture()
def registry(db_path: str) -> LearningCandidateRegistry:
    return LearningCandidateRegistry(db_path=db_path)


# ---------------------------------------------------------------------------
# Test: Candidates Generated Deterministically
# ---------------------------------------------------------------------------


class TestCandidatePersistence:
    """Candidates persist and retrieve deterministically."""

    def test_register_and_retrieve(self, registry: LearningCandidateRegistry):
        c = LearningCandidate(
            candidate_id="cand_001",
            candidate_name="GridCreation success pattern",
            candidate_type=CandidateType.REPEATED_SUCCESS,
            strength=CandidateStrength.MODERATE,
            confidence_score=45,
            description="Grid creation succeeds consistently with standard params",
        )
        registry.register_candidate(c)

        retrieved = registry.get_candidate("cand_001")
        assert retrieved is not None
        assert retrieved.candidate_name == "GridCreation success pattern"
        assert retrieved.candidate_type == CandidateType.REPEATED_SUCCESS
        assert retrieved.strength == CandidateStrength.MODERATE
        assert retrieved.confidence_score == 45

    def test_multiple_candidates(self, registry: LearningCandidateRegistry):
        for i in range(5):
            registry.register_candidate(LearningCandidate(
                candidate_id=f"cand_{i}",
                candidate_name=f"Pattern {i}",
                candidate_type=CandidateType.REPEATED_SUCCESS,
                confidence_score=i * 10,
            ))
        assert registry.candidate_count() == 5

    def test_unknown_id_returns_none(self, registry: LearningCandidateRegistry):
        assert registry.get_candidate("nonexistent") is None

    def test_empty_name_rejected(self, registry: LearningCandidateRegistry):
        with pytest.raises(ValueError, match="candidate_name must not be empty"):
            registry.register_candidate(LearningCandidate(
                candidate_id="bad",
                candidate_name="",
            ))

    def test_dismiss_candidate(self, registry: LearningCandidateRegistry):
        registry.register_candidate(LearningCandidate(
            candidate_id="dis_1",
            candidate_name="Dismissible",
            candidate_type=CandidateType.REPEATED_FAILURE,
        ))
        result = registry.dismiss("dis_1")
        assert result is True

        # Excluded from default listing
        candidates = registry.list_candidates()
        ids = [c.candidate_id for c in candidates]
        assert "dis_1" not in ids

        # Included with flag
        candidates = registry.list_candidates(include_dismissed=True)
        ids = [c.candidate_id for c in candidates]
        assert "dis_1" in ids

    def test_all_candidate_types(self, registry: LearningCandidateRegistry):
        for i, ct in enumerate(CandidateType):
            registry.register_candidate(LearningCandidate(
                candidate_id=f"type_{i}",
                candidate_name=f"Type {ct.value}",
                candidate_type=ct,
            ))
        assert registry.candidate_count() == len(CandidateType)

    def test_type_filter(self, registry: LearningCandidateRegistry):
        registry.register_candidate(LearningCandidate(
            candidate_id="tf_1",
            candidate_name="Success Pattern",
            candidate_type=CandidateType.REPEATED_SUCCESS,
        ))
        registry.register_candidate(LearningCandidate(
            candidate_id="tf_2",
            candidate_name="Failure Pattern",
            candidate_type=CandidateType.REPEATED_FAILURE,
        ))

        results = registry.list_candidates(candidate_type=CandidateType.REPEATED_SUCCESS)
        assert len(results) == 1
        assert results[0].candidate_id == "tf_1"


# ---------------------------------------------------------------------------
# Test: Duplicate Candidates Merged
# ---------------------------------------------------------------------------


class TestDuplicateMerge:
    """Duplicate candidates (same name + type) are merged, not duplicated."""

    def test_same_name_type_merges(self, registry: LearningCandidateRegistry):
        c1 = LearningCandidate(
            candidate_id="dup_1",
            candidate_name="GridCreation repeating",
            candidate_type=CandidateType.REPEATED_SUCCESS,
            confidence_score=20,
            sources=[CandidateSource(source_type="run", source_id="run_001")],
        )
        registry.register_candidate(c1)

        c2 = LearningCandidate(
            candidate_id="dup_2",
            candidate_name="GridCreation repeating",
            candidate_type=CandidateType.REPEATED_SUCCESS,
            confidence_score=15,
            sources=[CandidateSource(source_type="run", source_id="run_002")],
        )
        merged = registry.register_candidate(c2)

        # Should have merged into existing
        assert merged.observation_count == 2
        assert merged.confidence_score == 35
        assert len(merged.sources) == 2
        assert registry.candidate_count() == 1

    def test_different_type_not_merged(self, registry: LearningCandidateRegistry):
        c1 = LearningCandidate(
            candidate_id="nm_1",
            candidate_name="Same Name",
            candidate_type=CandidateType.REPEATED_SUCCESS,
        )
        c2 = LearningCandidate(
            candidate_id="nm_2",
            candidate_name="Same Name",
            candidate_type=CandidateType.REPEATED_FAILURE,
        )
        registry.register_candidate(c1)
        registry.register_candidate(c2)
        assert registry.candidate_count() == 2

    def test_strength_upgrades_on_observations(self, registry: LearningCandidateRegistry):
        for i in range(5):
            registry.register_candidate(LearningCandidate(
                candidate_id=f"up_{i}",
                candidate_name="Recurring parameter usage",
                candidate_type=CandidateType.RECURRING_PARAMETER_USAGE,
                confidence_score=10,
            ))

        candidates = registry.list_candidates()
        assert len(candidates) == 1
        assert candidates[0].observation_count == 5
        assert candidates[0].strength == CandidateStrength.STRONG

    def test_moderate_at_three_observations(self, registry: LearningCandidateRegistry):
        for i in range(3):
            registry.register_candidate(LearningCandidate(
                candidate_id=f"mod_{i}",
                candidate_name="Three times pattern",
                candidate_type=CandidateType.REPEATED_WORKFLOW,
                confidence_score=10,
            ))

        candidates = registry.list_candidates()
        assert candidates[0].observation_count == 3
        assert candidates[0].strength == CandidateStrength.MODERATE

    def test_confidence_capped_at_100(self, registry: LearningCandidateRegistry):
        for i in range(15):
            registry.register_candidate(LearningCandidate(
                candidate_id=f"cap_{i}",
                candidate_name="High confidence",
                candidate_type=CandidateType.RECURRING_VALIDATION_PATTERN,
                confidence_score=20,
            ))

        candidates = registry.list_candidates()
        assert candidates[0].confidence_score <= 100


# ---------------------------------------------------------------------------
# Test: Evidence Paths Preserved
# ---------------------------------------------------------------------------


class TestEvidencePreserved:
    """Evidence paths and sources are preserved through persistence."""

    def test_evidence_roundtrip(self, registry: LearningCandidateRegistry):
        c = LearningCandidate(
            candidate_id="ev_1",
            candidate_name="Evidence test",
            candidate_type=CandidateType.REPEATED_SUCCESS,
            evidence=[
                CandidateEvidence(
                    evidence_type="run_artifact",
                    evidence_path="artifacts/runs/run_001/run_summary.md",
                    description="First successful run",
                ),
                CandidateEvidence(
                    evidence_type="validation_result",
                    evidence_path="artifacts/validation_runs/v_001/result.json",
                    description="Validation passed",
                ),
            ],
        )
        registry.register_candidate(c)

        retrieved = registry.get_candidate("ev_1")
        assert len(retrieved.evidence) == 2
        assert retrieved.evidence[0].evidence_path == "artifacts/runs/run_001/run_summary.md"
        assert retrieved.evidence[0].evidence_type == "run_artifact"
        assert retrieved.evidence[1].evidence_path == "artifacts/validation_runs/v_001/result.json"

    def test_sources_roundtrip(self, registry: LearningCandidateRegistry):
        c = LearningCandidate(
            candidate_id="src_1",
            candidate_name="Source test",
            candidate_type=CandidateType.REPEATED_FAILURE,
            sources=[
                CandidateSource(
                    source_type="capability_state",
                    source_id="cap_grid",
                    source_name="GridCreation",
                ),
                CandidateSource(
                    source_type="workflow_registry",
                    source_id="wf_001",
                    source_name="MEP Load Workflow",
                ),
            ],
        )
        registry.register_candidate(c)

        retrieved = registry.get_candidate("src_1")
        assert len(retrieved.sources) == 2
        assert retrieved.sources[0].source_type == "capability_state"
        assert retrieved.sources[0].source_name == "GridCreation"
        assert retrieved.sources[1].source_type == "workflow_registry"

    def test_merged_evidence_accumulated(self, registry: LearningCandidateRegistry):
        c1 = LearningCandidate(
            candidate_id="acc_1",
            candidate_name="Accumulating evidence",
            candidate_type=CandidateType.REPEATED_SUCCESS,
            evidence=[CandidateEvidence(evidence_path="path/a.json")],
        )
        c2 = LearningCandidate(
            candidate_id="acc_2",
            candidate_name="Accumulating evidence",
            candidate_type=CandidateType.REPEATED_SUCCESS,
            evidence=[CandidateEvidence(evidence_path="path/b.json")],
        )
        registry.register_candidate(c1)
        merged = registry.register_candidate(c2)

        assert len(merged.evidence) == 2
        paths = [e.evidence_path for e in merged.evidence]
        assert "path/a.json" in paths
        assert "path/b.json" in paths

    def test_metadata_preserved(self, registry: LearningCandidateRegistry):
        c = LearningCandidate(
            candidate_id="meta_1",
            candidate_name="Metadata test",
            candidate_type=CandidateType.RECURRING_PARAMETER_USAGE,
            metadata={"parameter": "Height", "frequency": 12},
        )
        registry.register_candidate(c)

        retrieved = registry.get_candidate("meta_1")
        assert retrieved.metadata == {"parameter": "Height", "frequency": 12}

    def test_empty_metadata_roundtrip(self, registry: LearningCandidateRegistry):
        c = LearningCandidate(
            candidate_id="emeta_1",
            candidate_name="Empty metadata",
            candidate_type=CandidateType.REPEATED_SUCCESS,
            metadata={},
        )
        registry.register_candidate(c)

        retrieved = registry.get_candidate("emeta_1")
        assert retrieved.metadata == {}

    def test_empty_sources_roundtrip(self, registry: LearningCandidateRegistry):
        c = LearningCandidate(
            candidate_id="esrc_1",
            candidate_name="Empty sources",
            candidate_type=CandidateType.REPEATED_SUCCESS,
            sources=[],
        )
        registry.register_candidate(c)

        retrieved = registry.get_candidate("esrc_1")
        assert retrieved.sources == []

    def test_empty_evidence_roundtrip(self, registry: LearningCandidateRegistry):
        c = LearningCandidate(
            candidate_id="eev_1",
            candidate_name="Empty evidence",
            candidate_type=CandidateType.REPEATED_SUCCESS,
            evidence=[],
        )
        registry.register_candidate(c)

        retrieved = registry.get_candidate("eev_1")
        assert retrieved.evidence == []


# ---------------------------------------------------------------------------
# Test: Confidence Ordering Stable
# ---------------------------------------------------------------------------


class TestConfidenceOrdering:
    """Candidates are ordered by confidence score (highest first), then name."""

    def test_ordered_by_confidence_desc(self, registry: LearningCandidateRegistry):
        registry.register_candidate(LearningCandidate(
            candidate_id="ord_1", candidate_name="Low", confidence_score=10,
        ))
        registry.register_candidate(LearningCandidate(
            candidate_id="ord_2", candidate_name="High", confidence_score=90,
        ))
        registry.register_candidate(LearningCandidate(
            candidate_id="ord_3", candidate_name="Mid", confidence_score=50,
        ))

        candidates = registry.list_candidates()
        scores = [c.confidence_score for c in candidates]
        assert scores == [90, 50, 10]

    def test_same_confidence_ordered_by_name(self, registry: LearningCandidateRegistry):
        registry.register_candidate(LearningCandidate(
            candidate_id="nm_z", candidate_name="Zebra", confidence_score=50,
        ))
        registry.register_candidate(LearningCandidate(
            candidate_id="nm_a", candidate_name="Apple", confidence_score=50,
        ))
        registry.register_candidate(LearningCandidate(
            candidate_id="nm_m", candidate_name="Mango", confidence_score=50,
        ))

        candidates = registry.list_candidates()
        names = [c.candidate_name for c in candidates]
        assert names == ["Apple", "Mango", "Zebra"]

    def test_deterministic_repeated_queries(self, registry: LearningCandidateRegistry):
        for i in range(10):
            registry.register_candidate(LearningCandidate(
                candidate_id=f"det_{i}",
                candidate_name=f"Pattern {i:02d}",
                confidence_score=(10 - i) * 5,
            ))

        r1 = registry.list_candidates()
        r2 = registry.list_candidates()
        assert [c.candidate_id for c in r1] == [c.candidate_id for c in r2]


# ---------------------------------------------------------------------------
# Test: JSON Output
# ---------------------------------------------------------------------------


class TestJsonOutput:
    """JSON serialization is valid and complete."""

    def test_json_valid(self, registry: LearningCandidateRegistry):
        registry.register_candidate(LearningCandidate(
            candidate_id="json_1",
            candidate_name="JSON Test",
            candidate_type=CandidateType.REPEATED_WORKFLOW,
            evidence=[CandidateEvidence(evidence_path="test/path.json")],
        ))

        output = registry.to_json()
        data = json.loads(output)
        assert isinstance(data, list)
        assert len(data) == 1
        required_fields = [
            "candidate_id", "candidate_name", "candidate_type", "strength",
            "status", "confidence_score", "observation_count", "sources",
            "evidence", "metadata", "created_at", "updated_at",
        ]
        for f in required_fields:
            assert f in data[0], f"Missing field: {f}"

    def test_name_filter(self, registry: LearningCandidateRegistry):
        registry.register_candidate(LearningCandidate(
            candidate_id="nf_1", candidate_name="Grid success pattern",
        ))
        registry.register_candidate(LearningCandidate(
            candidate_id="nf_2", candidate_name="Level failure pattern",
        ))

        results = registry.list_candidates(name_filter="Grid")
        assert len(results) == 1
        assert results[0].candidate_id == "nf_1"

    def test_sql_wildcard_escaped(self, registry: LearningCandidateRegistry):
        registry.register_candidate(LearningCandidate(
            candidate_id="wc_1", candidate_name="100% success rate",
        ))
        registry.register_candidate(LearningCandidate(
            candidate_id="wc_2", candidate_name="Other pattern",
        ))

        results = registry.list_candidates(name_filter="%")
        assert len(results) == 1
        assert results[0].candidate_id == "wc_1"
