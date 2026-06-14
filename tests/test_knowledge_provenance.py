"""Tests for Knowledge Provenance & Trust Engine (PR #38).

Tests proving:
- provenance persists
- trust ordering deterministic
- deprecated knowledge supported
- supersession chains valid
"""

from __future__ import annotations

import json
import pathlib

import pytest
from axiom_core.knowledge_provenance import (
    KnowledgeProvenance,
    KnowledgeProvenanceRegistry,
    ProvenanceStatus,
    SourceConfidence,
    TrustLevel,
    trust_rank,
)


@pytest.fixture()
def db_path(tmp_path: pathlib.Path) -> str:
    return str(tmp_path / "test_provenance.db")


@pytest.fixture()
def registry(db_path: str) -> KnowledgeProvenanceRegistry:
    return KnowledgeProvenanceRegistry(db_path=db_path)


# ---------------------------------------------------------------------------
# Test: Provenance Persists
# ---------------------------------------------------------------------------


class TestProvenancePersistence:
    """Provenance records roundtrip through SQLite correctly."""

    def test_register_and_retrieve(self, registry: KnowledgeProvenanceRegistry):
        prov = KnowledgeProvenance(
            provenance_id="prov_001",
            knowledge_name="Grid Creation Pattern",
            trust_level=TrustLevel.HUMAN_VERIFIED,
            source_confidence=SourceConfidence.HIGH,
            origin="docs/architecture/grid-creation.md",
            evidence_paths=["artifacts/grid_test_runs/run_001"],
            approving_source="founder_review",
            confidence_score=0.95,
            notes="Verified via live Revit session",
        )
        registry.register(prov)

        retrieved = registry.get("prov_001")
        assert retrieved is not None
        assert retrieved.knowledge_name == "Grid Creation Pattern"
        assert retrieved.trust_level == TrustLevel.HUMAN_VERIFIED
        assert retrieved.source_confidence == SourceConfidence.HIGH
        assert retrieved.origin == "docs/architecture/grid-creation.md"
        assert retrieved.evidence_paths == ["artifacts/grid_test_runs/run_001"]
        assert retrieved.approving_source == "founder_review"
        assert retrieved.confidence_score == 0.95
        assert retrieved.notes == "Verified via live Revit session"
        assert retrieved.status == ProvenanceStatus.ACTIVE

    def test_update_existing(self, registry: KnowledgeProvenanceRegistry):
        prov = KnowledgeProvenance(
            provenance_id="prov_up",
            knowledge_name="Old Name",
            trust_level=TrustLevel.CANDIDATE,
        )
        registry.register(prov)

        prov.knowledge_name = "Updated Name"
        prov.trust_level = TrustLevel.EVIDENCE_SUPPORTED
        registry.register(prov)

        retrieved = registry.get("prov_up")
        assert retrieved is not None
        assert retrieved.knowledge_name == "Updated Name"
        assert retrieved.trust_level == TrustLevel.EVIDENCE_SUPPORTED

    def test_multiple_records(self, registry: KnowledgeProvenanceRegistry):
        for i in range(5):
            registry.register(KnowledgeProvenance(
                provenance_id=f"prov_{i}",
                knowledge_name=f"Knowledge Item {i}",
                trust_level=TrustLevel.CANDIDATE,
            ))
        assert registry.provenance_count() == 5

    def test_unknown_id_returns_none(self, registry: KnowledgeProvenanceRegistry):
        assert registry.get("nonexistent") is None

    def test_empty_name_rejected(self, registry: KnowledgeProvenanceRegistry):
        with pytest.raises(ValueError, match="knowledge_name must not be empty"):
            registry.register(KnowledgeProvenance(
                provenance_id="bad",
                knowledge_name="",
                trust_level=TrustLevel.CANDIDATE,
            ))

    def test_confidence_score_none_roundtrips(self, registry: KnowledgeProvenanceRegistry):
        registry.register(KnowledgeProvenance(
            provenance_id="prov_none_score",
            knowledge_name="No Score",
            trust_level=TrustLevel.CANDIDATE,
            confidence_score=None,
        ))
        retrieved = registry.get("prov_none_score")
        assert retrieved is not None
        assert retrieved.confidence_score is None

    def test_evidence_paths_roundtrip(self, registry: KnowledgeProvenanceRegistry):
        paths = ["artifacts/run_001", "artifacts/run_002", "docs/evidence.md"]
        registry.register(KnowledgeProvenance(
            provenance_id="prov_paths",
            knowledge_name="Multi Evidence",
            trust_level=TrustLevel.EVIDENCE_SUPPORTED,
            evidence_paths=paths,
        ))
        retrieved = registry.get("prov_paths")
        assert retrieved is not None
        assert retrieved.evidence_paths == paths


