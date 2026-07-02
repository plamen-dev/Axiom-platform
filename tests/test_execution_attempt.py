"""Tests for the Execution Attempt Framework v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.execution_attempt import (
    ExecutionAttempt,
    ExecutionAttemptEngine,
    ExecutionAttemptEvidence,
    ExecutionAttemptReport,
    ExecutionAttemptStatus,
    ExecutionAttemptType,
)

from tests.conftest import make_symlink_or_skip


@pytest.fixture()
def engine(tmp_path: Path) -> ExecutionAttemptEngine:
    return ExecutionAttemptEngine(artifacts_root=str(tmp_path))


def _sample_attempts() -> list[dict]:
    return [
        {
            "work_id": "w1",
            "attempt_type": "implementation",
            "status": "succeeded",
            "started_at": "2026-01-01T00:00:00+00:00",
            "completed_at": "2026-01-01T00:00:05+00:00",
            "duration_ms": 5000,
            "created_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "work_id": "w2",
            "attempt_type": "validation",
            "status": "failed",
            "duration_ms": 1200,
            "created_at": "2026-01-02T00:00:00+00:00",
        },
        {
            "work_id": "w3",
            "attempt_type": "repair",
            "status": "partial_success",
            "duration_ms": 800,
            "created_at": "2026-01-03T00:00:00+00:00",
        },
    ]


# ---------------------------------------------------------------------------
# TestModels
# ---------------------------------------------------------------------------


class TestModels:
    def test_attempt_defaults(self) -> None:
        a = ExecutionAttempt()
        assert a.attempt_id
        assert a.created_at
        assert a.attempt_type == "implementation"
        assert a.status == "created"
        assert a.duration_ms == 0

    def test_report_defaults(self) -> None:
        r = ExecutionAttemptReport()
        assert r.report_id
        assert r.created_at
        assert r.attempt_count == 0

    def test_evidence_defaults(self) -> None:
        e = ExecutionAttemptEvidence()
        assert e.evidence_id
        assert e.created_at


# ---------------------------------------------------------------------------
# TestCreate
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_empty(self, engine: ExecutionAttemptEngine) -> None:
        result = engine.create()
        assert result["attempt_count"] == 0
        assert result["attempts"] == []

    def test_create_with_attempts(self, engine: ExecutionAttemptEngine) -> None:
        result = engine.create(attempts=_sample_attempts())
        assert result["attempt_count"] == 3

    def test_all_types(self, engine: ExecutionAttemptEngine) -> None:
        attempts = [
            {"work_id": f"w{t.value}", "attempt_type": t.value, "status": "created"}
            for t in ExecutionAttemptType
        ]
        result = engine.create(attempts=attempts)
        assert result["attempt_count"] == len(ExecutionAttemptType)

    def test_all_statuses(self, engine: ExecutionAttemptEngine) -> None:
        attempts = [
            {"work_id": f"w{s.value}", "attempt_type": "other", "status": s.value}
            for s in ExecutionAttemptStatus
        ]
        result = engine.create(attempts=attempts)
        assert result["attempt_count"] == len(ExecutionAttemptStatus)


# ---------------------------------------------------------------------------
# TestStatusCounts
# ---------------------------------------------------------------------------


class TestStatusCounts:
    def test_status_counts(self, engine: ExecutionAttemptEngine) -> None:
        result = engine.create(attempts=_sample_attempts())
        assert result["succeeded_count"] == 1
        assert result["failed_count"] == 1
        assert result["partial_success_count"] == 1
        assert result["cancelled_count"] == 0

    def test_cancelled_counted(self, engine: ExecutionAttemptEngine) -> None:
        attempts = [
            {"work_id": "w1", "attempt_type": "other", "status": "cancelled"},
            {"work_id": "w2", "attempt_type": "other", "status": "cancelled"},
        ]
        result = engine.create(attempts=attempts)
        assert result["cancelled_count"] == 2


# ---------------------------------------------------------------------------
# TestStatusPersistence
# ---------------------------------------------------------------------------


class TestStatusPersistence:
    def test_status_persisted(self, engine: ExecutionAttemptEngine) -> None:
        result = engine.create(attempts=_sample_attempts())
        by_work = {a["work_id"]: a for a in result["attempts"]}
        assert by_work["w1"]["status"] == "succeeded"
        assert by_work["w2"]["status"] == "failed"


# ---------------------------------------------------------------------------
# TestDurationPersistence
# ---------------------------------------------------------------------------


class TestDurationPersistence:
    def test_duration_persisted(self, engine: ExecutionAttemptEngine) -> None:
        result = engine.create(attempts=_sample_attempts())
        by_work = {a["work_id"]: a for a in result["attempts"]}
        assert by_work["w1"]["duration_ms"] == 5000
        assert by_work["w2"]["duration_ms"] == 1200

    def test_timestamps_persisted(self, engine: ExecutionAttemptEngine) -> None:
        result = engine.create(attempts=_sample_attempts())
        by_work = {a["work_id"]: a for a in result["attempts"]}
        assert by_work["w1"]["started_at"] == "2026-01-01T00:00:00+00:00"
        assert by_work["w1"]["completed_at"] == "2026-01-01T00:00:05+00:00"


# ---------------------------------------------------------------------------
# TestValidation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_type_rejected(self, engine: ExecutionAttemptEngine) -> None:
        with pytest.raises(ValueError, match="Invalid attempt_type"):
            engine.create(
                attempts=[{"work_id": "w1", "attempt_type": "teleport"}]
            )

    def test_invalid_status_rejected(self, engine: ExecutionAttemptEngine) -> None:
        with pytest.raises(ValueError, match="Invalid status"):
            engine.create(
                attempts=[{"work_id": "w1", "status": "exploded"}]
            )

    def test_missing_work_id_rejected(self, engine: ExecutionAttemptEngine) -> None:
        with pytest.raises(ValueError, match="work_id is required"):
            engine.create(attempts=[{"attempt_type": "review"}])

    def test_negative_duration_rejected(
        self, engine: ExecutionAttemptEngine
    ) -> None:
        with pytest.raises(ValueError, match="duration_ms must not be negative"):
            engine.create(
                attempts=[{"work_id": "w1", "duration_ms": -1}]
            )


# ---------------------------------------------------------------------------
# TestDeterministicOrdering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_attempts_ordered(self, engine: ExecutionAttemptEngine) -> None:
        result = engine.create(attempts=_sample_attempts())
        created = [a["created_at"] for a in result["attempts"]]
        assert created == sorted(created)

    def test_order_independent(self, engine: ExecutionAttemptEngine) -> None:
        r1 = engine.create(attempts=_sample_attempts())
        r2 = engine.create(attempts=list(reversed(_sample_attempts())))
        keys1 = [(a["created_at"], a["work_id"]) for a in r1["attempts"]]
        keys2 = [(a["created_at"], a["work_id"]) for a in r2["attempts"]]
        assert keys1 == keys2


# ---------------------------------------------------------------------------
# TestEvidenceGeneration
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_four_files_created(self, engine: ExecutionAttemptEngine) -> None:
        result = engine.create(attempts=_sample_attempts())
        report_dir = Path(engine._report_dir) / result["report_id"]
        expected = {
            "execution_attempt_request.json",
            "execution_attempt_result.json",
            "execution_attempt_summary.md",
            "pass_fail.json",
        }
        actual = {f.name for f in report_dir.iterdir() if f.is_file()}
        assert expected.issubset(actual)

    def test_request_valid_json(self, engine: ExecutionAttemptEngine) -> None:
        result = engine.create(attempts=_sample_attempts())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads(
            (report_dir / "execution_attempt_request.json").read_text()
        )
        assert len(data["attempts"]) == 3

    def test_summary_has_sections(self, engine: ExecutionAttemptEngine) -> None:
        result = engine.create(attempts=_sample_attempts())
        report_dir = Path(engine._report_dir) / result["report_id"]
        md = (report_dir / "execution_attempt_summary.md").read_text()
        assert "# Execution Attempt Report" in md
        assert "## Status Counts" in md
        assert "## Attempts" in md

    def test_pass_fail_passes_no_failures(
        self, engine: ExecutionAttemptEngine
    ) -> None:
        attempts = [
            {"work_id": "w1", "attempt_type": "review", "status": "succeeded"},
        ]
        result = engine.create(attempts=attempts)
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True

    def test_pass_fail_fails_on_failure(
        self, engine: ExecutionAttemptEngine
    ) -> None:
        result = engine.create(attempts=_sample_attempts())
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is False
        assert pf["failed_count"] == 1

    def test_pass_fail_empty_passes(self, engine: ExecutionAttemptEngine) -> None:
        result = engine.create()
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, engine: ExecutionAttemptEngine) -> None:
        result = engine.create(attempts=_sample_attempts())
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]
        assert loaded["attempt_count"] == 3

    def test_list_reports_deterministic(
        self, engine: ExecutionAttemptEngine
    ) -> None:
        engine.create(attempts=_sample_attempts())
        engine.create()
        reports = engine.list_reports()
        assert len(reports) == 2
        assert reports[0]["created_at"] <= reports[1]["created_at"]


# ---------------------------------------------------------------------------
# TestExport
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_returns_markdown(self, engine: ExecutionAttemptEngine) -> None:
        result = engine.create(attempts=_sample_attempts())
        md = engine.export_report(result["report_id"])
        assert "# Execution Attempt Report" in md
        assert "IMPLEMENTATION" in md

    def test_export_nonexistent_raises(
        self, engine: ExecutionAttemptEngine
    ) -> None:
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id-abc123")


# ---------------------------------------------------------------------------
# TestSafety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(self, engine: ExecutionAttemptEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("../../etc/passwd")

    def test_empty_id_rejected(self, engine: ExecutionAttemptEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("")

    def test_whitespace_id_rejected(self, engine: ExecutionAttemptEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("   ")

    def test_symlink_escape_rejected(
        self, engine: ExecutionAttemptEngine, tmp_path: Path
    ) -> None:
        target = tmp_path / "outside"
        target.mkdir()
        link = Path(engine._report_dir) / "evil-link"
        make_symlink_or_skip(link, target)
        with pytest.raises(ValueError):
            engine.get_report("evil-link")

    def test_nonexistent_returns_none(
        self, engine: ExecutionAttemptEngine
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
            "execution-attempt-create",
            "execution-attempt-show",
            "execution-attempt-export",
        }
        assert expected.issubset(set(names))


# ---------------------------------------------------------------------------
# TestSelectionMapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_execution_attempt_mapped(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/execution_attempt.py"]
            == "tests/test_execution_attempt.py"
        )
