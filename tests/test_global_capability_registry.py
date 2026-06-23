"""Comprehensive tests for Global Capability Registry Framework v1."""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from pathlib import Path

import pytest
from axiom_core.global_capability_registry import (
    SCHEMA_VERSION,
    GlobalCapabilityEntry,
    GlobalCapabilityEvidence,
    GlobalCapabilityRegistry,
    GlobalCapabilityRegistryEngine,
    GlobalCapabilityReport,
    GlobalCapabilityRepositoryRef,
    GlobalCapabilityStatus,
    GlobalCapabilityValidationSummary,
    GlobalCapabilityWorkerRef,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tmp_engine() -> GlobalCapabilityRegistryEngine:
    tmp = tempfile.mkdtemp()
    return GlobalCapabilityRegistryEngine(artifacts_root=tmp)


def _entry(number: int, name: str, **overrides) -> dict:
    data = {
        "global_capability_number": number,
        "capability_name": name,
        "status": "merged",
        "primary_program": "program-1",
        "worker": {"worker_id": "w-1", "worker_type": "devin"},
        "repository": {
            "repository_owner": "plamen-dev",
            "repository_name": "Axiom-platform",
            "repository_pr_number": number - 111,
            "repository_pr_url": f"https://github.com/plamen-dev/Axiom-platform/pull/{number - 111}",
            "branch_name": f"devin/{number}-x",
            "commit_sha": f"sha{number}",
            "merge_sha": f"msha{number}",
        },
        "validation": {
            "new_tests": 40,
            "total_tests": 3800 + number,
            "skipped_tests": 1,
            "ruff_clean": True,
            "ci_status": "green",
        },
        "created_at": f"2026-06-{number:02d}T00:00:00+00:00",
    }
    data.update(overrides)
    return data


def _basic_entries() -> list[dict]:
    return [
        _entry(121, "Capability Chain Framework"),
        _entry(112, "Execution Outcome Framework"),
    ]


# ---------------------------------------------------------------------------
# TestModels
# ---------------------------------------------------------------------------


class TestModels:
    def test_repository_ref_round_trip(self):
        ref = GlobalCapabilityRepositoryRef(
            repository_owner="o", repository_name="r", repository_pr_number=5
        )
        d = ref.to_dict()
        assert d["repository_owner"] == "o"
        assert d["repository_pr_number"] == 5
        restored = GlobalCapabilityRepositoryRef.from_dict(d)
        assert restored == ref

    def test_worker_ref_round_trip(self):
        ref = GlobalCapabilityWorkerRef(worker_id="w", worker_type="devin")
        restored = GlobalCapabilityWorkerRef.from_dict(ref.to_dict())
        assert restored == ref

    def test_validation_summary_round_trip(self):
        v = GlobalCapabilityValidationSummary(
            new_tests=10, total_tests=100, ruff_clean=True, ci_status="green"
        )
        restored = GlobalCapabilityValidationSummary.from_dict(v.to_dict())
        assert restored == v

    def test_entry_defaults(self):
        entry = GlobalCapabilityEntry(global_capability_number=1, capability_name="x")
        assert entry.global_capability_id
        assert entry.created_at
        assert entry.updated_at == entry.created_at
        assert entry.schema_version == SCHEMA_VERSION
        assert entry.status == "proposed"
        assert entry.raw_metadata == {}

    def test_entry_serialization_nested(self):
        entry = GlobalCapabilityEntry(
            global_capability_number=1,
            capability_name="x",
            worker=GlobalCapabilityWorkerRef(worker_id="w"),
            repository=GlobalCapabilityRepositoryRef(repository_owner="o"),
        )
        d = entry.to_dict()
        assert d["worker"]["worker_id"] == "w"
        assert d["repository"]["repository_owner"] == "o"
        assert "validation" in d

    def test_registry_to_dict(self):
        reg = GlobalCapabilityRegistry(
            entries=[GlobalCapabilityEntry(global_capability_number=1, capability_name="x")]
        )
        assert len(reg.to_dict()["entries"]) == 1

    def test_report_defaults(self):
        report = GlobalCapabilityReport()
        assert report.report_id
        assert report.entry_count == 0
        assert report.schema_version == SCHEMA_VERSION

    def test_evidence_defaults(self):
        ev = GlobalCapabilityEvidence(report_id="r", summary="s")
        assert ev.evidence_id
        assert ev.created_at

    def test_status_enum_values(self):
        assert GlobalCapabilityStatus.PROPOSED.value == "proposed"
        assert GlobalCapabilityStatus.OPEN.value == "open"
        assert GlobalCapabilityStatus.MERGED.value == "merged"
        assert GlobalCapabilityStatus.CLOSED.value == "closed"
        assert GlobalCapabilityStatus.SUPERSEDED.value == "superseded"


# ---------------------------------------------------------------------------
# TestCreate
# ---------------------------------------------------------------------------


class TestCreate:
    def test_empty_create(self):
        engine = _tmp_engine()
        report = engine.create()
        assert report["entry_count"] == 0
        assert report["status_counts"] == {}
        assert report["program_counts"] == {}
        assert report["entries"] == []

    def test_create_with_entries(self):
        engine = _tmp_engine()
        report = engine.create(entries=_basic_entries())
        assert report["entry_count"] == 2

    def test_schema_version_present(self):
        engine = _tmp_engine()
        report = engine.create(entries=_basic_entries())
        assert report["schema_version"] == SCHEMA_VERSION

    def test_status_counts(self):
        engine = _tmp_engine()
        entries = [
            _entry(112, "a", status="merged"),
            _entry(113, "b", status="merged"),
            _entry(114, "c", status="open"),
        ]
        report = engine.create(entries=entries)
        assert report["status_counts"]["merged"] == 2
        assert report["status_counts"]["open"] == 1

    def test_program_counts(self):
        engine = _tmp_engine()
        entries = [
            _entry(112, "a", primary_program="program-1"),
            _entry(113, "b", primary_program="program-2"),
        ]
        report = engine.create(entries=entries)
        assert report["program_counts"]["program-1"] == 1
        assert report["program_counts"]["program-2"] == 1

    def test_status_counts_sorted_keys(self):
        engine = _tmp_engine()
        entries = [
            _entry(112, "a", status="open"),
            _entry(113, "b", status="closed"),
            _entry(114, "c", status="merged"),
        ]
        report = engine.create(entries=entries)
        keys = list(report["status_counts"].keys())
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# TestDuplicateRejection
# ---------------------------------------------------------------------------


class TestDuplicateRejection:
    def test_duplicate_global_number_rejected(self):
        engine = _tmp_engine()
        entries = [
            _entry(112, "a"),
            _entry(112, "b"),
        ]
        with pytest.raises(ValueError, match="Duplicate global_capability_number"):
            engine.create(entries=entries)

    def test_missing_global_number_rejected(self):
        engine = _tmp_engine()
        with pytest.raises(ValueError, match="global_capability_number is required"):
            engine.create(entries=[{"capability_name": "x"}])

    def test_missing_capability_name_rejected(self):
        engine = _tmp_engine()
        with pytest.raises(ValueError, match="capability_name is required"):
            engine.create(entries=[{"global_capability_number": 1, "capability_name": ""}])

    def test_invalid_status_rejected(self):
        engine = _tmp_engine()
        with pytest.raises(ValueError, match="Invalid status"):
            engine.create(entries=[_entry(112, "a", status="bogus")])


# ---------------------------------------------------------------------------
# TestOrdering
# ---------------------------------------------------------------------------


class TestOrdering:
    def test_ordered_by_global_number(self):
        engine = _tmp_engine()
        entries = [
            _entry(121, "later"),
            _entry(112, "earlier"),
            _entry(115, "middle"),
        ]
        report = engine.create(entries=entries)
        numbers = [e["global_capability_number"] for e in report["entries"]]
        assert numbers == [112, 115, 121]

    def test_order_independent(self):
        engine = _tmp_engine()
        entries_a = [_entry(112, "a"), _entry(113, "b"), _entry(114, "c")]
        entries_b = list(reversed(entries_a))
        r1 = engine.create(entries=entries_a)
        r2 = engine.create(entries=entries_b)
        assert [e["global_capability_number"] for e in r1["entries"]] == [
            e["global_capability_number"] for e in r2["entries"]
        ]

    def test_tie_break_by_created_at(self):
        # Same number is impossible (rejected), so tie-break uses later keys
        # via distinct numbers but identical timestamps still ordered by number.
        engine = _tmp_engine()
        entries = [
            _entry(113, "b", created_at="2026-06-01T00:00:00+00:00"),
            _entry(112, "a", created_at="2026-06-01T00:00:00+00:00"),
        ]
        report = engine.create(entries=entries)
        numbers = [e["global_capability_number"] for e in report["entries"]]
        assert numbers == [112, 113]


# ---------------------------------------------------------------------------
# TestRawMetadataAndSchema
# ---------------------------------------------------------------------------


class TestRawMetadataAndSchema:
    def test_raw_metadata_preserved(self):
        engine = _tmp_engine()
        meta = {"custom": "value", "nested": {"a": 1}}
        report = engine.create(entries=[_entry(112, "a", raw_metadata=meta)])
        assert report["entries"][0]["raw_metadata"] == meta

    def test_custom_schema_version_preserved(self):
        engine = _tmp_engine()
        report = engine.create(
            entries=[_entry(112, "a", schema_version="2.5")]
        )
        assert report["entries"][0]["schema_version"] == "2.5"

    def test_relationship_fields_preserved(self):
        engine = _tmp_engine()
        report = engine.create(entries=[_entry(
            112, "a",
            secondary_programs=["program-2", "program-3"],
            parent_capability_ids=["gc-110"],
            related_capability_ids=["gc-111"],
            affected_files=["src/x.py", "tests/test_x.py"],
        )])
        e = report["entries"][0]
        assert e["secondary_programs"] == ["program-2", "program-3"]
        assert e["parent_capability_ids"] == ["gc-110"]
        assert e["related_capability_ids"] == ["gc-111"]
        assert e["affected_files"] == ["src/x.py", "tests/test_x.py"]


# ---------------------------------------------------------------------------
# TestEvidenceGeneration
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_evidence_files_created(self):
        engine = _tmp_engine()
        report = engine.create(entries=_basic_entries())
        report_dir = Path(engine._report_dir) / report["report_id"]
        expected = {
            "global_capability_request.json",
            "global_capability_result.json",
            "global_capability_summary.md",
            "global_capability_timeline.csv",
            "pass_fail.json",
            "report.json",
        }
        assert expected == set(os.listdir(report_dir))

    def test_pass_fail_passed_when_entries(self):
        engine = _tmp_engine()
        report = engine.create(entries=_basic_entries())
        report_dir = Path(engine._report_dir) / report["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True
        assert pf["status"] == "passed"

    def test_pass_fail_failed_when_empty(self):
        engine = _tmp_engine()
        report = engine.create(entries=[])
        report_dir = Path(engine._report_dir) / report["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is False
        assert pf["status"] == "failed"

    def test_summary_md_sections(self):
        engine = _tmp_engine()
        report = engine.create(entries=_basic_entries())
        report_dir = Path(engine._report_dir) / report["report_id"]
        md = (report_dir / "global_capability_summary.md").read_text()
        assert "# Global Capability Registry" in md
        assert "## Status Counts" in md
        assert "## Timeline" in md

    def test_timeline_csv_valid(self):
        engine = _tmp_engine()
        report = engine.create(entries=_basic_entries())
        report_dir = Path(engine._report_dir) / report["report_id"]
        content = (report_dir / "global_capability_timeline.csv").read_text()
        rows = list(csv.reader(io.StringIO(content)))
        assert rows[0][0] == "global_capability_number"
        assert len(rows) == 3  # header + 2 entries


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self):
        engine = _tmp_engine()
        report = engine.create(entries=_basic_entries())
        loaded = engine.get_report(report["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == report["report_id"]

    def test_round_trip_identical(self):
        engine = _tmp_engine()
        report = engine.create(entries=_basic_entries())
        loaded = engine.get_report(report["report_id"])
        assert loaded == report

    def test_list_reports(self):
        engine = _tmp_engine()
        r1 = engine.create(entries=[_entry(112, "a")])
        r2 = engine.create(entries=[_entry(113, "b")])
        reports = engine.list_reports()
        ids = [r["report_id"] for r in reports]
        assert r1["report_id"] in ids
        assert r2["report_id"] in ids

    def test_nonexistent_returns_none(self):
        engine = _tmp_engine()
        assert engine.get_report("nonexistent") is None


# ---------------------------------------------------------------------------
# TestExport
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_markdown(self):
        engine = _tmp_engine()
        report = engine.create(entries=_basic_entries())
        md = engine.export_report(report["report_id"], fmt="markdown")
        assert "# Global Capability Registry" in md
        assert "## Timeline" in md
        assert "#112" in md
        assert "#121" in md

    def test_export_json(self):
        engine = _tmp_engine()
        report = engine.create(entries=_basic_entries())
        out = engine.export_report(report["report_id"], fmt="json")
        parsed = json.loads(out)
        assert parsed["entry_count"] == 2

    def test_export_csv(self):
        engine = _tmp_engine()
        report = engine.create(entries=_basic_entries())
        out = engine.export_report(report["report_id"], fmt="csv")
        rows = list(csv.reader(io.StringIO(out)))
        assert rows[0][0] == "global_capability_number"
        assert len(rows) == 3
        # ordered by global number ascending
        assert rows[1][0] == "112"
        assert rows[2][0] == "121"

    def test_export_default_is_markdown(self):
        engine = _tmp_engine()
        report = engine.create(entries=_basic_entries())
        out = engine.export_report(report["report_id"])
        assert "# Global Capability Registry" in out

    def test_export_invalid_format_rejected(self):
        engine = _tmp_engine()
        report = engine.create(entries=_basic_entries())
        with pytest.raises(ValueError, match="Invalid export format"):
            engine.export_report(report["report_id"], fmt="xml")

    def test_export_nonexistent_raises(self):
        engine = _tmp_engine()
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent")


# ---------------------------------------------------------------------------
# TestSafety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(self):
        engine = _tmp_engine()
        with pytest.raises(ValueError):
            engine.get_report("../../etc")

    def test_empty_id_rejected(self):
        engine = _tmp_engine()
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("")

    def test_slash_in_id_rejected(self):
        engine = _tmp_engine()
        with pytest.raises(ValueError):
            engine.get_report("foo/bar")

    def test_backslash_in_id_rejected(self):
        engine = _tmp_engine()
        with pytest.raises(ValueError):
            engine.get_report("foo\\bar")


# ---------------------------------------------------------------------------
# TestCommandRegistryIntegration
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_global_capability_commands_registered(self):
        from axiom_core.runner.command_registry import command_names

        names = command_names()
        assert "global-capability-create" in names
        assert "global-capability-list" in names
        assert "global-capability-show" in names
        assert "global-capability-export" in names


# ---------------------------------------------------------------------------
# TestSelectionMapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_global_capability_mapping_exists(self):
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/global_capability_registry.py"]
            == "tests/test_global_capability_registry.py"
        )
