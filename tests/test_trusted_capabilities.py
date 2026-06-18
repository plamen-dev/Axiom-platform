"""Tests for Trusted Capability Registry (PR #54).

Acceptance criteria:
- trusted capabilities persist
- promotion requires explicit action
- failed capabilities block promotion
- revocation works
- trust history preserved
- JSON output valid
"""

import json
import os
import subprocess
import sys

import pytest
from axiom_core.trusted_capabilities import (
    TrustAction,
    TrustedCapability,
    TrustedCapabilityRegistry,
    TrustEvidence,
    TrustHistory,
    TrustRevocation,
    TrustStatus,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path):
    return str(tmp_path / "test_trust.db")


@pytest.fixture()
def registry(tmp_db):
    os.environ["AXIOM_DB_PATH"] = tmp_db
    reg = TrustedCapabilityRegistry(db_path=tmp_db)
    yield reg
    os.environ.pop("AXIOM_DB_PATH", None)


# ---------------------------------------------------------------------------
# TestEnums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_trust_status_values(self):
        assert TrustStatus.UNKNOWN.value == "unknown"
        assert TrustStatus.ELIGIBLE.value == "eligible"
        assert TrustStatus.TRUSTED.value == "trusted"
        assert TrustStatus.REVOKED.value == "revoked"
        assert TrustStatus.BLOCKED.value == "blocked"

    def test_trust_action_values(self):
        assert TrustAction.PROMOTED.value == "promoted"
        assert TrustAction.REVOKED.value == "revoked"
        assert TrustAction.BLOCKED.value == "blocked"
        assert TrustAction.ELIGIBILITY_GRANTED.value == "eligibility_granted"
        assert TrustAction.VALIDATION_PASSED.value == "validation_passed"
        assert TrustAction.VALIDATION_FAILED.value == "validation_failed"


# ---------------------------------------------------------------------------
# TestTrustEvidence
# ---------------------------------------------------------------------------


class TestTrustEvidence:
    def test_defaults(self):
        ev = TrustEvidence()
        assert ev.evidence_type == ""
        assert ev.timestamp

    def test_to_dict_roundtrip(self):
        ev = TrustEvidence(
            evidence_type="validation_pass",
            reference_id="run-001",
            description="Grid validation passed",
        )
        d = ev.to_dict()
        restored = TrustEvidence.from_dict(d)
        assert restored.evidence_type == "validation_pass"
        assert restored.reference_id == "run-001"


# ---------------------------------------------------------------------------
# TestTrustRevocation
# ---------------------------------------------------------------------------


class TestTrustRevocation:
    def test_to_dict(self):
        rev = TrustRevocation(
            capability_name="CreateGrids",
            revoked_by="admin",
            reason="Flaky in production",
        )
        d = rev.to_dict()
        assert d["capability_name"] == "CreateGrids"
        assert d["revoked_by"] == "admin"
        assert d["reason"] == "Flaky in production"


# ---------------------------------------------------------------------------
# TestTrustHistory
# ---------------------------------------------------------------------------


class TestTrustHistory:
    def test_empty(self):
        h = TrustHistory(capability_name="X")
        d = h.to_dict()
        assert d["event_count"] == 0

    def test_with_events(self):
        h = TrustHistory(
            capability_name="CreateGrids",
            events=[
                {"action": "promoted", "actor": "human"},
                {"action": "revoked", "actor": "admin"},
            ],
        )
        assert h.to_dict()["event_count"] == 2


# ---------------------------------------------------------------------------
# TestTrustedCapability
# ---------------------------------------------------------------------------


class TestTrustedCapability:
    def test_defaults(self):
        cap = TrustedCapability(capability_name="CreateGrids")
        assert cap.trust_status == TrustStatus.UNKNOWN
        assert cap.validation_count == 0
        assert cap.failure_count == 0

    def test_string_status_parsed(self):
        cap = TrustedCapability(capability_name="X", trust_status="trusted")
        assert cap.trust_status == TrustStatus.TRUSTED

    def test_invalid_status_defaults_unknown(self):
        cap = TrustedCapability(capability_name="X", trust_status="invalid")
        assert cap.trust_status == TrustStatus.UNKNOWN

    def test_to_dict(self):
        cap = TrustedCapability(
            capability_name="CreateGrids",
            trust_status=TrustStatus.TRUSTED,
            promoted_by="admin",
        )
        d = cap.to_dict()
        assert d["trust_status"] == "trusted"
        assert d["promoted_by"] == "admin"

    def test_to_json_valid(self):
        cap = TrustedCapability(capability_name="CreateLevels")
        j = cap.to_json()
        parsed = json.loads(j)
        assert parsed["capability_name"] == "CreateLevels"


