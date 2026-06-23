"""Tests for the Execution Outcome Framework v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.execution_outcome import (
    ExecutionOutcome,
    ExecutionOutcomeEngine,
    ExecutionOutcomeEvidence,
    ExecutionOutcomeReport,
    ExecutionOutcomeStatus,
    ExecutionOutcomeType,
)


@pytest.fixture()
def engine(tmp_path: Path) -> ExecutionOutcomeEngine:
    return ExecutionOutcomeEngine(artifacts_root=str(tmp_path))


def _sample_outcomes() -> list[dict]:
    return [
        {
            "attempt_id": "a1",
            "outcome_type": "success",
            "status": "completed",
            "summary": "implemented feature",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "attempt_id": "a2",
            "outcome_type": "failure",
            "status": "failed",
            "created_at": "2026-01-02T00:00:00+00:00",
        },
        {
            "attempt_id": "a3",
            "outcome_type": "partial_success",
            "status": "partial",
            "created_at": "2026-01-03T00:00:00+00:00",
        },
    ]


# ---------------------------------------------------------------------------
# TestModels
# ---------------------------------------------------------------------------


class TestModels:
    def test_outcome_defaults(self) -> None:
        o = ExecutionOutcome()
        assert o.outcome_id
        assert o.created_at
        assert o.outcome_type == "success"
        assert o.status == "completed"

    def test_report_defaults(self) -> None:
        r = ExecutionOutcomeReport()
        assert r.report_id
        assert r.created_at
        assert r.outcome_count == 0

    def test_evidence_defaults(self) -> None:
        e = ExecutionOutcomeEvidence()
        assert e.evidence_id
        assert e.created_at


# ---------------------------------------------------------------------------
# TestCreate
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_empty(self, engine: ExecutionOutcomeEngine) -> None:
        result = engine.create()
        assert result["outcome_count"] == 0
        assert result["outcomes"] == []

    def test_create_with_outcomes(self, engine: ExecutionOutcomeEngine) -> None:
        result = engine.create(outcomes=_sample_outcomes())
        assert result["outcome_count"] == 3

    def test_all_types(self, engine: ExecutionOutcomeEngine) -> None:
        outcomes = [
            {"attempt_id": f"a{t.value}", "outcome_type": t.value, "status": "completed"}
            for t in ExecutionOutcomeType
        ]
        result = engine.create(outcomes=outcomes)
        assert result["outcome_count"] == len(ExecutionOutcomeType)

    def test_all_statuses(self, engine: ExecutionOutcomeEngine) -> None:
        outcomes = [
            {"attempt_id": f"a{s.value}", "outcome_type": "success", "status": s.value}
            for s in ExecutionOutcomeStatus
        ]
        result = engine.create(outcomes=outcomes)
        assert result["outcome_count"] == len(ExecutionOutcomeStatus)

    def test_no_action_type(self, engine: ExecutionOutcomeEngine) -> None:
        outcomes = [
            {"attempt_id": "a1", "outcome_type": "no_action", "status": "completed"},
        ]
        result = engine.create(outcomes=outcomes)
        assert result["outcome_count"] == 1
        assert result["success_count"] == 0
        assert result["failure_count"] == 0
        assert result["partial_count"] == 0
        assert result["cancelled_count"] == 0


# ---------------------------------------------------------------------------
# TestStatusCounts
# ---------------------------------------------------------------------------


class TestStatusCounts:
    def test_status_counts(self, engine: ExecutionOutcomeEngine) -> None:
        result = engine.create(outcomes=_sample_outcomes())
        assert result["success_count"] == 1
        assert result["failure_count"] == 1
        assert result["partial_count"] == 1
        assert result["cancelled_count"] == 0

    def test_cancelled_counted(self, engine: ExecutionOutcomeEngine) -> None:
        outcomes = [
            {"attempt_id": "a1", "outcome_type": "cancelled", "status": "cancelled"},
            {"attempt_id": "a2", "outcome_type": "cancelled", "status": "cancelled"},
        ]
        result = engine.create(outcomes=outcomes)
        assert result["cancelled_count"] == 2


# ---------------------------------------------------------------------------
# TestStatusPersistence
# ---------------------------------------------------------------------------


class TestStatusPersistence:
    def test_status_persisted(self, engine: ExecutionOutcomeEngine) -> None:
        result = engine.create(outcomes=_sample_outcomes())
        by_attempt = {o["attempt_id"]: o for o in result["outcomes"]}
        assert by_attempt["a1"]["status"] == "completed"
        assert by_attempt["a2"]["status"] == "failed"

    def test_type_and_summary_persisted(self, engine: ExecutionOutcomeEngine) -> None:
        result = engine.create(outcomes=_sample_outcomes())
        by_attempt = {o["attempt_id"]: o for o in result["outcomes"]}
        assert by_attempt["a1"]["outcome_type"] == "success"
        assert by_attempt["a1"]["summary"] == "implemented feature"


# ---------------------------------------------------------------------------
# TestValidation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_type_rejected(self, engine: ExecutionOutcomeEngine) -> None:
        with pytest.raises(ValueError, match="Invalid outcome_type"):
            engine.create(
                outcomes=[{"attempt_id": "a1", "outcome_type": "teleport"}]
            )

    def test_invalid_status_rejected(self, engine: ExecutionOutcomeEngine) -> None:
        with pytest.raises(ValueError, match="Invalid status"):
            engine.create(
                outcomes=[{"attempt_id": "a1", "status": "exploded"}]
            )

    def test_missing_attempt_id_rejected(
        self, engine: ExecutionOutcomeEngine
    ) -> None:
        with pytest.raises(ValueError, match="attempt_id is required"):
            engine.create(outcomes=[{"outcome_type": "success"}])


# ---------------------------------------------------------------------------
# TestDeterministicOrdering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_outcomes_ordered(self, engine: ExecutionOutcomeEngine) -> None:
        result = engine.create(outcomes=_sample_outcomes())
        created = [o["created_at"] for o in result["outcomes"]]
        assert created == sorted(created)

    def test_order_independent(self, engine: ExecutionOutcomeEngine) -> None:
        r1 = engine.create(outcomes=_sample_outcomes())
        r2 = engine.create(outcomes=list(reversed(_sample_outcomes())))
        keys1 = [(o["created_at"], o["attempt_id"]) for o in r1["outcomes"]]
        keys2 = [(o["created_at"], o["attempt_id"]) for o in r2["outcomes"]]
        assert keys1 == keys2


# ---------------------------------------------------------------------------
# TestEvidenceGeneration
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_four_files_created(self, engine: ExecutionOutcomeEngine) -> None:
        result = engine.create(outcomes=_sample_outcomes())
        report_dir = Path(engine._report_dir) / result["report_id"]
        expected = {
            "execution_outcome_request.json",
            "execution_outcome_result.json",
            "execution_outcome_summary.md",
            "pass_fail.json",
        }
        actual = {f.name for f in report_dir.iterdir() if f.is_file()}
        assert expected.issubset(actual)

    def test_request_valid_json(self, engine: ExecutionOutcomeEngine) -> None:
        result = engine.create(outcomes=_sample_outcomes())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads(
            (report_dir / "execution_outcome_request.json").read_text()
        )
        assert len(data["outcomes"]) == 3

    def test_result_valid_json(self, engine: ExecutionOutcomeEngine) -> None:
        result = engine.create(outcomes=_sample_outcomes())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads(
            (report_dir / "execution_outcome_result.json").read_text()
        )
        assert data["report_id"] == result["report_id"]
        assert data["outcome_count"] == 3

    def test_summary_has_sections(self, engine: ExecutionOutcomeEngine) -> None:
        result = engine.create(outcomes=_sample_outcomes())
        report_dir = Path(engine._report_dir) / result["report_id"]
        md = (report_dir / "execution_outcome_summary.md").read_text()
        assert "# Execution Outcome Report" in md
        assert "## Status Counts" in md
        assert "## Outcomes" in md

    def test_pass_fail_passes_no_failures(
        self, engine: ExecutionOutcomeEngine
    ) -> None:
        outcomes = [
            {"attempt_id": "a1", "outcome_type": "success", "status": "completed"},
        ]
        result = engine.create(outcomes=outcomes)
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True
        assert pf["status"] == "passed"

    def test_pass_fail_fails_on_failure(
        self, engine: ExecutionOutcomeEngine
    ) -> None:
        result = engine.create(outcomes=_sample_outcomes())
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is False
        assert pf["failure_count"] == 1

    def test_pass_fail_empty_passes(self, engine: ExecutionOutcomeEngine) -> None:
        result = engine.create()
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, engine: ExecutionOutcomeEngine) -> None:
        result = engine.create(outcomes=_sample_outcomes())
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]
        assert loaded["outcome_count"] == 3

    def test_list_reports_deterministic(
        self, engine: ExecutionOutcomeEngine
    ) -> None:
        engine.create(outcomes=_sample_outcomes())
        engine.create()
        reports = engine.list_reports()
        assert len(reports) == 2
        assert reports[0]["created_at"] <= reports[1]["created_at"]


# ---------------------------------------------------------------------------
# TestExport
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_returns_markdown(self, engine: ExecutionOutcomeEngine) -> None:
        result = engine.create(outcomes=_sample_outcomes())
        md = engine.export_report(result["report_id"])
        assert "# Execution Outcome Report" in md
        assert "SUCCESS" in md

    def test_export_nonexistent_raises(
        self, engine: ExecutionOutcomeEngine
    ) -> None:
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id-abc123")


# ---------------------------------------------------------------------------
# TestSafety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(self, engine: ExecutionOutcomeEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("../../etc/passwd")

    def test_empty_id_rejected(self, engine: ExecutionOutcomeEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("")

    def test_whitespace_id_rejected(self, engine: ExecutionOutcomeEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("   ")

    def test_symlink_escape_rejected(
        self, engine: ExecutionOutcomeEngine, tmp_path: Path
    ) -> None:
        target = tmp_path / "outside"
        target.mkdir()
        link = Path(engine._report_dir) / "evil-link"
        link.symlink_to(target)
        with pytest.raises(ValueError):
            engine.get_report("evil-link")

    def test_nonexistent_returns_none(
        self, engine: ExecutionOutcomeEngine
    ) -> None:
        result = engine.get_report("valid-but-missing-id")
        assert result is None


# ---------------------------------------------------------------------------
# TestCommandRegistryIntegration
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_commands_registered(self) -> None:
        from axiom_core.runner.command_registry import command_names

        names = command_names()
        expected = {
            "execution-outcome-create",
            "execution-outcome-show",
            "execution-outcome-export",
        }
        assert expected.issubset(set(names))


# ---------------------------------------------------------------------------
# TestSelectionMapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_execution_outcome_mapped(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/execution_outcome.py"]
            == "tests/test_execution_outcome.py"
        )
