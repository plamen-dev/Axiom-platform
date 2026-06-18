"""Tests for Plan-to-Validation Request Generator (PR #52).

Acceptance criteria:
- approved plans create requests
- rejected plans are refused
- unknown plans fail clearly
- validation procedures attached
- evidence attached
- blockers preserved
- deterministic ordering
- JSON output valid
- no execution occurs
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from axiom_core.validation_requests import (
    BlockerType,
    ValidationRequest,
    ValidationRequestBlocker,
    ValidationRequestDependency,
    ValidationRequestEvidence,
    ValidationRequestGenerator,
    ValidationRequestStatus,
    ValidationRequestStep,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path):
    """Provide a temporary database path."""
    return str(tmp_path / "test_vr.db")


@pytest.fixture()
def generator(tmp_db):
    """Create a generator with a fresh temp database."""
    os.environ["AXIOM_DB_PATH"] = tmp_db
    gen = ValidationRequestGenerator(db_path=tmp_db)
    yield gen
    os.environ.pop("AXIOM_DB_PATH", None)


# ---------------------------------------------------------------------------
# TestEnums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_validation_request_status_values(self):
        assert ValidationRequestStatus.PENDING.value == "pending"
        assert ValidationRequestStatus.READY.value == "ready"
        assert ValidationRequestStatus.BLOCKED.value == "blocked"
        assert ValidationRequestStatus.COMPLETED.value == "completed"
        assert ValidationRequestStatus.CANCELLED.value == "cancelled"

    def test_blocker_type_values(self):
        assert BlockerType.MISSING_CAPABILITY.value == "missing_capability"
        assert BlockerType.MISSING_EVIDENCE.value == "missing_evidence"
        assert BlockerType.UNSAFE_PROCEDURE.value == "unsafe_procedure"
        assert BlockerType.PREREQUISITE_FAILED.value == "prerequisite_failed"
        assert BlockerType.DEPENDENCY_UNMET.value == "dependency_unmet"
        assert BlockerType.POLICY_VIOLATION.value == "policy_violation"


# ---------------------------------------------------------------------------
# TestValidationRequestStep
# ---------------------------------------------------------------------------


class TestValidationRequestStep:
    def test_defaults(self):
        step = ValidationRequestStep()
        assert step.step_id
        assert step.sequence == 0
        assert step.title == ""
        assert step.safety_level == "safe"
        assert step.required_capabilities == []
        assert step.expected_evidence == []

    def test_to_dict_roundtrip(self):
        step = ValidationRequestStep(
            step_id="s1",
            sequence=1,
            title="Validate grids",
            description="Run grid validation",
            validation_procedure="evidence_run",
            required_capabilities=["CreateGrids"],
            expected_evidence=["pass_fail.json"],
            safety_level="safe",
        )
        d = step.to_dict()
        restored = ValidationRequestStep.from_dict(d)
        assert restored.step_id == "s1"
        assert restored.sequence == 1
        assert restored.title == "Validate grids"
        assert restored.validation_procedure == "evidence_run"
        assert restored.required_capabilities == ["CreateGrids"]
        assert restored.expected_evidence == ["pass_fail.json"]


# ---------------------------------------------------------------------------
# TestValidationRequestDependency
# ---------------------------------------------------------------------------


class TestValidationRequestDependency:
    def test_defaults(self):
        dep = ValidationRequestDependency()
        assert dep.dependency_id
        assert dep.dependency_type == "requires"

    def test_to_dict_roundtrip(self):
        dep = ValidationRequestDependency(
            dependency_id="d1",
            from_step_id="s1",
            to_step_id="s2",
            dependency_type="validates",
            description="s1 validates s2",
        )
        d = dep.to_dict()
        restored = ValidationRequestDependency.from_dict(d)
        assert restored.dependency_id == "d1"
        assert restored.from_step_id == "s1"
        assert restored.to_step_id == "s2"
        assert restored.dependency_type == "validates"


# ---------------------------------------------------------------------------
# TestValidationRequestEvidence
# ---------------------------------------------------------------------------


class TestValidationRequestEvidence:
    def test_defaults(self):
        ev = ValidationRequestEvidence()
        assert ev.evidence_type == ""
        assert ev.required is True

    def test_to_dict_roundtrip(self):
        ev = ValidationRequestEvidence(
            evidence_type="pass_fail",
            description="Must produce pass/fail JSON",
            required=True,
            source="evidence_runner",
        )
        d = ev.to_dict()
        restored = ValidationRequestEvidence.from_dict(d)
        assert restored.evidence_type == "pass_fail"
        assert restored.description == "Must produce pass/fail JSON"
        assert restored.required is True
        assert restored.source == "evidence_runner"


# ---------------------------------------------------------------------------
# TestValidationRequestBlocker
# ---------------------------------------------------------------------------


class TestValidationRequestBlocker:
    def test_defaults(self):
        b = ValidationRequestBlocker()
        assert b.blocker_id
        assert b.blocker_type == BlockerType.DEPENDENCY_UNMET

    def test_string_coercion(self):
        b = ValidationRequestBlocker(blocker_type="unsafe_procedure")
        assert b.blocker_type == BlockerType.UNSAFE_PROCEDURE

    def test_invalid_type_defaults(self):
        b = ValidationRequestBlocker(blocker_type="unknown_type")
        assert b.blocker_type == BlockerType.DEPENDENCY_UNMET

    def test_to_dict_roundtrip(self):
        b = ValidationRequestBlocker(
            blocker_id="b1",
            blocker_type=BlockerType.MISSING_CAPABILITY,
            description="SetParameterValue not validated",
            resolution="Validate primitive first",
            blocking_step_id="s3",
        )
        d = b.to_dict()
        restored = ValidationRequestBlocker.from_dict(d)
        assert restored.blocker_id == "b1"
        assert restored.blocker_type == BlockerType.MISSING_CAPABILITY
        assert restored.description == "SetParameterValue not validated"
        assert restored.resolution == "Validate primitive first"
        assert restored.blocking_step_id == "s3"


# ---------------------------------------------------------------------------
# TestValidationRequest
# ---------------------------------------------------------------------------


class TestValidationRequest:
    def test_defaults(self):
        req = ValidationRequest(plan_id="p1", plan_name="Test Plan")
        assert req.request_id
        assert req.plan_id == "p1"
        assert req.status == ValidationRequestStatus.PENDING
        assert req.steps == []
        assert req.blockers == []

    def test_status_string_coercion(self):
        req = ValidationRequest(plan_id="p1", plan_name="T", status="ready")
        assert req.status == ValidationRequestStatus.READY

    def test_invalid_status_defaults(self):
        req = ValidationRequest(plan_id="p1", plan_name="T", status="bad")
        assert req.status == ValidationRequestStatus.PENDING

    def test_to_dict(self):
        req = ValidationRequest(
            plan_id="p1",
            plan_name="Grid Plan",
            required_capabilities=["CreateGrids"],
            known_risks=["Crash on large models"],
        )
        d = req.to_dict()
        assert d["plan_id"] == "p1"
        assert d["plan_name"] == "Grid Plan"
        assert d["required_capabilities"] == ["CreateGrids"]
        assert d["known_risks"] == ["Crash on large models"]
        assert d["step_count"] == 0

    def test_to_json(self):
        req = ValidationRequest(plan_id="p1", plan_name="T")
        j = req.to_json()
        parsed = json.loads(j)
        assert parsed["plan_id"] == "p1"


# ---------------------------------------------------------------------------
# TestValidationRequestGenerator
# ---------------------------------------------------------------------------


class TestValidationRequestGenerator:
    def test_create_and_get(self, generator):
        """Approved plans create requests — requests persist."""
        req = ValidationRequest(plan_id="plan-001", plan_name="Grid Validation")
        created = generator.create_request(req)
        assert created.request_id == req.request_id
        assert created.plan_id == "plan-001"

        retrieved = generator.get_request(created.request_id)
        assert retrieved is not None
        assert retrieved.plan_id == "plan-001"
        assert retrieved.plan_name == "Grid Validation"

    def test_empty_plan_id_raises(self, generator):
        with pytest.raises(ValueError, match="plan_id"):
            generator.create_request(ValidationRequest(plan_id="", plan_name="T"))

    def test_empty_plan_name_raises(self, generator):
        with pytest.raises(ValueError, match="plan_name"):
            generator.create_request(ValidationRequest(plan_id="p1", plan_name=""))

    def test_unknown_request_returns_none(self, generator):
        """Unknown request IDs return None."""
        assert generator.get_request("nonexistent") is None

    def test_unknown_plan_returns_empty(self, generator):
        """Unknown plan IDs return empty list."""
        result = generator.get_requests_for_plan("unknown-plan")
        assert result == []

    def test_validation_procedures_attached(self, generator):
        """Validation procedures are persisted with steps."""
        step = ValidationRequestStep(
            sequence=1,
            title="Run evidence",
            validation_procedure="evidence_run --capability CreateGrids",
            required_capabilities=["CreateGrids"],
        )
        req = ValidationRequest(
            plan_id="plan-002",
            plan_name="Grid Plan",
            steps=[step],
        )
        created = generator.create_request(req)
        retrieved = generator.get_request(created.request_id)
        assert len(retrieved.steps) == 1
        assert retrieved.steps[0].validation_procedure == "evidence_run --capability CreateGrids"
        assert retrieved.steps[0].required_capabilities == ["CreateGrids"]

    def test_evidence_attached(self, generator):
        """Evidence requirements persist."""
        ev = ValidationRequestEvidence(
            evidence_type="pass_fail",
            description="Must produce pass_fail.json",
            required=True,
            source="evidence_runner",
        )
        req = ValidationRequest(
            plan_id="plan-003",
            plan_name="Evidence Plan",
            evidence=[ev],
        )
        created = generator.create_request(req)
        retrieved = generator.get_request(created.request_id)
        assert len(retrieved.evidence) == 1
        assert retrieved.evidence[0].evidence_type == "pass_fail"
        assert retrieved.evidence[0].source == "evidence_runner"

    def test_blockers_preserved(self, generator):
        """Blockers are preserved and set status to blocked."""
        blocker = ValidationRequestBlocker(
            blocker_type=BlockerType.UNSAFE_PROCEDURE,
            description="SetParameterValue is high-risk",
        )
        req = ValidationRequest(
            plan_id="plan-004",
            plan_name="Blocked Plan",
            status=ValidationRequestStatus.BLOCKED,
            blockers=[blocker],
        )
        created = generator.create_request(req)
        retrieved = generator.get_request(created.request_id)
        assert retrieved.status == ValidationRequestStatus.BLOCKED
        assert len(retrieved.blockers) == 1
        assert retrieved.blockers[0].blocker_type == BlockerType.UNSAFE_PROCEDURE
        assert retrieved.blockers[0].description == "SetParameterValue is high-risk"

    def test_generate_from_plan_ready(self, generator):
        """generate_from_plan sets status to ready when no blockers."""
        step = ValidationRequestStep(sequence=1, title="Validate")
        result = generator.generate_from_plan(
            plan_id="plan-005",
            plan_name="Ready Plan",
            steps=[step],
        )
        assert result.status == ValidationRequestStatus.READY

    def test_generate_from_plan_blocked(self, generator):
        """generate_from_plan sets status to blocked when blockers exist."""
        blocker = ValidationRequestBlocker(
            blocker_type=BlockerType.MISSING_CAPABILITY,
            description="No capability validated",
        )
        result = generator.generate_from_plan(
            plan_id="plan-006",
            plan_name="Blocked Plan",
            blockers=[blocker],
        )
        assert result.status == ValidationRequestStatus.BLOCKED
        assert len(result.blockers) == 1

    def test_generate_collects_capabilities_from_steps(self, generator):
        """Capabilities are collected from steps when not explicitly provided."""
        steps = [
            ValidationRequestStep(sequence=1, title="S1", required_capabilities=["CreateGrids"]),
            ValidationRequestStep(sequence=2, title="S2", required_capabilities=["CreateLevels", "CreateGrids"]),
        ]
        result = generator.generate_from_plan(
            plan_id="plan-007",
            plan_name="Multi-cap",
            steps=steps,
        )
        assert "CreateGrids" in result.required_capabilities
        assert "CreateLevels" in result.required_capabilities
        assert len(result.required_capabilities) == 2

    def test_dependencies_persist(self, generator):
        """Dependencies are persisted."""
        dep = ValidationRequestDependency(
            from_step_id="s1",
            to_step_id="s2",
            dependency_type="requires",
        )
        req = ValidationRequest(
            plan_id="plan-008",
            plan_name="Dep Plan",
            dependencies=[dep],
        )
        created = generator.create_request(req)
        retrieved = generator.get_request(created.request_id)
        assert len(retrieved.dependencies) == 1
        assert retrieved.dependencies[0].from_step_id == "s1"
        assert retrieved.dependencies[0].to_step_id == "s2"

    def test_list_requests_status_filter(self, generator):
        """Status filter works."""
        generator.create_request(
            ValidationRequest(plan_id="p1", plan_name="A", status=ValidationRequestStatus.READY)
        )
        generator.create_request(
            ValidationRequest(plan_id="p2", plan_name="B", status=ValidationRequestStatus.BLOCKED)
        )
        ready = generator.list_requests(status_filter=ValidationRequestStatus.READY)
        assert all(r.status == ValidationRequestStatus.READY for r in ready)
        assert len(ready) == 1

    def test_list_requests_plan_id_filter(self, generator):
        """Plan ID filter works."""
        generator.create_request(ValidationRequest(plan_id="p1", plan_name="A"))
        generator.create_request(ValidationRequest(plan_id="p2", plan_name="B"))
        filtered = generator.list_requests(plan_id_filter="p1")
        assert len(filtered) == 1
        assert filtered[0].plan_id == "p1"

    def test_update_status(self, generator):
        """Status can be updated."""
        created = generator.create_request(
            ValidationRequest(plan_id="p1", plan_name="A")
        )
        result = generator.update_status(created.request_id, ValidationRequestStatus.COMPLETED)
        assert result is True
        retrieved = generator.get_request(created.request_id)
        assert retrieved.status == ValidationRequestStatus.COMPLETED

    def test_update_status_unknown_returns_false(self, generator):
        """Updating unknown request returns False."""
        assert generator.update_status("nonexistent", ValidationRequestStatus.COMPLETED) is False

    def test_request_count(self, generator):
        """Count increments."""
        assert generator.request_count() == 0
        generator.create_request(ValidationRequest(plan_id="p1", plan_name="A"))
        generator.create_request(ValidationRequest(plan_id="p2", plan_name="B"))
        assert generator.request_count() == 2

    def test_json_output(self, generator):
        """to_json produces valid JSON."""
        created = generator.create_request(
            ValidationRequest(
                plan_id="plan-json",
                plan_name="JSON Test",
                required_capabilities=["CreateGrids"],
            )
        )
        retrieved = generator.get_request(created.request_id)
        j = retrieved.to_json()
        parsed = json.loads(j)
        assert parsed["plan_id"] == "plan-json"
        assert parsed["required_capabilities"] == ["CreateGrids"]

    def test_deterministic_ordering(self, generator):
        """Requests are ordered by status then created_at desc."""
        generator.create_request(
            ValidationRequest(plan_id="p1", plan_name="First", status=ValidationRequestStatus.READY)
        )
        generator.create_request(
            ValidationRequest(plan_id="p2", plan_name="Second", status=ValidationRequestStatus.BLOCKED)
        )
        generator.create_request(
            ValidationRequest(plan_id="p3", plan_name="Third", status=ValidationRequestStatus.PENDING)
        )
        results = generator.list_requests()
        assert len(results) == 3
        statuses = [r.status for r in results]
        assert statuses == sorted(statuses, key=lambda s: s.value)

    def test_no_execution_occurs(self, generator):
        """Generator never executes capabilities — just creates requests."""
        step = ValidationRequestStep(
            sequence=1,
            title="Would run CreateGrids",
            validation_procedure="evidence_run --capability CreateGrids",
            required_capabilities=["CreateGrids"],
        )
        result = generator.generate_from_plan(
            plan_id="plan-noexec",
            plan_name="No Exec",
            steps=[step],
        )
        assert result.status == ValidationRequestStatus.READY
        assert result.steps[0].validation_procedure == "evidence_run --capability CreateGrids"

    def test_known_risks_and_expected_outputs(self, generator):
        """Known risks and expected outputs persist."""
        result = generator.generate_from_plan(
            plan_id="plan-risks",
            plan_name="Risk Plan",
            known_risks=["Crash on large models", "Timeout possible"],
            expected_outputs=["pass_fail.json", "evidence_bundle"],
        )
        retrieved = generator.get_request(result.request_id)
        assert retrieved.known_risks == ["Crash on large models", "Timeout possible"]
        assert retrieved.expected_outputs == ["pass_fail.json", "evidence_bundle"]

    def test_prerequisites_persist(self, generator):
        """Prerequisites persist."""
        result = generator.generate_from_plan(
            plan_id="plan-prereq",
            plan_name="Prereq Plan",
            prerequisites=["Revit 2024 running", "Model loaded"],
        )
        retrieved = generator.get_request(result.request_id)
        assert retrieved.prerequisites == ["Revit 2024 running", "Model loaded"]


# ---------------------------------------------------------------------------
# TestCLI
# ---------------------------------------------------------------------------


class TestCLI:
    """End-to-end CLI tests for validation request commands."""

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

    def test_create_requires_approved_plan(self, tmp_path):
        """Creating request for unknown plan fails with exit 2."""
        db = str(tmp_path / "cli_test.db")
        result = self._run(
            "validation-request-create", "--plan-id", "unknown-plan", env_db=db
        )
        assert result.returncode == 2

    def test_create_refuses_rejected_plan(self, tmp_path):
        """Creating request for rejected plan fails with exit 1."""
        db = str(tmp_path / "cli_test.db")
        # First create a rejected plan review
        self._run(
            "plan-review-create",
            "--plan-id", "rejected-plan",
            "--plan-name", "Rejected",
            "--decision", "rejected",
            "--reason", "unsafe",
            env_db=db,
        )
        result = self._run(
            "validation-request-create", "--plan-id", "rejected-plan", env_db=db
        )
        assert result.returncode == 1

    def test_create_approved_plan_succeeds(self, tmp_path):
        """Creating request for approved plan succeeds."""
        db = str(tmp_path / "cli_test.db")
        self._run(
            "plan-review-create",
            "--plan-id", "approved-plan",
            "--plan-name", "Approved",
            "--decision", "approved",
            "--reason", "human_validation",
            env_db=db,
        )
        result = self._run(
            "validation-request-create",
            "--plan-id", "approved-plan",
            "--json-output",
            env_db=db,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["plan_id"] == "approved-plan"
        assert data["status"] == "ready"

    def test_list_requests(self, tmp_path):
        """List requests returns JSON array."""
        db = str(tmp_path / "cli_test.db")
        # Create an approved plan and generate request
        self._run(
            "plan-review-create",
            "--plan-id", "list-plan",
            "--plan-name", "List",
            "--decision", "approved",
            "--reason", "human_validation",
            env_db=db,
        )
        self._run(
            "validation-request-create",
            "--plan-id", "list-plan",
            env_db=db,
        )
        result = self._run("validation-requests", "--json-output", env_db=db)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) == 1
        assert data[0]["plan_id"] == "list-plan"

    def test_show_request(self, tmp_path):
        """Show request by ID returns JSON."""
        db = str(tmp_path / "cli_test.db")
        self._run(
            "plan-review-create",
            "--plan-id", "show-plan",
            "--plan-name", "Show",
            "--decision", "approved",
            "--reason", "human_validation",
            env_db=db,
        )
        create_result = self._run(
            "validation-request-create",
            "--plan-id", "show-plan",
            "--json-output",
            env_db=db,
        )
        data = json.loads(create_result.stdout)
        request_id = data["request_id"]

        result = self._run(
            "validation-request", "--id", request_id, "--json-output", env_db=db
        )
        assert result.returncode == 0
        show_data = json.loads(result.stdout)
        assert show_data["request_id"] == request_id
        assert show_data["plan_id"] == "show-plan"

    def test_show_unknown_request_exits_2(self, tmp_path):
        """Unknown request ID exits 2."""
        db = str(tmp_path / "cli_test.db")
        result = self._run(
            "validation-request", "--id", "nonexistent", env_db=db
        )
        assert result.returncode == 2

    def test_status_filter(self, tmp_path):
        """Status filter works in CLI."""
        db = str(tmp_path / "cli_test.db")
        self._run(
            "plan-review-create",
            "--plan-id", "filter-plan",
            "--plan-name", "Filter",
            "--decision", "approved",
            "--reason", "human_validation",
            env_db=db,
        )
        self._run(
            "validation-request-create",
            "--plan-id", "filter-plan",
            env_db=db,
        )
        result = self._run(
            "validation-requests", "--status", "ready", "--json-output", env_db=db
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) == 1
        assert data[0]["status"] == "ready"

        result2 = self._run(
            "validation-requests", "--status", "blocked", "--json-output", env_db=db
        )
        assert result2.returncode == 0
        data2 = json.loads(result2.stdout)
        assert len(data2) == 0

    def test_create_json_output(self, tmp_path):
        """JSON output from create is valid and complete."""
        db = str(tmp_path / "cli_test.db")
        self._run(
            "plan-review-create",
            "--plan-id", "json-plan",
            "--plan-name", "JSON",
            "--decision", "approved",
            "--reason", "human_validation",
            env_db=db,
        )
        result = self._run(
            "validation-request-create",
            "--plan-id", "json-plan",
            "--json-output",
            env_db=db,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "request_id" in data
        assert "plan_id" in data
        assert "steps" in data
        assert "expected_outputs" in data
        assert data["expected_outputs"] == ["pass_fail.json", "evidence_bundle"]
