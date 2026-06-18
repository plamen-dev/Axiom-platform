"""Tests for Controlled Validation Orchestrator (PR #53).

Acceptance criteria:
- approved requests run
- unsafe requests refused
- blocked requests handled
- evidence always written
- JSON valid
- no mutations
"""

import json
import os
import subprocess
import sys

import pytest
from axiom_core.validation_orchestrator import (
    ControlledValidationOrchestrator,
    OrchestrationStatus,
    StepResult,
    ValidationOrchestrationEvidence,
    ValidationOrchestrationResult,
    ValidationOrchestrationStep,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path):
    return str(tmp_path / "test_orch.db")


@pytest.fixture()
def orchestrator(tmp_db):
    os.environ["AXIOM_DB_PATH"] = tmp_db
    orch = ControlledValidationOrchestrator(db_path=tmp_db)
    yield orch
    os.environ.pop("AXIOM_DB_PATH", None)


# ---------------------------------------------------------------------------
# TestEnums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_orchestration_status_values(self):
        assert OrchestrationStatus.PENDING.value == "pending"
        assert OrchestrationStatus.SIMULATED.value == "simulated"
        assert OrchestrationStatus.RUNNING.value == "running"
        assert OrchestrationStatus.COMPLETED.value == "completed"
        assert OrchestrationStatus.FAILED.value == "failed"
        assert OrchestrationStatus.REFUSED.value == "refused"

    def test_step_result_values(self):
        assert StepResult.PASSED.value == "passed"
        assert StepResult.FAILED.value == "failed"
        assert StepResult.SKIPPED.value == "skipped"
        assert StepResult.REFUSED.value == "refused"
        assert StepResult.NOT_RUN.value == "not_run"


# ---------------------------------------------------------------------------
# TestValidationOrchestrationStep
# ---------------------------------------------------------------------------


class TestValidationOrchestrationStep:
    def test_defaults(self):
        step = ValidationOrchestrationStep()
        assert step.step_id
        assert step.result == StepResult.NOT_RUN

    def test_to_dict_roundtrip(self):
        step = ValidationOrchestrationStep(
            step_id="s1",
            sequence=1,
            title="Run grids",
            procedure="evidence_run",
            result=StepResult.PASSED,
            duration_ms=150,
        )
        d = step.to_dict()
        restored = ValidationOrchestrationStep.from_dict(d)
        assert restored.step_id == "s1"
        assert restored.result == StepResult.PASSED
        assert restored.duration_ms == 150


# ---------------------------------------------------------------------------
# TestValidationOrchestrationEvidence
# ---------------------------------------------------------------------------


class TestValidationOrchestrationEvidence:
    def test_defaults(self):
        ev = ValidationOrchestrationEvidence()
        assert ev.evidence_type == ""

    def test_to_dict_roundtrip(self):
        ev = ValidationOrchestrationEvidence(
            evidence_type="pass_fail",
            path="/artifacts/run1/pass_fail.json",
            description="Pass/fail result",
            step_id="s1",
        )
        d = ev.to_dict()
        restored = ValidationOrchestrationEvidence.from_dict(d)
        assert restored.path == "/artifacts/run1/pass_fail.json"
        assert restored.step_id == "s1"


# ---------------------------------------------------------------------------
# TestValidationOrchestrationResult
# ---------------------------------------------------------------------------


class TestValidationOrchestrationResult:
    def test_defaults(self):
        r = ValidationOrchestrationResult(request_id="req-1")
        assert r.run_id
        assert r.status == OrchestrationStatus.PENDING
        assert r.step_count == 0

    def test_to_dict(self):
        r = ValidationOrchestrationResult(
            request_id="req-1",
            status=OrchestrationStatus.COMPLETED,
            steps=[ValidationOrchestrationStep(sequence=1, title="S1", result=StepResult.PASSED)],
        )
        d = r.to_dict()
        assert d["status"] == "completed"
        assert d["step_count"] == 1
        assert d["passed_count"] == 1

    def test_to_json(self):
        r = ValidationOrchestrationResult(request_id="req-1")
        j = r.to_json()
        parsed = json.loads(j)
        assert parsed["request_id"] == "req-1"


# ---------------------------------------------------------------------------
# TestControlledValidationOrchestrator
# ---------------------------------------------------------------------------


