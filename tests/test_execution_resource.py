"""Tests for the Execution Resource Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.execution_resource import (
    ExecutionResource,
    ExecutionResourceEngine,
    ExecutionResourceEvidence,
    ExecutionResourceReport,
    ExecutionResourceRequirement,
    ExecutionResourceStatus,
    ExecutionResourceType,
)


def _res(
    context_id: str,
    environment_id: str,
    capability_id: str,
    resource_type: str,
    status: str,
    **kw,
) -> dict:
    data = {
        "context_id": context_id,
        "environment_id": environment_id,
        "capability_id": capability_id,
        "resource_type": resource_type,
        "status": status,
        "summary": kw.get("summary", ""),
    }
    if "resource_id" in kw:
        data["resource_id"] = kw["resource_id"]
    if "requirements" in kw:
        data["requirements"] = kw["requirements"]
    if "raw_payload" in kw:
        data["raw_payload"] = kw["raw_payload"]
    return data


def _req(requirement_type: str, requirement_value: str, **kw) -> dict:
    data = {
        "requirement_type": requirement_type,
        "requirement_value": requirement_value,
        "summary": kw.get("summary", ""),
    }
    if "requirement_id" in kw:
        data["requirement_id"] = kw["requirement_id"]
    return data


@pytest.fixture
def engine(tmp_path):
    return ExecutionResourceEngine(artifacts_root=str(tmp_path / "artifacts"))


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_requirement_round_trip(self):
        r = ExecutionResourceRequirement(
            requirement_id="r-1",
            requirement_type="min_memory_gb",
            requirement_value="8",
            summary="memory",
        )
        assert ExecutionResourceRequirement.from_dict(r.to_dict()) == r

    def test_resource_round_trip(self):
        r = ExecutionResource(
            resource_id="res-1",
            context_id="ctx-1",
            environment_id="env-1",
            capability_id="cap-1",
            resource_type="MEMORY",
            status="AVAILABLE",
            requirements=[
                ExecutionResourceRequirement(
                    requirement_id="r-1",
                    requirement_type="min_gb",
                    requirement_value="8",
                )
            ],
            summary="ram",
            created_at="2026-01-01T00:00:00+00:00",
            raw_payload={"k": "v"},
        )
        assert ExecutionResource.from_dict(r.to_dict()) == r

    def test_resource_gets_id_and_timestamp(self):
        r = ExecutionResource(
            context_id="ctx-1",
            environment_id="env-1",
            capability_id="cap-1",
            resource_type="CPU",
            status="AVAILABLE",
        )
        assert r.resource_id
        assert r.created_at

    def test_report_defaults(self):
        report = ExecutionResourceReport()
        assert report.report_id
        assert report.created_at
        assert report.resource_count == 0
        assert report.requirement_count == 0
        assert report.schema_version == "1.0"

    def test_evidence_defaults(self):
        ev = ExecutionResourceEvidence(report_id="rep-1")
        assert ev.evidence_id
        assert ev.created_at
        assert ev.report_id == "rep-1"

    def test_all_resource_types_present(self):
        assert {t.value for t in ExecutionResourceType} == {
            "CPU",
            "MEMORY",
            "STORAGE",
            "NETWORK",
            "GPU",
            "REPOSITORY",
            "TOOL",
            "SOFTWARE",
            "CREDENTIAL",
            "OTHER",
        }

    def test_all_statuses_present(self):
        assert {t.value for t in ExecutionResourceStatus} == {
            "AVAILABLE",
            "UNAVAILABLE",
            "DEGRADED",
            "UNKNOWN",
        }


# ---------------------------------------------------------------------------
# Create / determinism
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_counts(self, engine):
        report = engine.create(
            resources=[
                _res("ctx-1", "env-1", "cap-1", "CPU", "AVAILABLE"),
                _res("ctx-2", "env-2", "cap-2", "MEMORY", "AVAILABLE"),
                _res("ctx-3", "env-3", "cap-3", "GPU", "UNKNOWN"),
            ]
        )
        assert report["resource_count"] == 3
        assert report["status_counts"] == {
            "AVAILABLE": 2,
            "UNKNOWN": 1,
        }
        assert report["resource_type_counts"] == {
            "CPU": 1,
            "GPU": 1,
            "MEMORY": 1,
        }
        assert report["unavailable_count"] == 0
        assert report["degraded_count"] == 0

    def test_deterministic_ordering(self, engine):
        report = engine.create(
            resources=[
                _res("ctx-2", "env-1", "cap-1", "CPU", "AVAILABLE"),
                _res("ctx-1", "env-1", "cap-2", "MEMORY", "AVAILABLE"),
                _res("ctx-1", "env-1", "cap-1", "CPU", "AVAILABLE"),
            ]
        )
        order = [
            (
                r["context_id"],
                r["environment_id"],
                r["capability_id"],
                r["resource_type"],
            )
            for r in report["resources"]
        ]
        assert order == [
            ("ctx-1", "env-1", "cap-1", "CPU"),
            ("ctx-1", "env-1", "cap-2", "MEMORY"),
            ("ctx-2", "env-1", "cap-1", "CPU"),
        ]

    def test_ordering_is_input_independent(self, engine):
        resources = [
            _res("ctx-1", "env-1", "cap-1", "CPU", "AVAILABLE"),
            _res("ctx-2", "env-2", "cap-2", "MEMORY", "AVAILABLE"),
            _res("ctx-3", "env-3", "cap-3", "TOOL", "AVAILABLE"),
        ]
        r1 = engine.create(resources=list(resources))
        r2 = engine.create(resources=list(reversed(resources)))
        key = lambda rep: [  # noqa: E731
            (r["context_id"], r["capability_id"]) for r in rep["resources"]
        ]
        assert key(r1) == key(r2)

    def test_requirements_ordered_deterministically(self, engine):
        report = engine.create(
            resources=[
                _res(
                    "ctx-1",
                    "env-1",
                    "cap-1",
                    "MEMORY",
                    "AVAILABLE",
                    requirements=[
                        _req("min_gb", "8"),
                        _req("arch", "x86_64"),
                        _req("min_cores", "4"),
                    ],
                )
            ]
        )
        order = [
            (r["requirement_type"], r["requirement_value"])
            for r in report["resources"][0]["requirements"]
        ]
        assert order == [
            ("arch", "x86_64"),
            ("min_cores", "4"),
            ("min_gb", "8"),
        ]

    def test_requirement_count_aggregated(self, engine):
        report = engine.create(
            resources=[
                _res(
                    "ctx-1",
                    "env-1",
                    "cap-1",
                    "CPU",
                    "AVAILABLE",
                    requirements=[_req("min_cores", "4"), _req("arch", "x86")],
                ),
                _res(
                    "ctx-2",
                    "env-2",
                    "cap-2",
                    "MEMORY",
                    "AVAILABLE",
                    requirements=[_req("min_gb", "8")],
                ),
            ]
        )
        assert report["requirement_count"] == 3

    def test_schema_version_preserved(self, engine):
        report = engine.create(
            resources=[_res("ctx-1", "env-1", "cap-1", "CPU", "AVAILABLE")]
        )
        assert report["schema_version"] == "1.0"

    def test_raw_metadata_preserved(self, engine):
        report = engine.create(
            resources=[_res("ctx-1", "env-1", "cap-1", "CPU", "AVAILABLE")],
            raw_metadata={"source": "program-0"},
        )
        assert report["raw_metadata"] == {"source": "program-0"}

    def test_resource_raw_payload_preserved(self, engine):
        report = engine.create(
            resources=[
                _res(
                    "ctx-1",
                    "env-1",
                    "cap-1",
                    "CPU",
                    "AVAILABLE",
                    raw_payload={"nested": {"deep": [1, 2]}},
                )
            ]
        )
        assert report["resources"][0]["raw_payload"] == {
            "nested": {"deep": [1, 2]}
        }


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_resource_type_normalized(self, engine):
        report = engine.create(
            resources=[_res("ctx-1", "env-1", "cap-1", "memory", "AVAILABLE")]
        )
        assert report["resources"][0]["resource_type"] == "MEMORY"

    def test_status_normalized(self, engine):
        report = engine.create(
            resources=[_res("ctx-1", "env-1", "cap-1", "CPU", "available")]
        )
        assert report["resources"][0]["status"] == "AVAILABLE"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_resource_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid resource_type"):
            engine.create(
                resources=[
                    _res("ctx-1", "env-1", "cap-1", "NONSENSE", "AVAILABLE")
                ]
            )

    def test_invalid_status_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid status"):
            engine.create(
                resources=[_res("ctx-1", "env-1", "cap-1", "CPU", "NOPE")]
            )

    def test_missing_context_id_rejected(self, engine):
        with pytest.raises(ValueError, match="context_id is required"):
            engine.create(
                resources=[_res("", "env-1", "cap-1", "CPU", "AVAILABLE")]
            )

    def test_missing_environment_id_rejected(self, engine):
        with pytest.raises(ValueError, match="environment_id is required"):
            engine.create(
                resources=[_res("ctx-1", "", "cap-1", "CPU", "AVAILABLE")]
            )

    def test_missing_capability_id_rejected(self, engine):
        with pytest.raises(ValueError, match="capability_id is required"):
            engine.create(
                resources=[_res("ctx-1", "env-1", "", "CPU", "AVAILABLE")]
            )

    def test_missing_resource_type_rejected(self, engine):
        with pytest.raises(ValueError, match="resource_type is required"):
            engine.create(
                resources=[_res("ctx-1", "env-1", "cap-1", "", "AVAILABLE")]
            )

    def test_missing_status_rejected(self, engine):
        with pytest.raises(ValueError, match="status is required"):
            engine.create(
                resources=[_res("ctx-1", "env-1", "cap-1", "CPU", "")]
            )

    def test_missing_requirement_type_rejected(self, engine):
        with pytest.raises(ValueError, match="requirement_type is required"):
            engine.create(
                resources=[
                    _res(
                        "ctx-1",
                        "env-1",
                        "cap-1",
                        "CPU",
                        "AVAILABLE",
                        requirements=[_req("", "4")],
                    )
                ]
            )

    def test_missing_requirement_value_rejected(self, engine):
        with pytest.raises(ValueError, match="requirement_value is required"):
            engine.create(
                resources=[
                    _res(
                        "ctx-1",
                        "env-1",
                        "cap-1",
                        "CPU",
                        "AVAILABLE",
                        requirements=[_req("min_cores", "")],
                    )
                ]
            )


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


class TestDuplicateDetection:
    def test_duplicate_resource_deduped_and_counted(self, engine):
        report = engine.create(
            resources=[
                _res("ctx-1", "env-1", "cap-1", "CPU", "AVAILABLE"),
                _res("ctx-1", "env-1", "cap-1", "cpu", "DEGRADED"),
            ]
        )
        assert report["resource_count"] == 1
        assert report["duplicate_resource_count"] == 1

    def test_distinct_resource_type_not_duplicate(self, engine):
        report = engine.create(
            resources=[
                _res("ctx-1", "env-1", "cap-1", "CPU", "AVAILABLE"),
                _res("ctx-1", "env-1", "cap-1", "MEMORY", "AVAILABLE"),
            ]
        )
        assert report["resource_count"] == 2
        assert report["duplicate_resource_count"] == 0

    def test_distinct_environment_not_duplicate(self, engine):
        report = engine.create(
            resources=[
                _res("ctx-1", "env-1", "cap-1", "CPU", "AVAILABLE"),
                _res("ctx-1", "env-2", "cap-1", "CPU", "AVAILABLE"),
            ]
        )
        assert report["resource_count"] == 2
        assert report["duplicate_resource_count"] == 0


# ---------------------------------------------------------------------------
# Unavailable / degraded detection
# ---------------------------------------------------------------------------


class TestUnavailableDegradedDetection:
    def test_unavailable_detected(self, engine):
        report = engine.create(
            resources=[
                _res("ctx-1", "env-1", "cap-1", "CPU", "UNAVAILABLE"),
                _res("ctx-2", "env-2", "cap-2", "MEMORY", "AVAILABLE"),
            ]
        )
        assert report["unavailable_count"] == 1
        assert report["degraded_count"] == 0

    def test_degraded_detected(self, engine):
        report = engine.create(
            resources=[
                _res("ctx-1", "env-1", "cap-1", "CPU", "DEGRADED"),
                _res("ctx-2", "env-2", "cap-2", "MEMORY", "AVAILABLE"),
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
    def test_pass_with_clean_resources(self, engine):
        report = engine.create(
            resources=[
                _res("ctx-1", "env-1", "cap-1", "CPU", "AVAILABLE"),
                _res("ctx-2", "env-2", "cap-2", "MEMORY", "UNKNOWN"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is True
        assert pf["resource_count"] == 2
        assert pf["status"] == "passed"

    def test_empty_report_fails(self, engine):
        report = engine.create(resources=[])
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["resource_count"] == 0
        assert pf["status"] == "failed"

    def test_unavailable_fails(self, engine):
        report = engine.create(
            resources=[_res("ctx-1", "env-1", "cap-1", "CPU", "UNAVAILABLE")]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["unavailable_count"] == 1

    def test_degraded_fails(self, engine):
        report = engine.create(
            resources=[_res("ctx-1", "env-1", "cap-1", "CPU", "DEGRADED")]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["degraded_count"] == 1

    def test_duplicate_does_not_fail_when_clean(self, engine):
        report = engine.create(
            resources=[
                _res("ctx-1", "env-1", "cap-1", "CPU", "AVAILABLE"),
                _res("ctx-1", "env-1", "cap-1", "CPU", "AVAILABLE"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["duplicate_resource_count"] == 1
        assert pf["passed"] is True

    def test_evidence_bundle_files_written(self, engine):
        report = engine.create(
            resources=[_res("ctx-1", "env-1", "cap-1", "CPU", "AVAILABLE")]
        )
        report_dir = engine._report_dir / report["report_id"]
        for name in (
            "execution_resource_request.json",
            "execution_resource_result.json",
            "execution_resource_summary.md",
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
            resources=[_res("ctx-1", "env-1", "cap-1", "CPU", "AVAILABLE")]
        )
        report_id = created["report_id"]
        appended = engine.append(
            report_id,
            resources=[_res("ctx-2", "env-2", "cap-2", "MEMORY", "AVAILABLE")],
        )
        assert appended["report_id"] == report_id
        assert appended["resource_count"] == 2
        caps = {r["capability_id"] for r in appended["resources"]}
        assert caps == {"cap-1", "cap-2"}

    def test_append_preserves_raw_metadata(self, engine):
        created = engine.create(
            resources=[_res("ctx-1", "env-1", "cap-1", "CPU", "AVAILABLE")],
            raw_metadata={"origin": "p0"},
        )
        appended = engine.append(
            created["report_id"],
            resources=[_res("ctx-2", "env-2", "cap-2", "MEMORY", "AVAILABLE")],
        )
        assert appended["raw_metadata"] == {"origin": "p0"}

    def test_append_missing_report_raises(self, engine):
        with pytest.raises(ValueError, match="Report not found"):
            engine.append("does-not-exist", resources=[])


# ---------------------------------------------------------------------------
# Retrieval / exports
# ---------------------------------------------------------------------------


class TestRetrievalExport:
    def test_get_report_round_trip(self, engine):
        created = engine.create(
            resources=[_res("ctx-1", "env-1", "cap-1", "CPU", "AVAILABLE")]
        )
        loaded = engine.get_report(created["report_id"])
        assert loaded["report_id"] == created["report_id"]
        assert loaded["resource_count"] == 1

    def test_get_missing_returns_none(self, engine):
        assert engine.get_report("missing-id") is None

    def test_list_reports_sorted(self, engine):
        engine.create(
            resources=[_res("ctx-1", "env-1", "cap-1", "CPU", "AVAILABLE")]
        )
        engine.create(
            resources=[_res("ctx-2", "env-2", "cap-2", "MEMORY", "AVAILABLE")]
        )
        assert len(engine.list_reports()) == 2

    def test_export_json_valid(self, engine):
        created = engine.create(
            resources=[_res("ctx-1", "env-1", "cap-1", "CPU", "AVAILABLE")]
        )
        parsed = json.loads(
            engine.export_report(created["report_id"], fmt="json")
        )
        assert parsed["report_id"] == created["report_id"]

    def test_export_markdown_headings(self, engine):
        created = engine.create(
            resources=[
                _res(
                    "ctx-1",
                    "env-1",
                    "cap-122",
                    "MEMORY",
                    "AVAILABLE",
                    requirements=[_req("min_gb", "8")],
                )
            ]
        )
        out = engine.export_report(created["report_id"], fmt="markdown")
        assert "# Execution Resource Report" in out
        assert "## Status Counts" in out
        assert "## Resource Type Counts" in out
        assert "## Resources" in out
        assert "[AVAILABLE]" in out
        assert "[MEMORY]" in out
        assert "capability=cap-122" in out
        assert "[min_gb] 8" in out

    def test_export_csv_rows(self, engine):
        created = engine.create(
            resources=[
                _res(
                    "ctx-1",
                    "env-1",
                    "cap-1",
                    "MEMORY",
                    "AVAILABLE",
                    requirements=[_req("min_gb", "8")],
                ),
                _res("ctx-2", "env-2", "cap-2", "CPU", "UNKNOWN"),
            ]
        )
        out = engine.export_report(created["report_id"], fmt="csv")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        assert lines[0].startswith("record_kind,")
        # header + 2 resources + 1 requirement
        assert len(lines) == 4
        resource_rows = [
            ln for ln in lines[1:] if ln.startswith("resource,")
        ]
        requirement_rows = [
            ln for ln in lines[1:] if ln.startswith("requirement,")
        ]
        assert len(resource_rows) == 2
        assert len(requirement_rows) == 1

    def test_export_invalid_format_raises(self, engine):
        created = engine.create(
            resources=[_res("ctx-1", "env-1", "cap-1", "CPU", "AVAILABLE")]
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
