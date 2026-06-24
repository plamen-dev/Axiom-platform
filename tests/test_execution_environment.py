"""Tests for the Execution Environment Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.execution_environment import (
    ExecutionEnvironment,
    ExecutionEnvironmentEngine,
    ExecutionEnvironmentEvidence,
    ExecutionEnvironmentReference,
    ExecutionEnvironmentReferenceType,
    ExecutionEnvironmentReport,
    ExecutionEnvironmentStatus,
    ExecutionEnvironmentType,
)


def _env(
    context_id: str,
    capability_id: str,
    environment_type: str,
    status: str,
    **kw,
) -> dict:
    data = {
        "context_id": context_id,
        "capability_id": capability_id,
        "environment_type": environment_type,
        "status": status,
        "summary": kw.get("summary", ""),
    }
    if "environment_id" in kw:
        data["environment_id"] = kw["environment_id"]
    if "references" in kw:
        data["references"] = kw["references"]
    if "raw_payload" in kw:
        data["raw_payload"] = kw["raw_payload"]
    return data


def _ref(reference_type: str, reference_value: str, **kw) -> dict:
    data = {
        "reference_type": reference_type,
        "reference_value": reference_value,
        "summary": kw.get("summary", ""),
    }
    if "reference_id" in kw:
        data["reference_id"] = kw["reference_id"]
    return data


@pytest.fixture
def engine(tmp_path):
    return ExecutionEnvironmentEngine(
        artifacts_root=str(tmp_path / "artifacts")
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_reference_round_trip(self):
        r = ExecutionEnvironmentReference(
            reference_id="r-1",
            reference_type="CONTEXT",
            reference_value="ctx-1",
            summary="state",
        )
        assert ExecutionEnvironmentReference.from_dict(r.to_dict()) == r

    def test_environment_round_trip(self):
        e = ExecutionEnvironment(
            environment_id="e-1",
            context_id="ctx-1",
            capability_id="cap-1",
            environment_type="DEVIN",
            status="AVAILABLE",
            references=[
                ExecutionEnvironmentReference(
                    reference_id="r-1",
                    reference_type="REPOSITORY",
                    reference_value="Axiom-platform",
                )
            ],
            summary="devin box",
            created_at="2026-01-01T00:00:00+00:00",
            raw_payload={"k": "v"},
        )
        assert ExecutionEnvironment.from_dict(e.to_dict()) == e

    def test_environment_gets_id_and_timestamp(self):
        e = ExecutionEnvironment(
            context_id="ctx-1",
            capability_id="cap-1",
            environment_type="DEVIN",
            status="AVAILABLE",
        )
        assert e.environment_id
        assert e.created_at

    def test_report_defaults(self):
        report = ExecutionEnvironmentReport()
        assert report.report_id
        assert report.created_at
        assert report.environment_count == 0
        assert report.schema_version == "1.0"

    def test_evidence_defaults(self):
        ev = ExecutionEnvironmentEvidence(report_id="rep-1")
        assert ev.evidence_id
        assert ev.created_at
        assert ev.report_id == "rep-1"

    def test_all_environment_types_present(self):
        assert {t.value for t in ExecutionEnvironmentType} == {
            "LOCAL",
            "DEVIN",
            "GITHUB_ACTIONS",
            "WINDOWS_REVIT",
            "LOCAL_RUNNER",
            "AXIOM_WORKER",
            "OTHER",
        }

    def test_all_statuses_present(self):
        assert {t.value for t in ExecutionEnvironmentStatus} == {
            "AVAILABLE",
            "UNAVAILABLE",
            "DEGRADED",
            "UNKNOWN",
        }

    def test_all_reference_types_present(self):
        assert {t.value for t in ExecutionEnvironmentReferenceType} == {
            "CONTEXT",
            "CAPABILITY",
            "WORKER",
            "REPOSITORY",
            "BRANCH",
            "COMMIT",
            "ARTIFACT",
            "CONFIGURATION",
            "OTHER",
        }


# ---------------------------------------------------------------------------
# Create / determinism
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_counts(self, engine):
        report = engine.create(
            environments=[
                _env("ctx-1", "cap-1", "DEVIN", "AVAILABLE"),
                _env("ctx-2", "cap-2", "LOCAL", "AVAILABLE"),
                _env("ctx-3", "cap-3", "GITHUB_ACTIONS", "UNKNOWN"),
            ]
        )
        assert report["environment_count"] == 3
        assert report["status_counts"] == {
            "AVAILABLE": 2,
            "UNKNOWN": 1,
        }
        assert report["environment_type_counts"] == {
            "DEVIN": 1,
            "GITHUB_ACTIONS": 1,
            "LOCAL": 1,
        }
        assert report["unavailable_count"] == 0
        assert report["degraded_count"] == 0

    def test_deterministic_ordering(self, engine):
        report = engine.create(
            environments=[
                _env("ctx-2", "cap-1", "DEVIN", "AVAILABLE"),
                _env("ctx-1", "cap-2", "LOCAL", "AVAILABLE"),
                _env("ctx-1", "cap-1", "DEVIN", "AVAILABLE"),
            ]
        )
        order = [
            (e["context_id"], e["capability_id"], e["environment_type"])
            for e in report["environments"]
        ]
        assert order == [
            ("ctx-1", "cap-1", "DEVIN"),
            ("ctx-1", "cap-2", "LOCAL"),
            ("ctx-2", "cap-1", "DEVIN"),
        ]

    def test_ordering_is_input_independent(self, engine):
        environments = [
            _env("ctx-1", "cap-1", "DEVIN", "AVAILABLE"),
            _env("ctx-2", "cap-2", "LOCAL", "AVAILABLE"),
            _env("ctx-3", "cap-3", "AXIOM_WORKER", "AVAILABLE"),
        ]
        r1 = engine.create(environments=list(environments))
        r2 = engine.create(environments=list(reversed(environments)))
        key = lambda rep: [  # noqa: E731
            (e["context_id"], e["capability_id"]) for e in rep["environments"]
        ]
        assert key(r1) == key(r2)

    def test_references_ordered_deterministically(self, engine):
        report = engine.create(
            environments=[
                _env(
                    "ctx-1",
                    "cap-1",
                    "DEVIN",
                    "AVAILABLE",
                    references=[
                        _ref("WORKER", "w-9"),
                        _ref("BRANCH", "main"),
                        _ref("CONTEXT", "ctx-1"),
                    ],
                )
            ]
        )
        order = [
            (r["reference_type"], r["reference_value"])
            for r in report["environments"][0]["references"]
        ]
        assert order == [
            ("BRANCH", "main"),
            ("CONTEXT", "ctx-1"),
            ("WORKER", "w-9"),
        ]

    def test_schema_version_preserved(self, engine):
        report = engine.create(
            environments=[_env("ctx-1", "cap-1", "DEVIN", "AVAILABLE")]
        )
        assert report["schema_version"] == "1.0"

    def test_raw_metadata_preserved(self, engine):
        report = engine.create(
            environments=[_env("ctx-1", "cap-1", "DEVIN", "AVAILABLE")],
            raw_metadata={"source": "program-0"},
        )
        assert report["raw_metadata"] == {"source": "program-0"}

    def test_environment_raw_payload_preserved(self, engine):
        report = engine.create(
            environments=[
                _env(
                    "ctx-1",
                    "cap-1",
                    "DEVIN",
                    "AVAILABLE",
                    raw_payload={"nested": {"deep": [1, 2]}},
                )
            ]
        )
        assert report["environments"][0]["raw_payload"] == {
            "nested": {"deep": [1, 2]}
        }


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_environment_type_normalized(self, engine):
        report = engine.create(
            environments=[_env("ctx-1", "cap-1", "devin", "AVAILABLE")]
        )
        assert report["environments"][0]["environment_type"] == "DEVIN"

    def test_status_normalized(self, engine):
        report = engine.create(
            environments=[_env("ctx-1", "cap-1", "DEVIN", "available")]
        )
        assert report["environments"][0]["status"] == "AVAILABLE"

    def test_reference_type_normalized(self, engine):
        report = engine.create(
            environments=[
                _env(
                    "ctx-1",
                    "cap-1",
                    "DEVIN",
                    "AVAILABLE",
                    references=[_ref("repository", "Axiom-platform")],
                )
            ]
        )
        assert (
            report["environments"][0]["references"][0]["reference_type"]
            == "REPOSITORY"
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_environment_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid environment_type"):
            engine.create(
                environments=[_env("ctx-1", "cap-1", "NONSENSE", "AVAILABLE")]
            )

    def test_invalid_status_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid status"):
            engine.create(
                environments=[_env("ctx-1", "cap-1", "DEVIN", "NOPE")]
            )

    def test_missing_context_id_rejected(self, engine):
        with pytest.raises(ValueError, match="context_id is required"):
            engine.create(
                environments=[_env("", "cap-1", "DEVIN", "AVAILABLE")]
            )

    def test_missing_capability_id_rejected(self, engine):
        with pytest.raises(ValueError, match="capability_id is required"):
            engine.create(
                environments=[_env("ctx-1", "", "DEVIN", "AVAILABLE")]
            )

    def test_missing_environment_type_rejected(self, engine):
        with pytest.raises(ValueError, match="environment_type is required"):
            engine.create(
                environments=[_env("ctx-1", "cap-1", "", "AVAILABLE")]
            )

    def test_missing_status_rejected(self, engine):
        with pytest.raises(ValueError, match="status is required"):
            engine.create(
                environments=[_env("ctx-1", "cap-1", "DEVIN", "")]
            )

    def test_invalid_reference_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid reference_type"):
            engine.create(
                environments=[
                    _env(
                        "ctx-1",
                        "cap-1",
                        "DEVIN",
                        "AVAILABLE",
                        references=[_ref("NONSENSE", "x")],
                    )
                ]
            )

    def test_missing_reference_value_rejected(self, engine):
        with pytest.raises(ValueError, match="reference_value is required"):
            engine.create(
                environments=[
                    _env(
                        "ctx-1",
                        "cap-1",
                        "DEVIN",
                        "AVAILABLE",
                        references=[_ref("REPOSITORY", "")],
                    )
                ]
            )


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


class TestDuplicateDetection:
    def test_duplicate_environment_deduped_and_counted(self, engine):
        report = engine.create(
            environments=[
                _env("ctx-1", "cap-1", "DEVIN", "AVAILABLE"),
                _env("ctx-1", "cap-1", "devin", "DEGRADED"),
            ]
        )
        assert report["environment_count"] == 1
        assert report["duplicate_environment_count"] == 1

    def test_distinct_environment_type_not_duplicate(self, engine):
        report = engine.create(
            environments=[
                _env("ctx-1", "cap-1", "DEVIN", "AVAILABLE"),
                _env("ctx-1", "cap-1", "LOCAL", "AVAILABLE"),
            ]
        )
        assert report["environment_count"] == 2
        assert report["duplicate_environment_count"] == 0

    def test_distinct_capability_not_duplicate(self, engine):
        report = engine.create(
            environments=[
                _env("ctx-1", "cap-1", "DEVIN", "AVAILABLE"),
                _env("ctx-1", "cap-2", "DEVIN", "AVAILABLE"),
            ]
        )
        assert report["environment_count"] == 2
        assert report["duplicate_environment_count"] == 0


# ---------------------------------------------------------------------------
# Unavailable / degraded detection
# ---------------------------------------------------------------------------


class TestUnavailableDegradedDetection:
    def test_unavailable_detected(self, engine):
        report = engine.create(
            environments=[
                _env("ctx-1", "cap-1", "DEVIN", "UNAVAILABLE"),
                _env("ctx-2", "cap-2", "LOCAL", "AVAILABLE"),
            ]
        )
        assert report["unavailable_count"] == 1
        assert report["degraded_count"] == 0

    def test_degraded_detected(self, engine):
        report = engine.create(
            environments=[
                _env("ctx-1", "cap-1", "DEVIN", "DEGRADED"),
                _env("ctx-2", "cap-2", "LOCAL", "AVAILABLE"),
            ]
        )
        assert report["degraded_count"] == 1
        assert report["unavailable_count"] == 0


# ---------------------------------------------------------------------------
# Pass/fail
# ---------------------------------------------------------------------------


def _read_pass_fail(engine, report_id: str) -> dict:
    path = engine._report_dir / report_id / "pass_fail.json"
    return json.loads(path.read_text(encoding="utf-8"))


class TestPassFail:
    def test_pass_with_clean_environments(self, engine):
        report = engine.create(
            environments=[
                _env("ctx-1", "cap-1", "DEVIN", "AVAILABLE"),
                _env("ctx-2", "cap-2", "LOCAL", "UNKNOWN"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is True
        assert pf["environment_count"] == 2
        assert pf["status"] == "passed"

    def test_empty_report_fails(self, engine):
        report = engine.create(environments=[])
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["environment_count"] == 0
        assert pf["status"] == "failed"

    def test_unavailable_fails(self, engine):
        report = engine.create(
            environments=[_env("ctx-1", "cap-1", "DEVIN", "UNAVAILABLE")]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["unavailable_count"] == 1

    def test_degraded_fails(self, engine):
        report = engine.create(
            environments=[_env("ctx-1", "cap-1", "DEVIN", "DEGRADED")]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["degraded_count"] == 1

    def test_duplicate_does_not_fail_when_clean(self, engine):
        report = engine.create(
            environments=[
                _env("ctx-1", "cap-1", "DEVIN", "AVAILABLE"),
                _env("ctx-1", "cap-1", "DEVIN", "AVAILABLE"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["duplicate_environment_count"] == 1
        assert pf["passed"] is True

    def test_evidence_bundle_files_written(self, engine):
        report = engine.create(
            environments=[_env("ctx-1", "cap-1", "DEVIN", "AVAILABLE")]
        )
        report_dir = engine._report_dir / report["report_id"]
        for name in (
            "execution_environment_request.json",
            "execution_environment_result.json",
            "execution_environment_summary.md",
            "pass_fail.json",
            "report.json",
        ):
            assert (report_dir / name).exists()


# ---------------------------------------------------------------------------
# Append-only
# ---------------------------------------------------------------------------


class TestAppend:
    def test_append_preserves_and_adds(self, engine):
        created = engine.create(
            environments=[_env("ctx-1", "cap-1", "DEVIN", "AVAILABLE")]
        )
        report_id = created["report_id"]
        appended = engine.append(
            report_id,
            environments=[_env("ctx-2", "cap-2", "LOCAL", "AVAILABLE")],
        )
        assert appended["report_id"] == report_id
        assert appended["environment_count"] == 2
        caps = {e["capability_id"] for e in appended["environments"]}
        assert caps == {"cap-1", "cap-2"}

    def test_append_preserves_raw_metadata(self, engine):
        created = engine.create(
            environments=[_env("ctx-1", "cap-1", "DEVIN", "AVAILABLE")],
            raw_metadata={"origin": "p0"},
        )
        appended = engine.append(
            created["report_id"],
            environments=[_env("ctx-2", "cap-2", "LOCAL", "AVAILABLE")],
        )
        assert appended["raw_metadata"] == {"origin": "p0"}

    def test_append_missing_report_raises(self, engine):
        with pytest.raises(ValueError, match="Report not found"):
            engine.append("does-not-exist", environments=[])


# ---------------------------------------------------------------------------
# Retrieval / exports
# ---------------------------------------------------------------------------


class TestRetrievalExport:
    def test_get_report_round_trip(self, engine):
        created = engine.create(
            environments=[_env("ctx-1", "cap-1", "DEVIN", "AVAILABLE")]
        )
        loaded = engine.get_report(created["report_id"])
        assert loaded["report_id"] == created["report_id"]
        assert loaded["environment_count"] == 1

    def test_get_missing_returns_none(self, engine):
        assert engine.get_report("missing-id") is None

    def test_list_reports_sorted(self, engine):
        engine.create(
            environments=[_env("ctx-1", "cap-1", "DEVIN", "AVAILABLE")]
        )
        engine.create(
            environments=[_env("ctx-2", "cap-2", "LOCAL", "AVAILABLE")]
        )
        assert len(engine.list_reports()) == 2

    def test_export_json_valid(self, engine):
        created = engine.create(
            environments=[_env("ctx-1", "cap-1", "DEVIN", "AVAILABLE")]
        )
        parsed = json.loads(
            engine.export_report(created["report_id"], fmt="json")
        )
        assert parsed["report_id"] == created["report_id"]

    def test_export_markdown_headings(self, engine):
        created = engine.create(
            environments=[
                _env(
                    "ctx-1",
                    "cap-122",
                    "DEVIN",
                    "AVAILABLE",
                    references=[_ref("REPOSITORY", "Axiom-platform")],
                )
            ]
        )
        out = engine.export_report(created["report_id"], fmt="markdown")
        assert "# Execution Environment Report" in out
        assert "## Status Counts" in out
        assert "## Environment Type Counts" in out
        assert "## Environments" in out
        assert "[AVAILABLE]" in out
        assert "[DEVIN]" in out
        assert "capability=cap-122" in out
        assert "[REPOSITORY] Axiom-platform" in out

    def test_export_csv_rows(self, engine):
        created = engine.create(
            environments=[
                _env(
                    "ctx-1",
                    "cap-1",
                    "DEVIN",
                    "AVAILABLE",
                    references=[_ref("REPOSITORY", "Axiom-platform")],
                ),
                _env("ctx-2", "cap-2", "LOCAL", "UNKNOWN"),
            ]
        )
        out = engine.export_report(created["report_id"], fmt="csv")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        assert lines[0].startswith("record_kind,")
        # header + 2 environments + 1 reference
        assert len(lines) == 4
        environment_rows = [
            ln for ln in lines[1:] if ln.startswith("environment,")
        ]
        reference_rows = [
            ln for ln in lines[1:] if ln.startswith("reference,")
        ]
        assert len(environment_rows) == 2
        assert len(reference_rows) == 1

    def test_export_invalid_format_raises(self, engine):
        created = engine.create(
            environments=[_env("ctx-1", "cap-1", "DEVIN", "AVAILABLE")]
        )
        with pytest.raises(ValueError, match="Invalid export format"):
            engine.export_report(created["report_id"], fmt="xml")

    def test_export_missing_raises(self, engine):
        with pytest.raises(ValueError, match="Report not found"):
            engine.export_report("missing-id", fmt="json")


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


class TestPathSafety:
    def test_traversal_rejected_on_get(self, engine):
        with pytest.raises(ValueError, match="must not contain"):
            engine.get_report("../../etc")

    def test_traversal_rejected_on_export(self, engine):
        with pytest.raises(ValueError, match="must not contain"):
            engine.export_report("../../etc", fmt="json")

    def test_empty_id_rejected(self, engine):
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("   ")