# ---------------------------------------------------------------------------
# Test: Trust Ordering Deterministic
# ---------------------------------------------------------------------------


class TestTrustOrdering:
    """Trust level ordering is deterministic and stable."""

    def test_trust_rank_ordering(self):
        assert trust_rank(TrustLevel.FOUNDER_VERIFIED) < trust_rank(TrustLevel.HUMAN_VERIFIED)
        assert trust_rank(TrustLevel.HUMAN_VERIFIED) < trust_rank(TrustLevel.EVIDENCE_SUPPORTED)
        assert trust_rank(TrustLevel.EVIDENCE_SUPPORTED) < trust_rank(TrustLevel.DERIVED)
        assert trust_rank(TrustLevel.DERIVED) < trust_rank(TrustLevel.CANDIDATE)
        assert trust_rank(TrustLevel.CANDIDATE) < trust_rank(TrustLevel.DEPRECATED)

    def test_unknown_trust_level_gets_lowest_rank(self):
        rank = trust_rank("nonexistent_level")
        assert rank >= trust_rank(TrustLevel.DEPRECATED)

    def test_list_ordered_by_trust_then_name(self, registry: KnowledgeProvenanceRegistry):
        registry.register(KnowledgeProvenance(
            provenance_id="p1", knowledge_name="Zebra",
            trust_level=TrustLevel.CANDIDATE,
        ))
        registry.register(KnowledgeProvenance(
            provenance_id="p2", knowledge_name="Apple",
            trust_level=TrustLevel.FOUNDER_VERIFIED,
        ))
        registry.register(KnowledgeProvenance(
            provenance_id="p3", knowledge_name="Banana",
            trust_level=TrustLevel.FOUNDER_VERIFIED,
        ))
        registry.register(KnowledgeProvenance(
            provenance_id="p4", knowledge_name="Cherry",
            trust_level=TrustLevel.EVIDENCE_SUPPORTED,
        ))

        results = registry.list_provenance()
        names = [r.knowledge_name for r in results]
        # founder_verified first (Apple, Banana), then evidence_supported (Cherry), then candidate (Zebra)
        assert names == ["Apple", "Banana", "Cherry", "Zebra"]

    def test_repeated_listing_deterministic(self, registry: KnowledgeProvenanceRegistry):
        for i, level in enumerate([TrustLevel.DERIVED, TrustLevel.CANDIDATE, TrustLevel.HUMAN_VERIFIED]):
            registry.register(KnowledgeProvenance(
                provenance_id=f"det_{i}", knowledge_name=f"Item {i}",
                trust_level=level,
            ))
        results_1 = [r.to_dict() for r in registry.list_provenance()]
        results_2 = [r.to_dict() for r in registry.list_provenance()]
        assert results_1 == results_2

    def test_json_output_deterministic(self, registry: KnowledgeProvenanceRegistry):
        registry.register(KnowledgeProvenance(
            provenance_id="j1", knowledge_name="First",
            trust_level=TrustLevel.HUMAN_VERIFIED,
        ))
        registry.register(KnowledgeProvenance(
            provenance_id="j2", knowledge_name="Second",
            trust_level=TrustLevel.CANDIDATE,
        ))
        json_1 = registry.to_json()
        json_2 = registry.to_json()
        assert json_1 == json_2
        data = json.loads(json_1)
        assert isinstance(data, list)
        assert len(data) == 2