class TestControlledValidationOrchestrator:
    def test_empty_request_id_raises(self, orchestrator):
        with pytest.raises(ValueError, match="request_id"):
            orchestrator.orchestrate(request_id="")

    def test_safe_request_completes(self, orchestrator):
        """Approved safe requests run to completion."""
        step = ValidationOrchestrationStep(sequence=1, title="Validate grids")
        result = orchestrator.orchestrate(
            request_id="req-001",
            steps=[step],
            required_capabilities=["CreateGrids"],
        )
        assert result.status == OrchestrationStatus.COMPLETED
        assert result.passed_count == 1
        assert len(result.evidence) > 0

    def test_simulate_mode(self, orchestrator):
        """Simulate mode marks steps passed without execution."""
        step = ValidationOrchestrationStep(sequence=1, title="Check levels")
        result = orchestrator.orchestrate(
            request_id="req-002",
            steps=[step],
            simulate=True,
        )
        assert result.status == OrchestrationStatus.SIMULATED
        assert result.simulate is True
        assert result.steps[0].notes == "simulated"

    def test_unsafe_capability_refused(self, orchestrator):
        """Mutation capabilities are refused."""
        step = ValidationOrchestrationStep(sequence=1, title="Set param")
        result = orchestrator.orchestrate(
            request_id="req-003",
            steps=[step],
            required_capabilities=["SetParameterValue"],
        )
        assert result.status == OrchestrationStatus.REFUSED
        assert "SetParameterValue" in result.refusal_reason
        assert "mutation" in result.refusal_reason

    def test_unsafe_procedure_refused(self, orchestrator):
        """Unsafe procedures are refused."""
        step = ValidationOrchestrationStep(sequence=1, title="Full scan", procedure="unbounded_inventory_scan")
        result = orchestrator.orchestrate(
            request_id="req-004",
            steps=[step],
            procedures=["unbounded_inventory_scan"],
        )
        assert result.status == OrchestrationStatus.REFUSED
        assert "unbounded_inventory_scan" in result.refusal_reason

    def test_delete_elements_refused(self, orchestrator):
        """DeleteElements capability is refused."""
        result = orchestrator.orchestrate(
            request_id="req-005",
            required_capabilities=["DeleteElements"],
        )
        assert result.status == OrchestrationStatus.REFUSED

    def test_evidence_always_written(self, orchestrator):
        """Evidence is generated even for refused runs."""
        result = orchestrator.orchestrate(
            request_id="req-006",
            required_capabilities=["SetParameterValue"],
        )
        assert result.status == OrchestrationStatus.REFUSED
        # Refused runs don't produce step evidence but are persisted
        retrieved = orchestrator.get_run(result.run_id)
        assert retrieved is not None
        assert retrieved.status == OrchestrationStatus.REFUSED

    def test_evidence_written_on_success(self, orchestrator):
        """Successful runs produce evidence items."""
        step = ValidationOrchestrationStep(sequence=1, title="Check")
        result = orchestrator.orchestrate(
            request_id="req-007",
            steps=[step],
        )
        assert len(result.evidence) >= 1
        assert any(e.evidence_type == "orchestration_summary" for e in result.evidence)

    def test_get_run_persists(self, orchestrator):
        """Runs are persisted and retrievable."""
        step = ValidationOrchestrationStep(sequence=1, title="Grid check")
        result = orchestrator.orchestrate(
            request_id="req-008",
            steps=[step],
        )
        retrieved = orchestrator.get_run(result.run_id)
        assert retrieved is not None
        assert retrieved.request_id == "req-008"
        assert retrieved.status == OrchestrationStatus.COMPLETED

    def test_get_unknown_run_returns_none(self, orchestrator):
        assert orchestrator.get_run("nonexistent") is None

    def test_runs_for_request(self, orchestrator):
        """Multiple runs for same request are tracked."""
        orchestrator.orchestrate(request_id="req-multi", simulate=True)
        orchestrator.orchestrate(request_id="req-multi", simulate=True)
        runs = orchestrator.get_runs_for_request("req-multi")
        assert len(runs) == 2

    def test_list_runs(self, orchestrator):
        """List runs works with filter."""
        orchestrator.orchestrate(request_id="req-list-1", simulate=True)
        orchestrator.orchestrate(
            request_id="req-list-2",
            required_capabilities=["SetParameterValue"],
        )
        all_runs = orchestrator.list_runs()
        assert len(all_runs) == 2

        refused = orchestrator.list_runs(status_filter=OrchestrationStatus.REFUSED)
        assert len(refused) == 1
        assert refused[0].request_id == "req-list-2"

    def test_run_count(self, orchestrator):
        assert orchestrator.run_count() == 0
        orchestrator.orchestrate(request_id="req-count", simulate=True)
        assert orchestrator.run_count() == 1

    def test_no_mutations_occur(self, orchestrator):
        """Even completed runs only perform safe read-only validations."""
        step = ValidationOrchestrationStep(
            sequence=1,
            title="Would run CreateGrids",
            procedure="evidence_run",
        )
        result = orchestrator.orchestrate(
            request_id="req-nomut",
            steps=[step],
            required_capabilities=["CreateGrids"],
        )
        assert result.status == OrchestrationStatus.COMPLETED
        assert result.steps[0].result == StepResult.PASSED
        assert result.steps[0].notes == "executed (safe validation)"

    def test_json_output_valid(self, orchestrator):
        """JSON output is valid and complete."""
        step = ValidationOrchestrationStep(sequence=1, title="T")
        result = orchestrator.orchestrate(
            request_id="req-json",
            steps=[step],
            simulate=True,
        )
        j = result.to_json()
        parsed = json.loads(j)
        assert parsed["status"] == "simulated"
        assert parsed["step_count"] == 1
        assert "evidence" in parsed

    def test_check_safety_returns_none_for_safe(self, orchestrator):
        assert orchestrator.check_safety(["CreateGrids", "CreateLevels"]) is None

    def test_check_safety_returns_reason_for_unsafe(self, orchestrator):
        reason = orchestrator.check_safety(["SetParameterValue"])
        assert reason is not None
        assert "SetParameterValue" in reason

    def test_multiple_steps_all_pass(self, orchestrator):
        """Multiple steps all pass in sequence."""
        steps = [
            ValidationOrchestrationStep(sequence=1, title="Step 1"),
            ValidationOrchestrationStep(sequence=2, title="Step 2"),
            ValidationOrchestrationStep(sequence=3, title="Step 3"),
        ]
        result = orchestrator.orchestrate(
            request_id="req-multi-steps",
            steps=steps,
        )
        assert result.step_count == 3
        assert result.passed_count == 3
        assert result.failed_count == 0

    def test_step_procedures_checked_even_when_explicit_procedures_provided(
        self, orchestrator
    ):
        """Safety check must include step-level procedures even when the
        caller passes an explicit procedures list (regression)."""
        step = ValidationOrchestrationStep(
            sequence=1,
            title="Dangerous step",
            procedure="live_mutation",
        )
        result = orchestrator.orchestrate(
            request_id="req-step-proc",
            steps=[step],
            procedures=["evidence_run"],  # safe explicit list
        )
        assert result.status == OrchestrationStatus.REFUSED
        assert "live_mutation" in result.refusal_reason


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

    def test_unknown_request_exits_2(self, tmp_path):
        db = str(tmp_path / "cli.db")
        result = self._run(
            "validation-orchestrate", "--request-id", "nonexistent", env_db=db
        )
        assert result.returncode == 2

    def test_orchestrate_with_approved_request(self, tmp_path):
        """Full chain: create plan review → create request → orchestrate."""
        db = str(tmp_path / "cli.db")
        # 1. Create approved plan review
        self._run(
            "plan-review-create",
            "--plan-id", "orch-plan",
            "--plan-name", "Orch",
            "--decision", "approved",
            "--reason", "human_validation",
            env_db=db,
        )
        # 2. Create validation request
        create_result = self._run(
            "validation-request-create",
            "--plan-id", "orch-plan",
            "--json-output",
            env_db=db,
        )
        assert create_result.returncode == 0
        req_data = json.loads(create_result.stdout)
        request_id = req_data["request_id"]

        # 3. Orchestrate
        orch_result = self._run(
            "validation-orchestrate",
            "--request-id", request_id,
            "--simulate",
            "--json-output",
            env_db=db,
        )
        assert orch_result.returncode == 0
        orch_data = json.loads(orch_result.stdout)
        assert orch_data["status"] == "simulated"
        assert orch_data["simulate"] is True

    def test_completed_request_rejected(self, tmp_path):
        """CLI must reject orchestration for already-completed requests."""
        db = str(tmp_path / "cli_completed.db")
        from axiom_core.validation_requests import (
            ValidationRequestGenerator,
            ValidationRequestStatus,
        )

        gen = ValidationRequestGenerator(db_path=db)
        req = gen.generate_from_plan(
            plan_id="done-plan", plan_name="Done", steps=[]
        )
        gen.update_status(req.request_id, ValidationRequestStatus.COMPLETED)

        result = self._run(
            "validation-orchestrate",
            "--request-id", req.request_id,
            "--json-output",
            env_db=db,
        )
        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert data["error"] == "request_completed"

    def test_cancelled_request_rejected(self, tmp_path):
        """CLI must reject orchestration for cancelled requests."""
        db = str(tmp_path / "cli_cancelled.db")
        from axiom_core.validation_requests import (
            ValidationRequestGenerator,
            ValidationRequestStatus,
        )

        gen = ValidationRequestGenerator(db_path=db)
        req = gen.generate_from_plan(
            plan_id="cancel-plan", plan_name="Cancel", steps=[]
        )
        gen.update_status(req.request_id, ValidationRequestStatus.CANCELLED)

        result = self._run(
            "validation-orchestrate",
            "--request-id", req.request_id,
            "--json-output",
            env_db=db,
        )
        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert data["error"] == "request_cancelled"
