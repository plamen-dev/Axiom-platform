"""Tests for the Work Queue Framework v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.work_queue import (
    WorkItem,
    WorkPriority,
    WorkQueue,
    WorkQueueEngine,
    WorkQueueReport,
    WorkStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine(tmp_path: Path) -> WorkQueueEngine:
    return WorkQueueEngine(artifacts_root=str(tmp_path))


def _sample_items() -> list[dict]:
    return [
        {"title": "low task", "priority": "low", "status": "pending"},
        {"title": "critical task", "priority": "critical", "status": "running"},
        {"title": "normal task", "priority": "normal", "status": "completed"},
        {"title": "high task", "priority": "high", "status": "failed"},
    ]


# ---------------------------------------------------------------------------
# TestModels
# ---------------------------------------------------------------------------


class TestModels:
    def test_work_item_defaults(self) -> None:
        w = WorkItem()
        assert w.work_id
        assert w.created_at
        assert w.priority == "normal"
        assert w.status == "pending"

    def test_queue_defaults(self) -> None:
        q = WorkQueue()
        assert q.queue_id
        assert q.created_at
        assert q.work_items == []
        assert q.item_count == 0

    def test_report_defaults(self) -> None:
        r = WorkQueueReport()
        assert r.report_id
        assert r.created_at
        assert r.pending_count == 0
        assert r.failed_count == 0


# ---------------------------------------------------------------------------
# TestCreate
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_empty(self, engine: WorkQueueEngine) -> None:
        result = engine.create(work_items=[])
        assert result["queue"]["item_count"] == 0
        assert result["pending_count"] == 0

    def test_create_with_items(self, engine: WorkQueueEngine) -> None:
        result = engine.create(work_items=_sample_items())
        assert result["queue"]["item_count"] == 4

    def test_all_priorities(self, engine: WorkQueueEngine) -> None:
        items = [{"title": p.value, "priority": p.value} for p in WorkPriority]
        result = engine.create(work_items=items)
        assert result["queue"]["item_count"] == len(WorkPriority)

    def test_all_statuses(self, engine: WorkQueueEngine) -> None:
        items = [{"title": s.value, "status": s.value} for s in WorkStatus]
        result = engine.create(work_items=items)
        assert result["queue"]["item_count"] == len(WorkStatus)


# ---------------------------------------------------------------------------
# TestStatusCounts
# ---------------------------------------------------------------------------


class TestStatusCounts:
    def test_counts(self, engine: WorkQueueEngine) -> None:
        result = engine.create(work_items=_sample_items())
        assert result["pending_count"] == 1
        assert result["running_count"] == 1
        assert result["completed_count"] == 1
        assert result["failed_count"] == 1
        assert result["blocked_count"] == 0


# ---------------------------------------------------------------------------
# TestPersistencePriorityStatus
# ---------------------------------------------------------------------------


class TestPersistencePriorityStatus:
    def test_priority_persisted(self, engine: WorkQueueEngine) -> None:
        result = engine.create(work_items=_sample_items())
        by_title = {w["title"]: w for w in result["queue"]["work_items"]}
        assert by_title["critical task"]["priority"] == "critical"
        assert by_title["low task"]["priority"] == "low"

    def test_status_persisted(self, engine: WorkQueueEngine) -> None:
        result = engine.create(work_items=_sample_items())
        by_title = {w["title"]: w for w in result["queue"]["work_items"]}
        assert by_title["high task"]["status"] == "failed"
        assert by_title["normal task"]["status"] == "completed"


# ---------------------------------------------------------------------------
# TestValidation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_priority_rejected(self, engine: WorkQueueEngine) -> None:
        with pytest.raises(ValueError, match="Invalid priority"):
            engine.create(work_items=[{"title": "x", "priority": "urgent"}])

    def test_invalid_status_rejected(self, engine: WorkQueueEngine) -> None:
        with pytest.raises(ValueError, match="Invalid status"):
            engine.create(work_items=[{"title": "x", "status": "paused"}])


# ---------------------------------------------------------------------------
# TestDeterministicOrdering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_items_ordered_by_priority(self, engine: WorkQueueEngine) -> None:
        result = engine.create(work_items=_sample_items())
        priorities = [w["priority"] for w in result["queue"]["work_items"]]
        assert priorities == ["critical", "high", "normal", "low"]

    def test_stable_for_same_priority(self, engine: WorkQueueEngine) -> None:
        items = [
            {"title": "b", "priority": "high", "created_at": "2026-01-02T00:00:00+00:00"},
            {"title": "a", "priority": "high", "created_at": "2026-01-01T00:00:00+00:00"},
        ]
        result = engine.create(work_items=items)
        titles = [w["title"] for w in result["queue"]["work_items"]]
        assert titles == ["a", "b"]


# ---------------------------------------------------------------------------
# TestEvidenceGeneration
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_four_files_created(self, engine: WorkQueueEngine) -> None:
        result = engine.create(work_items=_sample_items())
        report_dir = Path(engine._report_dir) / result["report_id"]
        expected = {
            "work_queue_request.json",
            "work_queue_result.json",
            "work_queue_summary.md",
            "pass_fail.json",
        }
        actual = {f.name for f in report_dir.iterdir() if f.is_file()}
        assert expected.issubset(actual)

    def test_request_valid_json(self, engine: WorkQueueEngine) -> None:
        result = engine.create(work_items=_sample_items())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads((report_dir / "work_queue_request.json").read_text())
        assert len(data["work_items"]) == 4

    def test_result_valid_json(self, engine: WorkQueueEngine) -> None:
        result = engine.create(work_items=_sample_items())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads((report_dir / "work_queue_result.json").read_text())
        assert data["queue"]["item_count"] == 4

    def test_summary_has_header(self, engine: WorkQueueEngine) -> None:
        result = engine.create(work_items=_sample_items())
        report_dir = Path(engine._report_dir) / result["report_id"]
        md = (report_dir / "work_queue_summary.md").read_text()
        assert "# Work Queue Report" in md
        assert "## Status Counts" in md
        assert "## Work Items" in md

    def test_pass_fail_fails_with_failed_item(self, engine: WorkQueueEngine) -> None:
        result = engine.create(work_items=_sample_items())
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is False
        assert pf["failed_count"] == 1

    def test_pass_fail_passes_without_failed_item(self, engine: WorkQueueEngine) -> None:
        items = [{"title": "ok", "priority": "normal", "status": "completed"}]
        result = engine.create(work_items=items)
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True

    def test_pass_fail_empty_passes(self, engine: WorkQueueEngine) -> None:
        result = engine.create(work_items=[])
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, engine: WorkQueueEngine) -> None:
        result = engine.create(work_items=_sample_items())
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]
        assert loaded["queue"]["item_count"] == 4

    def test_list_reports_deterministic(self, engine: WorkQueueEngine) -> None:
        engine.create(work_items=_sample_items())
        engine.create(work_items=[])
        reports = engine.list_reports()
        assert len(reports) == 2
        assert reports[0]["created_at"] <= reports[1]["created_at"]


# ---------------------------------------------------------------------------
# TestExport
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_returns_markdown(self, engine: WorkQueueEngine) -> None:
        result = engine.create(work_items=_sample_items())
        md = engine.export_report(result["report_id"])
        assert "# Work Queue Report" in md
        assert "CRITICAL" in md

    def test_export_nonexistent_raises(self, engine: WorkQueueEngine) -> None:
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id-abc123")


# ---------------------------------------------------------------------------
# TestSafety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(self, engine: WorkQueueEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("../../etc/passwd")

    def test_empty_id_rejected(self, engine: WorkQueueEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("")

    def test_whitespace_id_rejected(self, engine: WorkQueueEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("   ")

    def test_symlink_escape_rejected(self, engine: WorkQueueEngine, tmp_path: Path) -> None:
        target = tmp_path / "outside"
        target.mkdir()
        link = Path(engine._report_dir) / "evil-link"
        link.symlink_to(target)
        with pytest.raises(ValueError):
            engine.get_report("evil-link")

    def test_nonexistent_returns_none(self, engine: WorkQueueEngine) -> None:
        result = engine.get_report("valid-but-missing-id")
        assert result is None


# ---------------------------------------------------------------------------
# TestCommandRegistryIntegration
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_commands_registered(self) -> None:
        from axiom_core.runner.command_registry import command_names

        names = command_names()
        expected = {"work-create", "work-show", "work-export"}
        assert expected.issubset(set(names))


# ---------------------------------------------------------------------------
# TestSelectionMapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_work_queue_mapped(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/work_queue.py"]
            == "tests/test_work_queue.py"
        )