# ---------------------------------------------------------------------------
# Test: Deprecated Knowledge Supported
# ---------------------------------------------------------------------------


class TestDeprecatedKnowledge:
    """Deprecated provenance records are handled correctly."""

    def test_deprecate_excludes_from_default_list(self, registry: KnowledgeProvenanceRegistry):
        registry.register(KnowledgeProvenance(
            provenance_id="dep_1", knowledge_name="Old Pattern",
            trust_level=TrustLevel.HUMAN_VERIFIED,
        ))
        registry.register(KnowledgeProvenance(
            provenance_id="dep_2", knowledge_name="Active Pattern",
            trust_level=TrustLevel.HUMAN_VERIFIED,
        ))

        registry.deprecate("dep_1")

        results = registry.list_provenance()
        ids = [r.provenance_id for r in results]
        assert "dep_1" not in ids
        assert "dep_2" in ids

    def test_include_deprecated_flag(self, registry: KnowledgeProvenanceRegistry):
        registry.register(KnowledgeProvenance(
            provenance_id="dep_3", knowledge_name="Deprecated Item",
            trust_level=TrustLevel.DERIVED,
        ))
        registry.deprecate("dep_3")

        results = registry.list_provenance(include_deprecated=True)
        ids = [r.provenance_id for r in results]
        assert "dep_3" in ids

    def test_deprecated_status_persists(self, registry: KnowledgeProvenanceRegistry):
        registry.register(KnowledgeProvenance(
            provenance_id="dep_4", knowledge_name="Will Deprecate",
            trust_level=TrustLevel.CANDIDATE,
        ))
        registry.deprecate("dep_4")

        retrieved = registry.get("dep_4")
        assert retrieved is not None
        assert retrieved.status == ProvenanceStatus.DEPRECATED

    def test_deprecate_nonexistent_returns_false(self, registry: KnowledgeProvenanceRegistry):
        assert registry.deprecate("nonexistent") is False


# ---------------------------------------------------------------------------
# Test: Supersession Chains Valid
# ---------------------------------------------------------------------------


