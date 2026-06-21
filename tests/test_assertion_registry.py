"""Tests for Assertion Registry v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.assertion_registry import (
    Assertion,
    AssertionRegistry,
    AssertionResult,
    AssertionSeverity,
    AssertionStatus,
    AssertionType,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry(tmp_path: Path) -> AssertionRegistry:
    return AssertionRegistry(artifacts_root=str(tmp_path))


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestEnums:
    def test_assertion_type_values(self):
        assert AssertionType.EXIT_CODE.value == "exit_code"
        assert AssertionType.STRATEGY.value == "strategy"
        assert AssertionType.READ_ONLY.value == "read_only"
        assert AssertionType.REASON.value == "reason"
        assert AssertionType.EVIDENCE.value == "evidence"
        assert AssertionType.DETERMINISTIC.value == "deterministic"
        assert AssertionType.CLASSIFICATION.value == "classification"
        assert AssertionType.PERSISTENCE.value == "persistence"

    def test_assertion_status_values(self):
        assert AssertionStatus.PENDING.value == "pending"
        assert AssertionStatus.PASSED.value == "passed"
        assert AssertionStatus.FAILED.value == "failed"
        assert AssertionStatus.SKIPPED.value == "skipped"

    def test_assertion_severity_values(self):
        assert AssertionSeverity.CRITICAL.value == "critical"
        assert AssertionSeverity.HIGH.value == "high"
        assert AssertionSeverity.MEDIUM.value == "medium"
        assert AssertionSeverity.LOW.value == "low"


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_assertion_result_to_dict(self):
        r = AssertionResult(
            assertion_id="a1",
            status="passed",
            actual_value="0",
            message="Exit code is 0",
        )
        d = r.to_dict()
        assert d["assertion_id"] == "a1"
        assert d["status"] == "passed"
        assert d["actual_value"] == "0"
        assert d["message"] == "Exit code is 0"
        assert d["result_id"]
        assert d["evaluated_at"]

    def test_assertion_result_auto_id(self):
        r1 = AssertionResult(status="passed")
        r2 = AssertionResult(status="failed")
        assert r1.result_id != r2.result_id

    def test_assertion_to_dict(self):
        a = Assertion(
            assertion_type="exit_code",
            description="Command exits 0",
            expected_value="0",
        )
        d = a.to_dict()
        assert d["assertion_type"] == "exit_code"
        assert d["description"] == "Command exits 0"
        assert d["expected_value"] == "0"
        assert d["status"] == "pending"
        assert d["severity"] == "medium"
        assert d["assertion_id"]
        assert d["created_at"]
        assert "assertion_summary" in d

    def test_assertion_summary(self):
        r1 = AssertionResult(status="passed")
        r2 = AssertionResult(status="failed")
        a = Assertion(
            assertion_type="exit_code",
            description="test",
            results=[r1, r2],
        )
        d = a.to_dict()
        summary = d["assertion_summary"]
        assert summary["total_results"] == 2
        assert summary["passed"] == 1
        assert summary["failed"] == 1


# ---------------------------------------------------------------------------
# Create assertion tests
# ---------------------------------------------------------------------------


class TestCreateAssertion:
    def test_create_minimal(self, registry: AssertionRegistry):
        a = registry.create_assertion(
            assertion_type="exit_code",
            description="Command exits 0",
        )
        assert a["assertion_type"] == "exit_code"
        assert a["description"] == "Command exits 0"
        assert a["status"] == "pending"
        assert a["assertion_id"]

    def test_create_with_all_fields(self, registry: AssertionRegistry):
        a = registry.create_assertion(
            assertion_type="strategy",
            description="Strategy is targeted",
            expected_value="targeted",
            severity="high",
            plan_id="plan-001",
            question_id="q-001",
            work_item_id="wi-001",
            capability="test-selection",
            rationale="Targeted strategy required",
        )
        assert a["assertion_type"] == "strategy"
        assert a["expected_value"] == "targeted"
        assert a["severity"] == "high"
        assert a["plan_id"] == "plan-001"
        assert a["question_id"] == "q-001"
        assert a["work_item_id"] == "wi-001"
        assert a["capability"] == "test-selection"
        assert a["rationale"] == "Targeted strategy required"

    def test_create_persists(self, registry: AssertionRegistry):
        a = registry.create_assertion(
            assertion_type="read_only",
            description="No mutation",
        )
        loaded = registry.get_assertion(a["assertion_id"])
        assert loaded is not None
        assert loaded["description"] == "No mutation"

    def test_create_unique_ids(self, registry: AssertionRegistry):
        a1 = registry.create_assertion(
            assertion_type="exit_code", description="A1",
        )
        a2 = registry.create_assertion(
            assertion_type="exit_code", description="A2",
        )
        assert a1["assertion_id"] != a2["assertion_id"]


# ---------------------------------------------------------------------------
# Get assertion tests
# ---------------------------------------------------------------------------


class TestGetAssertion:
    def test_get_existing(self, registry: AssertionRegistry):
        a = registry.create_assertion(
            assertion_type="exit_code", description="test",
        )
        loaded = registry.get_assertion(a["assertion_id"])
        assert loaded is not None
        assert loaded["assertion_id"] == a["assertion_id"]

    def test_get_nonexistent(self, registry: AssertionRegistry):
        result = registry.get_assertion("nonexistent-id")
        assert result is None


# ---------------------------------------------------------------------------
# List assertions tests
# ---------------------------------------------------------------------------


class TestListAssertions:
    def test_list_empty(self, registry: AssertionRegistry):
        result = registry.list_assertions()
        assert result == []

    def test_list_all(self, registry: AssertionRegistry):
        registry.create_assertion(
            assertion_type="exit_code", description="A1",
        )
        registry.create_assertion(
            assertion_type="strategy", description="A2",
        )
        result = registry.list_assertions()
        assert len(result) == 2

    def test_list_filter_by_status(self, registry: AssertionRegistry):
        a = registry.create_assertion(
            assertion_type="exit_code", description="A1",
        )
        registry.record_result(a["assertion_id"], status="passed")
        registry.create_assertion(
            assertion_type="strategy", description="A2",
        )
        pending = registry.list_assertions(status="pending")
        assert len(pending) == 1
        assert pending[0]["description"] == "A2"

    def test_list_filter_by_type(self, registry: AssertionRegistry):
        registry.create_assertion(
            assertion_type="exit_code", description="A1",
        )
        registry.create_assertion(
            assertion_type="strategy", description="A2",
        )
        result = registry.list_assertions(assertion_type="strategy")
        assert len(result) == 1
        assert result[0]["assertion_type"] == "strategy"

    def test_list_filter_by_capability(self, registry: AssertionRegistry):
        registry.create_assertion(
            assertion_type="exit_code",
            description="A1",
            capability="test-selection",
        )
        registry.create_assertion(
            assertion_type="exit_code",
            description="A2",
            capability="other",
        )
        result = registry.list_assertions(capability="test-selection")
        assert len(result) == 1
        assert result[0]["capability"] == "test-selection"


# ---------------------------------------------------------------------------
# Record result tests
# ---------------------------------------------------------------------------


class TestRecordResult:
    def test_record_passed(self, registry: AssertionRegistry):
        a = registry.create_assertion(
            assertion_type="exit_code",
            description="Exits 0",
            expected_value="0",
        )
        updated = registry.record_result(
            a["assertion_id"],
            status="passed",
            actual_value="0",
            message="Exit code matches",
            source="CLI test",
        )
        assert updated is not None
        assert updated["status"] == "passed"
        assert len(updated["results"]) == 1
        assert updated["results"][0]["actual_value"] == "0"
        assert updated["results"][0]["source"] == "CLI test"

    def test_record_failed(self, registry: AssertionRegistry):
        a = registry.create_assertion(
            assertion_type="exit_code",
            description="Exits 0",
            expected_value="0",
        )
        updated = registry.record_result(
            a["assertion_id"],
            status="failed",
            actual_value="1",
            message="Unexpected exit code",
        )
        assert updated is not None
        assert updated["status"] == "failed"

    def test_record_nonexistent(self, registry: AssertionRegistry):
        result = registry.record_result("nonexistent", status="passed")
        assert result is None

    def test_record_invalid_status_raises(self, registry: AssertionRegistry):
        a = registry.create_assertion(
            assertion_type="exit_code", description="test",
        )
        with pytest.raises(ValueError, match="Invalid status"):
            registry.record_result(a["assertion_id"], status="bogus")

    def test_record_multiple_results(self, registry: AssertionRegistry):
        a = registry.create_assertion(
            assertion_type="exit_code", description="test",
        )
        registry.record_result(a["assertion_id"], status="failed")
        updated = registry.record_result(a["assertion_id"], status="passed")
        assert updated is not None
        assert len(updated["results"]) == 2
        assert updated["status"] == "passed"

    def test_record_updates_timestamp(self, registry: AssertionRegistry):
        a = registry.create_assertion(
            assertion_type="exit_code", description="test",
        )
        original = a["updated_at"]
        updated = registry.record_result(a["assertion_id"], status="passed")
        assert updated is not None
        assert updated["updated_at"] >= original

    def test_record_recomputes_summary(self, registry: AssertionRegistry):
        a = registry.create_assertion(
            assertion_type="exit_code", description="test",
        )
        registry.record_result(a["assertion_id"], status="passed")
        updated = registry.record_result(a["assertion_id"], status="failed")
        assert updated is not None
        summary = updated["assertion_summary"]
        assert summary["total_results"] == 2
        assert summary["passed"] == 1
        assert summary["failed"] == 1


# ---------------------------------------------------------------------------
# List results tests
# ---------------------------------------------------------------------------


class TestListResults:
    def test_list_results_empty(self, registry: AssertionRegistry):
        a = registry.create_assertion(
            assertion_type="exit_code", description="test",
        )
        results = registry.list_results(a["assertion_id"])
        assert results == []

    def test_list_results_with_data(self, registry: AssertionRegistry):
        a = registry.create_assertion(
            assertion_type="exit_code", description="test",
        )
        registry.record_result(a["assertion_id"], status="passed")
        registry.record_result(a["assertion_id"], status="failed")
        results = registry.list_results(a["assertion_id"])
        assert len(results) == 2

    def test_list_results_nonexistent(self, registry: AssertionRegistry):
        results = registry.list_results("nonexistent")
        assert results == []


# ---------------------------------------------------------------------------
# Export assertion tests
# ---------------------------------------------------------------------------


class TestExportAssertion:
    def test_export_markdown(self, registry: AssertionRegistry):
        a = registry.create_assertion(
            assertion_type="exit_code",
            description="Command exits 0",
            expected_value="0",
            capability="test-selection",
            rationale="Must exit cleanly",
        )
        md = registry.export_assertion(a["assertion_id"])
        assert "# Assertion: Command exits 0" in md
        assert "- Type: exit_code" in md
        assert "- Expected: 0" in md
        assert "- Capability: test-selection" in md
        assert "## Rationale" in md
        assert "Must exit cleanly" in md

    def test_export_with_results(self, registry: AssertionRegistry):
        a = registry.create_assertion(
            assertion_type="exit_code",
            description="Exits 0",
            expected_value="0",
        )
        registry.record_result(
            a["assertion_id"],
            status="passed",
            actual_value="0",
            source="test",
        )
        md = registry.export_assertion(a["assertion_id"])
        assert "## Results (1)" in md
        assert "[passed]" in md
        assert "actual=0" in md

    def test_export_nonexistent_raises(self, registry: AssertionRegistry):
        with pytest.raises(ValueError, match="Assertion not found"):
            registry.export_assertion("nonexistent")


# ---------------------------------------------------------------------------
# Evidence writing tests
# ---------------------------------------------------------------------------


class TestWriteEvidence:
    def test_evidence_files_created(self, registry: AssertionRegistry):
        a = registry.create_assertion(
            assertion_type="exit_code", description="Evidence A",
        )
        evidence_dir = registry.write_evidence(a["assertion_id"])
        p = Path(evidence_dir)
        assert (p / "assertion_request.json").exists()
        assert (p / "assertion_result.json").exists()
        assert (p / "assertion_summary.md").exists()
        assert (p / "pass_fail.json").exists()

    def test_evidence_request_valid_json(self, registry: AssertionRegistry):
        a = registry.create_assertion(
            assertion_type="strategy",
            description="JSON A",
            capability="cap-x",
        )
        evidence_dir = registry.write_evidence(a["assertion_id"])
        p = Path(evidence_dir)
        req = json.loads((p / "assertion_request.json").read_text())
        assert req["assertion_id"] == a["assertion_id"]
        assert req["assertion_type"] == "strategy"
        assert req["capability"] == "cap-x"

    def test_evidence_result_valid_json(self, registry: AssertionRegistry):
        a = registry.create_assertion(
            assertion_type="exit_code", description="Result A",
        )
        evidence_dir = registry.write_evidence(a["assertion_id"])
        p = Path(evidence_dir)
        result = json.loads((p / "assertion_result.json").read_text())
        assert result["assertion_id"] == a["assertion_id"]
        assert "assertion_summary" in result

    def test_evidence_pass_fail_pending(self, registry: AssertionRegistry):
        a = registry.create_assertion(
            assertion_type="exit_code", description="PF A",
        )
        evidence_dir = registry.write_evidence(a["assertion_id"])
        p = Path(evidence_dir)
        pf = json.loads((p / "pass_fail.json").read_text())
        assert pf["passed"] is True
        assert pf["status"] == "pending"

    def test_evidence_pass_fail_failed(self, registry: AssertionRegistry):
        a = registry.create_assertion(
            assertion_type="exit_code", description="PF Failed",
        )
        registry.record_result(a["assertion_id"], status="failed")
        evidence_dir = registry.write_evidence(a["assertion_id"])
        p = Path(evidence_dir)
        pf = json.loads((p / "pass_fail.json").read_text())
        assert pf["passed"] is False
        assert pf["status"] == "failed"

    def test_evidence_markdown_contains_header(self, registry: AssertionRegistry):
        a = registry.create_assertion(
            assertion_type="exit_code", description="MD A",
        )
        evidence_dir = registry.write_evidence(a["assertion_id"])
        p = Path(evidence_dir)
        md = (p / "assertion_summary.md").read_text()
        assert "# Assertion: MD A" in md

    def test_evidence_nonexistent_raises(self, registry: AssertionRegistry):
        with pytest.raises(ValueError, match="Assertion not found"):
            registry.write_evidence("nonexistent")


# ---------------------------------------------------------------------------
# ID validation tests
# ---------------------------------------------------------------------------


class TestIDValidation:
    def test_empty_id_raises(self, registry: AssertionRegistry):
        with pytest.raises(ValueError, match="must not be empty"):
            registry.get_assertion("")

    def test_whitespace_only_raises(self, registry: AssertionRegistry):
        with pytest.raises(ValueError, match="must not be empty"):
            registry.get_assertion("   ")

    def test_path_traversal_raises(self, registry: AssertionRegistry):
        with pytest.raises(ValueError, match="must not contain"):
            registry.get_assertion("../etc/passwd")

    def test_forward_slash_raises(self, registry: AssertionRegistry):
        with pytest.raises(ValueError, match="must not contain"):
            registry.get_assertion("a/b")

    def test_backslash_raises(self, registry: AssertionRegistry):
        with pytest.raises(ValueError, match="must not contain"):
            registry.get_assertion("a\\b")


# ---------------------------------------------------------------------------
# Deterministic ordering tests
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_assertions_sorted_by_status_rank(self, registry: AssertionRegistry):
        a1 = registry.create_assertion(
            assertion_type="exit_code", description="A1",
        )
        registry.create_assertion(
            assertion_type="exit_code", description="A2",
        )
        registry.record_result(a1["assertion_id"], status="passed")
        assertions = registry.list_assertions()
        assert len(assertions) == 2
        assert assertions[0]["status"] == "pending"
        assert assertions[1]["status"] == "passed"

    def test_assertions_sorted_by_severity_within_status(
        self, registry: AssertionRegistry,
    ):
        registry.create_assertion(
            assertion_type="exit_code",
            description="Low",
            severity="low",
        )
        registry.create_assertion(
            assertion_type="exit_code",
            description="Critical",
            severity="critical",
        )
        registry.create_assertion(
            assertion_type="exit_code",
            description="High",
            severity="high",
        )
        assertions = registry.list_assertions()
        severities = [a["severity"] for a in assertions]
        assert severities == ["critical", "high", "low"]


# ---------------------------------------------------------------------------
# Command registry spec tests
# ---------------------------------------------------------------------------


class TestCommandRegistrySpecs:
    def test_assertion_create_registered(self):
        from axiom_core.runner.command_registry import get_command
        cmd = get_command("assertion-create")
        assert cmd is not None
        assert cmd.classification.value == "read_only"
        assert cmd.safety_level.value == "safe"

    def test_assertion_create_has_evidence_outputs(self):
        from axiom_core.runner.command_registry import get_command
        cmd = get_command("assertion-create")
        assert cmd is not None
        names = [e.location for e in cmd.evidence_outputs]
        assert "assertion_request.json" in names
        assert "assertion_result.json" in names
        assert "assertion_summary.md" in names
        assert "pass_fail.json" in names

    def test_assertions_registered(self):
        from axiom_core.runner.command_registry import get_command
        cmd = get_command("assertions")
        assert cmd is not None
        assert cmd.classification.value == "read_only"

    def test_assertion_results_registered(self):
        from axiom_core.runner.command_registry import get_command
        cmd = get_command("assertion-results")
        assert cmd is not None
        assert cmd.classification.value == "read_only"


# ---------------------------------------------------------------------------
# Test selection mapping test
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_mapping_exists(self):
        from axiom_core.test_selection_engine import _FILE_TO_TEST
        assert (
            _FILE_TO_TEST["src/axiom_core/assertion_registry.py"]
            == "tests/test_assertion_registry.py"
        )
