"""Tests for Knowledge Review and Approval Layer (PR #41).

Tests proving:
- review persistence roundtrip
- deterministic ordering
- approved knowledge retrievable
- rejected knowledge retrievable
- supersession chains supported
- duplicate reviews do not corrupt history
- conflicting decisions preserved in history
- JSON output valid
- CLI filters work
- unknown knowledge handled cleanly
"""

from __future__ import annotations

import json
import pathlib

import pytest
from axiom_core.knowledge_reviews import (
    DECISION_ORDER,
    KnowledgeReview,
    KnowledgeReviewRegistry,
    ReviewDecision,
    ReviewEvidence,
    ReviewReason,
    ReviewStatus,
    decision_rank,
)


@pytest.fixture()
def db_path(tmp_path: pathlib.Path) -> str:
    return str(tmp_path / "test_reviews.db")


@pytest.fixture()
def registry(db_path: str) -> KnowledgeReviewRegistry:
    return KnowledgeReviewRegistry(db_path=db_path)


# ---------------------------------------------------------------------------
# Test: Review Persistence Roundtrip
# ---------------------------------------------------------------------------


class TestReviewPersistence:
    """Reviews persist and retrieve deterministically."""

    def test_create_and_retrieve(self, registry: KnowledgeReviewRegistry):
        r = KnowledgeReview(
            review_id="rev_001",
            knowledge_id="kobj_001",
            knowledge_name="GridCreation pattern",
            decision=ReviewDecision.APPROVED,
            reason=ReviewReason.HUMAN_VALIDATION,
            reviewer="founder",
            notes="Validated against engineering standard",
            evidence_paths=["/evidence/run_001.json", "/evidence/run_002.json"],
            metadata={"source_pr": "PR #38"},
        )
        registry.create_review(r)

        retrieved = registry.get_review("rev_001")
        assert retrieved is not None
        assert retrieved.review_id == "rev_001"
        assert retrieved.knowledge_id == "kobj_001"
        assert retrieved.knowledge_name == "GridCreation pattern"
        assert retrieved.decision == ReviewDecision.APPROVED
        assert retrieved.reason == ReviewReason.HUMAN_VALIDATION
        assert retrieved.status == ReviewStatus.OPEN
        assert retrieved.reviewer == "founder"
        assert retrieved.notes == "Validated against engineering standard"
        assert retrieved.evidence_paths == ["/evidence/run_001.json", "/evidence/run_002.json"]
        assert retrieved.metadata == {"source_pr": "PR #38"}

    def test_missing_review_returns_none(self, registry: KnowledgeReviewRegistry):
        assert registry.get_review("nonexistent") is None

    def test_empty_knowledge_id_raises(self, registry: KnowledgeReviewRegistry):
        r = KnowledgeReview(knowledge_id="", knowledge_name="Test")
        with pytest.raises(ValueError, match="knowledge_id must not be empty"):
            registry.create_review(r)

    def test_empty_knowledge_name_raises(self, registry: KnowledgeReviewRegistry):
        r = KnowledgeReview(knowledge_id="kobj_001", knowledge_name="")
        with pytest.raises(ValueError, match="knowledge_name must not be empty"):
            registry.create_review(r)

    def test_create_does_not_mutate_input(self, registry: KnowledgeReviewRegistry):
        """create_review must not mutate the caller's input object."""
        r = KnowledgeReview(
            review_id="no_mut",
            knowledge_id="k1",
            knowledge_name="Immutable input",
            decision=ReviewDecision.PROPOSED,
        )
        original_updated_at = r.updated_at
        returned = registry.create_review(r)
        # Input object must be unchanged
        assert r.updated_at == original_updated_at
        # Returned object reflects persisted state (may differ)
        assert returned.review_id == "no_mut"
        assert returned is not r

    def test_review_count(self, registry: KnowledgeReviewRegistry):
        assert registry.review_count() == 0
        registry.create_review(
            KnowledgeReview(
                review_id="rev_c1",
                knowledge_id="k1",
                knowledge_name="Test 1",
            )
        )
        registry.create_review(
            KnowledgeReview(
                review_id="rev_c2",
                knowledge_id="k2",
                knowledge_name="Test 2",
            )
        )
        assert registry.review_count() == 2

    def test_to_dict_roundtrip(self, registry: KnowledgeReviewRegistry):
        r = KnowledgeReview(
            review_id="rev_dict",
            knowledge_id="k_dict",
            knowledge_name="Dict test",
            decision=ReviewDecision.REJECTED,
            reason=ReviewReason.INSUFFICIENT_EVIDENCE,
            reviewer="human",
        )
        d = r.to_dict()
        assert d["review_id"] == "rev_dict"
        assert d["decision"] == "rejected"
        assert d["reason"] == "insufficient_evidence"
        assert d["status"] == "open"
        assert isinstance(d["evidence_paths"], list)
        assert isinstance(d["metadata"], dict)


