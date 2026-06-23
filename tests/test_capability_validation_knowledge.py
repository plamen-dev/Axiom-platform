"""Tests for the Capability Validation Knowledge Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.capability_validation_knowledge import (
    CapabilityValidationArtifact,
    CapabilityValidationFinding,
    CapabilityValidationFindingSeverity,
    CapabilityValidationKnowledge,
    CapabilityValidationKnowledgeEngine,
    CapabilityValidationKnowledgeEvidence,
    CapabilityValidationKnowledgeReport,
    CapabilityValidationRecord,
    CapabilityValidationStatus,
    CapabilityValidationType,
)


def _rec(
    capability_id: str,
    validation_type: str,
    validation_status: str,
    **kw,
) -> dict:
    data = {
        "capability_id": capability_id,
        "validation_type": validation_type,
        "validation_status": validation_status,
        "validator": kw.get("validator", "devin"),
        "summary": kw.get("summary", f"{validation_type} {validation_status}"),
    }
    if "validation_id" in kw:
        data["validation_id"] = kw["validation_id"]
    if "raw_payload" in kw:
        data["raw_payload"] = kw["raw_payload"]
    return data


def _find(validation_id: str, severity: str, resolved: bool, **kw) -> dict:
    data = {
        "validation_id": validation_id,
        "severity": severity,
        "resolved": resolved,
        "summary": kw.get("summary", f"{severity} finding"),
    }
    if "finding_id" in kw:
        data["finding_id"] = kw["finding_id"]
    return data


def _art(validation_id: str, artifact_path: str, **kw) -> dict:
    data = {
        "validation_id": validation_id,
        "artifact_path": artifact_path,
        "summary": kw.get("summary", ""),
    }
    if "artifact_id" in kw:
        data["artifact_id"] = kw["artifact_id"]
    return data


@pytest.fixture
def engine(tmp_path):
    return CapabilityValidationKnowledgeEngine(
        artifacts_root=str(tmp_path / "artifacts")
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_record_round_trip(self):
        r = CapabilityValidationRecord(
            validation_id="v-1",
            capability_id="cap-122",
            validation_type="PYTEST",
            validation_status="PASSED",
            validator="devin",
            summary="ran pytest",
            created_at="2026-01-01T00:00:00+00:00",
            raw_payload={"k": "v"},
        )
        assert CapabilityValidationRecord.from_dict(r.to_dict()) == r

    def test_record_gets_id_and_timestamp(self):
        r = CapabilityValidationRecord(
            capability_id="a",
            validation_type="PYTEST",
            validation_status="PASSED",
        )
        assert r.validation_id
        assert r.created_at

    def test_finding_round_trip(self):
        f = CapabilityValidationFinding(
            finding_id="f-1",
            validation_id="v-1",
            severity="ERROR",
            summary="bad",
            resolved=True,
            created_at="2026-01-01T00:00:00+00:00",
        )
        assert CapabilityValidationFinding.from_dict(f.to_dict()) == f

    def test_artifact_round_trip(self):
        a = CapabilityValidationArtifact(
            artifact_id="a-1",
            validation_id="v-1",
            artifact_path="artifacts/x/pass_fail.json",
            summary="evidence",
            created_at="2026-01-01T00:00:00+00:00",
        )
        assert CapabilityValidationArtifact.from_dict(a.to_dict()) == a

    def test_knowledge_round_trip(self):
        k = CapabilityValidationKnowledge(
            knowledge_id="k-1",
            capability_id="cap-122",
            validation_count=2,
            finding_count=3,
            unresolved_count=1,
            validation_type_counts={"PYTEST": 1, "RUFF": 1},
            created_at="2026-01-01T00:00:00+00:00",
            raw_payload={"k": "v"},
        )
        assert CapabilityValidationKnowledge.from_dict(k.to_dict()) == k

    def test_report_defaults(self):
        report = CapabilityValidationKnowledgeReport()
        assert report.report_id
        assert report.created_at
        assert report.validation_count == 0
        assert report.schema_version == "1.0"

    def test_evidence_defaults(self):
        ev = CapabilityValidationKnowledgeEvidence(report_id="rep-1")
        assert ev.evidence_id
        assert ev.created_at
        assert ev.report_id == "rep-1"

    def test_all_validation_types_present(self):
        assert {t.value for t in CapabilityValidationType} == {
            "PYTEST",
            "RUFF",
            "CI",
            "DEVIN_REVIEW",
            "CLI_TEST",
            "MANUAL_TEST",
            "INTEGRATION_TEST",
            "REGRESSION_TEST",
        }

    def test_all_statuses_present(self):
        assert {s.value for s in CapabilityValidationStatus} == {
            "PASSED",
            "FAILED",
            "PARTIAL",
            "WARNING",
        }

    def test_all_severities_present(self):
        assert {s.value for s in CapabilityValidationFindingSeverity} == {
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        }


# ---------------------------------------------------------------------------
# Create / determinism
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_counts(self, engine):
        report = engine.create(
            validation_records=[
                _rec("cap-122", "PYTEST", "PASSED"),
                _rec("cap-122", "RUFF", "PASSED"),
                _rec("cap-124", "CLI_TEST", "PASSED"),
            ]
        )
        assert report["validation_count"] == 3
        assert report["capability_count"] == 2
        assert report["validation_type_counts"] == {
            "CLI_TEST": 1,
            "PYTEST": 1,
            "RUFF": 1,
        }
        assert report["validation_status_counts"] == {"PASSED": 3}

    def test_deterministic_ordering(self, engine):
        report = engine.create(
            validation_records=[
                _rec("cap-124", "RUFF", "PASSED"),
                _rec("cap-122", "RUFF", "PASSED"),
                _rec("cap-122", "PYTEST", "PASSED"),
                _rec("cap-122", "PYTEST", "FAILED"),
            ]
        )
        order = [
            (
                r["capability_id"],
                r["validation_type"],
                r["validation_status"],
            )
            for r in report["records"]
        ]
        assert order == [
            ("cap-122", "PYTEST", "FAILED"),
            ("cap-122", "PYTEST", "PASSED"),
            ("cap-122", "RUFF", "PASSED"),
            ("cap-124", "RUFF", "PASSED"),
        ]

    def test_ordering_is_input_independent(self, engine):
        recs = [
            _rec("a", "PYTEST", "PASSED"),
            _rec("c", "RUFF", "PASSED"),
            _rec("a", "CLI_TEST", "PASSED"),
        ]
        r1 = engine.create(validation_records=list(recs))
        r2 = engine.create(validation_records=list(reversed(recs)))
        key = lambda rep: [  # noqa: E731
            (x["capability_id"], x["validation_type"], x["validation_status"])
            for x in rep["records"]
        ]
        assert key(r1) == key(r2)

    def test_schema_version_preserved(self, engine):
        report = engine.create(
            validation_records=[_rec("a", "PYTEST", "PASSED")]
        )
        assert report["schema_version"] == "1.0"

    def test_raw_metadata_preserved(self, engine):
        report = engine.create(
            validation_records=[_rec("a", "PYTEST", "PASSED")],
            raw_metadata={"source": "program-0"},
        )
        assert report["raw_metadata"] == {"source": "program-0"}

    def test_record_raw_payload_preserved(self, engine):
        report = engine.create(
            validation_records=[
                _rec(
                    "a",
                    "PYTEST",
                    "PASSED",
                    raw_payload={"nested": {"deep": [1, 2]}},
                )
            ]
        )
        assert report["records"][0]["raw_payload"] == {
            "nested": {"deep": [1, 2]}
        }

    def test_knowledge_raw_payload_preserved(self, engine):
        report = engine.create(
            validation_records=[_rec("cap-122", "PYTEST", "PASSED")],
            knowledge_payloads={"cap-122": {"nested": {"deep": [1, 2]}}},
        )
        knowledge = {k["capability_id"]: k for k in report["knowledge"]}
        assert knowledge["cap-122"]["raw_payload"] == {
            "nested": {"deep": [1, 2]}
        }


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_validation_type_normalized(self, engine):
        report = engine.create(
            validation_records=[_rec("a", "pytest", "PASSED")]
        )
        assert report["records"][0]["validation_type"] == "PYTEST"

    def test_validation_status_normalized(self, engine):
        report = engine.create(
            validation_records=[_rec("a", "PYTEST", "passed")]
        )
        assert report["records"][0]["validation_status"] == "PASSED"

    def test_severity_normalized(self, engine):
        report = engine.create(
            validation_records=[
                _rec("a", "PYTEST", "FAILED", validation_id="v-1")
            ],
            validation_findings=[_find("v-1", "error", False)],
        )
        assert report["findings"][0]["severity"] == "ERROR"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_validation_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid validation_type"):
            engine.create(
                validation_records=[_rec("a", "NONSENSE", "PASSED")]
            )

    def test_invalid_validation_status_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid validation_status"):
            engine.create(
                validation_records=[_rec("a", "PYTEST", "NONSENSE")]
            )

    def test_invalid_severity_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid severity"):
            engine.create(
                validation_records=[
                    _rec("a", "PYTEST", "FAILED", validation_id="v-1")
                ],
                validation_findings=[_find("v-1", "NOPE", False)],
            )

    def test_missing_capability_rejected(self, engine):
        with pytest.raises(ValueError, match="capability_id is required"):
            engine.create(
                validation_records=[_rec("", "PYTEST", "PASSED")]
            )

    def test_missing_validation_type_rejected(self, engine):
        with pytest.raises(ValueError, match="validation_type is required"):
            engine.create(
                validation_records=[_rec("a", "", "PASSED")]
            )

    def test_missing_validation_status_rejected(self, engine):
        with pytest.raises(ValueError, match="validation_status is required"):
            engine.create(
                validation_records=[_rec("a", "PYTEST", "")]
            )

    def test_finding_missing_validation_id_rejected(self, engine):
        with pytest.raises(ValueError, match="validation_id is required"):
            engine.create(
                validation_findings=[_find("", "ERROR", False)]
            )

    def test_artifact_missing_path_rejected(self, engine):
        with pytest.raises(ValueError, match="artifact_path is required"):
            engine.create(
                validation_artifacts=[_art("v-1", "")]
            )


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


class TestDuplicateDetection:
    def test_duplicate_deduped_and_counted(self, engine):
        report = engine.create(
            validation_records=[
                _rec("a", "PYTEST", "PASSED", validator="devin"),
                _rec("a", "pytest", "passed", validator="devin"),
            ]
        )
        assert report["validation_count"] == 1
        assert report["duplicate_validation_count"] == 1

    def test_distinct_status_not_duplicate(self, engine):
        report = engine.create(
            validation_records=[
                _rec("a", "PYTEST", "PASSED"),
                _rec("a", "PYTEST", "FAILED"),
            ]
        )
        assert report["validation_count"] == 2
        assert report["duplicate_validation_count"] == 0

    def test_distinct_validator_not_duplicate(self, engine):
        report = engine.create(
            validation_records=[
                _rec("a", "PYTEST", "PASSED", validator="devin"),
                _rec("a", "PYTEST", "PASSED", validator="ci"),
            ]
        )
        assert report["validation_count"] == 2
        assert report["duplicate_validation_count"] == 0


# ---------------------------------------------------------------------------
# Finding / unresolved aggregation
# ---------------------------------------------------------------------------


class TestFindingAggregation:
    def test_finding_and_unresolved_counts(self, engine):
        report = engine.create(
            validation_records=[
                _rec("cap-1", "PYTEST", "FAILED", validation_id="v-1"),
            ],
            validation_findings=[
                _find("v-1", "ERROR", False),
                _find("v-1", "WARNING", True),
            ],
        )
        assert report["finding_count"] == 2
        assert report["unresolved_count"] == 1
        assert report["finding_severity_counts"] == {"ERROR": 1, "WARNING": 1}

    def test_per_capability_finding_counts(self, engine):
        report = engine.create(
            validation_records=[
                _rec("cap-1", "PYTEST", "FAILED", validation_id="v-1"),
                _rec("cap-2", "RUFF", "PASSED", validation_id="v-2"),
            ],
            validation_findings=[
                _find("v-1", "ERROR", False),
                _find("v-1", "INFO", True),
            ],
        )
        knowledge = {k["capability_id"]: k for k in report["knowledge"]}
        assert knowledge["cap-1"]["finding_count"] == 2
        assert knowledge["cap-1"]["unresolved_count"] == 1
        assert knowledge["cap-2"]["finding_count"] == 0
        assert knowledge["cap-2"]["unresolved_count"] == 0

    def test_per_capability_validation_type_counts(self, engine):
        report = engine.create(
            validation_records=[
                _rec("cap-1", "PYTEST", "PASSED"),
                _rec("cap-1", "RUFF", "PASSED"),
                _rec("cap-2", "CLI_TEST", "PASSED"),
            ]
        )
        knowledge = {k["capability_id"]: k for k in report["knowledge"]}
        assert knowledge["cap-1"]["validation_count"] == 2
        assert knowledge["cap-1"]["validation_type_counts"] == {
            "PYTEST": 1,
            "RUFF": 1,
        }

    def test_findings_sorted_deterministically(self, engine):
        report = engine.create(
            validation_records=[
                _rec("a", "PYTEST", "FAILED", validation_id="v-1"),
            ],
            validation_findings=[
                _find("v-1", "WARNING", False, finding_id="f-2"),
                _find("v-1", "CRITICAL", False, finding_id="f-1"),
                _find("v-1", "ERROR", False, finding_id="f-3"),
            ],
        )
        severities = [f["severity"] for f in report["findings"]]
        assert severities == ["CRITICAL", "ERROR", "WARNING"]


# ---------------------------------------------------------------------------
# Pass/fail
# ---------------------------------------------------------------------------


def _read_pass_fail(engine, report_id: str) -> dict:
    path = engine._report_dir / report_id / "pass_fail.json"
    return json.loads(path.read_text(encoding="utf-8"))


class TestPassFail:
    def test_pass_with_validations_no_unresolved(self, engine):
        report = engine.create(
            validation_records=[_rec("a", "PYTEST", "PASSED")]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is True
        assert pf["validation_count"] == 1
        assert pf["status"] == "passed"

    def test_empty_report_fails(self, engine):
        report = engine.create(validation_records=[])
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["validation_count"] == 0
        assert pf["status"] == "failed"

    def test_duplicate_fails(self, engine):
        report = engine.create(
            validation_records=[
                _rec("a", "PYTEST", "PASSED"),
                _rec("a", "PYTEST", "PASSED"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["duplicate_validation_count"] == 1

    def test_unresolved_finding_fails(self, engine):
        report = engine.create(
            validation_records=[
                _rec("a", "PYTEST", "FAILED", validation_id="v-1")
            ],
            validation_findings=[_find("v-1", "ERROR", False)],
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["unresolved_count"] == 1
        assert pf["status"] == "failed"

    def test_resolved_findings_pass(self, engine):
        report = engine.create(
            validation_records=[
                _rec("a", "PYTEST", "PASSED", validation_id="v-1")
            ],
            validation_findings=[_find("v-1", "INFO", True)],
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is True
        assert pf["unresolved_count"] == 0

    def test_evidence_bundle_files_written(self, engine):
        report = engine.create(
            validation_records=[_rec("a", "PYTEST", "PASSED")]
        )
        report_dir = engine._report_dir / report["report_id"]
        for name in (
            "capability_validation_request.json",
            "capability_validation_result.json",
            "capability_validation_summary.md",
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
            validation_records=[_rec("a", "PYTEST", "PASSED")]
        )
        report_id = created["report_id"]
        appended = engine.append(
            report_id,
            validation_records=[_rec("b", "RUFF", "PASSED")],
        )
        assert appended["report_id"] == report_id
        assert appended["validation_count"] == 2
        caps = {r["capability_id"] for r in appended["records"]}
        assert caps == {"a", "b"}

    def test_append_preserves_raw_payload(self, engine):
        created = engine.create(
            validation_records=[_rec("a", "PYTEST", "PASSED")],
            knowledge_payloads={"a": {"origin": "p0"}},
        )
        appended = engine.append(
            created["report_id"],
            validation_records=[_rec("a", "RUFF", "PASSED")],
        )
        knowledge = {k["capability_id"]: k for k in appended["knowledge"]}
        assert knowledge["a"]["raw_payload"] == {"origin": "p0"}

    def test_append_missing_report_raises(self, engine):
        with pytest.raises(ValueError, match="Report not found"):
            engine.append("does-not-exist", validation_records=[])


# ---------------------------------------------------------------------------
# Retrieval / exports
# ---------------------------------------------------------------------------


class TestRetrievalExport:
    def test_get_report_round_trip(self, engine):
        created = engine.create(
            validation_records=[_rec("a", "PYTEST", "PASSED")]
        )
        loaded = engine.get_report(created["report_id"])
        assert loaded["report_id"] == created["report_id"]
        assert loaded["validation_count"] == 1

    def test_get_missing_returns_none(self, engine):
        assert engine.get_report("missing-id") is None

    def test_list_reports_sorted(self, engine):
        engine.create(validation_records=[_rec("a", "PYTEST", "PASSED")])
        engine.create(validation_records=[_rec("b", "RUFF", "PASSED")])
        assert len(engine.list_reports()) == 2

    def test_export_json_valid(self, engine):
        created = engine.create(
            validation_records=[_rec("a", "PYTEST", "PASSED")]
        )
        parsed = json.loads(
            engine.export_report(created["report_id"], fmt="json")
        )
        assert parsed["report_id"] == created["report_id"]

    def test_export_markdown_headings(self, engine):
        created = engine.create(
            validation_records=[
                _rec("cap-122", "PYTEST", "PASSED", validation_id="v-1")
            ],
            validation_findings=[_find("v-1", "INFO", True)],
        )
        out = engine.export_report(created["report_id"], fmt="markdown")
        assert "# Capability Validation Knowledge Report" in out
        assert "## Validation Type Counts" in out
        assert "## Validation Status Counts" in out
        assert "## Finding Severity Counts" in out
        assert "## Validations" in out
        assert "## Findings" in out
        assert "[PYTEST]" in out
        assert "[cap-122]" in out

    def test_export_csv_rows(self, engine):
        created = engine.create(
            validation_records=[
                _rec("a", "PYTEST", "PASSED", validation_id="v-1"),
                _rec("a", "RUFF", "PASSED", validation_id="v-2"),
            ],
            validation_findings=[_find("v-1", "INFO", True)],
            validation_artifacts=[_art("v-1", "artifacts/x/pf.json")],
        )
        out = engine.export_report(created["report_id"], fmt="csv")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        assert lines[0].startswith("record_kind,")
        # header + 2 validations + 1 finding + 1 artifact
        assert len(lines) == 5

    def test_export_invalid_format_raises(self, engine):
        created = engine.create(
            validation_records=[_rec("a", "PYTEST", "PASSED")]
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
