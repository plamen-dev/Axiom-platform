"""Tests for the Execution Plan Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.execution_plan import (
    ExecutionPlan,
    ExecutionPlanEngine,
    ExecutionPlanEvidence,
    ExecutionPlanReport,
    ExecutionPlanStatus,
    ExecutionPlanStep,
    ExecutionPlanType,
)


def _plan(
    capability_id: str,
    readiness_id: str,
    chain_id: str,
    plan_type: str,
    status: str,
    **kw,
) -> dict:
    data = {
        "capability_id": capability_id,
        "readiness_id": readiness_id,
        "chain_id": chain_id,
        "plan_type": plan_type,
        "status": status,
        "summary": kw.get("summary", ""),
    }
    if "plan_id" in kw:
        data["plan_id"] = kw["plan_id"]
    if "steps" in kw:
        data["steps"] = kw["steps"]
    if "raw_payload" in kw:
        data["raw_payload"] = kw["raw_payload"]
    return data


def _step(order_index: int, step_name: str, **kw) -> dict:
    data = {
        "order_index": order_index,
        "step_name": step_name,
        "summary": kw.get("summary", ""),
    }
    if "step_id" in kw:
        data["step_id"] = kw["step_id"]
    return data


@pytest.fixture
def engine(tmp_path):
    return ExecutionPlanEngine(artifacts_root=str(tmp_path / "artifacts"))


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_step_round_trip(self):
        s = ExecutionPlanStep(
            step_id="s-1",
            plan_id="p-1",
            order_index=2,
            step_name="implement",
            summary="do work",
            created_at="2026-01-01T00:00:00+00:00",
        )
        assert ExecutionPlanStep.from_dict(s.to_dict()) == s

    def test_plan_round_trip(self):
        p = ExecutionPlan(
            plan_id="p-1",
            capability_id="cap-1",
            readiness_id="rdy-1",
            chain_id="chn-1",
            plan_type="IMPLEMENTATION",
            status="READY",
            steps=[
                ExecutionPlanStep(
                    step_id="s-1",
                    plan_id="p-1",
                    order_index=0,
                    step_name="start",
                    created_at="2026-01-01T00:00:00+00:00",
                )
            ],
            summary="plan",
            created_at="2026-01-01T00:00:00+00:00",
            raw_payload={"k": "v"},
        )
        assert ExecutionPlan.from_dict(p.to_dict()) == p

    def test_plan_gets_id_and_timestamp(self):
        p = ExecutionPlan(
            capability_id="cap-1",
            readiness_id="rdy-1",
            chain_id="chn-1",
            plan_type="IMPLEMENTATION",
            status="READY",
        )
        assert p.plan_id
        assert p.created_at

    def test_report_defaults(self):
        report = ExecutionPlanReport()
        assert report.report_id
        assert report.created_at
        assert report.plan_count == 0
        assert report.step_count == 0
        assert report.blocked_count == 0
        assert report.failed_count == 0
        assert report.schema_version == "1.0"

    def test_evidence_defaults(self):
        ev = ExecutionPlanEvidence(report_id="rep-1")
        assert ev.evidence_id
        assert ev.created_at
        assert ev.report_id == "rep-1"

    def test_all_plan_types_present(self):
        assert {t.value for t in ExecutionPlanType} == {
            "IMPLEMENTATION",
            "VALIDATION",
            "REPAIR",
            "REVIEW",
            "REPORTING",
            "INVESTIGATION",
            "CUSTOM",
        }

    def test_all_plan_statuses_present(self):
        assert {t.value for t in ExecutionPlanStatus} == {
            "CREATED",
            "READY",
            "BLOCKED",
            "COMPLETED",
            "FAILED",
        }


# ---------------------------------------------------------------------------
# Create / determinism
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_counts(self, engine):
        report = engine.create(
            plans=[
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "READY"),
                _plan("cap-2", "rdy-2", "chn-2", "VALIDATION", "READY"),
                _plan("cap-3", "rdy-3", "chn-3", "REVIEW", "CREATED"),
            ]
        )
        assert report["plan_count"] == 3
        assert report["status_counts"] == {"CREATED": 1, "READY": 2}
        assert report["blocked_count"] == 0
        assert report["failed_count"] == 0

    def test_create_type_aggregation(self, engine):
        report = engine.create(
            plans=[
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "READY"),
                _plan("cap-2", "rdy-2", "chn-2", "IMPLEMENTATION", "READY"),
                _plan("cap-3", "rdy-3", "chn-3", "VALIDATION", "READY"),
            ]
        )
        assert report["plan_type_counts"] == {
            "IMPLEMENTATION": 2,
            "VALIDATION": 1,
        }

    def test_create_step_aggregation(self, engine):
        report = engine.create(
            plans=[
                _plan(
                    "cap-1",
                    "rdy-1",
                    "chn-1",
                    "IMPLEMENTATION",
                    "READY",
                    steps=[_step(0, "a"), _step(1, "b")],
                ),
                _plan(
                    "cap-2",
                    "rdy-2",
                    "chn-2",
                    "VALIDATION",
                    "READY",
                    steps=[_step(0, "c")],
                ),
            ]
        )
        assert report["step_count"] == 3

    def test_deterministic_ordering(self, engine):
        report = engine.create(
            plans=[
                _plan("cap-2", "rdy-1", "chn-1", "IMPLEMENTATION", "READY"),
                _plan("cap-1", "rdy-1", "chn-1", "VALIDATION", "READY"),
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "READY"),
            ]
        )
        order = [
            (p["capability_id"], p["readiness_id"], p["chain_id"],
             p["plan_type"])
            for p in report["plans"]
        ]
        assert order == [
            ("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION"),
            ("cap-1", "rdy-1", "chn-1", "VALIDATION"),
            ("cap-2", "rdy-1", "chn-1", "IMPLEMENTATION"),
        ]

    def test_ordering_is_input_independent(self, engine):
        plans = [
            _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "READY"),
            _plan("cap-2", "rdy-2", "chn-2", "VALIDATION", "READY"),
            _plan("cap-3", "rdy-3", "chn-3", "REVIEW", "READY"),
        ]
        r1 = engine.create(plans=list(plans))
        r2 = engine.create(plans=list(reversed(plans)))
        key = lambda rep: [  # noqa: E731
            (p["capability_id"], p["plan_type"]) for p in rep["plans"]
        ]
        assert key(r1) == key(r2)

    def test_steps_ordered_by_order_index(self, engine):
        report = engine.create(
            plans=[
                _plan(
                    "cap-1",
                    "rdy-1",
                    "chn-1",
                    "IMPLEMENTATION",
                    "READY",
                    steps=[
                        _step(2, "third"),
                        _step(0, "first"),
                        _step(1, "second"),
                    ],
                )
            ]
        )
        order = [s["step_name"] for s in report["plans"][0]["steps"]]
        assert order == ["first", "second", "third"]

    def test_step_plan_id_assigned(self, engine):
        report = engine.create(
            plans=[
                _plan(
                    "cap-1",
                    "rdy-1",
                    "chn-1",
                    "IMPLEMENTATION",
                    "READY",
                    steps=[_step(0, "a")],
                )
            ]
        )
        plan = report["plans"][0]
        assert plan["steps"][0]["plan_id"] == plan["plan_id"]

    def test_schema_version_preserved(self, engine):
        report = engine.create(
            plans=[
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "READY")
            ]
        )
        assert report["schema_version"] == "1.0"

    def test_raw_metadata_preserved(self, engine):
        report = engine.create(
            plans=[
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "READY")
            ],
            raw_metadata={"source": "program-0"},
        )
        assert report["raw_metadata"] == {"source": "program-0"}

    def test_plan_raw_payload_preserved(self, engine):
        report = engine.create(
            plans=[
                _plan(
                    "cap-1",
                    "rdy-1",
                    "chn-1",
                    "IMPLEMENTATION",
                    "READY",
                    raw_payload={"nested": {"deep": [1, 2]}},
                )
            ]
        )
        assert report["plans"][0]["raw_payload"] == {
            "nested": {"deep": [1, 2]}
        }


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_plan_type_normalized(self, engine):
        report = engine.create(
            plans=[
                _plan("cap-1", "rdy-1", "chn-1", "implementation", "READY")
            ]
        )
        assert report["plans"][0]["plan_type"] == "IMPLEMENTATION"

    def test_status_normalized(self, engine):
        report = engine.create(
            plans=[
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "ready")
            ]
        )
        assert report["plans"][0]["status"] == "READY"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_plan_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid plan_type"):
            engine.create(
                plans=[
                    _plan("cap-1", "rdy-1", "chn-1", "NONSENSE", "READY")
                ]
            )

    def test_invalid_status_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid status"):
            engine.create(
                plans=[
                    _plan(
                        "cap-1", "rdy-1", "chn-1", "IMPLEMENTATION",
                        "NONSENSE"
                    )
                ]
            )

    def test_missing_capability_id_rejected(self, engine):
        with pytest.raises(ValueError, match="capability_id is required"):
            engine.create(
                plans=[
                    _plan("", "rdy-1", "chn-1", "IMPLEMENTATION", "READY")
                ]
            )

    def test_missing_readiness_id_rejected(self, engine):
        with pytest.raises(ValueError, match="readiness_id is required"):
            engine.create(
                plans=[
                    _plan("cap-1", "", "chn-1", "IMPLEMENTATION", "READY")
                ]
            )

    def test_missing_chain_id_rejected(self, engine):
        with pytest.raises(ValueError, match="chain_id is required"):
            engine.create(
                plans=[
                    _plan("cap-1", "rdy-1", "", "IMPLEMENTATION", "READY")
                ]
            )

    def test_missing_plan_type_rejected(self, engine):
        with pytest.raises(ValueError, match="plan_type is required"):
            engine.create(
                plans=[_plan("cap-1", "rdy-1", "chn-1", "", "READY")]
            )

    def test_missing_status_rejected(self, engine):
        with pytest.raises(ValueError, match="status is required"):
            engine.create(
                plans=[
                    _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "")
                ]
            )

    def test_missing_step_name_rejected(self, engine):
        with pytest.raises(ValueError, match="step_name is required"):
            engine.create(
                plans=[
                    _plan(
                        "cap-1",
                        "rdy-1",
                        "chn-1",
                        "IMPLEMENTATION",
                        "READY",
                        steps=[{"order_index": 0, "step_name": ""}],
                    )
                ]
            )

    def test_invalid_order_index_rejected(self, engine):
        with pytest.raises(ValueError, match="order_index must be an integer"):
            engine.create(
                plans=[
                    _plan(
                        "cap-1",
                        "rdy-1",
                        "chn-1",
                        "IMPLEMENTATION",
                        "READY",
                        steps=[{"order_index": "abc", "step_name": "a"}],
                    )
                ]
            )


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


class TestDuplicateDetection:
    def test_duplicate_plan_deduped_and_counted(self, engine):
        report = engine.create(
            plans=[
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "READY"),
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "BLOCKED"),
            ]
        )
        assert report["plan_count"] == 1
        assert report["duplicate_plan_count"] == 1

    def test_distinct_plan_type_not_duplicate(self, engine):
        report = engine.create(
            plans=[
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "READY"),
                _plan("cap-1", "rdy-1", "chn-1", "VALIDATION", "READY"),
            ]
        )
        assert report["plan_count"] == 2
        assert report["duplicate_plan_count"] == 0

    def test_distinct_chain_not_duplicate(self, engine):
        report = engine.create(
            plans=[
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "READY"),
                _plan("cap-1", "rdy-1", "chn-2", "IMPLEMENTATION", "READY"),
            ]
        )
        assert report["plan_count"] == 2
        assert report["duplicate_plan_count"] == 0


# ---------------------------------------------------------------------------
# Blocked / failed detection
# ---------------------------------------------------------------------------


class TestBlockedFailedDetection:
    def test_blocked_detected(self, engine):
        report = engine.create(
            plans=[
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "BLOCKED"),
                _plan("cap-2", "rdy-2", "chn-2", "VALIDATION", "READY"),
            ]
        )
        assert report["blocked_count"] == 1
        assert report["failed_count"] == 0

    def test_failed_detected(self, engine):
        report = engine.create(
            plans=[
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "FAILED"),
                _plan("cap-2", "rdy-2", "chn-2", "VALIDATION", "READY"),
            ]
        )
        assert report["failed_count"] == 1
        assert report["blocked_count"] == 0


# ---------------------------------------------------------------------------
# Pass/fail
# ---------------------------------------------------------------------------


def _read_pass_fail(engine, report_id: str) -> dict:
    path = engine._report_dir / report_id / "pass_fail.json"
    return json.loads(path.read_text(encoding="utf-8"))


class TestPassFail:
    def test_pass_with_clean_records(self, engine):
        report = engine.create(
            plans=[
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "READY"),
                _plan("cap-2", "rdy-2", "chn-2", "VALIDATION", "COMPLETED"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is True
        assert pf["plan_count"] == 2
        assert pf["status"] == "passed"

    def test_empty_report_fails(self, engine):
        report = engine.create(plans=[])
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["plan_count"] == 0
        assert pf["status"] == "failed"

    def test_blocked_fails(self, engine):
        report = engine.create(
            plans=[
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "BLOCKED")
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["blocked_count"] == 1

    def test_failed_fails(self, engine):
        report = engine.create(
            plans=[
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "FAILED")
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["failed_count"] == 1

    def test_duplicate_does_not_fail_when_clean(self, engine):
        report = engine.create(
            plans=[
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "READY"),
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "READY"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["duplicate_plan_count"] == 1
        assert pf["passed"] is True

    def test_evidence_bundle_files_written(self, engine):
        report = engine.create(
            plans=[
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "READY")
            ]
        )
        report_dir = engine._report_dir / report["report_id"]
        for name in (
            "execution_plan_request.json",
            "execution_plan_result.json",
            "execution_plan_summary.md",
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
            plans=[
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "READY")
            ]
        )
        report_id = created["report_id"]
        appended = engine.append(
            report_id,
            plans=[
                _plan("cap-2", "rdy-2", "chn-2", "VALIDATION", "READY")
            ],
        )
        assert appended["report_id"] == report_id
        assert appended["plan_count"] == 2
        caps = {p["capability_id"] for p in appended["plans"]}
        assert caps == {"cap-1", "cap-2"}

    def test_append_preserves_raw_metadata(self, engine):
        created = engine.create(
            plans=[
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "READY")
            ],
            raw_metadata={"origin": "p0"},
        )
        appended = engine.append(
            created["report_id"],
            plans=[
                _plan("cap-2", "rdy-2", "chn-2", "VALIDATION", "READY")
            ],
        )
        assert appended["raw_metadata"] == {"origin": "p0"}

    def test_append_missing_report_raises(self, engine):
        with pytest.raises(ValueError, match="Report not found"):
            engine.append("does-not-exist", plans=[])


# ---------------------------------------------------------------------------
# Retrieval / exports
# ---------------------------------------------------------------------------


class TestRetrievalExport:
    def test_get_report_round_trip(self, engine):
        created = engine.create(
            plans=[
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "READY")
            ]
        )
        loaded = engine.get_report(created["report_id"])
        assert loaded["report_id"] == created["report_id"]
        assert loaded["plan_count"] == 1

    def test_get_missing_returns_none(self, engine):
        assert engine.get_report("missing-id") is None

    def test_list_reports_sorted(self, engine):
        engine.create(
            plans=[
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "READY")
            ]
        )
        engine.create(
            plans=[
                _plan("cap-2", "rdy-2", "chn-2", "VALIDATION", "READY")
            ]
        )
        assert len(engine.list_reports()) == 2

    def test_export_json_valid(self, engine):
        created = engine.create(
            plans=[
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "READY")
            ]
        )
        parsed = json.loads(
            engine.export_report(created["report_id"], fmt="json")
        )
        assert parsed["report_id"] == created["report_id"]

    def test_export_markdown_headings(self, engine):
        created = engine.create(
            plans=[
                _plan(
                    "cap-122",
                    "rdy-1",
                    "chn-1",
                    "IMPLEMENTATION",
                    "READY",
                    steps=[_step(0, "scaffold")],
                )
            ]
        )
        out = engine.export_report(created["report_id"], fmt="markdown")
        assert "# Execution Plan Report" in out
        assert "## Status Counts" in out
        assert "## Plan Type Counts" in out
        assert "## Plans" in out
        assert "[READY]" in out
        assert "[IMPLEMENTATION]" in out
        assert "capability=cap-122" in out
        assert "[0] scaffold" in out

    def test_export_csv_rows(self, engine):
        created = engine.create(
            plans=[
                _plan(
                    "cap-1",
                    "rdy-1",
                    "chn-1",
                    "IMPLEMENTATION",
                    "READY",
                    steps=[_step(0, "scaffold")],
                ),
                _plan("cap-2", "rdy-2", "chn-2", "VALIDATION", "READY"),
            ]
        )
        out = engine.export_report(created["report_id"], fmt="csv")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        assert lines[0].startswith("record_kind,")
        # header + 2 plans + 1 step
        assert len(lines) == 4
        plan_rows = [ln for ln in lines[1:] if ln.startswith("plan,")]
        step_rows = [ln for ln in lines[1:] if ln.startswith("step,")]
        assert len(plan_rows) == 2
        assert len(step_rows) == 1

    def test_export_invalid_format_raises(self, engine):
        created = engine.create(
            plans=[
                _plan("cap-1", "rdy-1", "chn-1", "IMPLEMENTATION", "READY")
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
