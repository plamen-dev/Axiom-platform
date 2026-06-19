"""Tests for axiom_core.patch_review — Patch Review and Approval Queue v1."""

from __future__ import annotations

import json

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("AXIOM_DB_PATH", db_path)
    return db_path


@pytest.fixture()
def proposal_id(tmp_db):
    """Create a patch proposal and return its ID."""
    from axiom_core.patch_proposal import (
        PatchProposal,
        PatchProposalRegistry,
        ProposedFileChange,
    )

    registry = PatchProposalRegistry(db_path=tmp_db)
    proposal = PatchProposal(
        plan_id="plan-001",
        title="Patch: Test fix",
        summary="A test patch",
        file_changes=[ProposedFileChange(file_path="src/foo.py")],
    )
    registry._persist(proposal)
    return proposal.proposal_id


@pytest.fixture()
def review_registry(tmp_db):
    from axiom_core.patch_review import PatchReviewRegistry

    return PatchReviewRegistry(db_path=tmp_db)


# ---------------------------------------------------------------------------
# TestEnums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_review_decision_values(self):
        from axiom_core.patch_review import ReviewDecision

        assert ReviewDecision.PROPOSED.value == "proposed"
        assert ReviewDecision.APPROVED.value == "approved"
        assert ReviewDecision.REJECTED.value == "rejected"
        assert ReviewDecision.NEEDS_MORE_EVIDENCE.value == "needs_more_evidence"
        assert ReviewDecision.SUPERSEDED.value == "superseded"
        assert ReviewDecision.DEPRECATED.value == "deprecated"


# ---------------------------------------------------------------------------
# TestDataModels
# ---------------------------------------------------------------------------


class TestDataModels:
    def test_patch_review_evidence_roundtrip(self):
        from axiom_core.patch_review import PatchReviewEvidence

        ev = PatchReviewEvidence(
            description="Tests pass",
            evidence_type="test_output",
            artifact_path="artifacts/test.log",
        )
        d = ev.to_dict()
        assert d["evidence_type"] == "test_output"
        assert d["artifact_path"] == "artifacts/test.log"
        ev2 = PatchReviewEvidence.from_dict(d)
        assert ev2.description == ev.description
        assert ev2.artifact_path == ev.artifact_path

    def test_patch_review_to_dict(self):
        from axiom_core.patch_review import (
            PatchReview,
            PatchReviewEvidence,
            ReviewDecision,
        )

        review = PatchReview(
            proposal_id="prop-001",
            decision=ReviewDecision.APPROVED,
            reason="Looks good",
            reviewer="plamen",
            evidence=[PatchReviewEvidence(description="Tests pass")],
        )
        d = review.to_dict()
        assert d["proposal_id"] == "prop-001"
        assert d["decision"] == "approved"
        assert d["reason"] == "Looks good"
        assert len(d["evidence"]) == 1
        parsed = json.loads(json.dumps(d, default=str))
        assert parsed["reviewer"] == "plamen"

    def test_patch_review_history_entry_to_dict(self):
        from axiom_core.patch_review import PatchReviewHistoryEntry, ReviewDecision

        entry = PatchReviewHistoryEntry(
            proposal_id="prop-001",
            review_id="rev-001",
            decision=ReviewDecision.REJECTED,
            reason="Needs tests",
            reviewer="plamen",
        )
        d = entry.to_dict()
        assert d["decision"] == "rejected"
        assert d["proposal_id"] == "prop-001"


