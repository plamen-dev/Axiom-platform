"""Tests for the Execution Report Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.execution_report import (
    ExecutionReport,
    ExecutionReportEngine,
    ExecutionReportEvidence,
    ExecutionReportReference,
    ExecutionReportReferenceType,
    ExecutionReportSection,
    ExecutionReportSectionType,
    ExecutionReportStatus,
    ExecutionReportSummary,
    ExecutionReportType,
)


def _report(
    capability_id: str,
    attempt_id: str,
    result_id: str,
    report_type: str,
    status: str,
    **kw,
) -> dict:
    data = {
        "capability_id": capability_id,
        "attempt_id": attempt_id,
        "result_id": result_id,
        "report_type": report_type,
        "status": status,
        "summary": kw.get("summary", ""),
    }
    for k in (
        "report_id",
        "sections",
        "references",
        "raw_payload",
    ):
        if k in kw:
            data[k] = kw[k]
    return data


def _section(section_type: str, title: str, order_index: int, **kw) -> dict:
    data = {
        "section_type": section_type,
        "title": title,
        "order_index": order_index,
        "content": kw.get("content", ""),
    }
    if "section_id" in kw:
        data["section_id"] = kw["section_id"]
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
    return ExecutionReportEngine(artifacts_root=str(tmp_path / "artifacts"))


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_section_round_trip(self):
        s = ExecutionReportSection(
            section_id="s-1",
            section_type="OVERVIEW",
            title="Overview",
            content="body",
            order_index=2,
        )
        assert ExecutionReportSection.from_dict(s.to_dict()) == s

    def test_reference_round_trip(self):
        r = ExecutionReportReference(
            reference_id="r-1",
            reference_type="RESULT",
            reference_value="res-9",
            summary="result ref",
        )
        assert ExecutionReportReference.from_dict(r.to_dict()) == r

    def test_report_round_trip(self):
        r = ExecutionReport(
            report_id="rep-1",
            capability_id="cap-1",
            attempt_id="att-1",
            result_id="res-1",
            report_type="EXECUTION_SUMMARY",
            status="COMPLETE",
            sections=[
                ExecutionReportSection(
                    section_id="s-1",
                    section_type="OVERVIEW",
                    title="Overview",
                    order_index=0,
                )
            ],
            references=[
                ExecutionReportReference(
                    reference_id="r-1",
                    reference_type="RESULT",
                    reference_value="res-9",
                )
            ],
            summary="done",
            created_at="2026-01-01T00:00:00+00:00",
            raw_payload={"k": "v"},
        )
        assert ExecutionReport.from_dict(r.to_dict()) == r

    def test_report_gets_id_and_timestamp(self):
        r = ExecutionReport(
            capability_id="cap-1",
            attempt_id="att-1",
            result_id="res-1",
            report_type="EXECUTION_SUMMARY",
            status="COMPLETE",
        )
        assert r.report_id
        assert r.created_at

    def test_summary_defaults(self):
        summary = ExecutionReportSummary()
        assert summary.summary_id
        assert summary.created_at
        assert summary.report_count == 0
        assert summary.section_count == 0
        assert summary.failed_count == 0
        assert summary.partial_count == 0
        assert summary.complete_count == 0
        assert summary.schema_version == "1.0"

    def test_evidence_defaults(self):
        ev = ExecutionReportEvidence(summary_id="sum-1")
        assert ev.evidence_id
        assert ev.created_at
        assert ev.summary_id == "sum-1"

    def test_all_report_types_present(self):
        assert {t.value for t in ExecutionReportType} == {
            "EXECUTION_SUMMARY",
            "VALIDATION_SUMMARY",
            "FAILURE_SUMMARY",
            "ARTIFACT_SUMMARY",
            "REVIEW_SUMMARY",
            "FINAL_SUMMARY",
            "OTHER",
        }

    def test_all_statuses_present(self):
        assert {t.value for t in ExecutionReportStatus} == {
            "CREATED",
            "COMPLETE",
            "PARTIAL",
            "FAILED",
            "UNKNOWN",
        }

    def test_all_section_types_present(self):
        assert {t.value for t in ExecutionReportSectionType} == {
            "OVERVIEW",
            "RESULT",
            "ARTIFACTS",
            "FAILURES",
            "VALIDATION",
            "RISKS",
            "NEXT_STEPS",
            "OTHER",
        }

    def test_all_reference_types_present(self):
        assert {t.value for t in ExecutionReportReferenceType} == {
            "RESULT",
            "ARTIFACT",
            "ATTEMPT",
            "CAPABILITY",
            "FILE",
            "VALIDATION",
            "KNOWLEDGE_NODE",
            "OTHER",
        }


# ---------------------------------------------------------------------------
# Create / determinism
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_counts(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                ),
                _report(
                    "cap-2", "att-2", "res-2",
                    "FAILURE_SUMMARY", "PARTIAL",
                ),
                _report(
                    "cap-3", "att-3", "res-3",
                    "REVIEW_SUMMARY", "UNKNOWN",
                ),
            ]
        )
        assert summary["report_count"] == 3
        assert summary["status_counts"] == {
            "COMPLETE": 1,
            "PARTIAL": 1,
            "UNKNOWN": 1,
        }
        assert summary["report_type_counts"] == {
            "EXECUTION_SUMMARY": 1,
            "FAILURE_SUMMARY": 1,
            "REVIEW_SUMMARY": 1,
        }
        assert summary["failed_count"] == 0
        assert summary["partial_count"] == 1
        assert summary["complete_count"] == 1

    def test_section_count_aggregated(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                    sections=[
                        _section("OVERVIEW", "o", 0),
                        _section("RESULT", "r", 1),
                    ],
                ),
                _report(
                    "cap-2", "att-2", "res-2",
                    "FINAL_SUMMARY", "COMPLETE",
                    sections=[_section("RISKS", "x", 0)],
                ),
            ]
        )
        assert summary["section_count"] == 3

    def test_deterministic_ordering(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-2", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                ),
                _report(
                    "cap-1", "att-2", "res-2",
                    "EXECUTION_SUMMARY", "COMPLETE",
                ),
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                ),
            ]
        )
        order = [
            (r["capability_id"], r["attempt_id"], r["result_id"])
            for r in summary["reports"]
        ]
        assert order == [
            ("cap-1", "att-1", "res-1"),
            ("cap-1", "att-2", "res-2"),
            ("cap-2", "att-1", "res-1"),
        ]

    def test_ordering_is_input_independent(self, engine):
        reports = [
            _report("cap-1", "att-1", "res-1", "EXECUTION_SUMMARY", "COMPLETE"),
            _report("cap-2", "att-2", "res-2", "EXECUTION_SUMMARY", "COMPLETE"),
            _report("cap-3", "att-3", "res-3", "EXECUTION_SUMMARY", "COMPLETE"),
        ]
        r1 = engine.create(reports=list(reports))
        r2 = engine.create(reports=list(reversed(reports)))
        key = lambda rep: [  # noqa: E731
            (r["capability_id"], r["attempt_id"]) for r in rep["reports"]
        ]
        assert key(r1) == key(r2)

    def test_sections_ordered_by_order_index(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                    sections=[
                        _section("RISKS", "c", 2),
                        _section("OVERVIEW", "a", 0),
                        _section("RESULT", "b", 1),
                    ],
                )
            ]
        )
        order = [
            (s["order_index"], s["section_type"])
            for s in summary["reports"][0]["sections"]
        ]
        assert order == [
            (0, "OVERVIEW"),
            (1, "RESULT"),
            (2, "RISKS"),
        ]

    def test_references_ordered_deterministically(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                    references=[
                        _ref("RESULT", "res-9"),
                        _ref("ARTIFACT", "art-9"),
                        _ref("ATTEMPT", "att-9"),
                    ],
                )
            ]
        )
        order = [
            (r["reference_type"], r["reference_value"])
            for r in summary["reports"][0]["references"]
        ]
        assert order == [
            ("ARTIFACT", "art-9"),
            ("ATTEMPT", "att-9"),
            ("RESULT", "res-9"),
        ]

    def test_schema_version_preserved(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                )
            ]
        )
        assert summary["schema_version"] == "1.0"

    def test_raw_metadata_preserved(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                )
            ],
            raw_metadata={"source": "program-0"},
        )
        assert summary["raw_metadata"] == {"source": "program-0"}

    def test_report_raw_payload_preserved(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                    raw_payload={"nested": {"deep": [1, 2]}},
                )
            ]
        )
        assert summary["reports"][0]["raw_payload"] == {
            "nested": {"deep": [1, 2]}
        }


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_status_normalized(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "complete",
                )
            ]
        )
        assert summary["reports"][0]["status"] == "COMPLETE"

    def test_report_type_normalized(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "execution_summary", "COMPLETE",
                )
            ]
        )
        assert summary["reports"][0]["report_type"] == "EXECUTION_SUMMARY"

    def test_section_type_normalized(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                    sections=[_section("overview", "o", 0)],
                )
            ]
        )
        assert (
            summary["reports"][0]["sections"][0]["section_type"] == "OVERVIEW"
        )

    def test_reference_type_normalized(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                    references=[_ref("result", "res-9")],
                )
            ]
        )
        assert (
            summary["reports"][0]["references"][0]["reference_type"]
            == "RESULT"
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_status_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid status"):
            engine.create(
                reports=[
                    _report(
                        "cap-1", "att-1", "res-1",
                        "EXECUTION_SUMMARY", "NONSENSE",
                    )
                ]
            )

    def test_invalid_report_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid report_type"):
            engine.create(
                reports=[
                    _report("cap-1", "att-1", "res-1", "NOPE", "COMPLETE")
                ]
            )

    def test_missing_capability_id_rejected(self, engine):
        with pytest.raises(ValueError, match="capability_id is required"):
            engine.create(
                reports=[
                    _report(
                        "", "att-1", "res-1",
                        "EXECUTION_SUMMARY", "COMPLETE",
                    )
                ]
            )

    def test_missing_attempt_id_rejected(self, engine):
        with pytest.raises(ValueError, match="attempt_id is required"):
            engine.create(
                reports=[
                    _report(
                        "cap-1", "", "res-1",
                        "EXECUTION_SUMMARY", "COMPLETE",
                    )
                ]
            )

    def test_missing_result_id_rejected(self, engine):
        with pytest.raises(ValueError, match="result_id is required"):
            engine.create(
                reports=[
                    _report(
                        "cap-1", "att-1", "",
                        "EXECUTION_SUMMARY", "COMPLETE",
                    )
                ]
            )

    def test_missing_report_type_rejected(self, engine):
        with pytest.raises(ValueError, match="report_type is required"):
            engine.create(
                reports=[
                    _report("cap-1", "att-1", "res-1", "", "COMPLETE")
                ]
            )

    def test_missing_status_rejected(self, engine):
        with pytest.raises(ValueError, match="status is required"):
            engine.create(
                reports=[
                    _report(
                        "cap-1", "att-1", "res-1",
                        "EXECUTION_SUMMARY", "",
                    )
                ]
            )

    def test_invalid_section_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid section_type"):
            engine.create(
                reports=[
                    _report(
                        "cap-1", "att-1", "res-1",
                        "EXECUTION_SUMMARY", "COMPLETE",
                        sections=[_section("NONSENSE", "x", 0)],
                    )
                ]
            )

    def test_missing_section_type_rejected(self, engine):
        with pytest.raises(ValueError, match="section_type is required"):
            engine.create(
                reports=[
                    _report(
                        "cap-1", "att-1", "res-1",
                        "EXECUTION_SUMMARY", "COMPLETE",
                        sections=[_section("", "x", 0)],
                    )
                ]
            )

    def test_invalid_reference_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid reference_type"):
            engine.create(
                reports=[
                    _report(
                        "cap-1", "att-1", "res-1",
                        "EXECUTION_SUMMARY", "COMPLETE",
                        references=[_ref("NONSENSE", "x")],
                    )
                ]
            )

    def test_missing_reference_value_rejected(self, engine):
        with pytest.raises(ValueError, match="reference_value is required"):
            engine.create(
                reports=[
                    _report(
                        "cap-1", "att-1", "res-1",
                        "EXECUTION_SUMMARY", "COMPLETE",
                        references=[_ref("RESULT", "")],
                    )
                ]
            )


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


class TestDuplicateDetection:
    def test_duplicate_report_deduped_and_counted(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                ),
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "FAILED",
                ),
            ]
        )
        assert summary["report_count"] == 1
        assert summary["duplicate_report_count"] == 1

    def test_distinct_report_type_not_duplicate(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                ),
                _report(
                    "cap-1", "att-1", "res-1",
                    "FINAL_SUMMARY", "COMPLETE",
                ),
            ]
        )
        assert summary["report_count"] == 2
        assert summary["duplicate_report_count"] == 0

    def test_distinct_capability_not_duplicate(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                ),
                _report(
                    "cap-2", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                ),
            ]
        )
        assert summary["report_count"] == 2
        assert summary["duplicate_report_count"] == 0


# ---------------------------------------------------------------------------
# Failed / partial / complete detection
# ---------------------------------------------------------------------------


class TestFailedPartialDetection:
    def test_failed_detected(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "FAILURE_SUMMARY", "FAILED",
                ),
                _report(
                    "cap-2", "att-2", "res-2",
                    "EXECUTION_SUMMARY", "COMPLETE",
                ),
            ]
        )
        assert summary["failed_count"] == 1
        assert summary["partial_count"] == 0

    def test_partial_detected(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "PARTIAL",
                ),
                _report(
                    "cap-2", "att-2", "res-2",
                    "EXECUTION_SUMMARY", "COMPLETE",
                ),
            ]
        )
        assert summary["partial_count"] == 1
        assert summary["failed_count"] == 0

    def test_complete_counted(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                ),
                _report(
                    "cap-2", "att-2", "res-2",
                    "EXECUTION_SUMMARY", "CREATED",
                ),
            ]
        )
        assert summary["complete_count"] == 1


# ---------------------------------------------------------------------------
# Pass/fail
# ---------------------------------------------------------------------------


def _read_pass_fail(engine, summary_id: str) -> dict:
    path = engine._report_dir / summary_id / "pass_fail.json"
    return json.loads(path.read_text(encoding="utf-8"))


class TestPassFail:
    def test_pass_with_clean_reports(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                ),
                _report(
                    "cap-2", "att-2", "res-2",
                    "EXECUTION_SUMMARY", "PARTIAL",
                ),
            ]
        )
        pf = _read_pass_fail(engine, summary["summary_id"])
        assert pf["passed"] is True
        assert pf["report_count"] == 2
        assert pf["status"] == "passed"

    def test_empty_report_fails(self, engine):
        summary = engine.create(reports=[])
        pf = _read_pass_fail(engine, summary["summary_id"])
        assert pf["passed"] is False
        assert pf["report_count"] == 0
        assert pf["status"] == "failed"

    def test_failed_fails(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "FAILURE_SUMMARY", "FAILED",
                )
            ]
        )
        pf = _read_pass_fail(engine, summary["summary_id"])
        assert pf["passed"] is False
        assert pf["failed_count"] == 1

    def test_partial_does_not_fail(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "PARTIAL",
                )
            ]
        )
        pf = _read_pass_fail(engine, summary["summary_id"])
        assert pf["passed"] is True
        assert pf["partial_count"] == 1

    def test_unknown_does_not_fail(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "UNKNOWN",
                )
            ]
        )
        pf = _read_pass_fail(engine, summary["summary_id"])
        assert pf["passed"] is True

    def test_duplicate_does_not_fail_when_clean(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                ),
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                ),
            ]
        )
        pf = _read_pass_fail(engine, summary["summary_id"])
        assert pf["duplicate_report_count"] == 1
        assert pf["passed"] is True

    def test_evidence_bundle_files_written(self, engine):
        summary = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                )
            ]
        )
        summary_dir = engine._report_dir / summary["summary_id"]
        for name in (
            "execution_report_request.json",
            "execution_report_result.json",
            "execution_report_summary.md",
            "pass_fail.json",
            "report.json",
        ):
            assert (summary_dir / name).exists()


# ---------------------------------------------------------------------------
# Append-only
# ---------------------------------------------------------------------------


class TestAppend:
    def test_append_preserves_and_adds(self, engine):
        created = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                )
            ]
        )
        summary_id = created["summary_id"]
        appended = engine.append(
            summary_id,
            reports=[
                _report(
                    "cap-2", "att-2", "res-2",
                    "EXECUTION_SUMMARY", "COMPLETE",
                )
            ],
        )
        assert appended["summary_id"] == summary_id
        assert appended["report_count"] == 2
        caps = {r["capability_id"] for r in appended["reports"]}
        assert caps == {"cap-1", "cap-2"}

    def test_append_preserves_raw_metadata(self, engine):
        created = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                )
            ],
            raw_metadata={"origin": "p0"},
        )
        appended = engine.append(
            created["summary_id"],
            reports=[
                _report(
                    "cap-2", "att-2", "res-2",
                    "EXECUTION_SUMMARY", "COMPLETE",
                )
            ],
        )
        assert appended["raw_metadata"] == {"origin": "p0"}

    def test_append_missing_summary_raises(self, engine):
        with pytest.raises(ValueError, match="Report not found"):
            engine.append("does-not-exist", reports=[])


# ---------------------------------------------------------------------------
# Retrieval / exports
# ---------------------------------------------------------------------------


class TestRetrievalExport:
    def test_get_report_round_trip(self, engine):
        created = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                )
            ]
        )
        loaded = engine.get_report(created["summary_id"])
        assert loaded["summary_id"] == created["summary_id"]
        assert loaded["report_count"] == 1

    def test_get_missing_returns_none(self, engine):
        assert engine.get_report("missing-id") is None

    def test_list_reports_sorted(self, engine):
        engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                )
            ]
        )
        engine.create(
            reports=[
                _report(
                    "cap-2", "att-2", "res-2",
                    "EXECUTION_SUMMARY", "COMPLETE",
                )
            ]
        )
        assert len(engine.list_reports()) == 2

    def test_export_json_valid(self, engine):
        created = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                )
            ]
        )
        parsed = json.loads(
            engine.export_report(created["summary_id"], fmt="json")
        )
        assert parsed["summary_id"] == created["summary_id"]

    def test_export_markdown_headings(self, engine):
        created = engine.create(
            reports=[
                _report(
                    "cap-122", "att-1", "res-1",
                    "FAILURE_SUMMARY", "FAILED",
                    sections=[_section("FAILURES", "What broke", 0)],
                    references=[_ref("RESULT", "res-9")],
                )
            ]
        )
        out = engine.export_report(created["summary_id"], fmt="markdown")
        assert "# Execution Report Summary" in out
        assert "## Status Counts" in out
        assert "## Report Type Counts" in out
        assert "## Reports" in out
        assert "[FAILED]" in out
        assert "[FAILURE_SUMMARY]" in out
        assert "capability=cap-122" in out
        assert "[0] [FAILURES] What broke" in out
        assert "[RESULT] res-9" in out

    def test_export_csv_rows(self, engine):
        created = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                    sections=[_section("OVERVIEW", "o", 0)],
                    references=[_ref("RESULT", "res-9")],
                ),
                _report(
                    "cap-2", "att-2", "res-2",
                    "EXECUTION_SUMMARY", "COMPLETE",
                ),
            ]
        )
        out = engine.export_report(created["summary_id"], fmt="csv")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        assert lines[0].startswith("record_kind,")
        # header + 2 reports + 1 section + 1 reference
        assert len(lines) == 5
        report_rows = [ln for ln in lines[1:] if ln.startswith("report,")]
        section_rows = [ln for ln in lines[1:] if ln.startswith("section,")]
        reference_rows = [
            ln for ln in lines[1:] if ln.startswith("reference,")
        ]
        assert len(report_rows) == 2
        assert len(section_rows) == 1
        assert len(reference_rows) == 1

    def test_export_invalid_format_raises(self, engine):
        created = engine.create(
            reports=[
                _report(
                    "cap-1", "att-1", "res-1",
                    "EXECUTION_SUMMARY", "COMPLETE",
                )
            ]
        )
        with pytest.raises(ValueError, match="Invalid export format"):
            engine.export_report(created["summary_id"], fmt="xml")

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