# ---------------------------------------------------------------------------
# Test: Deterministic Ordering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    """Reviews list in decision-priority order, then alphabetically by name."""

    def test_decision_priority_ordering(self, registry: KnowledgeReviewRegistry):
        # Create reviews with different decisions
        for decision, name in [
            (ReviewDecision.REJECTED, "Zebra rule"),
            (ReviewDecision.APPROVED, "Apple guideline"),
            (ReviewDecision.PROPOSED, "Banana candidate"),
            (ReviewDecision.NEEDS_MORE_EVIDENCE, "Cherry principle"),
        ]:
            registry.create_review(
                KnowledgeReview(
                    knowledge_id=f"k_{name[:3]}",
                    knowledge_name=name,
                    decision=decision,
                )
            )

        results = registry.list_reviews()
        assert len(results) == 4
        assert results[0].decision == ReviewDecision.APPROVED
        assert results[1].decision == ReviewDecision.PROPOSED
        assert results[2].decision == ReviewDecision.NEEDS_MORE_EVIDENCE
        assert results[3].decision == ReviewDecision.REJECTED

    def test_alphabetical_within_same_decision(self, registry: KnowledgeReviewRegistry):
        for name in ["Zebra", "Apple", "Mango"]:
            registry.create_review(
                KnowledgeReview(
                    knowledge_id=f"k_{name}",
                    knowledge_name=name,
                    decision=ReviewDecision.APPROVED,
                )
            )
        results = registry.list_reviews()
        names = [r.knowledge_name for r in results]
        assert names == ["Apple", "Mango", "Zebra"]

    def test_decision_rank_function(self):
        assert decision_rank(ReviewDecision.APPROVED) < decision_rank(ReviewDecision.REJECTED)
        assert decision_rank(ReviewDecision.PROPOSED) < decision_rank(ReviewDecision.DEPRECATED)
        assert decision_rank("unknown_decision") == len(DECISION_ORDER)


# ---------------------------------------------------------------------------
# Test: Decision Filtering
# ---------------------------------------------------------------------------


class TestDecisionFiltering:
    """Approved/rejected/etc. knowledge retrievable via filters."""

    def _populate(self, registry: KnowledgeReviewRegistry):
        reviews = [
            ("rev_a1", "k1", "Approved pattern", ReviewDecision.APPROVED),
            ("rev_a2", "k2", "Rejected rule", ReviewDecision.REJECTED),
            ("rev_a3", "k3", "Proposed candidate", ReviewDecision.PROPOSED),
            ("rev_a4", "k4", "Deprecated workflow", ReviewDecision.DEPRECATED),
        ]
        for rid, kid, name, decision in reviews:
            registry.create_review(
                KnowledgeReview(
                    review_id=rid,
                    knowledge_id=kid,
                    knowledge_name=name,
                    decision=decision,
                )
            )

    def test_filter_approved(self, registry: KnowledgeReviewRegistry):
        self._populate(registry)
        results = registry.list_reviews(decision_filter=ReviewDecision.APPROVED)
        assert len(results) == 1
        assert results[0].decision == ReviewDecision.APPROVED

    def test_filter_rejected(self, registry: KnowledgeReviewRegistry):
        self._populate(registry)
        results = registry.list_reviews(decision_filter=ReviewDecision.REJECTED)
        assert len(results) == 1
        assert results[0].decision == ReviewDecision.REJECTED

    def test_filter_by_status(self, registry: KnowledgeReviewRegistry):
        self._populate(registry)
        registry.close_review("rev_a2")
        open_results = registry.list_reviews(status_filter=ReviewStatus.OPEN)
        closed_results = registry.list_reviews(status_filter=ReviewStatus.CLOSED)
        assert len(open_results) == 3
        assert len(closed_results) == 1
        assert closed_results[0].review_id == "rev_a2"

    def test_filter_by_name(self, registry: KnowledgeReviewRegistry):
        self._populate(registry)
        results = registry.list_reviews(name_filter="pattern")
        assert len(results) == 1
        assert results[0].knowledge_name == "Approved pattern"