# ---------------------------------------------------------------------------
# TestTrustedCapabilityRegistry
# ---------------------------------------------------------------------------


class TestTrustedCapabilityRegistry:
    def test_empty_registry(self, registry):
        assert registry.capability_count() == 0
        assert registry.list_capabilities() == []

    def test_get_unknown_returns_none(self, registry):
        assert registry.get_capability("Nonexistent") is None

    def test_promote_creates_trusted(self, registry):
        """Promotion requires explicit action — creates trusted status."""
        registry.record_validation("CreateGrids", passed=True)
        cap = registry.promote("CreateGrids", promoted_by="admin")
        assert cap.trust_status == TrustStatus.TRUSTED
        assert cap.promoted_by == "admin"
        assert cap.promoted_at is not None

    def test_promoted_capability_persists(self, registry):
        """Trusted capabilities persist across queries."""
        registry.record_validation("CreateGrids", passed=True)
        registry.promote("CreateGrids")
        retrieved = registry.get_capability("CreateGrids")
        assert retrieved is not None
        assert retrieved.trust_status == TrustStatus.TRUSTED

    def test_promote_blocked_capability_fails(self, registry):
        """Mutation/high-risk capabilities cannot be promoted."""
        with pytest.raises(ValueError, match="blocked"):
            registry.promote("SetParameterValue")

    def test_promote_delete_elements_fails(self, registry):
        with pytest.raises(ValueError, match="blocked"):
            registry.promote("DeleteElements")

    def test_promote_move_elements_fails(self, registry):
        with pytest.raises(ValueError, match="blocked"):
            registry.promote("MoveElements")

    def test_promote_rotate_elements_fails(self, registry):
        with pytest.raises(ValueError, match="blocked"):
            registry.promote("RotateElements")

    def test_promote_create_walls_fails(self, registry):
        with pytest.raises(ValueError, match="blocked"):
            registry.promote("CreateWalls")

    def test_failed_capability_blocks_promotion(self, registry):
        """Capabilities with failures cannot be promoted."""
        registry.record_validation("FlakyCap", passed=False)
        with pytest.raises(ValueError, match="failure"):
            registry.promote("FlakyCap")

    def test_revocation_works(self, registry):
        """Revocation changes status to revoked."""
        registry.record_validation("CreateGrids", passed=True)
        registry.promote("CreateGrids")
        cap = registry.revoke("CreateGrids", revoked_by="admin", reason="Flaky")
        assert cap is not None
        assert cap.trust_status == TrustStatus.REVOKED
        assert cap.revoked_by == "admin"
        assert cap.revocation_reason == "Flaky"

    def test_revoke_unknown_returns_none(self, registry):
        assert registry.revoke("Unknown") is None

    def test_history_preserved_on_promote(self, registry):
        """Trust history records promotion events."""
        registry.record_validation("CreateGrids", passed=True)
        registry.promote("CreateGrids")
        history = registry.get_history("CreateGrids")
        assert len(history.events) == 2
        assert history.events[1]["action"] == "promoted"

    def test_history_preserved_on_revoke(self, registry):
        """Trust history records revocation events."""
        registry.record_validation("CreateGrids", passed=True)
        registry.promote("CreateGrids")
        registry.revoke("CreateGrids", reason="Test")
        history = registry.get_history("CreateGrids")
        assert len(history.events) == 3
        assert history.events[2]["action"] == "revoked"

    def test_history_preserved_on_validation(self, registry):
        """Trust history records validation events."""
        registry.record_validation("CreateGrids", passed=True)
        registry.record_validation("CreateGrids", passed=False)
        history = registry.get_history("CreateGrids")
        assert len(history.events) == 2
        assert history.events[0]["action"] == "validation_passed"
        assert history.events[1]["action"] == "validation_failed"

    def test_record_validation_pass_grants_eligibility(self, registry):
        """Passing validation grants eligibility."""
        cap = registry.record_validation("CreateGrids", passed=True)
        assert cap.trust_status == TrustStatus.ELIGIBLE
        assert cap.validation_count == 1

    def test_record_validation_fail_increments_failures(self, registry):
        """Failed validation increments failure count."""
        cap = registry.record_validation("CreateGrids", passed=False)
        assert cap.failure_count == 1

    def test_record_validation_with_evidence(self, registry):
        """Evidence is stored with validation records."""
        ev = TrustEvidence(evidence_type="run", reference_id="run-1")
        cap = registry.record_validation("CreateGrids", passed=True, evidence=ev)
        assert len(cap.evidence) == 1
        assert cap.evidence[0].reference_id == "run-1"

    def test_list_capabilities_with_filter(self, registry):
        """Status filter works correctly."""
        registry.record_validation("CreateGrids", passed=True)
        registry.promote("CreateGrids")
        registry.record_validation("CreateLevels", passed=True)
        trusted = registry.list_capabilities(status_filter=TrustStatus.TRUSTED)
        assert len(trusted) == 1
        assert trusted[0].capability_name == "CreateGrids"

    def test_promote_with_evidence(self, registry):
        """Evidence can be attached during promotion."""
        registry.record_validation("CreateGrids", passed=True)
        ev = TrustEvidence(evidence_type="review", description="Human approved")
        cap = registry.promote("CreateGrids", evidence=[ev])
        assert len(cap.evidence) >= 1
        assert any(e.evidence_type == "review" for e in cap.evidence)

    def test_re_promote_after_revoke(self, registry):
        """Re-promotion after revocation clears revocation fields."""
        registry.record_validation("CreateGrids", passed=True)
        registry.promote("CreateGrids")
        registry.revoke("CreateGrids", reason="Test")
        cap = registry.promote("CreateGrids")
        assert cap.trust_status == TrustStatus.TRUSTED
        assert cap.revoked_by is None
        assert cap.revoked_at is None

    def test_capability_count(self, registry):
        registry.record_validation("CreateGrids", passed=True)
        registry.promote("CreateGrids")
        registry.record_validation("CreateLevels", passed=True)
        assert registry.capability_count() == 2

    def test_json_output_valid(self, registry):
        """JSON output is valid and complete."""
        registry.record_validation("CreateGrids", passed=True)
        registry.promote("CreateGrids", promoted_by="tester")
        cap = registry.get_capability("CreateGrids")
        j = cap.to_json()
        parsed = json.loads(j)
        assert parsed["capability_name"] == "CreateGrids"
        assert parsed["trust_status"] == "trusted"
        assert parsed["promoted_by"] == "tester"

    def test_promote_unknown_capability_rejected(self, registry):
        """Promoting unregistered capability must fail (regression)."""
        with pytest.raises(ValueError, match="not registered"):
            registry.promote("NeverSeen")

    def test_promote_unknown_status_rejected(self, registry):
        """Promoting from UNKNOWN status must fail — need ELIGIBLE first (regression).

        We use a capability that has been seen (via a passed then revoked flow)
        so failure_count is 0 but status is not ELIGIBLE.
        """
        registry.record_validation("SomeCap", passed=True)
        # Status is now ELIGIBLE — revoke to get REVOKED; then promote to TRUSTED;
        # then revoke again. This tests the governance flow.
        # Simpler: just check that UNKNOWN status is rejected via promote on a
        # freshly registered UNKNOWN row.
        # Since record_validation(passed=False) creates UNKNOWN, but also adds
        # failure_count, we test the status check with a direct insert.
        from axiom_core.database import get_session
        from axiom_core.trusted_capabilities import TrustedCapabilityRow

        sf = registry._session_factory
        with get_session(sf) as session:
            row = TrustedCapabilityRow(
                capability_name="DirectInsert",
                trust_status="unknown",
                validation_count=0,
                failure_count=0,
                created_at="2025-01-01T00:00:00+00:00",
                updated_at="2025-01-01T00:00:00+00:00",
            )
            session.add(row)
        with pytest.raises(ValueError, match="must be ELIGIBLE"):
            registry.promote("DirectInsert")

    def test_blocked_capability_never_becomes_eligible(self, registry):
        """Blocked/mutation capabilities must never get ELIGIBLE status (regression)."""
        cap = registry.record_validation("SetParameterValue", passed=True)
        assert cap.trust_status == TrustStatus.BLOCKED
        assert cap.validation_count == 1

    def test_blocked_capability_existing_row_stays_blocked(self, registry):
        """Existing blocked capability stays blocked on passing validation."""
        registry.record_validation("DeleteElements", passed=False)
        cap = registry.record_validation("DeleteElements", passed=True)
        assert cap.trust_status != TrustStatus.ELIGIBLE


