"""Tests for Controlled Discovery Loop (PR #55).

Acceptance criteria:
- loop works in simulate mode
- candidates generated
- validation requests generated
- validations executed safely
- unsafe paths refused
- evidence always written
- promotion checks generated but never applied
"""

import json
import os
import subprocess
import sys

import pytest
from axiom_core.controlled_discovery_loop import (
    ControlledDiscoveryLoop,
    DiscoveryLoopEvidence,
    DiscoveryLoopResult,
    DiscoveryLoopStep,
    LoopStatus,
    LoopStepType,
    StepOutcome,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path):
    return str(tmp_path / "test_loop.db")


@pytest.fixture()
def loop(tmp_db):
    os.environ["AXIOM_DB_PATH"] = tmp_db
    lp = ControlledDiscoveryLoop(db_path=tmp_db)
    yield lp
    os.environ.pop("AXIOM_DB_PATH", None)


# ---------------------------------------------------------------------------
# TestEnums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_loop_status_values(self):
        assert LoopStatus.PENDING.value == "pending"
        assert LoopStatus.RUNNING.value == "running"
        assert LoopStatus.SIMULATED.value == "simulated"
        assert LoopStatus.COMPLETED.value == "completed"
        assert LoopStatus.FAILED.value == "failed"
        assert LoopStatus.REFUSED.value == "refused"

    def test_loop_step_type_values(self):
        assert LoopStepType.DISCOVERY.value == "discovery"
        assert LoopStepType.CANDIDATE_GENERATION.value == "candidate_generation"
        assert LoopStepType.STATE_UPDATE.value == "state_update"
        assert LoopStepType.VALIDATION_REQUEST.value == "validation_request"
        assert LoopStepType.VALIDATION_EXECUTION.value == "validation_execution"
        assert LoopStepType.CLASSIFICATION.value == "classification"
        assert LoopStepType.PROMOTION_CHECK.value == "promotion_check"

    def test_step_outcome_values(self):
        assert StepOutcome.PASSED.value == "passed"
        assert StepOutcome.FAILED.value == "failed"
        assert StepOutcome.SKIPPED.value == "skipped"
        assert StepOutcome.REFUSED.value == "refused"
        assert StepOutcome.NOT_RUN.value == "not_run"


# ---------------------------------------------------------------------------
# TestDiscoveryLoopStep
# ---------------------------------------------------------------------------


class TestDiscoveryLoopStep:
    def test_defaults(self):
        step = DiscoveryLoopStep()
        assert step.step_id
        assert step.outcome == StepOutcome.NOT_RUN
        assert step.step_type == LoopStepType.DISCOVERY

    def test_to_dict_roundtrip(self):
        step = DiscoveryLoopStep(
            step_id="s1",
            sequence=1,
            step_type=LoopStepType.CLASSIFICATION,
            title="Classify",
            outcome=StepOutcome.PASSED,
            duration_ms=100,
        )
        d = step.to_dict()
        restored = DiscoveryLoopStep.from_dict(d)
        assert restored.step_type == LoopStepType.CLASSIFICATION
        assert restored.outcome == StepOutcome.PASSED

    def test_string_step_type_parsed(self):
        step = DiscoveryLoopStep(step_type="promotion_check")
        assert step.step_type == LoopStepType.PROMOTION_CHECK

    def test_invalid_step_type_defaults(self):
        step = DiscoveryLoopStep(step_type="invalid")
        assert step.step_type == LoopStepType.DISCOVERY


# ---------------------------------------------------------------------------
# TestDiscoveryLoopEvidence
# ---------------------------------------------------------------------------


class TestDiscoveryLoopEvidence:
    def test_defaults(self):
        ev = DiscoveryLoopEvidence()
        assert ev.evidence_type == ""

    def test_to_dict_roundtrip(self):
        ev = DiscoveryLoopEvidence(
            evidence_type="loop_summary",
            path="/artifacts/run1/loop_summary.md",
            description="Loop completed",
            step_id="s1",
        )
        d = ev.to_dict()
        restored = DiscoveryLoopEvidence.from_dict(d)
        assert restored.path == "/artifacts/run1/loop_summary.md"