# ---------------------------------------------------------------------------
# TestRegistry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_create_review(self, review_registry, proposal_id):
        from axiom_core.patch_review import ReviewDecision

        review = review_registry.create_review(
            proposal_id=proposal_id,
            decision=ReviewDecision.APPROVED,
            reason="human_validation",
            reviewer="plamen",
        )
        assert review.proposal_id == proposal_id
        assert review.decision == ReviewDecision.APPROVED
        assert review.reason == "human_validation"
        assert review.reviewer == "plamen"

    def test_create_review_unknown_proposal_raises(self, review_registry):
        from axiom_core.patch_review import ReviewDecision

        with pytest.raises(ValueError, match="not found"):
            review_registry.create_review(
                proposal_id="nonexistent-id",
                decision=ReviewDecision.APPROVED,
            )

    def test_create_review_syncs_proposal_status_approved(
        self, review_registry, proposal_id, tmp_db,
    ):
        from axiom_core.patch_proposal import PatchProposalRegistry, PatchStatus
        from axiom_core.patch_review import ReviewDecision

        review_registry.create_review(
            proposal_id=proposal_id,
            decision=ReviewDecision.APPROVED,
        )
        prop_reg = PatchProposalRegistry(db_path=tmp_db)
        proposal = prop_reg.get_proposal(proposal_id)
        assert proposal is not None
        assert proposal.status == PatchStatus.APPROVED

    def test_create_review_syncs_proposal_status_rejected(
        self, review_registry, proposal_id, tmp_db,
    ):
        from axiom_core.patch_proposal import PatchProposalRegistry, PatchStatus
        from axiom_core.patch_review import ReviewDecision

        review_registry.create_review(
            proposal_id=proposal_id,
            decision=ReviewDecision.REJECTED,
        )
        prop_reg = PatchProposalRegistry(db_path=tmp_db)
        proposal = prop_reg.get_proposal(proposal_id)
        assert proposal is not None
        assert proposal.status == PatchStatus.REJECTED

    def test_needs_more_evidence_does_not_sync(
        self, review_registry, proposal_id, tmp_db,
    ):
        from axiom_core.patch_proposal import PatchProposalRegistry, PatchStatus
        from axiom_core.patch_review import ReviewDecision

        review_registry.create_review(
            proposal_id=proposal_id,
            decision=ReviewDecision.NEEDS_MORE_EVIDENCE,
            reason="Need test coverage",
        )
        prop_reg = PatchProposalRegistry(db_path=tmp_db)
        proposal = prop_reg.get_proposal(proposal_id)
        assert proposal is not None
        assert proposal.status == PatchStatus.PROPOSED

    def test_json_output_valid(self, review_registry, proposal_id):
        from axiom_core.patch_review import ReviewDecision

        review = review_registry.create_review(
            proposal_id=proposal_id,
            decision=ReviewDecision.APPROVED,
        )
        output = json.dumps(review.to_dict(), indent=2, default=str)
        parsed = json.loads(output)
        assert parsed["decision"] == "approved"


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_review_persists_and_retrieves(self, review_registry, proposal_id):
        from axiom_core.patch_review import ReviewDecision

        review = review_registry.create_review(
            proposal_id=proposal_id,
            decision=ReviewDecision.APPROVED,
            reason="LGTM",
        )
        retrieved = review_registry.get_review(review.review_id)
        assert retrieved is not None
        assert retrieved.review_id == review.review_id
        assert retrieved.decision == ReviewDecision.APPROVED

    def test_get_review_unknown_returns_none(self, review_registry):
        assert review_registry.get_review("nonexistent-id") is None

    def test_get_latest_review(self, review_registry, proposal_id):
        from axiom_core.patch_review import ReviewDecision

        review_registry.create_review(
            proposal_id=proposal_id,
            decision=ReviewDecision.NEEDS_MORE_EVIDENCE,
        )
        review2 = review_registry.create_review(
            proposal_id=proposal_id,
            decision=ReviewDecision.APPROVED,
        )
        latest = review_registry.get_latest_review(proposal_id)
        assert latest is not None
        assert latest.review_id == review2.review_id
        assert latest.decision == ReviewDecision.APPROVED

    def test_get_latest_review_unknown_returns_none(self, review_registry):
        assert review_registry.get_latest_review("nonexistent") is None

    def test_list_reviews(self, review_registry, proposal_id):
        from axiom_core.patch_review import ReviewDecision

        review_registry.create_review(
            proposal_id=proposal_id,
            decision=ReviewDecision.APPROVED,
        )
        reviews = review_registry.list_reviews()
        assert len(reviews) >= 1

    def test_list_reviews_filter_by_proposal(self, review_registry, proposal_id):
        from axiom_core.patch_review import ReviewDecision

        review_registry.create_review(
            proposal_id=proposal_id,
            decision=ReviewDecision.APPROVED,
        )
        filtered = review_registry.list_reviews(proposal_id=proposal_id)
        assert len(filtered) >= 1
        for r in filtered:
            assert r.proposal_id == proposal_id

    def test_list_reviews_filter_by_decision(self, review_registry, proposal_id):
        from axiom_core.patch_review import ReviewDecision

        review_registry.create_review(
            proposal_id=proposal_id,
            decision=ReviewDecision.APPROVED,
        )
        approved = review_registry.list_reviews(decision=ReviewDecision.APPROVED)
        assert len(approved) >= 1
        for r in approved:
            assert r.decision == ReviewDecision.APPROVED

    def test_from_row_roundtrip(self, review_registry, proposal_id):
        from axiom_core.patch_review import ReviewDecision

        review = review_registry.create_review(
            proposal_id=proposal_id,
            decision=ReviewDecision.APPROVED,
            reason="Validated",
            reviewer="plamen",
        )
        retrieved = review_registry.get_review(review.review_id)
        assert retrieved is not None
        d_orig = review.to_dict()
        d_retr = retrieved.to_dict()
        for key in ("proposal_id", "decision", "reason", "reviewer"):
            assert d_orig[key] == d_retr[key], f"Roundtrip mismatch: {key}"