class TestSupersessionChains:
    """Supersession chains track knowledge evolution."""

    def test_simple_supersession(self, registry: KnowledgeProvenanceRegistry):
        registry.register(KnowledgeProvenance(
            provenance_id="v1", knowledge_name="Grid Pattern v1",
            trust_level=TrustLevel.HUMAN_VERIFIED,
        ))
        registry.register(KnowledgeProvenance(
            provenance_id="v2", knowledge_name="Grid Pattern v2",
            trust_level=TrustLevel.EVIDENCE_SUPPORTED,
        ))

        result = registry.supersede("v1", "v2")
        assert result is True

        old = registry.get("v1")
        assert old is not None
        assert old.status == ProvenanceStatus.SUPERSEDED
        assert old.superseded_by == "v2"

    def test_chain_walk(self, registry: KnowledgeProvenanceRegistry):
        registry.register(KnowledgeProvenance(
            provenance_id="c1", knowledge_name="Chain Start",
            trust_level=TrustLevel.CANDIDATE,
        ))
        registry.register(KnowledgeProvenance(
            provenance_id="c2", knowledge_name="Chain Middle",
            trust_level=TrustLevel.DERIVED,
        ))
        registry.register(KnowledgeProvenance(
            provenance_id="c3", knowledge_name="Chain End",
            trust_level=TrustLevel.HUMAN_VERIFIED,
        ))

        registry.supersede("c1", "c2")
        registry.supersede("c2", "c3")

        chain = registry.get_supersession_chain("c1")
        assert len(chain) == 3
        assert chain[0].provenance_id == "c1"
        assert chain[1].provenance_id == "c2"
        assert chain[2].provenance_id == "c3"

    def test_chain_stops_on_missing(self, registry: KnowledgeProvenanceRegistry):
        registry.register(KnowledgeProvenance(
            provenance_id="m1", knowledge_name="Has Missing Link",
            trust_level=TrustLevel.CANDIDATE,
            superseded_by="nonexistent",
        ))
        # Register with superseded_by already set
        registry.register(KnowledgeProvenance(
            provenance_id="m1", knowledge_name="Has Missing Link",
            trust_level=TrustLevel.CANDIDATE,
        ))
        # Manually set superseded_by via update
        prov = registry.get("m1")
        prov.superseded_by = "nonexistent"
        prov.status = ProvenanceStatus.SUPERSEDED
        registry.register(prov)

        chain = registry.get_supersession_chain("m1")
        assert len(chain) == 1  # Stops at m1 since nonexistent doesn't exist

    def test_chain_stops_on_cycle(self, registry: KnowledgeProvenanceRegistry):
        registry.register(KnowledgeProvenance(
            provenance_id="cyc_a", knowledge_name="Cycle A",
            trust_level=TrustLevel.CANDIDATE,
        ))
        registry.register(KnowledgeProvenance(
            provenance_id="cyc_b", knowledge_name="Cycle B",
            trust_level=TrustLevel.CANDIDATE,
        ))

        registry.supersede("cyc_a", "cyc_b")
        registry.supersede("cyc_b", "cyc_a")

        chain = registry.get_supersession_chain("cyc_a")
        # Should stop rather than infinite loop
        assert len(chain) == 2
        assert chain[0].provenance_id == "cyc_a"
        assert chain[1].provenance_id == "cyc_b"

    def test_supersede_nonexistent_returns_false(self, registry: KnowledgeProvenanceRegistry):
        registry.register(KnowledgeProvenance(
            provenance_id="exists", knowledge_name="Exists",
            trust_level=TrustLevel.CANDIDATE,
        ))
        assert registry.supersede("exists", "nonexistent") is False
        assert registry.supersede("nonexistent", "exists") is False


# ---------------------------------------------------------------------------
# Test: JSON Output
# ---------------------------------------------------------------------------


class TestJsonOutput:
    """JSON serialization is valid and complete."""

    def test_to_dict_fields(self, registry: KnowledgeProvenanceRegistry):
        prov = KnowledgeProvenance(
            provenance_id="json_1",
            knowledge_name="JSON Test",
            trust_level=TrustLevel.FOUNDER_VERIFIED,
            source_confidence=SourceConfidence.HIGH,
            origin="founder_doc",
            confidence_score=1.0,
        )
        registry.register(prov)

        d = prov.to_dict()
        required_fields = [
            "provenance_id", "knowledge_name", "trust_level",
            "source_confidence", "status", "origin", "evidence_paths",
            "approving_source", "confidence_score", "superseded_by",
            "notes", "created_at", "updated_at",
        ]
        for f in required_fields:
            assert f in d, f"Missing field: {f}"

    def test_trust_level_serialized_as_string(self, registry: KnowledgeProvenanceRegistry):
        prov = KnowledgeProvenance(
            provenance_id="json_2",
            knowledge_name="String Test",
            trust_level=TrustLevel.DERIVED,
        )
        d = prov.to_dict()
        assert d["trust_level"] == "derived"
        assert isinstance(d["trust_level"], str)

    def test_registry_json_valid(self, registry: KnowledgeProvenanceRegistry):
        registry.register(KnowledgeProvenance(
            provenance_id="jv_1", knowledge_name="Valid JSON 1",
            trust_level=TrustLevel.CANDIDATE,
        ))
        registry.register(KnowledgeProvenance(
            provenance_id="jv_2", knowledge_name="Valid JSON 2",
            trust_level=TrustLevel.HUMAN_VERIFIED,
        ))
        output = registry.to_json()
        data = json.loads(output)
        assert isinstance(data, list)
        assert len(data) == 2


