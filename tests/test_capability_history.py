"""Tests for the Capability History Framework v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.capability_history import (
    CapabilityHistory,
    CapabilityHistoryEngine,
    CapabilityHistoryEvent,
    CapabilityHistoryEventType,
    CapabilityHistoryEvidence,
    CapabilityHistoryReport,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine(tmp_path: Path) -> CapabilityHistoryEngine:
    return CapabilityHistoryEngine(artifacts_root=str(tmp_path))


def _sample_events() -> list[dict]:
    return [
        {
            "event_type": "capability_defined",
            "source_id": "cap-001",
            "summary": "Capability defined",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "event_type": "execution_reported",
            "source_id": "exec-001",
            "summary": "Execution recorded",
            "created_at": "2026-01-02T00:00:00+00:00",
        },
        {
            "event_type": "confidence_recorded",
            "source_id": "conf-001",
            "summary": "Confidence scored",
            "created_at": "2026-01-03T00:00:00+00:00",
        },
    ]


# ---------------------------------------------------------------------------
# TestModels
# ---------------------------------------------------------------------------


class TestModels:
    def test_event_defaults(self) -> None:
        e = CapabilityHistoryEvent()
        assert e.event_id
        assert e.created_at
        assert e.event_type == "no_action"

    def test_history_defaults(self) -> None:
        h = CapabilityHistory()
        assert h.history_id
        assert h.created_at
        assert h.events == []
        assert h.event_count == 0

    def test_report_defaults(self) -> None:
        r = CapabilityHistoryReport()
        assert r.report_id
        assert r.created_at
        assert r.event_count == 0

    def test_evidence_defaults(self) -> None:
        ev = CapabilityHistoryEvidence()
        assert ev.evidence_id
        assert ev.created_at


# ---------------------------------------------------------------------------
# TestCreate
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_empty(self, engine: CapabilityHistoryEngine) -> None:
        result = engine.create(capability_id="cap-empty", events=[])
        assert result["event_count"] == 0
        assert result["capability_id"] == "cap-empty"

    def test_create_with_events(self, engine: CapabilityHistoryEngine) -> None:
        result = engine.create(capability_id="cap-001", events=_sample_events())
        assert result["event_count"] == 3
        assert result["history"]["event_count"] == 3

    def test_create_all_event_types(self, engine: CapabilityHistoryEngine) -> None:
        events = [{"event_type": t.value, "summary": t.value} for t in CapabilityHistoryEventType]
        result = engine.create(capability_id="cap-all", events=events)
        assert result["event_count"] == len(CapabilityHistoryEventType)


# ---------------------------------------------------------------------------
# TestValidation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_valid_event_types(self, engine: CapabilityHistoryEngine) -> None:
        for t in CapabilityHistoryEventType:
            result = engine.create(
                capability_id="cap-v",
                events=[{"event_type": t.value, "summary": "x"}],
            )
            assert result["event_count"] == 1

    def test_invalid_event_type_rejected(self, engine: CapabilityHistoryEngine) -> None:
        with pytest.raises(ValueError, match="Invalid event_type"):
            engine.create(
                capability_id="cap-bad",
                events=[{"event_type": "exploded", "summary": "x"}],
            )


# ---------------------------------------------------------------------------
# TestDeterministicOrdering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_events_ordered_chronologically(self, engine: CapabilityHistoryEngine) -> None:
        events = [
            {
                "event_type": "confidence_recorded",
                "summary": "c",
                "created_at": "2026-01-03T00:00:00+00:00",
            },
            {
                "event_type": "capability_defined",
                "summary": "a",
                "created_at": "2026-01-01T00:00:00+00:00",
            },
            {
                "event_type": "execution_reported",
                "summary": "b",
                "created_at": "2026-01-02T00:00:00+00:00",
            },
        ]
        result = engine.create(capability_id="cap-order", events=events)
        timestamps = [e["created_at"] for e in result["history"]["events"]]
        assert timestamps == sorted(timestamps)
        types = [e["event_type"] for e in result["history"]["events"]]
        assert types == [
            "capability_defined",
            "execution_reported",
            "confidence_recorded",
        ]


# ---------------------------------------------------------------------------
# TestSourceReferences
# ---------------------------------------------------------------------------


class TestSourceReferences:
    def test_source_ids_preserved(self, engine: CapabilityHistoryEngine) -> None:
        result = engine.create(capability_id="cap-src", events=_sample_events())
        sources = [e["source_id"] for e in result["history"]["events"]]
        assert sources == ["cap-001", "exec-001", "conf-001"]


# ---------------------------------------------------------------------------
# TestEvidenceGeneration
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_four_files_created(self, engine: CapabilityHistoryEngine) -> None:
        result = engine.create(capability_id="cap-ev", events=_sample_events())
        report_dir = Path(engine._report_dir) / result["report_id"]
        expected = {
            "capability_history_request.json",
            "capability_history_result.json",
            "capability_history_summary.md",
            "pass_fail.json",
        }
        actual = {f.name for f in report_dir.iterdir() if f.is_file()}
        assert expected.issubset(actual)

    def test_request_valid_json(self, engine: CapabilityHistoryEngine) -> None:
        result = engine.create(capability_id="cap-req", events=_sample_events())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads((report_dir / "capability_history_request.json").read_text())
        assert data["capability_id"] == "cap-req"
        assert len(data["events"]) == 3

    def test_result_valid_json(self, engine: CapabilityHistoryEngine) -> None:
        result = engine.create(capability_id="cap-res", events=_sample_events())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads((report_dir / "capability_history_result.json").read_text())
        assert data["event_count"] == 3

    def test_summary_has_header(self, engine: CapabilityHistoryEngine) -> None:
        result = engine.create(capability_id="cap-sum", events=_sample_events())
        report_dir = Path(engine._report_dir) / result["report_id"]
        md = (report_dir / "capability_history_summary.md").read_text()
        assert "# Capability History Report" in md
        assert "## Timeline" in md

    def test_pass_fail_passes(self, engine: CapabilityHistoryEngine) -> None:
        result = engine.create(capability_id="cap-pf", events=_sample_events())
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True
        assert pf["event_count"] == 3


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, engine: CapabilityHistoryEngine) -> None:
        result = engine.create(capability_id="cap-get", events=_sample_events())
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]
        assert loaded["event_count"] == 3

    def test_list_reports_deterministic(self, engine: CapabilityHistoryEngine) -> None:
        engine.create(capability_id="a", events=_sample_events())
        engine.create(capability_id="b", events=[])
        reports = engine.list_reports()
        assert len(reports) == 2
        assert reports[0]["created_at"] <= reports[1]["created_at"]


# ---------------------------------------------------------------------------
# TestExport
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_returns_markdown(self, engine: CapabilityHistoryEngine) -> None:
        result = engine.create(capability_id="cap-exp", events=_sample_events())
        md = engine.export_report(result["report_id"])
        assert "# Capability History Report" in md
        assert "CAPABILITY_DEFINED" in md

    def test_export_nonexistent_raises(self, engine: CapabilityHistoryEngine) -> None:
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id-abc123")


# ---------------------------------------------------------------------------
# TestSafety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(self, engine: CapabilityHistoryEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("../../etc/passwd")

    def test_empty_id_rejected(self, engine: CapabilityHistoryEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("")

    def test_whitespace_id_rejected(self, engine: CapabilityHistoryEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("   ")

    def test_symlink_escape_rejected(self, engine: CapabilityHistoryEngine, tmp_path: Path) -> None:
        target = tmp_path / "outside"
        target.mkdir()
        link = Path(engine._report_dir) / "evil-link"
        link.symlink_to(target)
        with pytest.raises(ValueError):
            engine.get_report("evil-link")

    def test_nonexistent_returns_none(self, engine: CapabilityHistoryEngine) -> None:
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
            "capability-history-create",
            "capability-history-show",
            "capability-history-export",
        }
        assert expected.issubset(set(names))


# ---------------------------------------------------------------------------
# TestSelectionMapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_capability_history_mapped(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/capability_history.py"]
            == "tests/test_capability_history.py"
        )