# ---------------------------------------------------------------------------
# TestHistory
# ---------------------------------------------------------------------------


class TestHistory:
    def test_history_recorded(self, review_registry, proposal_id):
        from axiom_core.patch_review import ReviewDecision

        review_registry.create_review(
            proposal_id=proposal_id,
            decision=ReviewDecision.NEEDS_MORE_EVIDENCE,
            reason="Need tests",
        )
        history = review_registry.get_history(proposal_id)
        assert len(history) == 1
        assert history[0].decision == ReviewDecision.NEEDS_MORE_EVIDENCE

    def test_multiple_reviews_produce_history(self, review_registry, proposal_id):
        from axiom_core.patch_review import ReviewDecision

        review_registry.create_review(
            proposal_id=proposal_id,
            decision=ReviewDecision.NEEDS_MORE_EVIDENCE,
            reason="Need tests",
            reviewer="reviewer1",
        )
        review_registry.create_review(
            proposal_id=proposal_id,
            decision=ReviewDecision.APPROVED,
            reason="Tests added",
            reviewer="reviewer2",
        )
        history = review_registry.get_history(proposal_id)
        assert len(history) == 2
        assert history[0].decision == ReviewDecision.NEEDS_MORE_EVIDENCE
        assert history[1].decision == ReviewDecision.APPROVED

    def test_history_empty_for_unknown_proposal(self, review_registry):
        assert review_registry.get_history("nonexistent") == []

    def test_history_preserves_chronological_order(
        self, review_registry, proposal_id,
    ):
        from axiom_core.patch_review import ReviewDecision

        review_registry.create_review(
            proposal_id=proposal_id,
            decision=ReviewDecision.REJECTED,
        )
        review_registry.create_review(
            proposal_id=proposal_id,
            decision=ReviewDecision.NEEDS_MORE_EVIDENCE,
        )
        review_registry.create_review(
            proposal_id=proposal_id,
            decision=ReviewDecision.APPROVED,
        )
        history = review_registry.get_history(proposal_id)
        assert len(history) == 3
        assert history[0].decision == ReviewDecision.REJECTED
        assert history[1].decision == ReviewDecision.NEEDS_MORE_EVIDENCE
        assert history[2].decision == ReviewDecision.APPROVED
        for i in range(len(history) - 1):
            assert history[i].created_at <= history[i + 1].created_at
