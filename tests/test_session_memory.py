"""Tests for the Session Memory Framework v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.session_memory import (
    SessionMemory,
    SessionMemoryEngine,
    SessionMemoryEntry,
    SessionMemoryEvidence,
    SessionMemoryReport,
    SessionMemoryType,
)


@pytest.fixture()
def engine(tmp_path: Path) -> SessionMemoryEngine:
    return SessionMemoryEngine(artifacts_root=str(tmp_path))


def _sample_entries() -> list[dict]:
    return [
        {
            "memory_type": "attempt",
            "source_id": "a1",
            "summary": "attempt recorded",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "memory_type": "outcome",
            "source_id": "o1",
            "created_at": "2026-01-02T00:00:00+00:00",
        },
        {
            "memory_type": "failure",
            "source_id": "f1",
            "created_at": "2026-01-03T00:00:00+00:00",
        },
    ]


# ---------------------------------------------------------------------------
# TestModels
# ---------------------------------------------------------------------------


class TestModels:
    def test_entry_defaults(self) -> None:
        e = SessionMemoryEntry()
        assert e.entry_id
        assert e.created_at
        assert e.memory_type == "observation"

    def test_memory_defaults(self) -> None:
        m = SessionMemory()
        assert m.memory_id
        assert m.created_at
        assert m.entry_count == 0

    def test_report_defaults(self) -> None:
        r = SessionMemoryReport()
        assert r.report_id
        assert r.created_at
        assert r.entry_count == 0
        assert r.memory_type_counts == {}

    def test_evidence_defaults(self) -> None:
        e = SessionMemoryEvidence()
        assert e.evidence_id
        assert e.created_at


# ---------------------------------------------------------------------------
# TestCreate
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_empty(self, engine: SessionMemoryEngine) -> None:
        result = engine.create()
        assert result["entry_count"] == 0
        assert result["entries"] == []
        assert result["memory_type_counts"] == {}

    def test_create_with_entries(self, engine: SessionMemoryEngine) -> None:
        result = engine.create(entries=_sample_entries())
        assert result["entry_count"] == 3

    def test_memory_id_present(self, engine: SessionMemoryEngine) -> None:
        result = engine.create(entries=_sample_entries())
        assert result["memory_id"]

    def test_all_types(self, engine: SessionMemoryEngine) -> None:
        entries = [
            {"memory_type": t.value, "source_id": f"s{t.value}"}
            for t in SessionMemoryType
        ]
        result = engine.create(entries=entries)
        assert result["entry_count"] == len(SessionMemoryType)


# ---------------------------------------------------------------------------
# TestTypeCounts
# ---------------------------------------------------------------------------


class TestTypeCounts:
    def test_type_counts(self, engine: SessionMemoryEngine) -> None:
        result = engine.create(entries=_sample_entries())
        counts = result["memory_type_counts"]
        assert counts["attempt"] == 1
        assert counts["outcome"] == 1
        assert counts["failure"] == 1

    def test_repeated_type_counted(self, engine: SessionMemoryEngine) -> None:
        entries = [
            {"memory_type": "observation", "source_id": "s1"},
            {"memory_type": "observation", "source_id": "s2"},
        ]
        result = engine.create(entries=entries)
        assert result["memory_type_counts"]["observation"] == 2

    def test_type_counts_sorted_keys(self, engine: SessionMemoryEngine) -> None:
        result = engine.create(entries=_sample_entries())
        keys = list(result["memory_type_counts"].keys())
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# TestTypePersistence
# ---------------------------------------------------------------------------


class TestTypePersistence:
    def test_memory_type_persisted(self, engine: SessionMemoryEngine) -> None:
        result = engine.create(entries=_sample_entries())
        by_source = {e["source_id"]: e for e in result["entries"]}
        assert by_source["a1"]["memory_type"] == "attempt"
        assert by_source["f1"]["memory_type"] == "failure"

    def test_source_and_summary_persisted(
        self, engine: SessionMemoryEngine
    ) -> None:
        result = engine.create(entries=_sample_entries())
        by_source = {e["source_id"]: e for e in result["entries"]}
        assert by_source["a1"]["source_id"] == "a1"
        assert by_source["a1"]["summary"] == "attempt recorded"


# ---------------------------------------------------------------------------
# TestSourceReferences
# ---------------------------------------------------------------------------


class TestSourceReferences:
    def test_source_ids_preserved(self, engine: SessionMemoryEngine) -> None:
        result = engine.create(entries=_sample_entries())
        sources = {e["source_id"] for e in result["entries"]}
        assert sources == {"a1", "o1", "f1"}


# ---------------------------------------------------------------------------
# TestValidation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_type_rejected(self, engine: SessionMemoryEngine) -> None:
        with pytest.raises(ValueError, match="Invalid memory_type"):
            engine.create(entries=[{"memory_type": "boom", "source_id": "s1"}])

    def test_missing_source_id_rejected(
        self, engine: SessionMemoryEngine
    ) -> None:
        with pytest.raises(ValueError, match="source_id is required"):
            engine.create(entries=[{"memory_type": "attempt"}])


# ---------------------------------------------------------------------------
# TestDeterministicOrdering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_entries_ordered(self, engine: SessionMemoryEngine) -> None:
        result = engine.create(entries=_sample_entries())
        created = [e["created_at"] for e in result["entries"]]
        assert created == sorted(created)

    def test_order_independent(self, engine: SessionMemoryEngine) -> None:
        r1 = engine.create(entries=_sample_entries())
        r2 = engine.create(entries=list(reversed(_sample_entries())))
        keys1 = [(e["created_at"], e["source_id"]) for e in r1["entries"]]
        keys2 = [(e["created_at"], e["source_id"]) for e in r2["entries"]]
        assert keys1 == keys2


# ---------------------------------------------------------------------------
# TestEvidenceGeneration
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_four_files_created(self, engine: SessionMemoryEngine) -> None:
        result = engine.create(entries=_sample_entries())
        report_dir = Path(engine._report_dir) / result["report_id"]
        expected = {
            "session_memory_request.json",
            "session_memory_result.json",
            "session_memory_summary.md",
            "pass_fail.json",
        }
        actual = {f.name for f in report_dir.iterdir() if f.is_file()}
        assert expected.issubset(actual)

    def test_request_valid_json(self, engine: SessionMemoryEngine) -> None:
        result = engine.create(entries=_sample_entries())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads(
            (report_dir / "session_memory_request.json").read_text()
        )
        assert len(data["entries"]) == 3

    def test_result_valid_json(self, engine: SessionMemoryEngine) -> None:
        result = engine.create(entries=_sample_entries())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads(
            (report_dir / "session_memory_result.json").read_text()
        )
        assert data["report_id"] == result["report_id"]
        assert data["entry_count"] == 3

    def test_summary_has_sections(self, engine: SessionMemoryEngine) -> None:
        result = engine.create(entries=_sample_entries())
        report_dir = Path(engine._report_dir) / result["report_id"]
        md = (report_dir / "session_memory_summary.md").read_text()
        assert "# Session Memory Report" in md
        assert "## Memory Summary" in md
        assert "## Type Counts" in md
        assert "## Entries" in md

    def test_pass_fail_passes_no_failure(
        self, engine: SessionMemoryEngine
    ) -> None:
        entries = [
            {"memory_type": "attempt", "source_id": "s1"},
            {"memory_type": "observation", "source_id": "s2"},
        ]
        result = engine.create(entries=entries)
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True
        assert pf["status"] == "passed"

    def test_pass_fail_fails_on_failure_entry(
        self, engine: SessionMemoryEngine
    ) -> None:
        result = engine.create(entries=_sample_entries())
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is False
        assert pf["failure_count"] == 1

    def test_pass_fail_empty_passes(self, engine: SessionMemoryEngine) -> None:
        result = engine.create()
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, engine: SessionMemoryEngine) -> None:
        result = engine.create(entries=_sample_entries())
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]
        assert loaded["entry_count"] == 3

    def test_list_reports_deterministic(
        self, engine: SessionMemoryEngine
    ) -> None:
        engine.create(entries=_sample_entries())
        engine.create()
        reports = engine.list_reports()
        assert len(reports) == 2
        assert reports[0]["created_at"] <= reports[1]["created_at"]


# ---------------------------------------------------------------------------
# TestExport
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_returns_markdown(self, engine: SessionMemoryEngine) -> None:
        result = engine.create(entries=_sample_entries())
        md = engine.export_report(result["report_id"])
        assert "# Session Memory Report" in md
        assert "ATTEMPT" in md

    def test_export_nonexistent_raises(
        self, engine: SessionMemoryEngine
    ) -> None:
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id-abc123")


# ---------------------------------------------------------------------------
# TestSafety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(self, engine: SessionMemoryEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("../../etc/passwd")

    def test_empty_id_rejected(self, engine: SessionMemoryEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("")

    def test_whitespace_id_rejected(self, engine: SessionMemoryEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("   ")

    def test_symlink_escape_rejected(
        self, engine: SessionMemoryEngine, tmp_path: Path
    ) -> None:
        target = tmp_path / "outside"
        target.mkdir()
        link = Path(engine._report_dir) / "evil-link"
        link.symlink_to(target)
        with pytest.raises(ValueError):
            engine.get_report("evil-link")

    def test_nonexistent_returns_none(
        self, engine: SessionMemoryEngine
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
            "session-memory-create",
            "session-memory-show",
            "session-memory-export",
        }
        assert expected.issubset(set(names))


# ---------------------------------------------------------------------------
# TestSelectionMapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_session_memory_mapped(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/session_memory.py"]
            == "tests/test_session_memory.py"
        )