# ---------------------------------------------------------------------------
# TestDiscoveryLoopResult
# ---------------------------------------------------------------------------


class TestDiscoveryLoopResult:
    def test_defaults(self):
        r = DiscoveryLoopResult()
        assert r.run_id
        assert r.status == LoopStatus.PENDING
        assert r.promotions_applied == 0

    def test_step_count(self):
        r = DiscoveryLoopResult(
            steps=[DiscoveryLoopStep(sequence=1), DiscoveryLoopStep(sequence=2)]
        )
        assert r.step_count == 2

    def test_to_json_valid(self):
        r = DiscoveryLoopResult(source="test")
        j = r.to_json()
        parsed = json.loads(j)
        assert parsed["source"] == "test"
        assert "promotions_applied" in parsed


# ---------------------------------------------------------------------------
# TestControlledDiscoveryLoop
# ---------------------------------------------------------------------------


class TestControlledDiscoveryLoop:
    def test_simulate_mode_works(self, loop):
        """Loop works in simulate mode."""
        result = loop.run(source="test_folder", simulate=True)
        assert result.status == LoopStatus.SIMULATED
        assert result.simulate is True
        assert all(s.outcome == StepOutcome.PASSED for s in result.steps)
        assert all(s.notes == "simulated" for s in result.steps)

    def test_simulate_mode_reports_zero_validations_executed(self, loop):
        """In simulate mode, validations_executed must be 0 (regression)."""
        result = loop.run(
            source="test_folder",
            candidates=["cap1", "cap2"],
            simulate=True,
        )
        assert result.simulate is True
        assert result.validations_requested == 2
        assert result.validations_executed == 0

    def test_normal_mode_completes(self, loop):
        """Loop completes in normal (controlled) mode."""
        result = loop.run(source="test_folder", simulate=False)
        assert result.status == LoopStatus.COMPLETED
        assert result.step_count == 7

    def test_candidates_generated(self, loop):
        """Candidates are generated during the loop."""
        result = loop.run(candidates=["cap1", "cap2", "cap3"])
        assert result.candidates_generated == 3

    def test_validation_requests_generated(self, loop):
        """Validation requests are generated."""
        result = loop.run(candidates=["cap1", "cap2"])
        assert result.validations_requested == 2

    def test_validations_executed_safely(self, loop):
        """Safe validations execute."""
        result = loop.run(
            required_capabilities=["CreateGrids", "CreateLevels"],
            candidates=["cap1"],
        )
        assert result.status == LoopStatus.COMPLETED
        assert result.validations_executed == 1

    def test_unsafe_capability_refused(self, loop):
        """Unsafe paths (mutation capabilities) are refused."""
        result = loop.run(required_capabilities=["SetParameterValue"])
        assert result.status == LoopStatus.REFUSED
        assert "SetParameterValue" in result.refusal_reason

    def test_unsafe_procedure_refused(self, loop):
        """Unsafe procedures are refused."""
        result = loop.run(procedures=["unbounded_inventory_scan"])
        assert result.status == LoopStatus.REFUSED
        assert "unbounded_inventory_scan" in result.refusal_reason

    def test_delete_elements_refused(self, loop):
        result = loop.run(required_capabilities=["DeleteElements"])
        assert result.status == LoopStatus.REFUSED

    def test_evidence_always_written_on_success(self, loop):
        """Evidence is always written on successful runs."""
        result = loop.run(simulate=True)
        assert len(result.evidence) >= 1
        assert any(e.evidence_type == "loop_summary" for e in result.evidence)

    def test_evidence_always_written_on_refusal(self, loop):
        """Evidence is written even on refused runs."""
        result = loop.run(required_capabilities=["SetParameterValue"])
        assert len(result.evidence) >= 1
        assert any(e.evidence_type == "loop_refused" for e in result.evidence)

    def test_promotion_checks_generated(self, loop):
        """Promotion checks are generated."""
        result = loop.run(candidates=["cap1", "cap2"])
        assert result.promotions_checked == 2

    def test_promotions_never_applied(self, loop):
        """Promotions are NEVER applied — key invariant."""
        result = loop.run(candidates=["cap1", "cap2", "cap3"])
        assert result.promotions_applied == 0

    def test_promotions_never_applied_large(self, loop):
        """Even with many candidates, promotions are never applied."""
        result = loop.run(candidates=[f"cap{i}" for i in range(20)])
        assert result.promotions_applied == 0
        assert result.promotions_checked == 20

    def test_persistence(self, loop):
        """Runs are persisted and retrievable."""
        result = loop.run(source="persist_test", simulate=True)
        retrieved = loop.get_run(result.run_id)
        assert retrieved is not None
        assert retrieved.source == "persist_test"
        assert retrieved.status == LoopStatus.SIMULATED

    def test_get_unknown_returns_none(self, loop):
        assert loop.get_run("nonexistent") is None

    def test_list_runs(self, loop):
        loop.run(simulate=True)
        loop.run(required_capabilities=["SetParameterValue"])
        all_runs = loop.list_runs()
        assert len(all_runs) == 2

    def test_list_runs_with_filter(self, loop):
        loop.run(simulate=True)
        loop.run(required_capabilities=["SetParameterValue"])
        refused = loop.list_runs(status_filter=LoopStatus.REFUSED)
        assert len(refused) == 1

    def test_run_count(self, loop):
        assert loop.run_count() == 0
        loop.run(simulate=True)
        assert loop.run_count() == 1

    def test_all_7_step_types_present(self, loop):
        """Full loop includes all 7 step types."""
        result = loop.run(simulate=True)
        step_types = {s.step_type for s in result.steps}
        assert LoopStepType.DISCOVERY in step_types
        assert LoopStepType.CANDIDATE_GENERATION in step_types
        assert LoopStepType.STATE_UPDATE in step_types
        assert LoopStepType.VALIDATION_REQUEST in step_types
        assert LoopStepType.VALIDATION_EXECUTION in step_types
        assert LoopStepType.CLASSIFICATION in step_types
        assert LoopStepType.PROMOTION_CHECK in step_types

    def test_json_output_valid(self, loop):
        """JSON output is valid and complete."""
        result = loop.run(source="json_test", simulate=True)
        j = result.to_json()
        parsed = json.loads(j)
        assert parsed["status"] == "simulated"
        assert parsed["promotions_applied"] == 0
        assert "steps" in parsed
        assert "evidence" in parsed

    def test_metadata_preserved(self, loop):
        """Custom metadata is preserved."""
        result = loop.run(metadata={"version": "v1", "tag": "test"})
        retrieved = loop.get_run(result.run_id)
        assert retrieved.metadata["version"] == "v1"


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

    def test_simulate_mode_via_cli(self, tmp_path):
        db = str(tmp_path / "cli.db")
        result = self._run(
            "discovery-loop", "--simulate", "--json-output", env_db=db
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["status"] == "simulated"
        assert data["promotions_applied"] == 0

    def test_normal_mode_via_cli(self, tmp_path):
        db = str(tmp_path / "cli.db")
        result = self._run(
            "discovery-loop", "--json-output", env_db=db
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["status"] == "completed"
        assert data["promotions_applied"] == 0

    def test_with_source(self, tmp_path):
        db = str(tmp_path / "cli.db")
        result = self._run(
            "discovery-loop", "--source", "my_folder", "--json-output", env_db=db
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["source"] == "my_folder"

    def test_evidence_in_output(self, tmp_path):
        db = str(tmp_path / "cli.db")
        result = self._run(
            "discovery-loop", "--simulate", "--json-output", env_db=db
        )
        data = json.loads(result.stdout)
        assert len(data["evidence"]) >= 1