# ---------------------------------------------------------------------------
# Test: Supersession Chains
# ---------------------------------------------------------------------------


class TestSupersessionChains:
    """Supersession chains walk correctly and handle cycles."""

    def test_supersede_review(self, registry: KnowledgeReviewRegistry):
        registry.create_review(
            KnowledgeReview(
                review_id="rev_old",
                knowledge_id="k1",
                knowledge_name="Original review",
                decision=ReviewDecision.APPROVED,
            )
        )
        registry.create_review(
            KnowledgeReview(
                review_id="rev_new",
                knowledge_id="k1",
                knowledge_name="Updated review",
                decision=ReviewDecision.APPROVED,
            )
        )
        result = registry.supersede_review("rev_old", "rev_new")
        assert result is True

        old = registry.get_review("rev_old")
        assert old is not None
        assert old.decision == ReviewDecision.SUPERSEDED
        assert old.status == ReviewStatus.CLOSED
        assert old.superseded_by == "rev_new"

    def test_supersession_chain_walk(self, registry: KnowledgeReviewRegistry):
        # v1 -> v2 -> v3
        registry.create_review(
            KnowledgeReview(review_id="v1", knowledge_id="k1", knowledge_name="V1")
        )
        registry.create_review(
            KnowledgeReview(review_id="v2", knowledge_id="k1", knowledge_name="V2")
        )
        registry.create_review(
            KnowledgeReview(review_id="v3", knowledge_id="k1", knowledge_name="V3")
        )
        registry.supersede_review("v1", "v2")
        registry.supersede_review("v2", "v3")

        chain = registry.get_supersession_chain("v1")
        assert len(chain) == 3
        assert [c.review_id for c in chain] == ["v1", "v2", "v3"]

    def test_supersession_cycle_stops(self, registry: KnowledgeReviewRegistry):
        # A -> B -> A (cycle)
        registry.create_review(
            KnowledgeReview(review_id="cyc_a", knowledge_id="k1", knowledge_name="A")
        )
        registry.create_review(
            KnowledgeReview(review_id="cyc_b", knowledge_id="k1", knowledge_name="B")
        )
        registry.supersede_review("cyc_a", "cyc_b")
        registry.supersede_review("cyc_b", "cyc_a")

        chain = registry.get_supersession_chain("cyc_a")
        assert len(chain) == 2  # stops at cycle

    def test_supersede_missing_returns_false(self, registry: KnowledgeReviewRegistry):
        registry.create_review(
            KnowledgeReview(review_id="exists", knowledge_id="k1", knowledge_name="Exists")
        )
        assert registry.supersede_review("exists", "missing") is False
        assert registry.supersede_review("missing", "exists") is False

    def test_self_supersession_rejected(self, registry: KnowledgeReviewRegistry):
        registry.create_review(
            KnowledgeReview(
                review_id="self_ref",
                knowledge_id="k1",
                knowledge_name="Self test",
                decision=ReviewDecision.APPROVED,
            )
        )
        result = registry.supersede_review("self_ref", "self_ref")
        assert result is False
        # Record should remain untouched
        r = registry.get_review("self_ref")
        assert r is not None
        assert r.decision == ReviewDecision.APPROVED
        assert r.status == ReviewStatus.OPEN
        assert r.superseded_by is None


