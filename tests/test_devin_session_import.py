"""Comprehensive tests for Devin Session Metadata Import Framework v1."""

from __future__ import annotations

import csv
import io
import json
import tempfile

import pytest
from axiom_core.devin_session_import import (
    SCHEMA_VERSION,
    DevinSessionActionMetadata,
    DevinSessionActionType,
    DevinSessionArtifactMetadata,
    DevinSessionArtifactType,
    DevinSessionImportEvidence,
    DevinSessionImportReport,
    DevinSessionImportStatus,
    DevinSessionMetadata,
    DevinSessionMetadataImport,
    DevinSessionMetadataImportEngine,
    DevinSessionSkillProposalMetadata,
    DevinSessionSkillProposalStatus,
    DevinSessionValidationMetadata,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tmp_engine() -> DevinSessionMetadataImportEngine:
    tmp = tempfile.mkdtemp()
    return DevinSessionMetadataImportEngine(artifacts_root=tmp)


def _metadata(**overrides) -> dict:
    data = {
        "session": {
            "session_id": "8ad1c9ac0d2f",
            "session_url": "https://app.devin.ai/sessions/8ad1c9ac0d2f",
            "worker_id": "devin",
            "worker_name": "Devin",
            "worker_type": "ai",
            "repository_owner": "plamen-dev",
            "repository_name": "Axiom-platform",
            "repository_pr_number": 15,
            "global_capability_number": 126,
            "capability_id": "gc-126",
            "capability_name": "PR #126 — Devin Session Metadata Import",
            "started_at": "2026-06-23T00:00:00+00:00",
            "completed_at": "2026-06-23T03:00:00+00:00",
            "status": "merged",
            "summary": "Implemented and tested the session import framework.",
        },
        # Deliberately out of chronological order to detect broken sorting.
        "actions": [
            {
                "action_id": "a-04",
                "timestamp": "2026-06-23T02:00:00+00:00",
                "action_type": "tested",
                "summary": "Ran adversarial CLI walkthrough",
            },
            {
                "action_id": "a-01",
                "timestamp": "2026-06-23T00:10:00+00:00",
                "action_type": "started",
                "summary": "Started work",
            },
            {
                "action_id": "a-03",
                "timestamp": "2026-06-23T01:30:00+00:00",
                "action_type": "fixed_finding",
                "summary": "Fixed a review finding",
            },
            {
                "action_id": "a-02",
                "timestamp": "2026-06-23T00:30:00+00:00",
                "action_type": "implemented",
                "summary": "Implemented the framework",
            },
            {
                "action_id": "a-05",
                "timestamp": "2026-06-23T02:30:00+00:00",
                "action_type": "reported_ready",
                "summary": "Reported PR merge-ready",
            },
        ],
        "artifacts": [
            {
                "artifact_id": "art-02",
                "artifact_type": "screenshot",
                "artifact_path": "ss_t1.png",
                "summary": "T1 output",
                "created_at": "2026-06-23T02:05:00+00:00",
            },
            {
                "artifact_id": "art-01",
                "artifact_type": "recording",
                "artifact_url": "https://example.com/rec.mp4",
                "summary": "CLI walkthrough recording",
                "created_at": "2026-06-23T02:10:00+00:00",
            },
        ],
        "validation": {
            "pytest_passed": 4099,
            "pytest_skipped": 1,
            "ruff_status": "clean",
            "ci_status": "green",
            "cli_testing_summary": "6/6 passed",
            "devin_review_status": "no findings",
            "devin_review_findings": 0,
            "repaired_findings": 0,
        },
        "skill_proposals": [
            {
                "skill_id": "sk-02",
                "skill_name": "zeta-skill",
                "proposal_summary": "Add zeta testing checklist",
                "status": "proposed",
                "file_path": ".agents/skills/zeta/SKILL.md",
                "additions": 10,
                "deletions": 0,
            },
            {
                "skill_id": "sk-01",
                "skill_name": "alpha-skill",
                "proposal_summary": "Update alpha skill",
                "status": "approved",
                "file_path": ".agents/skills/alpha/SKILL.md",
                "additions": 5,
                "deletions": 1,
            },
        ],
        "raw_metadata": {"source": "fixture", "nested": {"k": "v"}},
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Model round-trips
# ---------------------------------------------------------------------------


def test_action_metadata_round_trip():
    action = DevinSessionActionMetadata(
        action_id="a1",
        timestamp="2026-06-23T00:00:00+00:00",
        action_type="tested",
        summary="ran tests",
        raw_payload={"k": "v"},
    )
    restored = DevinSessionActionMetadata.from_dict(action.to_dict())
    assert restored == action


def test_artifact_metadata_round_trip():
    artifact = DevinSessionArtifactMetadata(
        artifact_id="art1",
        artifact_type="recording",
        artifact_path="rec.mp4",
        artifact_url="https://example.com/rec.mp4",
        summary="recording",
        created_at="2026-06-23T00:00:00+00:00",
    )
    restored = DevinSessionArtifactMetadata.from_dict(artifact.to_dict())
    assert restored == artifact


def test_validation_metadata_round_trip():
    validation = DevinSessionValidationMetadata(
        pytest_passed=10,
        pytest_skipped=1,
        ruff_status="clean",
        ci_status="green",
        cli_testing_summary="6/6",
        devin_review_status="no findings",
        devin_review_findings=2,
        repaired_findings=2,
    )
    restored = DevinSessionValidationMetadata.from_dict(validation.to_dict())
    assert restored == validation


def test_skill_proposal_metadata_round_trip():
    proposal = DevinSessionSkillProposalMetadata(
        skill_id="sk1",
        skill_name="alpha",
        proposal_summary="add alpha",
        status="approved",
        file_path="SKILL.md",
        additions=5,
        deletions=1,
    )
    restored = DevinSessionSkillProposalMetadata.from_dict(proposal.to_dict())
    assert restored == proposal


def test_session_metadata_round_trip():
    session = DevinSessionMetadata.from_dict(_metadata()["session"])
    restored = DevinSessionMetadata.from_dict(session.to_dict())
    assert restored == session


def test_import_generates_ids_and_timestamps():
    imp = DevinSessionMetadataImport()
    assert imp.import_id
    assert imp.created_at
    assert imp.schema_version == SCHEMA_VERSION


def test_report_generates_ids():
    report = DevinSessionImportReport()
    assert report.report_id
    assert report.created_at


def test_evidence_generates_ids():
    evidence = DevinSessionImportEvidence()
    assert evidence.evidence_id
    assert evidence.created_at


def test_enum_values_are_distinct():
    assert len({t.value for t in DevinSessionActionType}) == 12
    assert len({t.value for t in DevinSessionArtifactType}) == 8
    assert DevinSessionActionType.TESTED.value == "tested"
    assert DevinSessionArtifactType.RECORDING.value == "recording"


# ---------------------------------------------------------------------------
# Import: happy path
# ---------------------------------------------------------------------------


def test_import_succeeds_and_counts():
    engine = _tmp_engine()
    report = engine.import_session(metadata=_metadata())
    assert report["status"] == DevinSessionImportStatus.IMPORTED.value
    assert report["action_count"] == 5
    assert report["artifact_count"] == 2
    assert report["skill_proposal_count"] == 2
    assert report["session_id"] == "8ad1c9ac0d2f"
    assert report["repository"] == "plamen-dev/Axiom-platform"
    assert report["global_capability_number"] == 126
    assert report["schema_version"] == SCHEMA_VERSION


def test_import_requires_session_id():
    engine = _tmp_engine()
    md = _metadata()
    md["session"] = dict(md["session"])
    md["session"]["session_id"] = ""
    with pytest.raises(ValueError, match="session_id"):
        engine.import_session(metadata=md)


def test_import_action_ordering_is_deterministic():
    engine = _tmp_engine()
    report = engine.import_session(metadata=_metadata())
    actions = report["metadata_import"]["actions"]
    timestamps = [a["timestamp"] for a in actions]
    assert timestamps == sorted(timestamps)
    assert [a["action_id"] for a in actions] == [
        "a-01",
        "a-02",
        "a-03",
        "a-04",
        "a-05",
    ]


def test_import_artifact_ordering_is_deterministic():
    engine = _tmp_engine()
    report = engine.import_session(metadata=_metadata())
    artifacts = report["metadata_import"]["artifacts"]
    created = [a["created_at"] for a in artifacts]
    assert created == sorted(created)


def test_import_skill_proposal_ordering_is_deterministic():
    engine = _tmp_engine()
    report = engine.import_session(metadata=_metadata())
    proposals = report["metadata_import"]["skill_proposals"]
    names = [p["skill_name"] for p in proposals]
    assert names == ["alpha-skill", "zeta-skill"]


def test_import_is_order_independent():
    engine_a = _tmp_engine()
    engine_b = _tmp_engine()
    md = _metadata()
    shuffled = _metadata()
    shuffled["actions"] = list(reversed(md["actions"]))
    shuffled["artifacts"] = list(reversed(md["artifacts"]))
    shuffled["skill_proposals"] = list(reversed(md["skill_proposals"]))

    report_a = engine_a.import_session(metadata=md)
    report_b = engine_b.import_session(metadata=shuffled)

    assert (
        report_a["metadata_import"]["actions"]
        == report_b["metadata_import"]["actions"]
    )
    assert (
        report_a["timeline_event_type_counts"]
        == report_b["timeline_event_type_counts"]
    )


def test_action_type_counts_sorted():
    engine = _tmp_engine()
    report = engine.import_session(metadata=_metadata())
    counts = report["action_type_counts"]
    assert list(counts.keys()) == sorted(counts.keys())
    assert counts["tested"] == 1
    assert counts["started"] == 1


def test_raw_metadata_preserved():
    engine = _tmp_engine()
    report = engine.import_session(metadata=_metadata())
    raw = report["metadata_import"]["raw_metadata"]
    assert raw == {"source": "fixture", "nested": {"k": "v"}}


def test_raw_payload_preserved_on_action():
    engine = _tmp_engine()
    md = _metadata()
    md["actions"] = [
        {
            "action_id": "a-x",
            "timestamp": "2026-06-23T00:00:00+00:00",
            "action_type": "note",
            "summary": "noted",
            "raw_payload": {"deep": {"value": 1}},
        }
    ]
    report = engine.import_session(metadata=md)
    action = report["metadata_import"]["actions"][0]
    assert action["raw_payload"] == {"deep": {"value": 1}}


def test_validation_metadata_persisted():
    engine = _tmp_engine()
    report = engine.import_session(metadata=_metadata())
    validation = report["metadata_import"]["validation"]
    assert validation["pytest_passed"] == 4099
    assert validation["ci_status"] == "green"


# ---------------------------------------------------------------------------
# Manual overrides
# ---------------------------------------------------------------------------


def test_manual_overrides_take_precedence():
    engine = _tmp_engine()
    md = _metadata()
    md["session"] = dict(md["session"])
    md["session"].pop("session_id")
    report = engine.import_session(
        metadata=md,
        session_id="override-session",
        repo="acme/widgets",
        pr_number=42,
        global_capability_number=999,
    )
    session = report["metadata_import"]["session"]
    assert session["session_id"] == "override-session"
    assert session["repository_owner"] == "acme"
    assert session["repository_name"] == "widgets"
    assert session["repository_pr_number"] == 42
    assert report["global_capability_number"] == 999


def test_invalid_repo_override_rejected():
    engine = _tmp_engine()
    with pytest.raises(ValueError, match="owner/name"):
        engine.import_session(metadata=_metadata(), repo="bad-repo")


# ---------------------------------------------------------------------------
# Duplicate handling
# ---------------------------------------------------------------------------


def test_duplicate_session_rejected():
    engine = _tmp_engine()
    engine.import_session(metadata=_metadata())
    with pytest.raises(ValueError, match="Duplicate import"):
        engine.import_session(metadata=_metadata())


def test_distinct_sessions_allowed():
    engine = _tmp_engine()
    engine.import_session(metadata=_metadata())
    md2 = _metadata()
    md2["session"] = dict(md2["session"])
    md2["session"]["session_id"] = "different-session"
    report = engine.import_session(metadata=md2)
    assert report["status"] == DevinSessionImportStatus.IMPORTED.value
    assert len(engine.list_reports()) == 2


# ---------------------------------------------------------------------------
# Malformed payload + missing artifact tolerance
# ---------------------------------------------------------------------------


def test_malformed_action_skipped_partial_import():
    engine = _tmp_engine()
    md = _metadata()
    md["actions"] = [
        {"action_type": "tested", "summary": "no timestamp"},
        {
            "action_id": "ok",
            "timestamp": "2026-06-23T00:00:00+00:00",
            "action_type": "note",
            "summary": "ok",
        },
    ]
    report = engine.import_session(metadata=md)
    assert report["status"] == DevinSessionImportStatus.PARTIAL_IMPORT.value
    assert report["action_count"] == 1
    assert any(
        "missing timestamp" in s
        for s in report["metadata_import"]["skipped"]
    )


def test_invalid_action_type_skipped():
    engine = _tmp_engine()
    md = _metadata()
    md["actions"] = [
        {
            "action_id": "bad",
            "timestamp": "2026-06-23T00:00:00+00:00",
            "action_type": "exploded",
            "summary": "invalid",
        }
    ]
    report = engine.import_session(metadata=md)
    assert report["status"] == DevinSessionImportStatus.PARTIAL_IMPORT.value
    assert report["action_count"] == 0


def test_invalid_artifact_type_skipped():
    engine = _tmp_engine()
    md = _metadata()
    md["artifacts"] = [
        {"artifact_id": "x", "artifact_type": "hologram", "summary": "bad"}
    ]
    report = engine.import_session(metadata=md)
    assert report["status"] == DevinSessionImportStatus.PARTIAL_IMPORT.value
    assert report["artifact_count"] == 0


def test_missing_artifacts_tolerated():
    engine = _tmp_engine()
    md = _metadata()
    md["artifacts"] = []
    report = engine.import_session(metadata=md)
    assert report["status"] == DevinSessionImportStatus.IMPORTED.value
    assert report["artifact_count"] == 0


def test_artifact_missing_optional_path_tolerated():
    engine = _tmp_engine()
    md = _metadata()
    md["artifacts"] = [
        {
            "artifact_id": "a",
            "artifact_type": "log",
            "summary": "log without path",
            "created_at": "2026-06-23T00:00:00+00:00",
        }
    ]
    report = engine.import_session(metadata=md)
    assert report["status"] == DevinSessionImportStatus.IMPORTED.value
    assert report["artifact_count"] == 1


def test_malformed_skill_proposal_skipped():
    engine = _tmp_engine()
    md = _metadata()
    md["skill_proposals"] = [
        {"skill_id": "x", "status": "proposed"},
        {"skill_id": "y", "skill_name": "ok", "status": "bogus"},
    ]
    report = engine.import_session(metadata=md)
    assert report["status"] == DevinSessionImportStatus.PARTIAL_IMPORT.value
    assert report["skill_proposal_count"] == 0


# ---------------------------------------------------------------------------
# Skill proposal statuses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [s.value for s in DevinSessionSkillProposalStatus],
)
def test_all_skill_proposal_statuses_accepted(status):
    engine = _tmp_engine()
    md = _metadata()
    md["skill_proposals"] = [
        {
            "skill_id": "sk",
            "skill_name": "alpha",
            "proposal_summary": "x",
            "status": status,
        }
    ]
    report = engine.import_session(metadata=md)
    assert report["skill_proposal_count"] == 1
    assert report["skill_proposal_status_counts"][status] == 1


# ---------------------------------------------------------------------------
# Timeline event creation
# ---------------------------------------------------------------------------


def test_timeline_events_created():
    engine = _tmp_engine()
    report = engine.import_session(metadata=_metadata())
    events = report["timeline_events"]
    assert len(events) > 0
    etypes = {e["event_type"] for e in events}
    # tested -> test_completed, fixed_finding -> bug_fixed,
    # reported_ready -> pr_ready, recording -> video_recorded,
    # screenshot -> screenshot_captured, proposed -> skill_proposed,
    # approved -> skill_approved
    assert "test_completed" in etypes
    assert "bug_fixed" in etypes
    assert "pr_ready" in etypes
    assert "video_recorded" in etypes
    assert "screenshot_captured" in etypes
    assert "skill_proposed" in etypes
    assert "skill_approved" in etypes


def test_timeline_events_sorted_and_sequenced():
    engine = _tmp_engine()
    report = engine.import_session(metadata=_metadata())
    events = report["timeline_events"]
    timestamps = [e["timestamp"] for e in events]
    assert timestamps == sorted(timestamps)
    sequences = [e["event_sequence"] for e in events]
    assert sequences == list(range(1, len(events) + 1))


def test_timeline_events_source_tagged():
    engine = _tmp_engine()
    report = engine.import_session(metadata=_metadata())
    for e in report["timeline_events"]:
        assert e["source"] == "devin_session_import"
        assert e["global_capability_id"] == "gc-126"


def test_artifact_event_carries_artifact():
    engine = _tmp_engine()
    report = engine.import_session(metadata=_metadata())
    media_events = [
        e
        for e in report["timeline_events"]
        if e["event_type"] in ("video_recorded", "screenshot_captured")
    ]
    assert media_events
    for e in media_events:
        assert e["artifacts"]


def test_started_action_maps_to_note_event():
    engine = _tmp_engine()
    md = _metadata()
    md["actions"] = [
        {
            "action_id": "s",
            "timestamp": "2026-06-23T00:00:00+00:00",
            "action_type": "started",
            "summary": "started",
        }
    ]
    md["artifacts"] = []
    md["skill_proposals"] = []
    report = engine.import_session(metadata=md)
    assert report["timeline_event_type_counts"].get("note") == 1


def test_slept_action_maps_to_warning():
    engine = _tmp_engine()
    md = _metadata()
    md["actions"] = [
        {
            "action_id": "z",
            "timestamp": "2026-06-23T00:00:00+00:00",
            "action_type": "slept",
            "summary": "session suspended",
        }
    ]
    md["artifacts"] = []
    md["skill_proposals"] = []
    report = engine.import_session(metadata=md)
    assert report["timeline_event_type_counts"].get("warning") == 1


# ---------------------------------------------------------------------------
# Registry reference (observed, never owned or mutated)
# ---------------------------------------------------------------------------


def test_registry_reference_built():
    engine = _tmp_engine()
    report = engine.import_session(metadata=_metadata())
    ref = report["registry_reference"]
    assert report["registry_reference_status"] == "referenced"
    assert ref["reference_status"] == "referenced"
    assert ref["global_capability_number"] == 126
    assert ref["capability_id"] == "gc-126"
    assert ref["capability_name"].startswith("PR #126")
    assert ref["worker"]["worker_id"] == "devin"
    assert ref["worker"]["worker_type"] == "ai"
    assert ref["repository_owner"] == "plamen-dev"
    assert ref["observed_session_status"] == "merged"


def test_registry_reference_does_not_mint_canonical_entry():
    # The reference is a plain observation, never a GlobalCapabilityEntry:
    # it carries no canonical-identity fields the registry owns.
    engine = _tmp_engine()
    ref = engine.import_session(metadata=_metadata())["registry_reference"]
    assert "global_capability_id" not in ref
    assert "merge_sha" not in ref
    assert "primary_program" not in ref


def test_missing_registry_reference_flagged_not_minted():
    engine = _tmp_engine()
    md = _metadata()
    md["session"] = dict(md["session"])
    md["session"]["capability_id"] = ""
    md["session"]["global_capability_number"] = 0
    md["global_capability_number"] = 0
    report = engine.import_session(metadata=md, global_capability_number=0)
    assert report["registry_reference_status"] == "missing_registry_reference"
    assert (
        report["registry_reference"]["reference_status"]
        == "missing_registry_reference"
    )
    # Still a successful import; absence is flagged, not failed.
    assert report["status"] == DevinSessionImportStatus.IMPORTED.value


def test_registry_reference_observes_session_status_verbatim():
    engine = _tmp_engine()
    md = _metadata()
    md["session"] = dict(md["session"])
    md["session"]["status"] = "in_progress"
    report = engine.import_session(metadata=md)
    ref = report["registry_reference"]
    assert ref["observed_session_status"] == "in_progress"
    assert report["registry_reference_status"] == "referenced"


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def test_get_report_round_trips():
    engine = _tmp_engine()
    report = engine.import_session(metadata=_metadata())
    loaded = engine.get_report(report["report_id"])
    assert loaded == report


def test_get_report_missing_returns_none():
    engine = _tmp_engine()
    assert engine.get_report("does-not-exist") is None


def test_list_reports_sorted_by_created_at():
    engine = _tmp_engine()
    engine.import_session(metadata=_metadata())
    md2 = _metadata()
    md2["session"] = dict(md2["session"])
    md2["session"]["session_id"] = "second"
    engine.import_session(metadata=md2)
    reports = engine.list_reports()
    created = [r["created_at"] for r in reports]
    assert created == sorted(created)


@pytest.mark.parametrize("bad", ["..", "a/b", "a\\b", "", "  "])
def test_get_report_rejects_unsafe_ids(bad):
    engine = _tmp_engine()
    with pytest.raises(ValueError):
        engine.get_report(bad)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def test_export_json_valid():
    engine = _tmp_engine()
    report = engine.import_session(metadata=_metadata())
    out = engine.export_report(report["report_id"], fmt="json")
    parsed = json.loads(out)
    assert parsed["report_id"] == report["report_id"]


def test_export_markdown_sections():
    engine = _tmp_engine()
    report = engine.import_session(metadata=_metadata())
    out = engine.export_report(report["report_id"], fmt="markdown")
    assert "# Devin Session Metadata Import" in out
    assert "## Action Type Counts" in out
    assert "## Artifact Type Counts" in out
    assert "## Skill Proposal Status Counts" in out
    assert "## Timeline Event Counts" in out
    assert "## Timeline Events" in out
    # Literal brackets render.
    assert "[TESTED]" in out


def test_export_csv_rows():
    engine = _tmp_engine()
    report = engine.import_session(metadata=_metadata())
    out = engine.export_report(report["report_id"], fmt="csv")
    rows = list(csv.reader(io.StringIO(out)))
    header = rows[0]
    assert header[0] == "record_type"
    record_types = {r[0] for r in rows[1:]}
    assert "action" in record_types
    assert "artifact" in record_types
    assert "skill_proposal" in record_types


def test_export_invalid_format_rejected():
    engine = _tmp_engine()
    report = engine.import_session(metadata=_metadata())
    with pytest.raises(ValueError, match="Invalid export format"):
        engine.export_report(report["report_id"], fmt="xml")


def test_export_missing_report_raises():
    engine = _tmp_engine()
    with pytest.raises(ValueError, match="not found"):
        engine.export_report("missing", fmt="json")


# ---------------------------------------------------------------------------
# Evidence bundle + pass/fail
# ---------------------------------------------------------------------------


def test_evidence_bundle_written():
    engine = _tmp_engine()
    report = engine.import_session(metadata=_metadata())
    report_dir = engine._safe_path(report["report_id"])
    for name in (
        "devin_session_import_request.json",
        "devin_session_import_result.json",
        "devin_session_import_summary.md",
        "pass_fail.json",
        "report.json",
    ):
        assert (report_dir / name).exists()


def test_pass_fail_passed_on_clean_import():
    engine = _tmp_engine()
    report = engine.import_session(metadata=_metadata())
    report_dir = engine._safe_path(report["report_id"])
    pf = json.loads((report_dir / "pass_fail.json").read_text())
    assert pf["passed"] is True
    assert pf["status"] == "passed"
    assert pf["skipped_count"] == 0


def test_pass_fail_failed_on_partial_import():
    engine = _tmp_engine()
    md = _metadata()
    md["actions"] = [{"action_type": "tested", "summary": "no timestamp"}]
    report = engine.import_session(metadata=md)
    report_dir = engine._safe_path(report["report_id"])
    pf = json.loads((report_dir / "pass_fail.json").read_text())
    assert pf["passed"] is False
    assert pf["status"] == "failed"
    assert pf["skipped_count"] >= 1


def test_request_evidence_contains_metadata_import():
    engine = _tmp_engine()
    report = engine.import_session(metadata=_metadata())
    report_dir = engine._safe_path(report["report_id"])
    req = json.loads(
        (report_dir / "devin_session_import_request.json").read_text()
    )
    assert req["global_capability_number"] == 126
    assert req["metadata_import"]["session"]["session_id"] == "8ad1c9ac0d2f"


# ---------------------------------------------------------------------------
# Empty session
# ---------------------------------------------------------------------------


def test_minimal_session_imports():
    engine = _tmp_engine()
    report = engine.import_session(
        metadata={"session": {"session_id": "minimal"}}
    )
    assert report["status"] == DevinSessionImportStatus.IMPORTED.value
    assert report["action_count"] == 0
    assert report["artifact_count"] == 0
    assert report["timeline_events"] == []


def test_schema_version_preserved_from_payload():
    engine = _tmp_engine()
    md = _metadata()
    md["session"] = dict(md["session"])
    md["session"]["schema_version"] = "1.0"
    report = engine.import_session(metadata=md)
    assert report["metadata_import"]["session"]["schema_version"] == "1.0"
