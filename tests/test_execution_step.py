"""Tests for the Execution Step Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.execution_step import (
    ExecutionStep,
    ExecutionStepEngine,
    ExecutionStepEvidence,
    ExecutionStepReference,
    ExecutionStepReferenceType,
    ExecutionStepReport,
    ExecutionStepStatus,
    ExecutionStepType,
)


def _step(
    plan_id: str,
    capability_id: str,
    order_index: int,
    step_type: str,
    status: str,
    **kw,
) -> dict:
    data = {
        "plan_id": plan_id,
        "capability_id": capability_id,
        "order_index": order_index,
        "step_type": step_type,
        "status": status,
        "summary": kw.get("summary", ""),
    }
    if "step_id" in kw:
        data["step_id"] = kw["step_id"]
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
    return ExecutionStepEngine(artifacts_root=str(tmp_path / "artifacts"))


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_reference_round_trip(self):
        r = ExecutionStepReference(
            reference_id="r-1",
            reference_type="PLAN",
            reference_value="plan-9",
            summary="plan ref",
        )
        assert ExecutionStepReference.from_dict(r.to_dict()) == r

    def test_step_round_trip(self):
        s = ExecutionStep(
            step_id="stp-1",
            plan_id="pln-1",
            capability_id="cap-1",
            order_index=2,
            step_type="IMPLEMENTATION",
            status="READY",
            references=[
                ExecutionStepReference(
                    reference_id="r-1",
                    reference_type="PLAN",
                    reference_value="plan-9",
                )
            ],
            summary="scaffold",
            created_at="2026-01-01T00:00:00+00:00",
            raw_payload={"k": "v"},
        )
        assert ExecutionStep.from_dict(s.to_dict()) == s

    def test_step_gets_id_and_timestamp(self):
        s = ExecutionStep(
            plan_id="pln-1",
            capability_id="cap-1",
            order_index=0,
            step_type="VALIDATION",
            status="CREATED",
        )
        assert s.step_id
        assert s.created_at

    def test_report_defaults(self):
        report = ExecutionStepReport()
        assert report.report_id
        assert report.created_at
        assert report.step_count == 0
        assert report.blocked_count == 0
        assert report.failed_count == 0
        assert report.skipped_count == 0
        assert report.schema_version == "1.0"

    def test_evidence_defaults(self):
        ev = ExecutionStepEvidence(report_id="rep-1")
        assert ev.evidence_id
        assert ev.created_at
        assert ev.report_id == "rep-1"

    def test_all_step_types_present(self):
        assert {t.value for t in ExecutionStepType} == {
            "IMPLEMENTATION",
            "VALIDATION",
            "REPAIR",
            "REVIEW",
            "REPORTING",
            "INVESTIGATION",
            "APPROVAL",
            "OTHER",
        }

    def test_all_statuses_present(self):
        assert {t.value for t in ExecutionStepStatus} == {
            "CREATED",
            "READY",
            "BLOCKED",
            "COMPLETED",
            "FAILED",
            "SKIPPED",
        }

    def test_all_reference_types_present(self):
        assert {t.value for t in ExecutionStepReferenceType} == {
            "CAPABILITY",
            "PLAN",
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
            steps=[
                _step("pln-1", "cap-1", 0, "IMPLEMENTATION", "READY"),
                _step("pln-1", "cap-2", 1, "VALIDATION", "READY"),
                _step("pln-1", "cap-3", 2, "REVIEW", "COMPLETED"),
            ]
        )
        assert report["step_count"] == 3
        assert report["status_counts"] == {
            "COMPLETED": 1,
            "READY": 2,
        }
        assert report["step_type_counts"] == {
            "IMPLEMENTATION": 1,
            "REVIEW": 1,
            "VALIDATION": 1,
        }
        assert report["blocked_count"] == 0
        assert report["failed_count"] == 0
        assert report["skipped_count"] == 0

    def test_deterministic_ordering(self, engine):
        report = engine.create(
            steps=[
                _step("pln-2", "cap-1", 0, "IMPLEMENTATION", "READY"),
                _step("pln-1", "cap-2", 0, "VALIDATION", "READY"),
                _step("pln-1", "cap-1", 0, "IMPLEMENTATION", "READY"),
            ]
        )
        order = [
            (s["plan_id"], s["order_index"], s["capability_id"])
            for s in report["steps"]
        ]
        assert order == [
            ("pln-1", 0, "cap-1"),
            ("pln-1", 0, "cap-2"),
            ("pln-2", 0, "cap-1"),
        ]

    def test_step_ordering_by_order_index(self, engine):
        report = engine.create(
            steps=[
                _step("pln-1", "cap-1", 2, "REVIEW", "READY"),
                _step("pln-1", "cap-1", 0, "IMPLEMENTATION", "READY"),
                _step("pln-1", "cap-1", 1, "VALIDATION", "READY"),
            ]
        )
        order = [s["order_index"] for s in report["steps"]]
        assert order == [0, 1, 2]

    def test_ordering_is_input_independent(self, engine):
        steps = [
            _step("pln-1", "cap-1", 0, "IMPLEMENTATION", "READY"),
            _step("pln-1", "cap-2", 1, "VALIDATION", "READY"),
            _step("pln-1", "cap-3", 2, "REVIEW", "READY"),
        ]
        r1 = engine.create(steps=list(steps))
        r2 = engine.create(steps=list(reversed(steps)))
        key = lambda rep: [  # noqa: E731
            (s["order_index"], s["capability_id"]) for s in rep["steps"]
        ]
        assert key(r1) == key(r2)

    def test_references_ordered_deterministically(self, engine):
        report = engine.create(
            steps=[
                _step(
                    "pln-1",
                    "cap-1",
                    0,
                    "IMPLEMENTATION",
                    "READY",
                    references=[
                        _ref("PLAN", "plan-9"),
                        _ref("CAPABILITY", "cap-9"),
                        _ref("ARTIFACT", "art-9"),
                    ],
                )
            ]
        )
        order = [
            (r["reference_type"], r["reference_value"])
            for r in report["steps"][0]["references"]
        ]
        assert order == [
            ("ARTIFACT", "art-9"),
            ("CAPABILITY", "cap-9"),
            ("PLAN", "plan-9"),
        ]

    def test_schema_version_preserved(self, engine):
        report = engine.create(
            steps=[_step("pln-1", "cap-1", 0, "IMPLEMENTATION", "READY")]
        )
        assert report["schema_version"] == "1.0"

    def test_raw_metadata_preserved(self, engine):
        report = engine.create(
            steps=[_step("pln-1", "cap-1", 0, "IMPLEMENTATION", "READY")],
            raw_metadata={"source": "program-0"},
        )
        assert report["raw_metadata"] == {"source": "program-0"}

    def test_step_raw_payload_preserved(self, engine):
        report = engine.create(
            steps=[
                _step(
                    "pln-1",
                    "cap-1",
                    0,
                    "IMPLEMENTATION",
                    "READY",
                    raw_payload={"nested": {"deep": [1, 2]}},
                )
            ]
        )
        assert report["steps"][0]["raw_payload"] == {
            "nested": {"deep": [1, 2]}
        }


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_step_type_normalized(self, engine):
        report = engine.create(
            steps=[_step("pln-1", "cap-1", 0, "implementation", "READY")]
        )
        assert report["steps"][0]["step_type"] == "IMPLEMENTATION"

    def test_status_normalized(self, engine):
        report = engine.create(
            steps=[_step("pln-1", "cap-1", 0, "VALIDATION", "ready")]
        )
        assert report["steps"][0]["status"] == "READY"

    def test_reference_type_normalized(self, engine):
        report = engine.create(
            steps=[
                _step(
                    "pln-1",
                    "cap-1",
                    0,
                    "IMPLEMENTATION",
                    "READY",
                    references=[_ref("plan", "plan-9")],
                )
            ]
        )
        assert (
            report["steps"][0]["references"][0]["reference_type"] == "PLAN"
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_step_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid step_type"):
            engine.create(
                steps=[_step("pln-1", "cap-1", 0, "NONSENSE", "READY")]
            )

    def test_invalid_status_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid status"):
            engine.create(
                steps=[_step("pln-1", "cap-1", 0, "VALIDATION", "NOPE")]
            )

    def test_missing_plan_id_rejected(self, engine):
        with pytest.raises(ValueError, match="plan_id is required"):
            engine.create(
                steps=[_step("", "cap-1", 0, "VALIDATION", "READY")]
            )

    def test_missing_capability_id_rejected(self, engine):
        with pytest.raises(ValueError, match="capability_id is required"):
            engine.create(
                steps=[_step("pln-1", "", 0, "VALIDATION", "READY")]
            )

    def test_missing_step_type_rejected(self, engine):
        with pytest.raises(ValueError, match="step_type is required"):
            engine.create(
                steps=[_step("pln-1", "cap-1", 0, "", "READY")]
            )

    def test_missing_status_rejected(self, engine):
        with pytest.raises(ValueError, match="status is required"):
            engine.create(
                steps=[_step("pln-1", "cap-1", 0, "VALIDATION", "")]
            )

    def test_non_integer_order_index_rejected(self, engine):
        with pytest.raises(ValueError, match="order_index must be an integer"):
            engine.create(
                steps=[_step("pln-1", "cap-1", "x", "VALIDATION", "READY")]
            )

    def test_bool_order_index_rejected(self, engine):
        with pytest.raises(ValueError, match="order_index must be an integer"):
            engine.create(
                steps=[_step("pln-1", "cap-1", True, "VALIDATION", "READY")]
            )

    def test_invalid_reference_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid reference_type"):
            engine.create(
                steps=[
                    _step(
                        "pln-1",
                        "cap-1",
                        0,
                        "IMPLEMENTATION",
                        "READY",
                        references=[_ref("NONSENSE", "x")],
                    )
                ]
            )

    def test_missing_reference_value_rejected(self, engine):
        with pytest.raises(ValueError, match="reference_value is required"):
            engine.create(
                steps=[
                    _step(
                        "pln-1",
                        "cap-1",
                        0,
                        "IMPLEMENTATION",
                        "READY",
                        references=[_ref("PLAN", "")],
                    )
                ]
            )


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


class TestDuplicateDetection:
    def test_duplicate_step_deduped_and_counted(self, engine):
        report = engine.create(
            steps=[
                _step("pln-1", "cap-1", 0, "IMPLEMENTATION", "READY"),
                _step("pln-1", "cap-1", 0, "implementation", "BLOCKED"),
            ]
        )
        assert report["step_count"] == 1
        assert report["duplicate_step_count"] == 1

    def test_distinct_order_index_not_duplicate(self, engine):
        report = engine.create(
            steps=[
                _step("pln-1", "cap-1", 0, "IMPLEMENTATION", "READY"),
                _step("pln-1", "cap-1", 1, "IMPLEMENTATION", "READY"),
            ]
        )
        assert report["step_count"] == 2
        assert report["duplicate_step_count"] == 0

    def test_distinct_plan_not_duplicate(self, engine):
        report = engine.create(
            steps=[
                _step("pln-1", "cap-1", 0, "IMPLEMENTATION", "READY"),
                _step("pln-2", "cap-1", 0, "IMPLEMENTATION", "READY"),
            ]
        )
        assert report["step_count"] == 2
        assert report["duplicate_step_count"] == 0


# ---------------------------------------------------------------------------
# Blocked / failed / skipped detection
# ---------------------------------------------------------------------------


class TestBlockedFailedDetection:
    def test_blocked_detected(self, engine):
        report = engine.create(
            steps=[
                _step("pln-1", "cap-1", 0, "IMPLEMENTATION", "BLOCKED"),
                _step("pln-1", "cap-2", 1, "VALIDATION", "READY"),
            ]
        )
        assert report["blocked_count"] == 1
        assert report["failed_count"] == 0

    def test_failed_detected(self, engine):
        report = engine.create(
            steps=[
                _step("pln-1", "cap-1", 0, "IMPLEMENTATION", "FAILED"),
                _step("pln-1", "cap-2", 1, "VALIDATION", "READY"),
            ]
        )
        assert report["failed_count"] == 1
        assert report["blocked_count"] == 0

    def test_skipped_detected(self, engine):
        report = engine.create(
            steps=[
                _step("pln-1", "cap-1", 0, "IMPLEMENTATION", "SKIPPED"),
                _step("pln-1", "cap-2", 1, "VALIDATION", "READY"),
            ]
        )
        assert report["skipped_count"] == 1


# ---------------------------------------------------------------------------
# Pass/fail
# ---------------------------------------------------------------------------


def _read_pass_fail(engine, report_id: str) -> dict:
    path = engine._report_dir / report_id / "pass_fail.json"
    return json.loads(path.read_text(encoding="utf-8"))


class TestPassFail:
    def test_pass_with_clean_steps(self, engine):
        report = engine.create(
            steps=[
                _step("pln-1", "cap-1", 0, "IMPLEMENTATION", "READY"),
                _step("pln-1", "cap-2", 1, "VALIDATION", "COMPLETED"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is True
        assert pf["step_count"] == 2
        assert pf["status"] == "passed"

    def test_empty_report_fails(self, engine):
        report = engine.create(steps=[])
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["step_count"] == 0
        assert pf["status"] == "failed"

    def test_blocked_fails(self, engine):
        report = engine.create(
            steps=[_step("pln-1", "cap-1", 0, "IMPLEMENTATION", "BLOCKED")]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["blocked_count"] == 1

    def test_failed_fails(self, engine):
        report = engine.create(
            steps=[_step("pln-1", "cap-1", 0, "IMPLEMENTATION", "FAILED")]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["failed_count"] == 1

    def test_skipped_does_not_fail(self, engine):
        report = engine.create(
            steps=[
                _step("pln-1", "cap-1", 0, "IMPLEMENTATION", "SKIPPED"),
                _step("pln-1", "cap-2", 1, "VALIDATION", "READY"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["skipped_count"] == 1
        assert pf["passed"] is True

    def test_duplicate_does_not_fail_when_clean(self, engine):
        report = engine.create(
            steps=[
                _step("pln-1", "cap-1", 0, "IMPLEMENTATION", "READY"),
                _step("pln-1", "cap-1", 0, "IMPLEMENTATION", "READY"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["duplicate_step_count"] == 1
        assert pf["passed"] is True

    def test_evidence_bundle_files_written(self, engine):
        report = engine.create(
            steps=[_step("pln-1", "cap-1", 0, "IMPLEMENTATION", "READY")]
        )
        report_dir = engine._report_dir / report["report_id"]
        for name in (
            "execution_step_request.json",
            "execution_step_result.json",
            "execution_step_summary.md",
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
            steps=[_step("pln-1", "cap-1", 0, "IMPLEMENTATION", "READY")]
        )
        report_id = created["report_id"]
        appended = engine.append(
            report_id,
            steps=[_step("pln-1", "cap-2", 1, "VALIDATION", "READY")],
        )
        assert appended["report_id"] == report_id
        assert appended["step_count"] == 2
        caps = {s["capability_id"] for s in appended["steps"]}
        assert caps == {"cap-1", "cap-2"}

    def test_append_preserves_raw_metadata(self, engine):
        created = engine.create(
            steps=[_step("pln-1", "cap-1", 0, "IMPLEMENTATION", "READY")],
            raw_metadata={"origin": "p0"},
        )
        appended = engine.append(
            created["report_id"],
            steps=[_step("pln-1", "cap-2", 1, "VALIDATION", "READY")],
        )
        assert appended["raw_metadata"] == {"origin": "p0"}

    def test_append_missing_report_raises(self, engine):
        with pytest.raises(ValueError, match="Report not found"):
            engine.append("does-not-exist", steps=[])


# ---------------------------------------------------------------------------
# Retrieval / exports
# ---------------------------------------------------------------------------


class TestRetrievalExport:
    def test_get_report_round_trip(self, engine):
        created = engine.create(
            steps=[_step("pln-1", "cap-1", 0, "IMPLEMENTATION", "READY")]
        )
        loaded = engine.get_report(created["report_id"])
        assert loaded["report_id"] == created["report_id"]
        assert loaded["step_count"] == 1

    def test_get_missing_returns_none(self, engine):
        assert engine.get_report("missing-id") is None

    def test_list_reports_sorted(self, engine):
        engine.create(
            steps=[_step("pln-1", "cap-1", 0, "IMPLEMENTATION", "READY")]
        )
        engine.create(
            steps=[_step("pln-2", "cap-2", 0, "VALIDATION", "READY")]
        )
        assert len(engine.list_reports()) == 2

    def test_export_json_valid(self, engine):
        created = engine.create(
            steps=[_step("pln-1", "cap-1", 0, "IMPLEMENTATION", "READY")]
        )
        parsed = json.loads(
            engine.export_report(created["report_id"], fmt="json")
        )
        assert parsed["report_id"] == created["report_id"]

    def test_export_markdown_headings(self, engine):
        created = engine.create(
            steps=[
                _step(
                    "pln-1",
                    "cap-122",
                    3,
                    "REVIEW",
                    "BLOCKED",
                    references=[_ref("PLAN", "plan-9")],
                )
            ]
        )
        out = engine.export_report(created["report_id"], fmt="markdown")
        assert "# Execution Step Report" in out
        assert "## Status Counts" in out
        assert "## Step Type Counts" in out
        assert "## Steps" in out
        assert "[BLOCKED]" in out
        assert "[REVIEW]" in out
        assert "[3]" in out
        assert "capability=cap-122" in out
        assert "[PLAN] plan-9" in out

    def test_export_csv_rows(self, engine):
        created = engine.create(
            steps=[
                _step(
                    "pln-1",
                    "cap-1",
                    0,
                    "IMPLEMENTATION",
                    "READY",
                    references=[_ref("PLAN", "plan-9")],
                ),
                _step("pln-1", "cap-2", 1, "VALIDATION", "READY"),
            ]
        )
        out = engine.export_report(created["report_id"], fmt="csv")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        assert lines[0].startswith("record_kind,")
        # header + 2 steps + 1 reference
        assert len(lines) == 4
        step_rows = [ln for ln in lines[1:] if ln.startswith("step,")]
        reference_rows = [
            ln for ln in lines[1:] if ln.startswith("reference,")
        ]
        assert len(step_rows) == 2
        assert len(reference_rows) == 1

    def test_export_invalid_format_raises(self, engine):
        created = engine.create(
            steps=[_step("pln-1", "cap-1", 0, "IMPLEMENTATION", "READY")]
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