# ---------------------------------------------------------------------------
# Test: Duplicate Reviews & History
# ---------------------------------------------------------------------------


class TestDuplicateReviewsAndHistory:
    """Duplicate reviews do not corrupt; conflicting decisions preserved."""

    def test_multiple_reviews_same_knowledge(self, registry: KnowledgeReviewRegistry):
        # Two different reviewers, conflicting decisions
        registry.create_review(
            KnowledgeReview(
                review_id="rev_1",
                knowledge_id="k_shared",
                knowledge_name="Shared pattern",
                decision=ReviewDecision.APPROVED,
                reviewer="reviewer_A",
            )
        )
        registry.create_review(
            KnowledgeReview(
                review_id="rev_2",
                knowledge_id="k_shared",
                knowledge_name="Shared pattern",
                decision=ReviewDecision.REJECTED,
                reviewer="reviewer_B",
                reason=ReviewReason.CONFLICTING_KNOWLEDGE,
            )
        )

        history = registry.get_reviews_for_knowledge("k_shared")
        assert len(history) == 2
        decisions = {r.decision for r in history}
        assert ReviewDecision.APPROVED in decisions
        assert ReviewDecision.REJECTED in decisions

    def test_conflicting_decisions_preserved_in_listing(self, registry: KnowledgeReviewRegistry):
        registry.create_review(
            KnowledgeReview(
                review_id="dup_1",
                knowledge_id="k1",
                knowledge_name="Same name",
                decision=ReviewDecision.APPROVED,
            )
        )
        registry.create_review(
            KnowledgeReview(
                review_id="dup_2",
                knowledge_id="k1",
                knowledge_name="Same name",
                decision=ReviewDecision.REJECTED,
            )
        )
        all_reviews = registry.list_reviews()
        assert len(all_reviews) == 2
        # Both are listed; approved sorts before rejected
        assert all_reviews[0].decision == ReviewDecision.APPROVED
        assert all_reviews[1].decision == ReviewDecision.REJECTED


# ---------------------------------------------------------------------------
# Test: JSON Output
# ---------------------------------------------------------------------------


class TestJsonOutput:
    """JSON output is valid and contains all required fields."""

    REQUIRED_FIELDS = {
        "review_id",
        "knowledge_id",
        "knowledge_name",
        "decision",
        "reason",
        "status",
        "reviewer",
        "notes",
        "evidence_paths",
        "metadata",
        "superseded_by",
        "created_at",
        "updated_at",
    }

    def test_to_json_valid(self, registry: KnowledgeReviewRegistry):
        registry.create_review(
            KnowledgeReview(
                review_id="json_1",
                knowledge_id="k_json",
                knowledge_name="JSON test",
                decision=ReviewDecision.APPROVED,
                evidence_paths=["/path/a"],
                metadata={"key": "value"},
            )
        )
        raw = registry.to_json()
        parsed = json.loads(raw)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert self.REQUIRED_FIELDS.issubset(parsed[0].keys())

    def test_json_with_filters(self, registry: KnowledgeReviewRegistry):
        registry.create_review(
            KnowledgeReview(
                review_id="jf_1",
                knowledge_id="k1",
                knowledge_name="Approved item",
                decision=ReviewDecision.APPROVED,
            )
        )
        registry.create_review(
            KnowledgeReview(
                review_id="jf_2",
                knowledge_id="k2",
                knowledge_name="Rejected item",
                decision=ReviewDecision.REJECTED,
            )
        )
        raw = registry.to_json(decision_filter=ReviewDecision.APPROVED)
        parsed = json.loads(raw)
        assert len(parsed) == 1
        assert parsed[0]["decision"] == "approved"


# ---------------------------------------------------------------------------
# Test: Empty Collection Roundtrips
# ---------------------------------------------------------------------------


