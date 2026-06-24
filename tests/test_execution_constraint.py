"""Tests for the Execution Constraint Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.execution_constraint import (
    ExecutionConstraint,
    ExecutionConstraintEngine,
    ExecutionConstraintEvidence,
    ExecutionConstraintReference,
    ExecutionConstraintReferenceType,
    ExecutionConstraintReport,
    ExecutionConstraintSeverity,
    ExecutionConstraintType,
)


def _con(
    context_id: str,
    environment_id: str,
    resource_id: str,
    capability_id: str,
    constraint_type: str,
    severity: str,
    **kw,
) -> dict:
    data = {
        "context_id": context_id,
        "environment_id": environment_id,
        "resource_id": resource_id,
        "capability_id": capability_id,
        "constraint_type": constraint_type,
        "severity": severity,
        "summary": kw.get("summary", ""),
    }
    if "constraint_id" in kw:
        data["constraint_id"] = kw["constraint_id"]
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
    return ExecutionConstraintEngine(
        artifacts_root=str(tmp_path / "artifacts")
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_reference_round_trip(self):
        r = ExecutionConstraintReference(
            reference_id="r-1",
            reference_type="POLICY",
            reference_value="max-runtime",
            summary="policy",
        )
        assert ExecutionConstraintReference.from_dict(r.to_dict()) == r

    def test_constraint_round_trip(self):
        c = ExecutionConstraint(
            constraint_id="con-1",
            context_id="ctx-1",
            environment_id="env-1",
            resource_id="res-1",
            capability_id="cap-1",
            constraint_type="TIME",
            severity="WARNING",
            references=[
                ExecutionConstraintReference(
                    reference_id="r-1",
                    reference_type="POLICY",
                    reference_value="max-runtime",
                )
            ],
            summary="time budget",
            created_at="2026-01-01T00:00:00+00:00",
            raw_payload={"k": "v"},
        )
        assert ExecutionConstraint.from_dict(c.to_dict()) == c

    def test_constraint_gets_id_and_timestamp(self):
        c = ExecutionConstraint(
            context_id="ctx-1",
            environment_id="env-1",
            resource_id="res-1",
            capability_id="cap-1",
            constraint_type="MEMORY",
            severity="INFO",
        )
        assert c.constraint_id
        assert c.created_at

    def test_report_defaults(self):
        report = ExecutionConstraintReport()
        assert report.report_id
        assert report.created_at
        assert report.constraint_count == 0
        assert report.critical_count == 0
        assert report.error_count == 0
        assert report.schema_version == "1.0"

    def test_evidence_defaults(self):
        ev = ExecutionConstraintEvidence(report_id="rep-1")
        assert ev.evidence_id
        assert ev.created_at
        assert ev.report_id == "rep-1"

    def test_all_constraint_types_present(self):
        assert {t.value for t in ExecutionConstraintType} == {
            "TIME",
            "MEMORY",
            "STORAGE",
            "SECURITY",
            "NETWORK",
            "TOOLING",
            "VERSION",
            "POLICY",
            "DEPENDENCY",
            "OTHER",
        }

    def test_all_severities_present(self):
        assert {t.value for t in ExecutionConstraintSeverity} == {
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        }

    def test_all_reference_types_present(self):
        assert {t.value for t in ExecutionConstraintReferenceType} == {
            "CAPABILITY",
            "CONTEXT",
            "ENVIRONMENT",
            "RESOURCE",
            "FILE",
            "VALIDATION",
            "ARTIFACT",
            "POLICY",
            "OTHER",
        }


# ---------------------------------------------------------------------------
# Create / determinism
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_counts(self, engine):
        report = engine.create(
            constraints=[
                _con("ctx-1", "env-1", "res-1", "cap-1", "TIME", "INFO"),
                _con("ctx-2", "env-2", "res-2", "cap-2", "MEMORY", "INFO"),
                _con("ctx-3", "env-3", "res-3", "cap-3", "POLICY", "WARNING"),
            ]
        )
        assert report["constraint_count"] == 3
        assert report["severity_counts"] == {
            "INFO": 2,
            "WARNING": 1,
        }
        assert report["constraint_type_counts"] == {
            "MEMORY": 1,
            "POLICY": 1,
            "TIME": 1,
        }
        assert report["critical_count"] == 0
        assert report["error_count"] == 0

    def test_deterministic_ordering(self, engine):
        report = engine.create(
            constraints=[
                _con("ctx-2", "env-1", "res-1", "cap-1", "TIME", "INFO"),
                _con("ctx-1", "env-1", "res-1", "cap-2", "MEMORY", "INFO"),
                _con("ctx-1", "env-1", "res-1", "cap-1", "TIME", "INFO"),
            ]
        )
        order = [
            (
                c["context_id"],
                c["environment_id"],
                c["resource_id"],
                c["capability_id"],
                c["constraint_type"],
            )
            for c in report["constraints"]
        ]
        assert order == [
            ("ctx-1", "env-1", "res-1", "cap-1", "TIME"),
            ("ctx-1", "env-1", "res-1", "cap-2", "MEMORY"),
            ("ctx-2", "env-1", "res-1", "cap-1", "TIME"),
        ]

    def test_ordering_is_input_independent(self, engine):
        constraints = [
            _con("ctx-1", "env-1", "res-1", "cap-1", "TIME", "INFO"),
            _con("ctx-2", "env-2", "res-2", "cap-2", "MEMORY", "INFO"),
            _con("ctx-3", "env-3", "res-3", "cap-3", "TOOLING", "INFO"),
        ]
        r1 = engine.create(constraints=list(constraints))
        r2 = engine.create(constraints=list(reversed(constraints)))
        key = lambda rep: [  # noqa: E731
            (c["context_id"], c["capability_id"]) for c in rep["constraints"]
        ]
        assert key(r1) == key(r2)

    def test_references_ordered_deterministically(self, engine):
        report = engine.create(
            constraints=[
                _con(
                    "ctx-1",
                    "env-1",
                    "res-1",
                    "cap-1",
                    "POLICY",
                    "INFO",
                    references=[
                        _ref("RESOURCE", "res-9"),
                        _ref("CAPABILITY", "cap-9"),
                        _ref("CONTEXT", "ctx-9"),
                    ],
                )
            ]
        )
        order = [
            (r["reference_type"], r["reference_value"])
            for r in report["constraints"][0]["references"]
        ]
        assert order == [
            ("CAPABILITY", "cap-9"),
            ("CONTEXT", "ctx-9"),
            ("RESOURCE", "res-9"),
        ]

    def test_schema_version_preserved(self, engine):
        report = engine.create(
            constraints=[
                _con("ctx-1", "env-1", "res-1", "cap-1", "TIME", "INFO")
            ]
        )
        assert report["schema_version"] == "1.0"

    def test_raw_metadata_preserved(self, engine):
        report = engine.create(
            constraints=[
                _con("ctx-1", "env-1", "res-1", "cap-1", "TIME", "INFO")
            ],
            raw_metadata={"source": "program-0"},
        )
        assert report["raw_metadata"] == {"source": "program-0"}

    def test_constraint_raw_payload_preserved(self, engine):
        report = engine.create(
            constraints=[
                _con(
                    "ctx-1",
                    "env-1",
                    "res-1",
                    "cap-1",
                    "TIME",
                    "INFO",
                    raw_payload={"nested": {"deep": [1, 2]}},
                )
            ]
        )
        assert report["constraints"][0]["raw_payload"] == {
            "nested": {"deep": [1, 2]}
        }


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_constraint_type_normalized(self, engine):
        report = engine.create(
            constraints=[
                _con("ctx-1", "env-1", "res-1", "cap-1", "memory", "INFO")
            ]
        )
        assert report["constraints"][0]["constraint_type"] == "MEMORY"

    def test_severity_normalized(self, engine):
        report = engine.create(
            constraints=[
                _con("ctx-1", "env-1", "res-1", "cap-1", "TIME", "warning")
            ]
        )
        assert report["constraints"][0]["severity"] == "WARNING"

    def test_reference_type_normalized(self, engine):
        report = engine.create(
            constraints=[
                _con(
                    "ctx-1",
                    "env-1",
                    "res-1",
                    "cap-1",
                    "POLICY",
                    "INFO",
                    references=[_ref("policy", "max-runtime")],
                )
            ]
        )
        assert (
            report["constraints"][0]["references"][0]["reference_type"]
            == "POLICY"
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_constraint_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid constraint_type"):
            engine.create(
                constraints=[
                    _con(
                        "ctx-1", "env-1", "res-1", "cap-1", "NONSENSE", "INFO"
                    )
                ]
            )

    def test_invalid_severity_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid severity"):
            engine.create(
                constraints=[
                    _con("ctx-1", "env-1", "res-1", "cap-1", "TIME", "NOPE")
                ]
            )

    def test_missing_context_id_rejected(self, engine):
        with pytest.raises(ValueError, match="context_id is required"):
            engine.create(
                constraints=[
                    _con("", "env-1", "res-1", "cap-1", "TIME", "INFO")
                ]
            )

    def test_missing_environment_id_rejected(self, engine):
        with pytest.raises(ValueError, match="environment_id is required"):
            engine.create(
                constraints=[
                    _con("ctx-1", "", "res-1", "cap-1", "TIME", "INFO")
                ]
            )

    def test_missing_resource_id_rejected(self, engine):
        with pytest.raises(ValueError, match="resource_id is required"):
            engine.create(
                constraints=[
                    _con("ctx-1", "env-1", "", "cap-1", "TIME", "INFO")
                ]
            )

    def test_missing_capability_id_rejected(self, engine):
        with pytest.raises(ValueError, match="capability_id is required"):
            engine.create(
                constraints=[
                    _con("ctx-1", "env-1", "res-1", "", "TIME", "INFO")
                ]
            )

    def test_missing_constraint_type_rejected(self, engine):
        with pytest.raises(ValueError, match="constraint_type is required"):
            engine.create(
                constraints=[
                    _con("ctx-1", "env-1", "res-1", "cap-1", "", "INFO")
                ]
            )

    def test_missing_severity_rejected(self, engine):
        with pytest.raises(ValueError, match="severity is required"):
            engine.create(
                constraints=[
                    _con("ctx-1", "env-1", "res-1", "cap-1", "TIME", "")
                ]
            )

    def test_invalid_reference_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid reference_type"):
            engine.create(
                constraints=[
                    _con(
                        "ctx-1",
                        "env-1",
                        "res-1",
                        "cap-1",
                        "POLICY",
                        "INFO",
                        references=[_ref("NONSENSE", "x")],
                    )
                ]
            )

    def test_missing_reference_value_rejected(self, engine):
        with pytest.raises(ValueError, match="reference_value is required"):
            engine.create(
                constraints=[
                    _con(
                        "ctx-1",
                        "env-1",
                        "res-1",
                        "cap-1",
                        "POLICY",
                        "INFO",
                        references=[_ref("POLICY", "")],
                    )
                ]
            )


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


class TestDuplicateDetection:
    def test_duplicate_constraint_deduped_and_counted(self, engine):
        report = engine.create(
            constraints=[
                _con("ctx-1", "env-1", "res-1", "cap-1", "TIME", "INFO"),
                _con("ctx-1", "env-1", "res-1", "cap-1", "time", "ERROR"),
            ]
        )
        assert report["constraint_count"] == 1
        assert report["duplicate_constraint_count"] == 1

    def test_distinct_constraint_type_not_duplicate(self, engine):
        report = engine.create(
            constraints=[
                _con("ctx-1", "env-1", "res-1", "cap-1", "TIME", "INFO"),
                _con("ctx-1", "env-1", "res-1", "cap-1", "MEMORY", "INFO"),
            ]
        )
        assert report["constraint_count"] == 2
        assert report["duplicate_constraint_count"] == 0

    def test_distinct_resource_not_duplicate(self, engine):
        report = engine.create(
            constraints=[
                _con("ctx-1", "env-1", "res-1", "cap-1", "TIME", "INFO"),
                _con("ctx-1", "env-1", "res-2", "cap-1", "TIME", "INFO"),
            ]
        )
        assert report["constraint_count"] == 2
        assert report["duplicate_constraint_count"] == 0


# ---------------------------------------------------------------------------
# Critical / error detection
# ---------------------------------------------------------------------------


class TestCriticalErrorDetection:
    def test_critical_detected(self, engine):
        report = engine.create(
            constraints=[
                _con("ctx-1", "env-1", "res-1", "cap-1", "SECURITY",
                     "CRITICAL"),
                _con("ctx-2", "env-2", "res-2", "cap-2", "MEMORY", "INFO"),
            ]
        )
        assert report["critical_count"] == 1
        assert report["error_count"] == 0

    def test_error_detected(self, engine):
        report = engine.create(
            constraints=[
                _con("ctx-1", "env-1", "res-1", "cap-1", "VERSION", "ERROR"),
                _con("ctx-2", "env-2", "res-2", "cap-2", "MEMORY", "INFO"),
            ]
        )
        assert report["error_count"] == 1
        assert report["critical_count"] == 0


# ---------------------------------------------------------------------------
# Pass/fail
# ---------------------------------------------------------------------------


def _read_pass_fail(engine, report_id: str) -> dict:
    path = engine._report_dir / report_id / "pass_fail.json"
    return json.loads(path.read_text(encoding="utf-8"))


class TestPassFail:
    def test_pass_with_clean_constraints(self, engine):
        report = engine.create(
            constraints=[
                _con("ctx-1", "env-1", "res-1", "cap-1", "TIME", "INFO"),
                _con("ctx-2", "env-2", "res-2", "cap-2", "MEMORY", "WARNING"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is True
        assert pf["constraint_count"] == 2
        assert pf["status"] == "passed"

    def test_empty_report_fails(self, engine):
        report = engine.create(constraints=[])
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["constraint_count"] == 0
        assert pf["status"] == "failed"

    def test_critical_fails(self, engine):
        report = engine.create(
            constraints=[
                _con("ctx-1", "env-1", "res-1", "cap-1", "SECURITY",
                     "CRITICAL")
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["critical_count"] == 1

    def test_error_fails(self, engine):
        report = engine.create(
            constraints=[
                _con("ctx-1", "env-1", "res-1", "cap-1", "VERSION", "ERROR")
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["error_count"] == 1

    def test_duplicate_does_not_fail_when_clean(self, engine):
        report = engine.create(
            constraints=[
                _con("ctx-1", "env-1", "res-1", "cap-1", "TIME", "INFO"),
                _con("ctx-1", "env-1", "res-1", "cap-1", "TIME", "INFO"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["duplicate_constraint_count"] == 1
        assert pf["passed"] is True

    def test_evidence_bundle_files_written(self, engine):
        report = engine.create(
            constraints=[
                _con("ctx-1", "env-1", "res-1", "cap-1", "TIME", "INFO")
            ]
        )
        report_dir = engine._report_dir / report["report_id"]
        for name in (
            "execution_constraint_request.json",
            "execution_constraint_result.json",
            "execution_constraint_summary.md",
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
            constraints=[
                _con("ctx-1", "env-1", "res-1", "cap-1", "TIME", "INFO")
            ]
        )
        report_id = created["report_id"]
        appended = engine.append(
            report_id,
            constraints=[
                _con("ctx-2", "env-2", "res-2", "cap-2", "MEMORY", "INFO")
            ],
        )
        assert appended["report_id"] == report_id
        assert appended["constraint_count"] == 2
        caps = {c["capability_id"] for c in appended["constraints"]}
        assert caps == {"cap-1", "cap-2"}

    def test_append_preserves_raw_metadata(self, engine):
        created = engine.create(
            constraints=[
                _con("ctx-1", "env-1", "res-1", "cap-1", "TIME", "INFO")
            ],
            raw_metadata={"origin": "p0"},
        )
        appended = engine.append(
            created["report_id"],
            constraints=[
                _con("ctx-2", "env-2", "res-2", "cap-2", "MEMORY", "INFO")
            ],
        )
        assert appended["raw_metadata"] == {"origin": "p0"}

    def test_append_missing_report_raises(self, engine):
        with pytest.raises(ValueError, match="Report not found"):
            engine.append("does-not-exist", constraints=[])


# ---------------------------------------------------------------------------
# Retrieval / exports
# ---------------------------------------------------------------------------


class TestRetrievalExport:
    def test_get_report_round_trip(self, engine):
        created = engine.create(
            constraints=[
                _con("ctx-1", "env-1", "res-1", "cap-1", "TIME", "INFO")
            ]
        )
        loaded = engine.get_report(created["report_id"])
        assert loaded["report_id"] == created["report_id"]
        assert loaded["constraint_count"] == 1

    def test_get_missing_returns_none(self, engine):
        assert engine.get_report("missing-id") is None

    def test_list_reports_sorted(self, engine):
        engine.create(
            constraints=[
                _con("ctx-1", "env-1", "res-1", "cap-1", "TIME", "INFO")
            ]
        )
        engine.create(
            constraints=[
                _con("ctx-2", "env-2", "res-2", "cap-2", "MEMORY", "INFO")
            ]
        )
        assert len(engine.list_reports()) == 2

    def test_export_json_valid(self, engine):
        created = engine.create(
            constraints=[
                _con("ctx-1", "env-1", "res-1", "cap-1", "TIME", "INFO")
            ]
        )
        parsed = json.loads(
            engine.export_report(created["report_id"], fmt="json")
        )
        assert parsed["report_id"] == created["report_id"]

    def test_export_markdown_headings(self, engine):
        created = engine.create(
            constraints=[
                _con(
                    "ctx-1",
                    "env-1",
                    "res-1",
                    "cap-122",
                    "POLICY",
                    "WARNING",
                    references=[_ref("POLICY", "max-runtime")],
                )
            ]
        )
        out = engine.export_report(created["report_id"], fmt="markdown")
        assert "# Execution Constraint Report" in out
        assert "## Severity Counts" in out
        assert "## Constraint Type Counts" in out
        assert "## Constraints" in out
        assert "[WARNING]" in out
        assert "[POLICY]" in out
        assert "capability=cap-122" in out
        assert "[POLICY] max-runtime" in out

    def test_export_csv_rows(self, engine):
        created = engine.create(
            constraints=[
                _con(
                    "ctx-1",
                    "env-1",
                    "res-1",
                    "cap-1",
                    "POLICY",
                    "INFO",
                    references=[_ref("POLICY", "max-runtime")],
                ),
                _con("ctx-2", "env-2", "res-2", "cap-2", "TIME", "WARNING"),
            ]
        )
        out = engine.export_report(created["report_id"], fmt="csv")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        assert lines[0].startswith("record_kind,")
        # header + 2 constraints + 1 reference
        assert len(lines) == 4
        constraint_rows = [
            ln for ln in lines[1:] if ln.startswith("constraint,")
        ]
        reference_rows = [
            ln for ln in lines[1:] if ln.startswith("reference,")
        ]
        assert len(constraint_rows) == 2
        assert len(reference_rows) == 1

    def test_export_invalid_format_raises(self, engine):
        created = engine.create(
            constraints=[
                _con("ctx-1", "env-1", "res-1", "cap-1", "TIME", "INFO")
            ]
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
