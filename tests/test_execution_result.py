"""Tests for the Execution Result Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.execution_result import (
    ExecutionResult,
    ExecutionResultEngine,
    ExecutionResultEvidence,
    ExecutionResultReference,
    ExecutionResultReferenceType,
    ExecutionResultReport,
    ExecutionResultStatus,
    ExecutionResultType,
)


def _result(
    attempt_id: str,
    step_id: str,
    capability_id: str,
    result_type: str,
    status: str,
    **kw,
) -> dict:
    data = {
        "attempt_id": attempt_id,
        "step_id": step_id,
        "capability_id": capability_id,
        "result_type": result_type,
        "status": status,
        "summary": kw.get("summary", ""),
    }
    for k in (
        "result_id",
        "references",
        "raw_payload",
    ):
        if k in kw:
            data[k] = kw[k]
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
    return ExecutionResultEngine(artifacts_root=str(tmp_path / "artifacts"))


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_reference_round_trip(self):
        r = ExecutionResultReference(
            reference_id="r-1",
            reference_type="ATTEMPT",
            reference_value="att-9",
            summary="attempt ref",
        )
        assert ExecutionResultReference.from_dict(r.to_dict()) == r

    def test_result_round_trip(self):
        r = ExecutionResult(
            result_id="res-1",
            attempt_id="att-1",
            step_id="stp-1",
            capability_id="cap-1",
            result_type="OUTPUT",
            status="PRODUCED",
            references=[
                ExecutionResultReference(
                    reference_id="r-1",
                    reference_type="ATTEMPT",
                    reference_value="att-9",
                )
            ],
            summary="produced",
            created_at="2026-01-01T00:00:00+00:00",
            raw_payload={"k": "v"},
        )
        assert ExecutionResult.from_dict(r.to_dict()) == r

    def test_result_gets_id_and_timestamp(self):
        r = ExecutionResult(
            attempt_id="att-1",
            step_id="stp-1",
            capability_id="cap-1",
            result_type="OUTPUT",
            status="PRODUCED",
        )
        assert r.result_id
        assert r.created_at

    def test_report_defaults(self):
        report = ExecutionResultReport()
        assert report.report_id
        assert report.created_at
        assert report.result_count == 0
        assert report.failed_count == 0
        assert report.empty_count == 0
        assert report.produced_count == 0
        assert report.schema_version == "1.0"

    def test_evidence_defaults(self):
        ev = ExecutionResultEvidence(report_id="rep-1")
        assert ev.evidence_id
        assert ev.created_at
        assert ev.report_id == "rep-1"

    def test_all_result_types_present(self):
        assert {t.value for t in ExecutionResultType} == {
            "OUTPUT",
            "VALIDATION",
            "ERROR",
            "ARTIFACT",
            "REPORT",
            "NO_ACTION",
            "OTHER",
        }

    def test_all_statuses_present(self):
        assert {t.value for t in ExecutionResultStatus} == {
            "PRODUCED",
            "FAILED",
            "PARTIAL",
            "EMPTY",
            "UNKNOWN",
        }

    def test_all_reference_types_present(self):
        assert {t.value for t in ExecutionResultReferenceType} == {
            "ATTEMPT",
            "STEP",
            "CAPABILITY",
            "FILE",
            "ARTIFACT",
            "VALIDATION",
            "KNOWLEDGE_NODE",
            "OTHER",
        }


# ---------------------------------------------------------------------------
# Create / determinism
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_counts(self, engine):
        report = engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "OUTPUT", "PRODUCED"),
                _result("att-2", "stp-2", "cap-2", "REPORT", "PRODUCED"),
                _result("att-3", "stp-3", "cap-3", "VALIDATION", "UNKNOWN"),
            ]
        )
        assert report["result_count"] == 3
        assert report["status_counts"] == {
            "PRODUCED": 2,
            "UNKNOWN": 1,
        }
        assert report["result_type_counts"] == {
            "OUTPUT": 1,
            "REPORT": 1,
            "VALIDATION": 1,
        }
        assert report["failed_count"] == 0
        assert report["empty_count"] == 0
        assert report["produced_count"] == 2

    def test_deterministic_ordering(self, engine):
        report = engine.create(
            results=[
                _result("att-2", "stp-1", "cap-1", "OUTPUT", "PRODUCED"),
                _result("att-1", "stp-2", "cap-2", "OUTPUT", "PRODUCED"),
                _result("att-1", "stp-1", "cap-1", "OUTPUT", "PRODUCED"),
            ]
        )
        order = [
            (r["attempt_id"], r["step_id"], r["capability_id"])
            for r in report["results"]
        ]
        assert order == [
            ("att-1", "stp-1", "cap-1"),
            ("att-1", "stp-2", "cap-2"),
            ("att-2", "stp-1", "cap-1"),
        ]

    def test_ordering_is_input_independent(self, engine):
        results = [
            _result("att-1", "stp-1", "cap-1", "OUTPUT", "PRODUCED"),
            _result("att-2", "stp-2", "cap-2", "OUTPUT", "PRODUCED"),
            _result("att-3", "stp-3", "cap-3", "OUTPUT", "PRODUCED"),
        ]
        r1 = engine.create(results=list(results))
        r2 = engine.create(results=list(reversed(results)))
        key = lambda rep: [  # noqa: E731
            (r["attempt_id"], r["step_id"]) for r in rep["results"]
        ]
        assert key(r1) == key(r2)

    def test_references_ordered_deterministically(self, engine):
        report = engine.create(
            results=[
                _result(
                    "att-1",
                    "stp-1",
                    "cap-1",
                    "OUTPUT",
                    "PRODUCED",
                    references=[
                        _ref("STEP", "stp-9"),
                        _ref("ATTEMPT", "att-9"),
                        _ref("ARTIFACT", "art-9"),
                    ],
                )
            ]
        )
        order = [
            (r["reference_type"], r["reference_value"])
            for r in report["results"][0]["references"]
        ]
        assert order == [
            ("ARTIFACT", "art-9"),
            ("ATTEMPT", "att-9"),
            ("STEP", "stp-9"),
        ]

    def test_schema_version_preserved(self, engine):
        report = engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "OUTPUT", "PRODUCED")
            ]
        )
        assert report["schema_version"] == "1.0"

    def test_raw_metadata_preserved(self, engine):
        report = engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "OUTPUT", "PRODUCED")
            ],
            raw_metadata={"source": "program-0"},
        )
        assert report["raw_metadata"] == {"source": "program-0"}

    def test_result_raw_payload_preserved(self, engine):
        report = engine.create(
            results=[
                _result(
                    "att-1",
                    "stp-1",
                    "cap-1",
                    "OUTPUT",
                    "PRODUCED",
                    raw_payload={"nested": {"deep": [1, 2]}},
                )
            ]
        )
        assert report["results"][0]["raw_payload"] == {
            "nested": {"deep": [1, 2]}
        }


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_status_normalized(self, engine):
        report = engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "OUTPUT", "produced")
            ]
        )
        assert report["results"][0]["status"] == "PRODUCED"

    def test_result_type_normalized(self, engine):
        report = engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "output", "PRODUCED")
            ]
        )
        assert report["results"][0]["result_type"] == "OUTPUT"

    def test_reference_type_normalized(self, engine):
        report = engine.create(
            results=[
                _result(
                    "att-1",
                    "stp-1",
                    "cap-1",
                    "OUTPUT",
                    "PRODUCED",
                    references=[_ref("attempt", "att-9")],
                )
            ]
        )
        assert (
            report["results"][0]["references"][0]["reference_type"]
            == "ATTEMPT"
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_status_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid status"):
            engine.create(
                results=[
                    _result("att-1", "stp-1", "cap-1", "OUTPUT", "NONSENSE")
                ]
            )

    def test_invalid_result_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid result_type"):
            engine.create(
                results=[
                    _result("att-1", "stp-1", "cap-1", "NOPE", "PRODUCED")
                ]
            )

    def test_missing_attempt_id_rejected(self, engine):
        with pytest.raises(ValueError, match="attempt_id is required"):
            engine.create(
                results=[
                    _result("", "stp-1", "cap-1", "OUTPUT", "PRODUCED")
                ]
            )

    def test_missing_step_id_rejected(self, engine):
        with pytest.raises(ValueError, match="step_id is required"):
            engine.create(
                results=[
                    _result("att-1", "", "cap-1", "OUTPUT", "PRODUCED")
                ]
            )

    def test_missing_capability_id_rejected(self, engine):
        with pytest.raises(ValueError, match="capability_id is required"):
            engine.create(
                results=[
                    _result("att-1", "stp-1", "", "OUTPUT", "PRODUCED")
                ]
            )

    def test_missing_result_type_rejected(self, engine):
        with pytest.raises(ValueError, match="result_type is required"):
            engine.create(
                results=[
                    _result("att-1", "stp-1", "cap-1", "", "PRODUCED")
                ]
            )

    def test_missing_status_rejected(self, engine):
        with pytest.raises(ValueError, match="status is required"):
            engine.create(
                results=[
                    _result("att-1", "stp-1", "cap-1", "OUTPUT", "")
                ]
            )

    def test_invalid_reference_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid reference_type"):
            engine.create(
                results=[
                    _result(
                        "att-1",
                        "stp-1",
                        "cap-1",
                        "OUTPUT",
                        "PRODUCED",
                        references=[_ref("NONSENSE", "x")],
                    )
                ]
            )

    def test_missing_reference_value_rejected(self, engine):
        with pytest.raises(ValueError, match="reference_value is required"):
            engine.create(
                results=[
                    _result(
                        "att-1",
                        "stp-1",
                        "cap-1",
                        "OUTPUT",
                        "PRODUCED",
                        references=[_ref("ATTEMPT", "")],
                    )
                ]
            )


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


class TestDuplicateDetection:
    def test_duplicate_result_deduped_and_counted(self, engine):
        report = engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "OUTPUT", "PRODUCED"),
                _result("att-1", "stp-1", "cap-1", "OUTPUT", "FAILED"),
            ]
        )
        assert report["result_count"] == 1
        assert report["duplicate_result_count"] == 1

    def test_distinct_result_type_not_duplicate(self, engine):
        report = engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "OUTPUT", "PRODUCED"),
                _result("att-1", "stp-1", "cap-1", "REPORT", "PRODUCED"),
            ]
        )
        assert report["result_count"] == 2
        assert report["duplicate_result_count"] == 0

    def test_distinct_attempt_not_duplicate(self, engine):
        report = engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "OUTPUT", "PRODUCED"),
                _result("att-2", "stp-1", "cap-1", "OUTPUT", "PRODUCED"),
            ]
        )
        assert report["result_count"] == 2
        assert report["duplicate_result_count"] == 0


# ---------------------------------------------------------------------------
# Failed / empty / produced detection
# ---------------------------------------------------------------------------


class TestFailedEmptyDetection:
    def test_failed_detected(self, engine):
        report = engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "ERROR", "FAILED"),
                _result("att-2", "stp-2", "cap-2", "OUTPUT", "PRODUCED"),
            ]
        )
        assert report["failed_count"] == 1
        assert report["empty_count"] == 0

    def test_empty_detected(self, engine):
        report = engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "NO_ACTION", "EMPTY"),
                _result("att-2", "stp-2", "cap-2", "OUTPUT", "PRODUCED"),
            ]
        )
        assert report["empty_count"] == 1
        assert report["failed_count"] == 0

    def test_produced_counted(self, engine):
        report = engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "OUTPUT", "PRODUCED"),
                _result("att-2", "stp-2", "cap-2", "OUTPUT", "PARTIAL"),
            ]
        )
        assert report["produced_count"] == 1


# ---------------------------------------------------------------------------
# Pass/fail
# ---------------------------------------------------------------------------


def _read_pass_fail(engine, report_id: str) -> dict:
    path = engine._report_dir / report_id / "pass_fail.json"
    return json.loads(path.read_text(encoding="utf-8"))


class TestPassFail:
    def test_pass_with_clean_results(self, engine):
        report = engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "OUTPUT", "PRODUCED"),
                _result("att-2", "stp-2", "cap-2", "OUTPUT", "PRODUCED"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is True
        assert pf["result_count"] == 2
        assert pf["status"] == "passed"

    def test_empty_report_fails(self, engine):
        report = engine.create(results=[])
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["result_count"] == 0
        assert pf["status"] == "failed"

    def test_failed_fails(self, engine):
        report = engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "ERROR", "FAILED")
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["failed_count"] == 1

    def test_empty_status_fails(self, engine):
        report = engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "NO_ACTION", "EMPTY")
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["empty_count"] == 1

    def test_partial_does_not_fail(self, engine):
        report = engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "OUTPUT", "PARTIAL"),
                _result("att-2", "stp-2", "cap-2", "OUTPUT", "PRODUCED"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is True

    def test_unknown_does_not_fail(self, engine):
        report = engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "OUTPUT", "UNKNOWN"),
                _result("att-2", "stp-2", "cap-2", "OUTPUT", "PRODUCED"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is True

    def test_duplicate_does_not_fail_when_clean(self, engine):
        report = engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "OUTPUT", "PRODUCED"),
                _result("att-1", "stp-1", "cap-1", "OUTPUT", "PRODUCED"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["duplicate_result_count"] == 1
        assert pf["passed"] is True

    def test_evidence_bundle_files_written(self, engine):
        report = engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "OUTPUT", "PRODUCED")
            ]
        )
        report_dir = engine._report_dir / report["report_id"]
        for name in (
            "execution_result_request.json",
            "execution_result_result.json",
            "execution_result_summary.md",
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
            results=[
                _result("att-1", "stp-1", "cap-1", "OUTPUT", "PRODUCED")
            ]
        )
        report_id = created["report_id"]
        appended = engine.append(
            report_id,
            results=[
                _result("att-2", "stp-2", "cap-2", "OUTPUT", "PRODUCED")
            ],
        )
        assert appended["report_id"] == report_id
        assert appended["result_count"] == 2
        attempts = {r["attempt_id"] for r in appended["results"]}
        assert attempts == {"att-1", "att-2"}

    def test_append_preserves_raw_metadata(self, engine):
        created = engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "OUTPUT", "PRODUCED")
            ],
            raw_metadata={"origin": "p0"},
        )
        appended = engine.append(
            created["report_id"],
            results=[
                _result("att-2", "stp-2", "cap-2", "OUTPUT", "PRODUCED")
            ],
        )
        assert appended["raw_metadata"] == {"origin": "p0"}

    def test_append_missing_report_raises(self, engine):
        with pytest.raises(ValueError, match="Report not found"):
            engine.append("does-not-exist", results=[])


# ---------------------------------------------------------------------------
# Retrieval / exports
# ---------------------------------------------------------------------------


class TestRetrievalExport:
    def test_get_report_round_trip(self, engine):
        created = engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "OUTPUT", "PRODUCED")
            ]
        )
        loaded = engine.get_report(created["report_id"])
        assert loaded["report_id"] == created["report_id"]
        assert loaded["result_count"] == 1

    def test_get_missing_returns_none(self, engine):
        assert engine.get_report("missing-id") is None

    def test_list_reports_sorted(self, engine):
        engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "OUTPUT", "PRODUCED")
            ]
        )
        engine.create(
            results=[
                _result("att-2", "stp-2", "cap-2", "OUTPUT", "PRODUCED")
            ]
        )
        assert len(engine.list_reports()) == 2

    def test_export_json_valid(self, engine):
        created = engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "OUTPUT", "PRODUCED")
            ]
        )
        parsed = json.loads(
            engine.export_report(created["report_id"], fmt="json")
        )
        assert parsed["report_id"] == created["report_id"]

    def test_export_markdown_headings(self, engine):
        created = engine.create(
            results=[
                _result(
                    "att-1",
                    "stp-1",
                    "cap-122",
                    "ERROR",
                    "FAILED",
                    references=[_ref("ATTEMPT", "att-9")],
                )
            ]
        )
        out = engine.export_report(created["report_id"], fmt="markdown")
        assert "# Execution Result Report" in out
        assert "## Status Counts" in out
        assert "## Result Type Counts" in out
        assert "## Results" in out
        assert "[FAILED]" in out
        assert "[ERROR]" in out
        assert "capability=cap-122" in out
        assert "[ATTEMPT] att-9" in out

    def test_export_csv_rows(self, engine):
        created = engine.create(
            results=[
                _result(
                    "att-1",
                    "stp-1",
                    "cap-1",
                    "OUTPUT",
                    "PRODUCED",
                    references=[_ref("ATTEMPT", "att-9")],
                ),
                _result("att-2", "stp-2", "cap-2", "OUTPUT", "PRODUCED"),
            ]
        )
        out = engine.export_report(created["report_id"], fmt="csv")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        assert lines[0].startswith("record_kind,")
        # header + 2 results + 1 reference
        assert len(lines) == 4
        result_rows = [ln for ln in lines[1:] if ln.startswith("result,")]
        reference_rows = [
            ln for ln in lines[1:] if ln.startswith("reference,")
        ]
        assert len(result_rows) == 2
        assert len(reference_rows) == 1

    def test_export_invalid_format_raises(self, engine):
        created = engine.create(
            results=[
                _result("att-1", "stp-1", "cap-1", "OUTPUT", "PRODUCED")
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