class TestEmptyCollectionRoundtrips:
    """Empty lists and dicts persist as proper JSON, not NULL."""

    def test_empty_evidence_paths_roundtrip(self, registry: KnowledgeReviewRegistry):
        r = KnowledgeReview(
            review_id="eev_1",
            knowledge_id="k1",
            knowledge_name="Empty evidence",
            evidence_paths=[],
        )
        registry.create_review(r)
        retrieved = registry.get_review("eev_1")
        assert retrieved is not None
        assert retrieved.evidence_paths == []

    def test_empty_metadata_roundtrip(self, registry: KnowledgeReviewRegistry):
        r = KnowledgeReview(
            review_id="emeta_1",
            knowledge_id="k1",
            knowledge_name="Empty metadata",
            metadata={},
        )
        registry.create_review(r)
        retrieved = registry.get_review("emeta_1")
        assert retrieved is not None
        assert retrieved.metadata == {}


# ---------------------------------------------------------------------------
# Test: Close Review
# ---------------------------------------------------------------------------


class TestCloseReview:
    """Reviews can be closed."""

    def test_close_existing(self, registry: KnowledgeReviewRegistry):
        registry.create_review(
            KnowledgeReview(
                review_id="close_1",
                knowledge_id="k1",
                knowledge_name="To close",
            )
        )
        result = registry.close_review("close_1")
        assert result is True
        retrieved = registry.get_review("close_1")
        assert retrieved is not None
        assert retrieved.status == ReviewStatus.CLOSED

    def test_close_missing_returns_false(self, registry: KnowledgeReviewRegistry):
        assert registry.close_review("missing") is False

    def test_close_event_records_prior_state(self, registry: KnowledgeReviewRegistry):
        """Close event captures the prior decision and status for audit trail."""
        from axiom_core.database import get_session, make_session_factory
        from axiom_core.knowledge_reviews import KnowledgeReviewEventRow
        registry.create_review(
            KnowledgeReview(
                review_id="close_audit",
                knowledge_id="k1",
                knowledge_name="Audit close",
                decision=ReviewDecision.APPROVED,
            )
        )
        registry.close_review("close_audit")

        sf = make_session_factory(registry._engine)
        with get_session(sf) as session:
            events = (
                session.query(KnowledgeReviewEventRow)
                .filter(KnowledgeReviewEventRow.review_id == "close_audit")
                .filter(KnowledgeReviewEventRow.event_type == "closed")
                .all()
            )
            assert len(events) == 1
            assert "prior_decision=approved" in events[0].details
            assert "prior_status=open" in events[0].details


# ---------------------------------------------------------------------------
# Test: Enum Coercion
# ---------------------------------------------------------------------------


class TestEnumCoercion:
    """Enum values persist and retrieve as proper enum instances."""

    def test_enum_types_after_roundtrip(self, registry: KnowledgeReviewRegistry):
        r = KnowledgeReview(
            review_id="enum_1",
            knowledge_id="k_enum",
            knowledge_name="Enum test",
            decision=ReviewDecision.NEEDS_MORE_EVIDENCE,
            reason=ReviewReason.LOW_CONFIDENCE,
            status=ReviewStatus.OPEN,
        )
        registry.create_review(r)
        retrieved = registry.get_review("enum_1")
        assert retrieved is not None
        assert type(retrieved.decision) is ReviewDecision
        assert type(retrieved.reason) is ReviewReason
        assert type(retrieved.status) is ReviewStatus
        assert retrieved.decision == ReviewDecision.NEEDS_MORE_EVIDENCE
        assert retrieved.reason == ReviewReason.LOW_CONFIDENCE


# ---------------------------------------------------------------------------
# Test: ReviewEvidence data model
# ---------------------------------------------------------------------------


class TestReviewEvidence:
    """ReviewEvidence helper persists correctly."""

    def test_to_dict_from_dict(self):
        ev = ReviewEvidence(
            evidence_type="run_artifact",
            evidence_path="/runs/run_001/evidence.json",
            description="Health run evidence",
        )
        d = ev.to_dict()
        assert d["evidence_type"] == "run_artifact"
        assert d["evidence_path"] == "/runs/run_001/evidence.json"

        restored = ReviewEvidence.from_dict(d)
        assert restored.evidence_type == ev.evidence_type
        assert restored.evidence_path == ev.evidence_path
        assert restored.description == ev.description