# ---------------------------------------------------------------------------
# Test: Name Filtering
# ---------------------------------------------------------------------------


class TestNameFiltering:
    """Name filter works correctly with SQL escape."""

    def test_name_filter_substring(self, registry: KnowledgeProvenanceRegistry):
        registry.register(KnowledgeProvenance(
            provenance_id="nf_1", knowledge_name="Grid Creation Pattern",
            trust_level=TrustLevel.HUMAN_VERIFIED,
        ))
        registry.register(KnowledgeProvenance(
            provenance_id="nf_2", knowledge_name="Level Setup Rule",
            trust_level=TrustLevel.CANDIDATE,
        ))

        results = registry.list_provenance(name_filter="Grid")
        assert len(results) == 1
        assert results[0].provenance_id == "nf_1"

    def test_name_filter_sql_wildcard_escaped(self, registry: KnowledgeProvenanceRegistry):
        registry.register(KnowledgeProvenance(
            provenance_id="wc_1", knowledge_name="100% Complete",
            trust_level=TrustLevel.CANDIDATE,
        ))
        registry.register(KnowledgeProvenance(
            provenance_id="wc_2", knowledge_name="Other Item",
            trust_level=TrustLevel.CANDIDATE,
        ))

        results = registry.list_provenance(name_filter="%")
        assert len(results) == 1
        assert results[0].provenance_id == "wc_1"

    def test_name_filter_backslash_escaped(self, registry: KnowledgeProvenanceRegistry):
        registry.register(KnowledgeProvenance(
            provenance_id="bs_1", knowledge_name=r"path\to\file",
            trust_level=TrustLevel.CANDIDATE,
        ))
        registry.register(KnowledgeProvenance(
            provenance_id="bs_2", knowledge_name="pathtofile",
            trust_level=TrustLevel.CANDIDATE,
        ))

        results = registry.list_provenance(name_filter="\\")
        assert len(results) == 1
        assert results[0].provenance_id == "bs_1"


# ---------------------------------------------------------------------------
# Test: Empty evidence_paths [] roundtrip (truthiness fix)
# ---------------------------------------------------------------------------


class TestEmptyEvidencePathsTruthiness:
    """Verify that empty list [] is preserved, not stored as NULL."""

    def test_empty_list_persists_as_json(self, registry: KnowledgeProvenanceRegistry):
        """Empty evidence_paths=[] must roundtrip, not collapse to None."""
        prov = KnowledgeProvenance(
            provenance_id="truth_1",
            knowledge_name="Empty Evidence Test",
            trust_level=TrustLevel.CANDIDATE,
            evidence_paths=[],
        )
        registry.register(prov)
        retrieved = registry.get("truth_1")
        assert retrieved is not None
        assert retrieved.evidence_paths == []

    def test_none_evidence_stays_none(self, registry: KnowledgeProvenanceRegistry):
        """evidence_paths=None must also roundtrip correctly."""
        prov = KnowledgeProvenance(
            provenance_id="truth_2",
            knowledge_name="None Evidence Test",
            trust_level=TrustLevel.CANDIDATE,
            evidence_paths=None,
        )
        registry.register(prov)
        retrieved = registry.get("truth_2")
        assert retrieved is not None
        assert retrieved.evidence_paths == []  # None → default empty list on read

    def test_populated_evidence_roundtrips(self, registry: KnowledgeProvenanceRegistry):
        """Non-empty evidence_paths must roundtrip."""
        prov = KnowledgeProvenance(
            provenance_id="truth_3",
            knowledge_name="Populated Evidence Test",
            trust_level=TrustLevel.CANDIDATE,
            evidence_paths=["path/a.json", "path/b.json"],
        )
        registry.register(prov)
        retrieved = registry.get("truth_3")
        assert retrieved is not None
        assert retrieved.evidence_paths == ["path/a.json", "path/b.json"]
