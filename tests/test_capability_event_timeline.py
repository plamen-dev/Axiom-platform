"""Comprehensive tests for Capability Event Timeline Framework v1."""

from __future__ import annotations

import csv
import io
import json
import tempfile

import pytest
from axiom_core.capability_event_timeline import (
    SCHEMA_VERSION,
    CapabilityEvent,
    CapabilityEventArtifact,
    CapabilityEventEvidence,
    CapabilityEventReference,
    CapabilityEventSummary,
    CapabilityEventTimeline,
    CapabilityEventTimelineEngine,
    CapabilityEventType,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tmp_engine() -> CapabilityEventTimelineEngine:
    tmp = tempfile.mkdtemp()
    return CapabilityEventTimelineEngine(artifacts_root=tmp)


def _event(seq: int, event_type: str, ts: str, **overrides) -> dict:
    data = {
        "global_capability_id": "gc-123",
        "timestamp": ts,
        "event_sequence": seq,
        "worker": "devin-1",
        "source": "session",
        "event_type": event_type,
        "summary": f"event {seq}",
        "references": [],
        "artifacts": [],
        "raw_payload": {},
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_reference_round_trip(self) -> None:
        ref = CapabilityEventReference(
            reference_type="pr_url",
            target="https://github.com/x/y/pull/1",
            label="PR",
        )
        assert CapabilityEventReference.from_dict(ref.to_dict()) == ref

    def test_artifact_round_trip(self) -> None:
        art = CapabilityEventArtifact(
            artifact_type="recording",
            path="rec.mp4",
            description="walkthrough",
        )
        assert CapabilityEventArtifact.from_dict(art.to_dict()) == art

    def test_event_defaults(self) -> None:
        e = CapabilityEvent(summary="x")
        assert e.event_id
        assert e.timestamp
        assert e.schema_version == SCHEMA_VERSION

    def test_event_to_dict_nested(self) -> None:
        e = CapabilityEvent(
            summary="x",
            references=[CapabilityEventReference(reference_type="file")],
            artifacts=[CapabilityEventArtifact(artifact_type="screenshot")],
            raw_payload={"k": "v"},
        )
        d = e.to_dict()
        assert d["references"][0]["reference_type"] == "file"
        assert d["artifacts"][0]["artifact_type"] == "screenshot"
        assert d["raw_payload"] == {"k": "v"}

    def test_timeline_defaults(self) -> None:
        t = CapabilityEventTimeline()
        assert t.timeline_id
        assert t.created_at

    def test_summary_defaults(self) -> None:
        s = CapabilityEventSummary()
        assert s.summary_id
        assert s.created_at

    def test_evidence_defaults(self) -> None:
        ev = CapabilityEventEvidence()
        assert ev.evidence_id
        assert ev.created_at

    def test_all_event_types_present(self) -> None:
        expected = {
            "pr_created",
            "ci_green",
            "review_started",
            "review_finding",
            "bug_fixed",
            "test_started",
            "test_completed",
            "artifact_created",
            "video_recorded",
            "screenshot_captured",
            "skill_proposed",
            "skill_approved",
            "pr_ready",
            "pr_merged",
            "warning",
            "note",
        }
        assert {t.value for t in CapabilityEventType} == expected


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_empty(self) -> None:
        engine = _tmp_engine()
        report = engine.create()
        assert report["event_count"] == 0
        assert report["events"] == []

    def test_create_with_events(self) -> None:
        engine = _tmp_engine()
        report = engine.create(
            global_capability_id="gc-123",
            events=[
                _event(1, "pr_created", "2026-06-01T00:00:00+00:00"),
                _event(2, "ci_green", "2026-06-01T01:00:00+00:00"),
            ],
        )
        assert report["event_count"] == 2
        assert report["global_capability_id"] == "gc-123"

    def test_create_event_type_counts_sorted(self) -> None:
        engine = _tmp_engine()
        report = engine.create(
            events=[
                _event(1, "note", "2026-06-01T00:00:00+00:00"),
                _event(2, "ci_green", "2026-06-01T01:00:00+00:00"),
                _event(3, "note", "2026-06-01T02:00:00+00:00"),
            ]
        )
        counts = report["summary"]["event_type_counts"]
        assert counts == {"ci_green": 1, "note": 2}
        assert list(counts) == sorted(counts)

    def test_create_first_last_timestamp(self) -> None:
        engine = _tmp_engine()
        report = engine.create(
            events=[
                _event(2, "note", "2026-06-02T00:00:00+00:00"),
                _event(1, "note", "2026-06-01T00:00:00+00:00"),
            ]
        )
        summary = report["summary"]
        assert summary["first_timestamp"] == "2026-06-01T00:00:00+00:00"
        assert summary["last_timestamp"] == "2026-06-02T00:00:00+00:00"

    def test_create_invalid_event_type_rejected(self) -> None:
        engine = _tmp_engine()
        with pytest.raises(ValueError, match="Invalid event_type"):
            engine.create(events=[_event(1, "bogus", "2026-06-01T00:00:00")])

    def test_create_missing_summary_rejected(self) -> None:
        engine = _tmp_engine()
        with pytest.raises(ValueError, match="summary is required"):
            engine.create(events=[_event(1, "note", "2026-06-01", summary="")])


# ---------------------------------------------------------------------------
# Ordering (authoritative)
# ---------------------------------------------------------------------------


class TestOrdering:
    def test_ordered_by_timestamp(self) -> None:
        engine = _tmp_engine()
        report = engine.create(
            events=[
                _event(3, "note", "2026-06-03T00:00:00+00:00"),
                _event(1, "note", "2026-06-01T00:00:00+00:00"),
                _event(2, "note", "2026-06-02T00:00:00+00:00"),
            ]
        )
        seqs = [e["event_sequence"] for e in report["events"]]
        assert seqs == [1, 2, 3]

    def test_order_independent_of_input(self) -> None:
        engine = _tmp_engine()
        events = [
            _event(1, "pr_created", "2026-06-01T00:00:00+00:00"),
            _event(2, "ci_green", "2026-06-01T01:00:00+00:00"),
            _event(3, "pr_merged", "2026-06-01T02:00:00+00:00"),
        ]
        r1 = engine.create(events=list(reversed(events)))
        r2 = engine.create(events=events)
        assert [e["event_sequence"] for e in r1["events"]] == [1, 2, 3]
        assert [e["event_sequence"] for e in r2["events"]] == [1, 2, 3]

    def test_tie_break_by_sequence_then_type(self) -> None:
        engine = _tmp_engine()
        # Same timestamp -> resolved by event_sequence then event_type.
        report = engine.create(
            events=[
                _event(2, "note", "2026-06-01T00:00:00+00:00"),
                _event(1, "warning", "2026-06-01T00:00:00+00:00"),
            ]
        )
        seqs = [e["event_sequence"] for e in report["events"]]
        assert seqs == [1, 2]

    def test_tie_break_same_seq_by_event_type(self) -> None:
        engine = _tmp_engine()
        report = engine.create(
            events=[
                _event(1, "note", "2026-06-01T00:00:00+00:00"),
                _event(1, "ci_green", "2026-06-01T00:00:00+00:00"),
            ]
        )
        types = [e["event_type"] for e in report["events"]]
        # "ci_green" < "note" lexicographically.
        assert types == ["ci_green", "note"]


# ---------------------------------------------------------------------------
# Append-only behavior
# ---------------------------------------------------------------------------


class TestAppendOnly:
    def test_append_preserves_existing(self) -> None:
        engine = _tmp_engine()
        report = engine.create(
            events=[_event(1, "pr_created", "2026-06-01T00:00:00+00:00")]
        )
        tid = report["timeline_id"]
        appended = engine.append(
            tid, events=[_event(2, "ci_green", "2026-06-01T01:00:00+00:00")]
        )
        assert appended["timeline_id"] == tid
        assert appended["event_count"] == 2
        seqs = [e["event_sequence"] for e in appended["events"]]
        assert seqs == [1, 2]

    def test_append_reorders_deterministically(self) -> None:
        engine = _tmp_engine()
        report = engine.create(
            events=[_event(2, "ci_green", "2026-06-02T00:00:00+00:00")]
        )
        tid = report["timeline_id"]
        appended = engine.append(
            tid,
            events=[_event(1, "pr_created", "2026-06-01T00:00:00+00:00")],
        )
        seqs = [e["event_sequence"] for e in appended["events"]]
        assert seqs == [1, 2]

    def test_append_keeps_event_ids(self) -> None:
        engine = _tmp_engine()
        report = engine.create(
            events=[_event(1, "pr_created", "2026-06-01T00:00:00+00:00")]
        )
        tid = report["timeline_id"]
        original_id = report["events"][0]["event_id"]
        appended = engine.append(
            tid, events=[_event(2, "ci_green", "2026-06-01T01:00:00+00:00")]
        )
        ids = [e["event_id"] for e in appended["events"]]
        assert original_id in ids

    def test_append_to_missing_raises(self) -> None:
        engine = _tmp_engine()
        with pytest.raises(ValueError, match="not found"):
            engine.append("does-not-exist", events=[])


# ---------------------------------------------------------------------------
# Raw payload & schema
# ---------------------------------------------------------------------------


class TestRawPayloadAndSchema:
    def test_raw_payload_preserved(self) -> None:
        engine = _tmp_engine()
        payload = {"nested": {"a": 1}, "list": [1, 2, 3]}
        report = engine.create(
            events=[
                _event(1, "note", "2026-06-01T00:00:00+00:00",
                       raw_payload=payload)
            ]
        )
        assert report["events"][0]["raw_payload"] == payload

    def test_custom_schema_version_preserved(self) -> None:
        engine = _tmp_engine()
        report = engine.create(
            events=[
                _event(1, "note", "2026-06-01T00:00:00+00:00",
                       schema_version="2.5")
            ]
        )
        assert report["events"][0]["schema_version"] == "2.5"

    def test_references_and_artifacts_preserved(self) -> None:
        engine = _tmp_engine()
        report = engine.create(
            events=[
                _event(
                    1, "artifact_created", "2026-06-01T00:00:00+00:00",
                    references=[
                        {"reference_type": "commit", "target": "abc123"}
                    ],
                    artifacts=[
                        {"artifact_type": "screenshot", "path": "s.png"}
                    ],
                )
            ]
        )
        e = report["events"][0]
        assert e["references"][0]["target"] == "abc123"
        assert e["artifacts"][0]["path"] == "s.png"


# ---------------------------------------------------------------------------
# Evidence generation
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_all_files_created(self) -> None:
        engine = _tmp_engine()
        report = engine.create(
            events=[_event(1, "pr_created", "2026-06-01T00:00:00+00:00")]
        )
        d = engine._safe_path(report["timeline_id"])
        for name in (
            "capability_event_request.json",
            "capability_event_result.json",
            "capability_event_summary.md",
            "capability_event_timeline.csv",
            "pass_fail.json",
            "report.json",
        ):
            assert (d / name).exists(), name

    def test_pass_fail_passed(self) -> None:
        engine = _tmp_engine()
        report = engine.create(
            events=[
                _event(1, "pr_created", "2026-06-01T00:00:00+00:00"),
                _event(2, "ci_green", "2026-06-01T01:00:00+00:00"),
            ]
        )
        d = engine._safe_path(report["timeline_id"])
        pf = json.loads((d / "pass_fail.json").read_text())
        assert pf["passed"] is True
        assert pf["status"] == "passed"

    def test_pass_fail_failed_empty(self) -> None:
        engine = _tmp_engine()
        report = engine.create(events=[])
        d = engine._safe_path(report["timeline_id"])
        pf = json.loads((d / "pass_fail.json").read_text())
        assert pf["passed"] is False

    def test_pass_fail_failed_on_duplicate_sequence(self) -> None:
        engine = _tmp_engine()
        report = engine.create(
            events=[
                _event(1, "note", "2026-06-01T00:00:00+00:00"),
                _event(1, "ci_green", "2026-06-01T01:00:00+00:00"),
            ]
        )
        d = engine._safe_path(report["timeline_id"])
        pf = json.loads((d / "pass_fail.json").read_text())
        assert pf["duplicate_sequence_count"] == 1
        assert pf["passed"] is False

    def test_summary_md_sections(self) -> None:
        engine = _tmp_engine()
        report = engine.create(
            events=[_event(1, "pr_created", "2026-06-01T00:00:00+00:00")]
        )
        d = engine._safe_path(report["timeline_id"])
        md = (d / "capability_event_summary.md").read_text()
        assert "# Capability Event Timeline" in md
        assert "## Summary" in md
        assert "## Event Type Counts" in md
        assert "## Timeline" in md

    def test_timeline_csv_valid(self) -> None:
        engine = _tmp_engine()
        report = engine.create(
            events=[
                _event(1, "pr_created", "2026-06-01T00:00:00+00:00"),
                _event(2, "ci_green", "2026-06-01T01:00:00+00:00"),
            ]
        )
        d = engine._safe_path(report["timeline_id"])
        rows = list(csv.reader(io.StringIO(
            (d / "capability_event_timeline.csv").read_text()
        )))
        assert rows[0][0] == "event_sequence"
        assert len(rows) == 3  # header + 2 events


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self) -> None:
        engine = _tmp_engine()
        report = engine.create(
            events=[_event(1, "note", "2026-06-01T00:00:00+00:00")]
        )
        fetched = engine.get_report(report["timeline_id"])
        assert fetched is not None
        assert fetched["timeline_id"] == report["timeline_id"]

    def test_round_trip_identical(self) -> None:
        engine = _tmp_engine()
        report = engine.create(
            events=[
                _event(1, "pr_created", "2026-06-01T00:00:00+00:00"),
                _event(2, "ci_green", "2026-06-01T01:00:00+00:00"),
            ]
        )
        fetched = engine.get_report(report["timeline_id"])
        assert fetched == report

    def test_list_reports(self) -> None:
        engine = _tmp_engine()
        engine.create(events=[_event(1, "note", "2026-06-01T00:00:00+00:00")])
        engine.create(events=[_event(1, "note", "2026-06-02T00:00:00+00:00")])
        assert len(engine.list_reports()) == 2

    def test_get_nonexistent_returns_none(self) -> None:
        engine = _tmp_engine()
        assert engine.get_report("nope") is None


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_markdown(self) -> None:
        engine = _tmp_engine()
        report = engine.create(
            events=[_event(1, "pr_created", "2026-06-01T00:00:00+00:00")]
        )
        out = engine.export_report(report["timeline_id"], fmt="markdown")
        assert "# Capability Event Timeline" in out
        assert "[PR_CREATED]" in out

    def test_export_json(self) -> None:
        engine = _tmp_engine()
        report = engine.create(
            events=[_event(1, "note", "2026-06-01T00:00:00+00:00")]
        )
        out = engine.export_report(report["timeline_id"], fmt="json")
        parsed = json.loads(out)
        assert parsed["event_count"] == 1

    def test_export_csv(self) -> None:
        engine = _tmp_engine()
        report = engine.create(
            events=[_event(1, "note", "2026-06-01T00:00:00+00:00")]
        )
        out = engine.export_report(report["timeline_id"], fmt="csv")
        rows = list(csv.reader(io.StringIO(out)))
        assert rows[0][0] == "event_sequence"

    def test_export_default_markdown(self) -> None:
        engine = _tmp_engine()
        report = engine.create(
            events=[_event(1, "note", "2026-06-01T00:00:00+00:00")]
        )
        out = engine.export_report(report["timeline_id"])
        assert "# Capability Event Timeline" in out

    def test_export_invalid_format(self) -> None:
        engine = _tmp_engine()
        report = engine.create(events=[])
        with pytest.raises(ValueError, match="Invalid export format"):
            engine.export_report(report["timeline_id"], fmt="xml")

    def test_export_nonexistent_raises(self) -> None:
        engine = _tmp_engine()
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("missing")


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(self) -> None:
        engine = _tmp_engine()
        with pytest.raises(ValueError, match="must not contain"):
            engine.get_report("../../etc")

    def test_empty_id_rejected(self) -> None:
        engine = _tmp_engine()
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("   ")

    def test_slash_rejected(self) -> None:
        engine = _tmp_engine()
        with pytest.raises(ValueError, match="must not contain"):
            engine.export_report("a/b")

    def test_backslash_rejected(self) -> None:
        engine = _tmp_engine()
        with pytest.raises(ValueError, match="must not contain"):
            engine.export_report("a\\b")


# ---------------------------------------------------------------------------
# Registry / selection integration
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_commands_registered(self) -> None:
        from axiom_core.runner.command_registry import command_names

        names = command_names()
        for name in (
            "capability-event-create",
            "capability-event-append",
            "capability-event-list",
            "capability-event-show",
            "capability-event-export",
        ):
            assert name in names


class TestSelectionMapping:
    def test_mapping_exists(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/capability_event_timeline.py"]
            == "tests/test_capability_event_timeline.py"
        )