# ---------------------------------------------------------------------------
# TestCLI
# ---------------------------------------------------------------------------


class TestCLI:
    @staticmethod
    def _run(*args: str, env_db: str | None = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        if env_db:
            env["AXIOM_DB_PATH"] = env_db
        return subprocess.run(
            [sys.executable, "-m", "axiom_cli.main", *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

    def test_list_empty(self, tmp_path):
        db = str(tmp_path / "cli.db")
        result = self._run("trusted-capabilities", "--json-output", env_db=db)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data == []

    def test_unknown_capability_exits_2(self, tmp_path):
        db = str(tmp_path / "cli.db")
        result = self._run(
            "trusted-capability", "--name", "Unknown", "--json-output", env_db=db
        )
        assert result.returncode == 2
        data = json.loads(result.stdout)
        assert data["error"] == "not_found"

    @staticmethod
    def _seed_eligible(db: str, capability: str) -> None:
        """Record a passing validation so the capability becomes ELIGIBLE."""
        from axiom_core.trusted_capabilities import TrustedCapabilityRegistry

        reg = TrustedCapabilityRegistry(db_path=db)
        reg.record_validation(capability, passed=True)

    def test_promote_via_cli(self, tmp_path):
        db = str(tmp_path / "cli.db")
        self._seed_eligible(db, "CreateGrids")
        result = self._run(
            "trusted-capability-promote",
            "--capability", "CreateGrids",
            "--json-output",
            env_db=db,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["trust_status"] == "trusted"
        assert data["capability_name"] == "CreateGrids"

    def test_promote_blocked_via_cli(self, tmp_path):
        db = str(tmp_path / "cli.db")
        result = self._run(
            "trusted-capability-promote",
            "--capability", "SetParameterValue",
            "--json-output",
            env_db=db,
        )
        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert data["error"] == "promotion_refused"

    def test_revoke_via_cli(self, tmp_path):
        db = str(tmp_path / "cli.db")
        self._seed_eligible(db, "CreateGrids")
        # First promote
        self._run(
            "trusted-capability-promote",
            "--capability", "CreateGrids",
            env_db=db,
        )
        # Then revoke
        result = self._run(
            "trusted-capability-revoke",
            "--capability", "CreateGrids",
            "--reason", "Flaky",
            "--json-output",
            env_db=db,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["trust_status"] == "revoked"
        assert data["revocation_reason"] == "Flaky"

    def test_revoke_unknown_exits_2(self, tmp_path):
        db = str(tmp_path / "cli.db")
        result = self._run(
            "trusted-capability-revoke",
            "--capability", "Nonexistent",
            "--json-output",
            env_db=db,
        )
        assert result.returncode == 2

    def test_list_after_promote(self, tmp_path):
        db = str(tmp_path / "cli.db")
        self._seed_eligible(db, "CreateGrids")
        self._run(
            "trusted-capability-promote",
            "--capability", "CreateGrids",
            env_db=db,
        )
        result = self._run("trusted-capabilities", "--json-output", env_db=db)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) == 1
        assert data[0]["capability_name"] == "CreateGrids"

    def test_filter_by_status(self, tmp_path):
        db = str(tmp_path / "cli.db")
        self._seed_eligible(db, "CreateGrids")
        self._run(
            "trusted-capability-promote", "--capability", "CreateGrids", env_db=db
        )
        # Filter for revoked — should be empty
        result = self._run(
            "trusted-capabilities", "--status", "revoked", "--json-output", env_db=db
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data == []
