"""Tests for the Execution Attempt Framework v2."""

from __future__ import annotations

import json

import pytest
from axiom_core.execution_attempt_v2 import (
    ExecutionAttempt,
    ExecutionAttemptEngine,
    ExecutionAttemptEvidence,
    ExecutionAttemptReference,
    ExecutionAttemptReferenceType,
    ExecutionAttemptReport,
    ExecutionAttemptResult,
    ExecutionAttemptStatus,
)


def _attempt(
    step_id: str,
    plan_id: str,
    capability_id: str,
    status: str,
    result: str,
    **kw,
) -> dict:
    data = {
        "step_id": step_id,
        "plan_id": plan_id,
        "capability_id": capability_id,
        "status": status,
        "result": result,
        "summary": kw.get("summary", ""),
    }
    for k in (
        "attempt_id",
        "started_at",
        "completed_at",
        "duration_seconds",
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
    return ExecutionAttemptEngine(artifacts_root=str(tmp_path / "artifacts"))


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_reference_round_trip(self):
        r = ExecutionAttemptReference(
            reference_id="r-1",
            reference_type="STEP",
            reference_value="stp-9",
            summary="step ref",
        )
        assert ExecutionAttemptReference.from_dict(r.to_dict()) == r

    def test_attempt_round_trip(self):
        a = ExecutionAttempt(
            attempt_id="att-1",
            step_id="stp-1",
            plan_id="pln-1",
            capability_id="cap-1",
            status="COMPLETED",
            result="SUCCESS",
            started_at="2026-01-01T00:00:00+00:00",
            completed_at="2026-01-01T00:00:05+00:00",
            duration_seconds=5.0,
            references=[
                ExecutionAttemptReference(
                    reference_id="r-1",
                    reference_type="STEP",
                    reference_value="stp-9",
                )
            ],
            summary="ran",
            created_at="2026-01-01T00:00:00+00:00",
            raw_payload={"k": "v"},
        )
        assert ExecutionAttempt.from_dict(a.to_dict()) == a

    def test_attempt_gets_id_and_timestamp(self):
        a = ExecutionAttempt(
            step_id="stp-1",
            plan_id="pln-1",
            capability_id="cap-1",
            status="CREATED",
            result="UNKNOWN",
        )
        assert a.attempt_id
        assert a.created_at

    def test_report_defaults(self):
        report = ExecutionAttemptReport()
        assert report.report_id
        assert report.created_at
        assert report.attempt_count == 0
        assert report.failed_count == 0
        assert report.timeout_count == 0
        assert report.success_count == 0
        assert report.total_duration_seconds == 0.0
        assert report.schema_version == "1.0"

    def test_evidence_defaults(self):
        ev = ExecutionAttemptEvidence(report_id="rep-1")
        assert ev.evidence_id
        assert ev.created_at
        assert ev.report_id == "rep-1"

    def test_all_statuses_present(self):
        assert {t.value for t in ExecutionAttemptStatus} == {
            "CREATED",
            "STARTED",
            "COMPLETED",
            "FAILED",
            "CANCELLED",
            "TIMED_OUT",
        }

    def test_all_results_present(self):
        assert {t.value for t in ExecutionAttemptResult} == {
            "SUCCESS",
            "FAILURE",
            "PARTIAL_SUCCESS",
            "NO_ACTION",
            "UNKNOWN",
        }

    def test_all_reference_types_present(self):
        assert {t.value for t in ExecutionAttemptReferenceType} == {
            "STEP",
            "PLAN",
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
            attempts=[
                _attempt("stp-1", "pln-1", "cap-1", "COMPLETED", "SUCCESS"),
                _attempt("stp-2", "pln-1", "cap-2", "COMPLETED", "SUCCESS"),
                _attempt("stp-3", "pln-1", "cap-3", "STARTED", "UNKNOWN"),
            ]
        )
        assert report["attempt_count"] == 3
        assert report["status_counts"] == {
            "COMPLETED": 2,
            "STARTED": 1,
        }
        assert report["result_counts"] == {
            "SUCCESS": 2,
            "UNKNOWN": 1,
        }
        assert report["failed_count"] == 0
        assert report["timeout_count"] == 0
        assert report["success_count"] == 2

    def test_deterministic_ordering(self, engine):
        report = engine.create(
            attempts=[
                _attempt("stp-1", "pln-2", "cap-1", "COMPLETED", "SUCCESS"),
                _attempt("stp-2", "pln-1", "cap-2", "COMPLETED", "SUCCESS"),
                _attempt("stp-1", "pln-1", "cap-1", "COMPLETED", "SUCCESS"),
            ]
        )
        order = [
            (a["plan_id"], a["step_id"], a["capability_id"])
            for a in report["attempts"]
        ]
        assert order == [
            ("pln-1", "stp-1", "cap-1"),
            ("pln-1", "stp-2", "cap-2"),
            ("pln-2", "stp-1", "cap-1"),
        ]

    def test_ordering_is_input_independent(self, engine):
        attempts = [
            _attempt("stp-1", "pln-1", "cap-1", "COMPLETED", "SUCCESS"),
            _attempt("stp-2", "pln-1", "cap-2", "COMPLETED", "SUCCESS"),
            _attempt("stp-3", "pln-1", "cap-3", "COMPLETED", "SUCCESS"),
        ]
        r1 = engine.create(attempts=list(attempts))
        r2 = engine.create(attempts=list(reversed(attempts)))
        key = lambda rep: [  # noqa: E731
            (a["step_id"], a["capability_id"]) for a in rep["attempts"]
        ]
        assert key(r1) == key(r2)

    def test_references_ordered_deterministically(self, engine):
        report = engine.create(
            attempts=[
                _attempt(
                    "stp-1",
                    "pln-1",
                    "cap-1",
                    "COMPLETED",
                    "SUCCESS",
                    references=[
                        _ref("STEP", "stp-9"),
                        _ref("CAPABILITY", "cap-9"),
                        _ref("ARTIFACT", "art-9"),
                    ],
                )
            ]
        )
        order = [
            (r["reference_type"], r["reference_value"])
            for r in report["attempts"][0]["references"]
        ]
        assert order == [
            ("ARTIFACT", "art-9"),
            ("CAPABILITY", "cap-9"),
            ("STEP", "stp-9"),
        ]

    def test_schema_version_preserved(self, engine):
        report = engine.create(
            attempts=[
                _attempt("stp-1", "pln-1", "cap-1", "COMPLETED", "SUCCESS")
            ]
        )
        assert report["schema_version"] == "1.0"

    def test_raw_metadata_preserved(self, engine):
        report = engine.create(
            attempts=[
                _attempt("stp-1", "pln-1", "cap-1", "COMPLETED", "SUCCESS")
            ],
            raw_metadata={"source": "program-0"},
        )
        assert report["raw_metadata"] == {"source": "program-0"}

    def test_attempt_raw_payload_preserved(self, engine):
        report = engine.create(
            attempts=[
                _attempt(
                    "stp-1",
                    "pln-1",
                    "cap-1",
                    "COMPLETED",
                    "SUCCESS",
                    raw_payload={"nested": {"deep": [1, 2]}},
                )
            ]
        )
        assert report["attempts"][0]["raw_payload"] == {
            "nested": {"deep": [1, 2]}
        }


# ---------------------------------------------------------------------------
# Duration calculation
# ---------------------------------------------------------------------------


class TestDuration:
    def test_duration_from_timestamps(self, engine):
        report = engine.create(
            attempts=[
                _attempt(
                    "stp-1",
                    "pln-1",
                    "cap-1",
                    "COMPLETED",
                    "SUCCESS",
                    started_at="2026-01-01T00:00:00+00:00",
                    completed_at="2026-01-01T00:00:30+00:00",
                )
            ]
        )
        assert report["attempts"][0]["duration_seconds"] == 30.0

    def test_explicit_duration_overrides_timestamps(self, engine):
        report = engine.create(
            attempts=[
                _attempt(
                    "stp-1",
                    "pln-1",
                    "cap-1",
                    "COMPLETED",
                    "SUCCESS",
                    started_at="2026-01-01T00:00:00+00:00",
                    completed_at="2026-01-01T00:00:30+00:00",
                    duration_seconds=12.5,
                )
            ]
        )
        assert report["attempts"][0]["duration_seconds"] == 12.5

    def test_duration_defaults_to_zero(self, engine):
        report = engine.create(
            attempts=[
                _attempt("stp-1", "pln-1", "cap-1", "STARTED", "UNKNOWN")
            ]
        )
        assert report["attempts"][0]["duration_seconds"] == 0.0

    def test_total_duration_aggregated(self, engine):
        report = engine.create(
            attempts=[
                _attempt(
                    "stp-1",
                    "pln-1",
                    "cap-1",
                    "COMPLETED",
                    "SUCCESS",
                    duration_seconds=10.0,
                ),
                _attempt(
                    "stp-2",
                    "pln-1",
                    "cap-2",
                    "COMPLETED",
                    "SUCCESS",
                    duration_seconds=5.5,
                ),
            ]
        )
        assert report["total_duration_seconds"] == 15.5

    def test_negative_duration_rejected(self, engine):
        with pytest.raises(ValueError, match="must not be negative"):
            engine.create(
                attempts=[
                    _attempt(
                        "stp-1",
                        "pln-1",
                        "cap-1",
                        "COMPLETED",
                        "SUCCESS",
                        duration_seconds=-1.0,
                    )
                ]
            )

    def test_non_numeric_duration_rejected(self, engine):
        with pytest.raises(ValueError, match="must be a number"):
            engine.create(
                attempts=[
                    _attempt(
                        "stp-1",
                        "pln-1",
                        "cap-1",
                        "COMPLETED",
                        "SUCCESS",
                        duration_seconds="x",
                    )
                ]
            )

    def test_bool_duration_rejected(self, engine):
        with pytest.raises(ValueError, match="must be a number"):
            engine.create(
                attempts=[
                    _attempt(
                        "stp-1",
                        "pln-1",
                        "cap-1",
                        "COMPLETED",
                        "SUCCESS",
                        duration_seconds=True,
                    )
                ]
            )

    def test_completed_before_started_rejected(self, engine):
        with pytest.raises(ValueError, match="must not precede"):
            engine.create(
                attempts=[
                    _attempt(
                        "stp-1",
                        "pln-1",
                        "cap-1",
                        "COMPLETED",
                        "SUCCESS",
                        started_at="2026-01-01T00:00:30+00:00",
                        completed_at="2026-01-01T00:00:00+00:00",
                    )
                ]
            )


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_status_normalized(self, engine):
        report = engine.create(
            attempts=[
                _attempt("stp-1", "pln-1", "cap-1", "completed", "SUCCESS")
            ]
        )
        assert report["attempts"][0]["status"] == "COMPLETED"

    def test_result_normalized(self, engine):
        report = engine.create(
            attempts=[
                _attempt("stp-1", "pln-1", "cap-1", "COMPLETED", "success")
            ]
        )
        assert report["attempts"][0]["result"] == "SUCCESS"

    def test_reference_type_normalized(self, engine):
        report = engine.create(
            attempts=[
                _attempt(
                    "stp-1",
                    "pln-1",
                    "cap-1",
                    "COMPLETED",
                    "SUCCESS",
                    references=[_ref("step", "stp-9")],
                )
            ]
        )
        assert (
            report["attempts"][0]["references"][0]["reference_type"]
            == "STEP"
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_status_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid status"):
            engine.create(
                attempts=[
                    _attempt("stp-1", "pln-1", "cap-1", "NONSENSE", "SUCCESS")
                ]
            )

    def test_invalid_result_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid result"):
            engine.create(
                attempts=[
                    _attempt("stp-1", "pln-1", "cap-1", "COMPLETED", "NOPE")
                ]
            )

    def test_missing_step_id_rejected(self, engine):
        with pytest.raises(ValueError, match="step_id is required"):
            engine.create(
                attempts=[
                    _attempt("", "pln-1", "cap-1", "COMPLETED", "SUCCESS")
                ]
            )

    def test_missing_plan_id_rejected(self, engine):
        with pytest.raises(ValueError, match="plan_id is required"):
            engine.create(
                attempts=[
                    _attempt("stp-1", "", "cap-1", "COMPLETED", "SUCCESS")
                ]
            )

    def test_missing_capability_id_rejected(self, engine):
        with pytest.raises(ValueError, match="capability_id is required"):
            engine.create(
                attempts=[
                    _attempt("stp-1", "pln-1", "", "COMPLETED", "SUCCESS")
                ]
            )

    def test_missing_status_rejected(self, engine):
        with pytest.raises(ValueError, match="status is required"):
            engine.create(
                attempts=[
                    _attempt("stp-1", "pln-1", "cap-1", "", "SUCCESS")
                ]
            )

    def test_missing_result_rejected(self, engine):
        with pytest.raises(ValueError, match="result is required"):
            engine.create(
                attempts=[
                    _attempt("stp-1", "pln-1", "cap-1", "COMPLETED", "")
                ]
            )

    def test_invalid_reference_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid reference_type"):
            engine.create(
                attempts=[
                    _attempt(
                        "stp-1",
                        "pln-1",
                        "cap-1",
                        "COMPLETED",
                        "SUCCESS",
                        references=[_ref("NONSENSE", "x")],
                    )
                ]
            )

    def test_missing_reference_value_rejected(self, engine):
        with pytest.raises(ValueError, match="reference_value is required"):
            engine.create(
                attempts=[
                    _attempt(
                        "stp-1",
                        "pln-1",
                        "cap-1",
                        "COMPLETED",
                        "SUCCESS",
                        references=[_ref("STEP", "")],
                    )
                ]
            )


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


class TestDuplicateDetection:
    def test_duplicate_attempt_deduped_and_counted(self, engine):
        report = engine.create(
            attempts=[
                _attempt(
                    "stp-1",
                    "pln-1",
                    "cap-1",
                    "COMPLETED",
                    "SUCCESS",
                    started_at="2026-01-01T00:00:00+00:00",
                ),
                _attempt(
                    "stp-1",
                    "pln-1",
                    "cap-1",
                    "FAILED",
                    "FAILURE",
                    started_at="2026-01-01T00:00:00+00:00",
                ),
            ]
        )
        assert report["attempt_count"] == 1
        assert report["duplicate_attempt_count"] == 1

    def test_distinct_started_at_not_duplicate(self, engine):
        report = engine.create(
            attempts=[
                _attempt(
                    "stp-1",
                    "pln-1",
                    "cap-1",
                    "FAILED",
                    "FAILURE",
                    started_at="2026-01-01T00:00:00+00:00",
                ),
                _attempt(
                    "stp-1",
                    "pln-1",
                    "cap-1",
                    "COMPLETED",
                    "SUCCESS",
                    started_at="2026-01-01T00:01:00+00:00",
                ),
            ]
        )
        assert report["attempt_count"] == 2
        assert report["duplicate_attempt_count"] == 0

    def test_distinct_step_not_duplicate(self, engine):
        report = engine.create(
            attempts=[
                _attempt("stp-1", "pln-1", "cap-1", "COMPLETED", "SUCCESS"),
                _attempt("stp-2", "pln-1", "cap-1", "COMPLETED", "SUCCESS"),
            ]
        )
        assert report["attempt_count"] == 2
        assert report["duplicate_attempt_count"] == 0


# ---------------------------------------------------------------------------
# Failed / timeout / success detection
# ---------------------------------------------------------------------------


class TestFailedTimeoutDetection:
    def test_failed_detected(self, engine):
        report = engine.create(
            attempts=[
                _attempt("stp-1", "pln-1", "cap-1", "FAILED", "FAILURE"),
                _attempt("stp-2", "pln-1", "cap-2", "COMPLETED", "SUCCESS"),
            ]
        )
        assert report["failed_count"] == 1
        assert report["timeout_count"] == 0

    def test_timeout_detected(self, engine):
        report = engine.create(
            attempts=[
                _attempt("stp-1", "pln-1", "cap-1", "TIMED_OUT", "FAILURE"),
                _attempt("stp-2", "pln-1", "cap-2", "COMPLETED", "SUCCESS"),
            ]
        )
        assert report["timeout_count"] == 1
        assert report["failed_count"] == 0

    def test_success_counted(self, engine):
        report = engine.create(
            attempts=[
                _attempt("stp-1", "pln-1", "cap-1", "COMPLETED", "SUCCESS"),
                _attempt(
                    "stp-2", "pln-1", "cap-2", "COMPLETED", "PARTIAL_SUCCESS"
                ),
            ]
        )
        assert report["success_count"] == 1


# ---------------------------------------------------------------------------
# Pass/fail
# ---------------------------------------------------------------------------


def _read_pass_fail(engine, report_id: str) -> dict:
    path = engine._report_dir / report_id / "pass_fail.json"
    return json.loads(path.read_text(encoding="utf-8"))


class TestPassFail:
    def test_pass_with_clean_attempts(self, engine):
        report = engine.create(
            attempts=[
                _attempt("stp-1", "pln-1", "cap-1", "COMPLETED", "SUCCESS"),
                _attempt("stp-2", "pln-1", "cap-2", "COMPLETED", "SUCCESS"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is True
        assert pf["attempt_count"] == 2
        assert pf["status"] == "passed"

    def test_empty_report_fails(self, engine):
        report = engine.create(attempts=[])
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["attempt_count"] == 0
        assert pf["status"] == "failed"

    def test_failed_fails(self, engine):
        report = engine.create(
            attempts=[
                _attempt("stp-1", "pln-1", "cap-1", "FAILED", "FAILURE")
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["failed_count"] == 1

    def test_timeout_fails(self, engine):
        report = engine.create(
            attempts=[
                _attempt("stp-1", "pln-1", "cap-1", "TIMED_OUT", "FAILURE")
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["timeout_count"] == 1

    def test_cancelled_does_not_fail(self, engine):
        report = engine.create(
            attempts=[
                _attempt("stp-1", "pln-1", "cap-1", "CANCELLED", "NO_ACTION"),
                _attempt("stp-2", "pln-1", "cap-2", "COMPLETED", "SUCCESS"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is True

    def test_duplicate_does_not_fail_when_clean(self, engine):
        report = engine.create(
            attempts=[
                _attempt(
                    "stp-1",
                    "pln-1",
                    "cap-1",
                    "COMPLETED",
                    "SUCCESS",
                    started_at="2026-01-01T00:00:00+00:00",
                ),
                _attempt(
                    "stp-1",
                    "pln-1",
                    "cap-1",
                    "COMPLETED",
                    "SUCCESS",
                    started_at="2026-01-01T00:00:00+00:00",
                ),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["duplicate_attempt_count"] == 1
        assert pf["passed"] is True

    def test_total_duration_in_pass_fail(self, engine):
        report = engine.create(
            attempts=[
                _attempt(
                    "stp-1",
                    "pln-1",
                    "cap-1",
                    "COMPLETED",
                    "SUCCESS",
                    duration_seconds=7.0,
                )
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["total_duration_seconds"] == 7.0

    def test_evidence_bundle_files_written(self, engine):
        report = engine.create(
            attempts=[
                _attempt("stp-1", "pln-1", "cap-1", "COMPLETED", "SUCCESS")
            ]
        )
        report_dir = engine._report_dir / report["report_id"]
        for name in (
            "execution_attempt_request.json",
            "execution_attempt_result.json",
            "execution_attempt_summary.md",
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
            attempts=[
                _attempt("stp-1", "pln-1", "cap-1", "COMPLETED", "SUCCESS")
            ]
        )
        report_id = created["report_id"]
        appended = engine.append(
            report_id,
            attempts=[
                _attempt("stp-2", "pln-1", "cap-2", "COMPLETED", "SUCCESS")
            ],
        )
        assert appended["report_id"] == report_id
        assert appended["attempt_count"] == 2
        steps = {a["step_id"] for a in appended["attempts"]}
        assert steps == {"stp-1", "stp-2"}

    def test_append_preserves_raw_metadata(self, engine):
        created = engine.create(
            attempts=[
                _attempt("stp-1", "pln-1", "cap-1", "COMPLETED", "SUCCESS")
            ],
            raw_metadata={"origin": "p0"},
        )
        appended = engine.append(
            created["report_id"],
            attempts=[
                _attempt("stp-2", "pln-1", "cap-2", "COMPLETED", "SUCCESS")
            ],
        )
        assert appended["raw_metadata"] == {"origin": "p0"}

    def test_append_missing_report_raises(self, engine):
        with pytest.raises(ValueError, match="Report not found"):
            engine.append("does-not-exist", attempts=[])


# ---------------------------------------------------------------------------
# Retrieval / exports
# ---------------------------------------------------------------------------


class TestRetrievalExport:
    def test_get_report_round_trip(self, engine):
        created = engine.create(
            attempts=[
                _attempt("stp-1", "pln-1", "cap-1", "COMPLETED", "SUCCESS")
            ]
        )
        loaded = engine.get_report(created["report_id"])
        assert loaded["report_id"] == created["report_id"]
        assert loaded["attempt_count"] == 1

    def test_get_missing_returns_none(self, engine):
        assert engine.get_report("missing-id") is None

    def test_list_reports_sorted(self, engine):
        engine.create(
            attempts=[
                _attempt("stp-1", "pln-1", "cap-1", "COMPLETED", "SUCCESS")
            ]
        )
        engine.create(
            attempts=[
                _attempt("stp-2", "pln-2", "cap-2", "COMPLETED", "SUCCESS")
            ]
        )
        assert len(engine.list_reports()) == 2

    def test_export_json_valid(self, engine):
        created = engine.create(
            attempts=[
                _attempt("stp-1", "pln-1", "cap-1", "COMPLETED", "SUCCESS")
            ]
        )
        parsed = json.loads(
            engine.export_report(created["report_id"], fmt="json")
        )
        assert parsed["report_id"] == created["report_id"]

    def test_export_markdown_headings(self, engine):
        created = engine.create(
            attempts=[
                _attempt(
                    "stp-1",
                    "pln-1",
                    "cap-122",
                    "FAILED",
                    "FAILURE",
                    references=[_ref("STEP", "stp-9")],
                )
            ]
        )
        out = engine.export_report(created["report_id"], fmt="markdown")
        assert "# Execution Attempt Report" in out
        assert "## Status Counts" in out
        assert "## Result Counts" in out
        assert "## Attempts" in out
        assert "[FAILED]" in out
        assert "[FAILURE]" in out
        assert "capability=cap-122" in out
        assert "[STEP] stp-9" in out

    def test_export_csv_rows(self, engine):
        created = engine.create(
            attempts=[
                _attempt(
                    "stp-1",
                    "pln-1",
                    "cap-1",
                    "COMPLETED",
                    "SUCCESS",
                    references=[_ref("STEP", "stp-9")],
                ),
                _attempt("stp-2", "pln-1", "cap-2", "COMPLETED", "SUCCESS"),
            ]
        )
        out = engine.export_report(created["report_id"], fmt="csv")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        assert lines[0].startswith("record_kind,")
        # header + 2 attempts + 1 reference
        assert len(lines) == 4
        attempt_rows = [ln for ln in lines[1:] if ln.startswith("attempt,")]
        reference_rows = [
            ln for ln in lines[1:] if ln.startswith("reference,")
        ]
        assert len(attempt_rows) == 2
        assert len(reference_rows) == 1

    def test_export_invalid_format_raises(self, engine):
        created = engine.create(
            attempts=[
                _attempt("stp-1", "pln-1", "cap-1", "COMPLETED", "SUCCESS")
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
