"""Tests for the Recovery Execution Framework v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.recovery_execution import (
    RecoveryExecution,
    RecoveryExecutionEngine,
    RecoveryExecutionEvidence,
    RecoveryExecutionReport,
    RecoveryExecutionStatus,
    RecoveryExecutionType,
)


@pytest.fixture()
def engine(tmp_path: Path) -> RecoveryExecutionEngine:
    return RecoveryExecutionEngine(artifacts_root=str(tmp_path))


def _sample_executions() -> list[dict]:
    return [
        {
            "recommendation_id": "r1",
            "execution_type": "retry_executed",
            "status": "succeeded",
            "summary": "retry worked",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "recommendation_id": "r2",
            "execution_type": "repair_executed",
            "status": "partial_success",
            "created_at": "2026-01-02T00:00:00+00:00",
        },
        {
            "recommendation_id": "r3",
            "execution_type": "rollback_executed",
            "status": "failed",
            "created_at": "2026-01-03T00:00:00+00:00",
        },
    ]


# ---------------------------------------------------------------------------
# TestModels
# ---------------------------------------------------------------------------


class TestModels:
    def test_execution_defaults(self) -> None:
        e = RecoveryExecution()
        assert e.execution_id
        assert e.created_at
        assert e.execution_type == "no_action"
        assert e.status == "created"

    def test_report_defaults(self) -> None:
        r = RecoveryExecutionReport()
        assert r.report_id
        assert r.created_at
        assert r.execution_count == 0

    def test_evidence_defaults(self) -> None:
        e = RecoveryExecutionEvidence()
        assert e.evidence_id
        assert e.created_at


# ---------------------------------------------------------------------------
# TestCreate
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_empty(self, engine: RecoveryExecutionEngine) -> None:
        result = engine.create()
        assert result["execution_count"] == 0
        assert result["executions"] == []

    def test_create_with_executions(
        self, engine: RecoveryExecutionEngine
    ) -> None:
        result = engine.create(executions=_sample_executions())
        assert result["execution_count"] == 3

    def test_all_types(self, engine: RecoveryExecutionEngine) -> None:
        executions = [
            {"recommendation_id": f"r{t.value}", "execution_type": t.value}
            for t in RecoveryExecutionType
        ]
        result = engine.create(executions=executions)
        assert result["execution_count"] == len(RecoveryExecutionType)

    def test_all_statuses(self, engine: RecoveryExecutionEngine) -> None:
        executions = [
            {"recommendation_id": f"r{s.value}", "status": s.value}
            for s in RecoveryExecutionStatus
        ]
        result = engine.create(executions=executions)
        assert result["execution_count"] == len(RecoveryExecutionStatus)


# ---------------------------------------------------------------------------
# TestStatusCounts
# ---------------------------------------------------------------------------


class TestStatusCounts:
    def test_status_counts(self, engine: RecoveryExecutionEngine) -> None:
        result = engine.create(executions=_sample_executions())
        assert result["succeeded_count"] == 1
        assert result["partial_success_count"] == 1
        assert result["failed_count"] == 1
        assert result["cancelled_count"] == 0

    def test_cancelled_counted(self, engine: RecoveryExecutionEngine) -> None:
        executions = [
            {"recommendation_id": "r1", "status": "cancelled"},
            {"recommendation_id": "r2", "status": "cancelled"},
        ]
        result = engine.create(executions=executions)
        assert result["cancelled_count"] == 2


# ---------------------------------------------------------------------------
# TestStatusPersistence
# ---------------------------------------------------------------------------


class TestStatusPersistence:
    def test_status_persisted(self, engine: RecoveryExecutionEngine) -> None:
        result = engine.create(executions=_sample_executions())
        by_rec = {e["recommendation_id"]: e for e in result["executions"]}
        assert by_rec["r1"]["status"] == "succeeded"
        assert by_rec["r3"]["status"] == "failed"

    def test_type_and_summary_persisted(
        self, engine: RecoveryExecutionEngine
    ) -> None:
        result = engine.create(executions=_sample_executions())
        by_rec = {e["recommendation_id"]: e for e in result["executions"]}
        assert by_rec["r1"]["execution_type"] == "retry_executed"
        assert by_rec["r1"]["summary"] == "retry worked"


# ---------------------------------------------------------------------------
# TestRecommendationReferences
# ---------------------------------------------------------------------------


class TestRecommendationReferences:
    def test_recommendation_id_preserved(
        self, engine: RecoveryExecutionEngine
    ) -> None:
        result = engine.create(executions=_sample_executions())
        rec_ids = {e["recommendation_id"] for e in result["executions"]}
        assert rec_ids == {"r1", "r2", "r3"}


# ---------------------------------------------------------------------------
# TestValidation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_type_rejected(
        self, engine: RecoveryExecutionEngine
    ) -> None:
        with pytest.raises(ValueError, match="Invalid execution_type"):
            engine.create(
                executions=[
                    {"recommendation_id": "r1", "execution_type": "boom"}
                ]
            )

    def test_invalid_status_rejected(
        self, engine: RecoveryExecutionEngine
    ) -> None:
        with pytest.raises(ValueError, match="Invalid status"):
            engine.create(
                executions=[{"recommendation_id": "r1", "status": "exploded"}]
            )

    def test_missing_recommendation_id_rejected(
        self, engine: RecoveryExecutionEngine
    ) -> None:
        with pytest.raises(ValueError, match="recommendation_id is required"):
            engine.create(executions=[{"execution_type": "retry_executed"}])


# ---------------------------------------------------------------------------
# TestDeterministicOrdering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_executions_ordered(
        self, engine: RecoveryExecutionEngine
    ) -> None:
        result = engine.create(executions=_sample_executions())
        created = [e["created_at"] for e in result["executions"]]
        assert created == sorted(created)

    def test_order_independent(self, engine: RecoveryExecutionEngine) -> None:
        r1 = engine.create(executions=_sample_executions())
        r2 = engine.create(executions=list(reversed(_sample_executions())))
        keys1 = [
            (e["created_at"], e["recommendation_id"]) for e in r1["executions"]
        ]
        keys2 = [
            (e["created_at"], e["recommendation_id"]) for e in r2["executions"]
        ]
        assert keys1 == keys2


# ---------------------------------------------------------------------------
# TestEvidenceGeneration
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_four_files_created(
        self, engine: RecoveryExecutionEngine
    ) -> None:
        result = engine.create(executions=_sample_executions())
        report_dir = Path(engine._report_dir) / result["report_id"]
        expected = {
            "recovery_execution_request.json",
            "recovery_execution_result.json",
            "recovery_execution_summary.md",
            "pass_fail.json",
        }
        actual = {f.name for f in report_dir.iterdir() if f.is_file()}
        assert expected.issubset(actual)

    def test_request_valid_json(
        self, engine: RecoveryExecutionEngine
    ) -> None:
        result = engine.create(executions=_sample_executions())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads(
            (report_dir / "recovery_execution_request.json").read_text()
        )
        assert len(data["executions"]) == 3

    def test_result_valid_json(
        self, engine: RecoveryExecutionEngine
    ) -> None:
        result = engine.create(executions=_sample_executions())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads(
            (report_dir / "recovery_execution_result.json").read_text()
        )
        assert data["report_id"] == result["report_id"]
        assert data["execution_count"] == 3

    def test_summary_has_sections(
        self, engine: RecoveryExecutionEngine
    ) -> None:
        result = engine.create(executions=_sample_executions())
        report_dir = Path(engine._report_dir) / result["report_id"]
        md = (report_dir / "recovery_execution_summary.md").read_text()
        assert "# Recovery Execution Report" in md
        assert "## Status Counts" in md
        assert "## Type Counts" in md
        assert "## Executions" in md

    def test_pass_fail_passes_no_failed(
        self, engine: RecoveryExecutionEngine
    ) -> None:
        executions = [
            {"recommendation_id": "r1", "status": "succeeded"},
            {"recommendation_id": "r2", "status": "partial_success"},
        ]
        result = engine.create(executions=executions)
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True
        assert pf["status"] == "passed"

    def test_pass_fail_fails_on_failed(
        self, engine: RecoveryExecutionEngine
    ) -> None:
        result = engine.create(executions=_sample_executions())
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is False
        assert pf["failed_count"] == 1

    def test_pass_fail_empty_passes(
        self, engine: RecoveryExecutionEngine
    ) -> None:
        result = engine.create()
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, engine: RecoveryExecutionEngine) -> None:
        result = engine.create(executions=_sample_executions())
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]
        assert loaded["execution_count"] == 3

    def test_list_reports_deterministic(
        self, engine: RecoveryExecutionEngine
    ) -> None:
        engine.create(executions=_sample_executions())
        engine.create()
        reports = engine.list_reports()
        assert len(reports) == 2
        assert reports[0]["created_at"] <= reports[1]["created_at"]


# ---------------------------------------------------------------------------
# TestExport
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_returns_markdown(
        self, engine: RecoveryExecutionEngine
    ) -> None:
        result = engine.create(executions=_sample_executions())
        md = engine.export_report(result["report_id"])
        assert "# Recovery Execution Report" in md
        assert "RETRY_EXECUTED" in md

    def test_export_nonexistent_raises(
        self, engine: RecoveryExecutionEngine
    ) -> None:
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id-abc123")


# ---------------------------------------------------------------------------
# TestSafety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(
        self, engine: RecoveryExecutionEngine
    ) -> None:
        with pytest.raises(ValueError):
            engine.get_report("../../etc/passwd")

    def test_empty_id_rejected(self, engine: RecoveryExecutionEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("")

    def test_whitespace_id_rejected(
        self, engine: RecoveryExecutionEngine
    ) -> None:
        with pytest.raises(ValueError):
            engine.get_report("   ")

    def test_symlink_escape_rejected(
        self, engine: RecoveryExecutionEngine, tmp_path: Path
    ) -> None:
        target = tmp_path / "outside"
        target.mkdir()
        link = Path(engine._report_dir) / "evil-link"
        link.symlink_to(target)
        with pytest.raises(ValueError):
            engine.get_report("evil-link")

    def test_nonexistent_returns_none(
        self, engine: RecoveryExecutionEngine
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
            "recovery-execution-create",
            "recovery-execution-show",
            "recovery-execution-export",
        }
        assert expected.issubset(set(names))


# ---------------------------------------------------------------------------
# TestSelectionMapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_recovery_execution_mapped(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/recovery_execution.py"]
            == "tests/test_recovery_execution.py"
        )
