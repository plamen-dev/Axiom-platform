"""Tests for the Plan Review Queue (PR #51).

Acceptance criteria verified:
- plan reviews persist
- decisions persist
- duplicate reviews preserve history
- approved plans are retrievable
- rejected plans are retrievable
- unknown plan IDs fail clearly
- JSON output works
- CLI filters work
- no plan execution occurs
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from axiom_core.plan_reviews import (
    DECISION_ORDER,
    VALID_DECISIONS,
    VALID_REASONS,
    VALID_STATUSES,
    PlanReview,
    PlanReviewDecision,
    PlanReviewEvidence,
    PlanReviewHistory,
    PlanReviewReason,
    PlanReviewRegistry,
    PlanReviewStatus,
    decision_rank,
)

_CLI = [sys.executable, "-m", "axiom_cli.main"]
_REPO_ROOT = str(Path(__file__).resolve().parents[1])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry(tmp_path):
    """Create a fresh registry backed by a temp database."""
    db = str(tmp_path / "test_plan_reviews.db")
    return PlanReviewRegistry(db_path=db)


@pytest.fixture()
def sample_review():
    """Create a sample PlanReview for testing."""
    return PlanReview(
        plan_id="plan-001",
        plan_name="Validate SetParameterValue on Walls",
        decision=PlanReviewDecision.PROPOSED,
        reason=PlanReviewReason.HUMAN_VALIDATION,
        reviewer="engineer-01",
        notes="Initial proposal",
    )


# ---------------------------------------------------------------------------
# Enum / model tests
# ---------------------------------------------------------------------------


class TestEnums:
    """Verify enum definitions match the specification."""

    def test_all_decisions_defined(self):
        expected = {"proposed", "approved", "rejected", "deferred", "needs_more_evidence", "superseded"}
        assert VALID_DECISIONS == expected

    def test_all_statuses_defined(self):
        assert VALID_STATUSES == {"open", "closed"}

    def test_all_reasons_defined(self):
        expected = {
            "human_validation", "insufficient_evidence", "unsafe",
            "conflicting_plan", "duplicate", "obsolete",
            "low_confidence", "founder_override", "policy_violation",
            "deferred_pending",
        }
        assert VALID_REASONS == expected

    def test_decision_rank_ordering(self):
        """Approved has highest priority (rank 0)."""
        assert decision_rank(PlanReviewDecision.APPROVED) == 0
        assert decision_rank(PlanReviewDecision.PROPOSED) == 1
        assert decision_rank(PlanReviewDecision.SUPERSEDED) == len(DECISION_ORDER) - 1

    def test_decision_rank_unknown_string(self):
        assert decision_rank("nonexistent") == len(DECISION_ORDER)


class TestPlanReviewModel:
    """Verify PlanReview data model."""

    def test_defaults(self):
        r = PlanReview(plan_id="p1", plan_name="Test Plan")
        assert r.review_id  # auto-generated UUID
        assert r.decision == PlanReviewDecision.PROPOSED
        assert r.reason == PlanReviewReason.HUMAN_VALIDATION
        assert r.status == PlanReviewStatus.OPEN
        assert r.evidence == []
        assert r.metadata == {}
        assert r.created_at
        assert r.updated_at

    def test_to_dict_serializes_all_fields(self):
        r = PlanReview(
            plan_id="p1",
            plan_name="Test Plan",
            decision=PlanReviewDecision.APPROVED,
            reason=PlanReviewReason.HUMAN_VALIDATION,
            evidence=[PlanReviewEvidence(evidence_type="bundle", evidence_path="/a/b")],
        )
        d = r.to_dict()
        assert d["plan_id"] == "p1"
        assert d["decision"] == "approved"
        assert d["reason"] == "human_validation"
        assert len(d["evidence"]) == 1
        assert d["evidence"][0]["evidence_type"] == "bundle"

    def test_string_coercion_for_decision(self):
        r = PlanReview(plan_id="p1", plan_name="T", decision="approved")
        assert r.decision == PlanReviewDecision.APPROVED

    def test_invalid_decision_string_raises(self):
        with pytest.raises(ValueError):
            PlanReview(plan_id="p1", plan_name="T", decision="invalid_decision")


class TestPlanReviewEvidence:
    def test_to_dict_from_dict_roundtrip(self):
        e = PlanReviewEvidence(
            evidence_type="validation_bundle",
            evidence_path="/artifacts/run-001/pass_fail.json",
            description="Evidence from validation run",
        )
        d = e.to_dict()
        restored = PlanReviewEvidence.from_dict(d)
        assert restored.evidence_type == e.evidence_type
        assert restored.evidence_path == e.evidence_path
        assert restored.description == e.description


class TestPlanReviewHistory:
    def test_latest_decision_empty(self):
        h = PlanReviewHistory(plan_id="p1", reviews=[])
        assert h.latest_decision is None

    def test_latest_decision_returns_last(self):
        r1 = PlanReview(plan_id="p1", plan_name="T", decision=PlanReviewDecision.PROPOSED)
        r2 = PlanReview(plan_id="p1", plan_name="T", decision=PlanReviewDecision.APPROVED)
        h = PlanReviewHistory(plan_id="p1", reviews=[r1, r2])
        assert h.latest_decision == PlanReviewDecision.APPROVED

    def test_to_dict(self):
        r1 = PlanReview(plan_id="p1", plan_name="T")
        h = PlanReviewHistory(plan_id="p1", reviews=[r1])
        d = h.to_dict()
        assert d["plan_id"] == "p1"
        assert d["review_count"] == 1
        assert d["latest_decision"] == "proposed"


# ---------------------------------------------------------------------------
# Registry persistence tests
# ---------------------------------------------------------------------------


class TestPlanReviewRegistry:
    """Verify persistence, retrieval, and filtering."""

    def test_create_and_get(self, registry, sample_review):
        """Plan reviews persist and are retrievable."""
        created = registry.create_review(sample_review)
        assert created.review_id == sample_review.review_id
        assert created.plan_id == "plan-001"
        assert created.decision == PlanReviewDecision.PROPOSED

        fetched = registry.get_review(created.review_id)
        assert fetched is not None
        assert fetched.plan_id == "plan-001"
        assert fetched.plan_name == "Validate SetParameterValue on Walls"

    def test_decisions_persist(self, registry):
        """Decisions persist through create/get cycle."""
        for decision in PlanReviewDecision:
            r = PlanReview(
                plan_id=f"plan-{decision.value}",
                plan_name=f"Plan {decision.value}",
                decision=decision,
                reason=PlanReviewReason.HUMAN_VALIDATION,
            )
            created = registry.create_review(r)
            fetched = registry.get_review(created.review_id)
            assert fetched.decision == decision

    def test_duplicate_reviews_preserve_history(self, registry):
        """Multiple reviews for same plan are all preserved."""
        plan_id = "plan-dup"
        r1 = PlanReview(plan_id=plan_id, plan_name="Dup Plan", decision=PlanReviewDecision.PROPOSED)
        r2 = PlanReview(plan_id=plan_id, plan_name="Dup Plan", decision=PlanReviewDecision.REJECTED, reason=PlanReviewReason.UNSAFE)
        r3 = PlanReview(plan_id=plan_id, plan_name="Dup Plan", decision=PlanReviewDecision.APPROVED)

        registry.create_review(r1)
        registry.create_review(r2)
        registry.create_review(r3)

        history = registry.get_reviews_for_plan(plan_id)
        assert len(history) == 3
        assert history[0].decision == PlanReviewDecision.PROPOSED
        assert history[1].decision == PlanReviewDecision.REJECTED
        assert history[2].decision == PlanReviewDecision.APPROVED

    def test_approved_plans_retrievable(self, registry):
        """Approved plans are retrievable via decision filter."""
        registry.create_review(PlanReview(plan_id="p-a", plan_name="Approved Plan", decision=PlanReviewDecision.APPROVED))
        registry.create_review(PlanReview(plan_id="p-r", plan_name="Rejected Plan", decision=PlanReviewDecision.REJECTED))

        approved = registry.list_reviews(decision_filter=PlanReviewDecision.APPROVED)
        assert len(approved) == 1
        assert approved[0].plan_id == "p-a"

    def test_rejected_plans_retrievable(self, registry):
        """Rejected plans are retrievable via decision filter."""
        registry.create_review(PlanReview(plan_id="p-a", plan_name="Approved Plan", decision=PlanReviewDecision.APPROVED))
        registry.create_review(PlanReview(plan_id="p-r", plan_name="Rejected Plan", decision=PlanReviewDecision.REJECTED, reason=PlanReviewReason.UNSAFE))

        rejected = registry.list_reviews(decision_filter=PlanReviewDecision.REJECTED)
        assert len(rejected) == 1
        assert rejected[0].plan_id == "p-r"

    def test_unknown_plan_id_returns_empty(self, registry):
        """Unknown plan IDs fail clearly (empty history, None get)."""
        assert registry.get_review("nonexistent-id") is None
        history = registry.get_reviews_for_plan("nonexistent-plan")
        assert history == []

    def test_json_output(self, registry, sample_review):
        """JSON output works."""
        registry.create_review(sample_review)
        output = registry.to_json()
        parsed = json.loads(output)
        assert len(parsed) == 1
        assert parsed[0]["plan_id"] == "plan-001"
        assert parsed[0]["decision"] == "proposed"

    def test_name_filter(self, registry):
        """Name filter works."""
        registry.create_review(PlanReview(plan_id="p1", plan_name="Walls validation"))
        registry.create_review(PlanReview(plan_id="p2", plan_name="Floors validation"))
        registry.create_review(PlanReview(plan_id="p3", plan_name="Grid creation"))

        results = registry.list_reviews(name_filter="validation")
        assert len(results) == 2
        assert all("validation" in r.plan_name.lower() for r in results)

    def test_status_filter(self, registry, sample_review):
        """Status filter works."""
        created = registry.create_review(sample_review)
        registry.close_review(created.review_id)

        open_reviews = registry.list_reviews(status_filter=PlanReviewStatus.OPEN)
        closed_reviews = registry.list_reviews(status_filter=PlanReviewStatus.CLOSED)
        assert len(open_reviews) == 0
        assert len(closed_reviews) == 1

    def test_close_review(self, registry, sample_review):
        """Closing a review changes status to closed."""
        created = registry.create_review(sample_review)
        assert registry.close_review(created.review_id) is True
        fetched = registry.get_review(created.review_id)
        assert fetched.status == PlanReviewStatus.CLOSED

    def test_close_nonexistent_returns_false(self, registry):
        assert registry.close_review("nonexistent") is False

    def test_supersede_review(self, registry):
        """Supersession links old → new."""
        r1 = PlanReview(plan_id="p1", plan_name="Plan v1")
        r2 = PlanReview(plan_id="p1", plan_name="Plan v2", decision=PlanReviewDecision.APPROVED)
        c1 = registry.create_review(r1)
        c2 = registry.create_review(r2)

        assert registry.supersede_review(c1.review_id, c2.review_id) is True
        old = registry.get_review(c1.review_id)
        assert old.decision == PlanReviewDecision.SUPERSEDED
        assert old.status == PlanReviewStatus.CLOSED
        assert old.superseded_by == c2.review_id

    def test_supersede_self_rejected(self, registry, sample_review):
        """Self-supersession is rejected."""
        created = registry.create_review(sample_review)
        assert registry.supersede_review(created.review_id, created.review_id) is False

    def test_review_count(self, registry):
        """Review count reflects total records."""
        assert registry.review_count() == 0
        registry.create_review(PlanReview(plan_id="p1", plan_name="Plan 1"))
        registry.create_review(PlanReview(plan_id="p2", plan_name="Plan 2"))
        assert registry.review_count() == 2

    def test_empty_plan_id_raises(self, registry):
        """Empty plan_id raises ValueError."""
        with pytest.raises(ValueError, match="plan_id"):
            registry.create_review(PlanReview(plan_id="", plan_name="T"))

    def test_empty_plan_name_raises(self, registry):
        """Empty plan_name raises ValueError."""
        with pytest.raises(ValueError, match="plan_name"):
            registry.create_review(PlanReview(plan_id="p1", plan_name=""))

    def test_evidence_persists(self, registry):
        """Evidence objects survive round-trip."""
        r = PlanReview(
            plan_id="p1",
            plan_name="Plan with evidence",
            evidence=[
                PlanReviewEvidence(evidence_type="bundle", evidence_path="/art/run-1"),
                PlanReviewEvidence(evidence_type="log", evidence_path="/art/run-1/log.txt"),
            ],
        )
        created = registry.create_review(r)
        fetched = registry.get_review(created.review_id)
        assert len(fetched.evidence) == 2
        assert fetched.evidence[0].evidence_type == "bundle"
        assert fetched.evidence[1].evidence_path == "/art/run-1/log.txt"

    def test_get_history(self, registry):
        """PlanReviewHistory aggregates correctly."""
        plan_id = "plan-hist"
        registry.create_review(PlanReview(plan_id=plan_id, plan_name="H", decision=PlanReviewDecision.PROPOSED))
        registry.create_review(PlanReview(plan_id=plan_id, plan_name="H", decision=PlanReviewDecision.DEFERRED, reason=PlanReviewReason.DEFERRED_PENDING))
        registry.create_review(PlanReview(plan_id=plan_id, plan_name="H", decision=PlanReviewDecision.APPROVED))

        h = registry.get_history(plan_id)
        assert h.plan_id == plan_id
        assert len(h.reviews) == 3
        assert h.latest_decision == PlanReviewDecision.APPROVED

    def test_no_execution_occurs(self, registry, sample_review):
        """Creating a review record does NOT trigger plan execution."""
        created = registry.create_review(sample_review)
        # The registry is governance only — no execution field, no side effects
        assert created.decision == PlanReviewDecision.PROPOSED
        assert not hasattr(created, "executed")
        assert not hasattr(created, "result")

    def test_deterministic_ordering(self, registry):
        """List ordering is deterministic: decision priority then name."""
        registry.create_review(PlanReview(plan_id="p1", plan_name="ZZZ Plan", decision=PlanReviewDecision.APPROVED))
        registry.create_review(PlanReview(plan_id="p2", plan_name="AAA Plan", decision=PlanReviewDecision.REJECTED))
        registry.create_review(PlanReview(plan_id="p3", plan_name="MMM Plan", decision=PlanReviewDecision.PROPOSED))

        results = registry.list_reviews()
        # approved (rank 0) first, then proposed (rank 1), then rejected (rank 4)
        assert results[0].decision == PlanReviewDecision.APPROVED
        assert results[1].decision == PlanReviewDecision.PROPOSED
        assert results[2].decision == PlanReviewDecision.REJECTED


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


class TestCLI:
    """CLI commands work end-to-end."""

    def _run(self, *args, env_db=None):
        import os

        env = os.environ.copy()
        if env_db:
            env["AXIOM_DB_PATH"] = env_db
        result = subprocess.run(
            [*_CLI, *args],
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
            env=env,
        )
        return result

    def test_plan_reviews_empty(self, tmp_path):
        db = str(tmp_path / "cli_test.db")
        result = self._run("plan-reviews", env_db=db)
        assert result.returncode == 0
        assert "No plan reviews" in result.stdout

    def test_plan_review_create_and_list(self, tmp_path):
        db = str(tmp_path / "cli_test.db")
        # Create
        result = self._run(
            "plan-review-create",
            "--plan-id", "plan-cli-001",
            "--plan-name", "CLI Test Plan",
            "--decision", "approved",
            "--reason", "human_validation",
            "--json-output",
            env_db=db,
        )
        assert result.returncode == 0
        created = json.loads(result.stdout)
        assert created["decision"] == "approved"
        assert created["plan_id"] == "plan-cli-001"

        # List
        result = self._run("plan-reviews", "--json-output", env_db=db)
        assert result.returncode == 0
        reviews = json.loads(result.stdout)
        assert len(reviews) == 1
        assert reviews[0]["plan_name"] == "CLI Test Plan"

    def test_plan_review_show(self, tmp_path):
        db = str(tmp_path / "cli_test.db")
        self._run(
            "plan-review-create",
            "--plan-id", "plan-show-001",
            "--plan-name", "Show Plan",
            "--decision", "rejected",
            "--reason", "unsafe",
            env_db=db,
        )
        result = self._run("plan-review", "--plan-id", "plan-show-001", "--json-output", env_db=db)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["plan_id"] == "plan-show-001"
        assert data["latest_decision"] == "rejected"
        assert data["review_count"] == 1

    def test_plan_review_unknown_plan_id(self, tmp_path):
        db = str(tmp_path / "cli_test.db")
        result = self._run("plan-review", "--plan-id", "nonexistent", env_db=db)
        assert result.returncode == 2

    def test_plan_reviews_unknown_plan_id_json_exits_2(self, tmp_path):
        """JSON mode also exits 2 for unknown plan IDs (consistency)."""
        db = str(tmp_path / "cli_test.db")
        result = self._run("plan-reviews", "--plan-id", "nonexistent", "--json-output", env_db=db)
        assert result.returncode == 2
        data = json.loads(result.stdout)
        assert data["review_count"] == 0

    def test_plan_review_create_invalid_decision(self, tmp_path):
        db = str(tmp_path / "cli_test.db")
        result = self._run(
            "plan-review-create",
            "--plan-id", "plan-bad",
            "--decision", "invalid_value",
            "--reason", "human_validation",
            env_db=db,
        )
        assert result.returncode == 1
        assert "Unknown decision" in result.stdout

    def test_plan_review_create_invalid_reason(self, tmp_path):
        db = str(tmp_path / "cli_test.db")
        result = self._run(
            "plan-review-create",
            "--plan-id", "plan-bad",
            "--decision", "approved",
            "--reason", "bad_reason",
            env_db=db,
        )
        assert result.returncode == 1
        assert "Unknown reason" in result.stdout

    def test_cli_decision_filter(self, tmp_path):
        db = str(tmp_path / "cli_test.db")
        self._run("plan-review-create", "--plan-id", "p1", "--plan-name", "A", "--decision", "approved", "--reason", "human_validation", env_db=db)
        self._run("plan-review-create", "--plan-id", "p2", "--plan-name", "B", "--decision", "rejected", "--reason", "unsafe", env_db=db)

        result = self._run("plan-reviews", "--decision", "approved", "--json-output", env_db=db)
        assert result.returncode == 0
        reviews = json.loads(result.stdout)
        assert len(reviews) == 1
        assert reviews[0]["decision"] == "approved"

    def test_cli_status_filter(self, tmp_path):
        db = str(tmp_path / "cli_test.db")
        self._run("plan-review-create", "--plan-id", "p1", "--plan-name", "A", "--decision", "proposed", "--reason", "human_validation", env_db=db)

        result = self._run("plan-reviews", "--status", "open", "--json-output", env_db=db)
        assert result.returncode == 0
        reviews = json.loads(result.stdout)
        assert len(reviews) == 1
        assert reviews[0]["status"] == "open"

    def test_plan_name_defaults_to_plan_id(self, tmp_path):
        """If --plan-name is omitted, defaults to plan-id."""
        db = str(tmp_path / "cli_test.db")
        result = self._run(
            "plan-review-create",
            "--plan-id", "plan-no-name",
            "--decision", "proposed",
            "--reason", "human_validation",
            "--json-output",
            env_db=db,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["plan_name"] == "plan-no-name"
