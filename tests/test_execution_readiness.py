"""Tests for the Execution Readiness Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.execution_readiness import (
    ExecutionReadiness,
    ExecutionReadinessCheck,
    ExecutionReadinessCheckType,
    ExecutionReadinessEngine,
    ExecutionReadinessEvidence,
    ExecutionReadinessReport,
    ExecutionReadinessStatus,
)


def _rdy(
    context_id: str,
    environment_id: str,
    resource_id: str,
    constraint_id: str,
    capability_id: str,
    readiness_status: str,
    **kw,
) -> dict:
    data = {
        "context_id": context_id,
        "environment_id": environment_id,
        "resource_id": resource_id,
        "constraint_id": constraint_id,
        "capability_id": capability_id,
        "readiness_status": readiness_status,
        "summary": kw.get("summary", ""),
    }
    if "readiness_id" in kw:
        data["readiness_id"] = kw["readiness_id"]
    if "checks" in kw:
        data["checks"] = kw["checks"]
    if "raw_payload" in kw:
        data["raw_payload"] = kw["raw_payload"]
    return data


def _chk(check_type: str, status: str, **kw) -> dict:
    data = {
        "check_type": check_type,
        "status": status,
        "summary": kw.get("summary", ""),
    }
    if "check_id" in kw:
        data["check_id"] = kw["check_id"]
    return data


@pytest.fixture
def engine(tmp_path):
    return ExecutionReadinessEngine(
        artifacts_root=str(tmp_path / "artifacts")
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_check_round_trip(self):
        c = ExecutionReadinessCheck(
            check_id="c-1",
            check_type="CONTEXT_CHECK",
            status="PASS",
            summary="ctx ok",
        )
        assert ExecutionReadinessCheck.from_dict(c.to_dict()) == c

    def test_readiness_round_trip(self):
        r = ExecutionReadiness(
            readiness_id="rdy-1",
            context_id="ctx-1",
            environment_id="env-1",
            resource_id="res-1",
            constraint_id="con-1",
            capability_id="cap-1",
            readiness_status="READY",
            checks=[
                ExecutionReadinessCheck(
                    check_id="c-1",
                    check_type="CONTEXT_CHECK",
                    status="PASS",
                )
            ],
            summary="all good",
            created_at="2026-01-01T00:00:00+00:00",
            raw_payload={"k": "v"},
        )
        assert ExecutionReadiness.from_dict(r.to_dict()) == r

    def test_readiness_gets_id_and_timestamp(self):
        r = ExecutionReadiness(
            context_id="ctx-1",
            environment_id="env-1",
            resource_id="res-1",
            constraint_id="con-1",
            capability_id="cap-1",
            readiness_status="READY",
        )
        assert r.readiness_id
        assert r.created_at

    def test_report_defaults(self):
        report = ExecutionReadinessReport()
        assert report.report_id
        assert report.created_at
        assert report.readiness_count == 0
        assert report.ready_count == 0
        assert report.degraded_count == 0
        assert report.not_ready_count == 0
        assert report.schema_version == "1.0"

    def test_evidence_defaults(self):
        ev = ExecutionReadinessEvidence(report_id="rep-1")
        assert ev.evidence_id
        assert ev.created_at
        assert ev.report_id == "rep-1"

    def test_all_readiness_statuses_present(self):
        assert {t.value for t in ExecutionReadinessStatus} == {
            "READY",
            "NOT_READY",
            "DEGRADED",
            "UNKNOWN",
        }

    def test_all_check_types_present(self):
        assert {t.value for t in ExecutionReadinessCheckType} == {
            "CONTEXT_CHECK",
            "ENVIRONMENT_CHECK",
            "RESOURCE_CHECK",
            "CONSTRAINT_CHECK",
            "VALIDATION_CHECK",
            "OTHER",
        }


# ---------------------------------------------------------------------------
# Create / determinism
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_counts(self, engine):
        report = engine.create(
            readinesses=[
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "READY"),
                _rdy("ctx-2", "env-2", "res-2", "con-2", "cap-2", "READY"),
                _rdy("ctx-3", "env-3", "res-3", "con-3", "cap-3", "UNKNOWN"),
            ]
        )
        assert report["readiness_count"] == 3
        assert report["readiness_status_counts"] == {
            "READY": 2,
            "UNKNOWN": 1,
        }
        assert report["ready_count"] == 2
        assert report["degraded_count"] == 0
        assert report["not_ready_count"] == 0

    def test_create_check_aggregation(self, engine):
        report = engine.create(
            readinesses=[
                _rdy(
                    "ctx-1",
                    "env-1",
                    "res-1",
                    "con-1",
                    "cap-1",
                    "READY",
                    checks=[
                        _chk("CONTEXT_CHECK", "PASS"),
                        _chk("RESOURCE_CHECK", "PASS"),
                    ],
                ),
                _rdy(
                    "ctx-2",
                    "env-2",
                    "res-2",
                    "con-2",
                    "cap-2",
                    "READY",
                    checks=[_chk("CONTEXT_CHECK", "PASS")],
                ),
            ]
        )
        assert report["check_count"] == 3
        assert report["check_type_counts"] == {
            "CONTEXT_CHECK": 2,
            "RESOURCE_CHECK": 1,
        }

    def test_deterministic_ordering(self, engine):
        report = engine.create(
            readinesses=[
                _rdy("ctx-2", "env-1", "res-1", "con-1", "cap-1", "READY"),
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-2", "READY"),
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "READY"),
            ]
        )
        order = [
            (
                r["context_id"],
                r["environment_id"],
                r["resource_id"],
                r["constraint_id"],
                r["capability_id"],
            )
            for r in report["readinesses"]
        ]
        assert order == [
            ("ctx-1", "env-1", "res-1", "con-1", "cap-1"),
            ("ctx-1", "env-1", "res-1", "con-1", "cap-2"),
            ("ctx-2", "env-1", "res-1", "con-1", "cap-1"),
        ]

    def test_ordering_is_input_independent(self, engine):
        readinesses = [
            _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "READY"),
            _rdy("ctx-2", "env-2", "res-2", "con-2", "cap-2", "READY"),
            _rdy("ctx-3", "env-3", "res-3", "con-3", "cap-3", "READY"),
        ]
        r1 = engine.create(readinesses=list(readinesses))
        r2 = engine.create(readinesses=list(reversed(readinesses)))
        key = lambda rep: [  # noqa: E731
            (r["context_id"], r["capability_id"])
            for r in rep["readinesses"]
        ]
        assert key(r1) == key(r2)

    def test_checks_ordered_deterministically(self, engine):
        report = engine.create(
            readinesses=[
                _rdy(
                    "ctx-1",
                    "env-1",
                    "res-1",
                    "con-1",
                    "cap-1",
                    "READY",
                    checks=[
                        _chk("RESOURCE_CHECK", "PASS"),
                        _chk("CONSTRAINT_CHECK", "PASS"),
                        _chk("CONTEXT_CHECK", "PASS"),
                    ],
                )
            ]
        )
        order = [
            c["check_type"]
            for c in report["readinesses"][0]["checks"]
        ]
        assert order == [
            "CONSTRAINT_CHECK",
            "CONTEXT_CHECK",
            "RESOURCE_CHECK",
        ]

    def test_schema_version_preserved(self, engine):
        report = engine.create(
            readinesses=[
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "READY")
            ]
        )
        assert report["schema_version"] == "1.0"

    def test_raw_metadata_preserved(self, engine):
        report = engine.create(
            readinesses=[
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "READY")
            ],
            raw_metadata={"source": "program-0"},
        )
        assert report["raw_metadata"] == {"source": "program-0"}

    def test_readiness_raw_payload_preserved(self, engine):
        report = engine.create(
            readinesses=[
                _rdy(
                    "ctx-1",
                    "env-1",
                    "res-1",
                    "con-1",
                    "cap-1",
                    "READY",
                    raw_payload={"nested": {"deep": [1, 2]}},
                )
            ]
        )
        assert report["readinesses"][0]["raw_payload"] == {
            "nested": {"deep": [1, 2]}
        }


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_readiness_status_normalized(self, engine):
        report = engine.create(
            readinesses=[
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "ready")
            ]
        )
        assert report["readinesses"][0]["readiness_status"] == "READY"

    def test_check_type_normalized(self, engine):
        report = engine.create(
            readinesses=[
                _rdy(
                    "ctx-1",
                    "env-1",
                    "res-1",
                    "con-1",
                    "cap-1",
                    "READY",
                    checks=[_chk("context_check", "pass")],
                )
            ]
        )
        assert (
            report["readinesses"][0]["checks"][0]["check_type"]
            == "CONTEXT_CHECK"
        )

    def test_check_status_normalized(self, engine):
        report = engine.create(
            readinesses=[
                _rdy(
                    "ctx-1",
                    "env-1",
                    "res-1",
                    "con-1",
                    "cap-1",
                    "READY",
                    checks=[_chk("CONTEXT_CHECK", "pass")],
                )
            ]
        )
        assert (
            report["readinesses"][0]["checks"][0]["status"] == "PASS"
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_readiness_status_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid readiness_status"):
            engine.create(
                readinesses=[
                    _rdy(
                        "ctx-1", "env-1", "res-1", "con-1", "cap-1",
                        "NONSENSE"
                    )
                ]
            )

    def test_missing_context_id_rejected(self, engine):
        with pytest.raises(ValueError, match="context_id is required"):
            engine.create(
                readinesses=[
                    _rdy("", "env-1", "res-1", "con-1", "cap-1", "READY")
                ]
            )

    def test_missing_environment_id_rejected(self, engine):
        with pytest.raises(ValueError, match="environment_id is required"):
            engine.create(
                readinesses=[
                    _rdy("ctx-1", "", "res-1", "con-1", "cap-1", "READY")
                ]
            )

    def test_missing_resource_id_rejected(self, engine):
        with pytest.raises(ValueError, match="resource_id is required"):
            engine.create(
                readinesses=[
                    _rdy("ctx-1", "env-1", "", "con-1", "cap-1", "READY")
                ]
            )

    def test_missing_constraint_id_rejected(self, engine):
        with pytest.raises(ValueError, match="constraint_id is required"):
            engine.create(
                readinesses=[
                    _rdy("ctx-1", "env-1", "res-1", "", "cap-1", "READY")
                ]
            )

    def test_missing_capability_id_rejected(self, engine):
        with pytest.raises(ValueError, match="capability_id is required"):
            engine.create(
                readinesses=[
                    _rdy("ctx-1", "env-1", "res-1", "con-1", "", "READY")
                ]
            )

    def test_missing_readiness_status_rejected(self, engine):
        with pytest.raises(ValueError, match="readiness_status is required"):
            engine.create(
                readinesses=[
                    _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "")
                ]
            )

    def test_invalid_check_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid check_type"):
            engine.create(
                readinesses=[
                    _rdy(
                        "ctx-1",
                        "env-1",
                        "res-1",
                        "con-1",
                        "cap-1",
                        "READY",
                        checks=[_chk("NONSENSE", "PASS")],
                    )
                ]
            )

    def test_missing_check_status_rejected(self, engine):
        with pytest.raises(ValueError, match="status is required"):
            engine.create(
                readinesses=[
                    _rdy(
                        "ctx-1",
                        "env-1",
                        "res-1",
                        "con-1",
                        "cap-1",
                        "READY",
                        checks=[_chk("CONTEXT_CHECK", "")],
                    )
                ]
            )


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


class TestDuplicateDetection:
    def test_duplicate_readiness_deduped_and_counted(self, engine):
        report = engine.create(
            readinesses=[
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "READY"),
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "DEGRADED"),
            ]
        )
        assert report["readiness_count"] == 1
        assert report["duplicate_readiness_count"] == 1

    def test_distinct_constraint_not_duplicate(self, engine):
        report = engine.create(
            readinesses=[
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "READY"),
                _rdy("ctx-1", "env-1", "res-1", "con-2", "cap-1", "READY"),
            ]
        )
        assert report["readiness_count"] == 2
        assert report["duplicate_readiness_count"] == 0

    def test_distinct_capability_not_duplicate(self, engine):
        report = engine.create(
            readinesses=[
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "READY"),
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-2", "READY"),
            ]
        )
        assert report["readiness_count"] == 2
        assert report["duplicate_readiness_count"] == 0


# ---------------------------------------------------------------------------
# Degraded / not-ready detection
# ---------------------------------------------------------------------------


class TestDegradedNotReadyDetection:
    def test_degraded_detected(self, engine):
        report = engine.create(
            readinesses=[
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "DEGRADED"),
                _rdy("ctx-2", "env-2", "res-2", "con-2", "cap-2", "READY"),
            ]
        )
        assert report["degraded_count"] == 1
        assert report["not_ready_count"] == 0

    def test_not_ready_detected(self, engine):
        report = engine.create(
            readinesses=[
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1",
                     "NOT_READY"),
                _rdy("ctx-2", "env-2", "res-2", "con-2", "cap-2", "READY"),
            ]
        )
        assert report["not_ready_count"] == 1
        assert report["degraded_count"] == 0


# ---------------------------------------------------------------------------
# Pass/fail
# ---------------------------------------------------------------------------


def _read_pass_fail(engine, report_id: str) -> dict:
    path = engine._report_dir / report_id / "pass_fail.json"
    return json.loads(path.read_text(encoding="utf-8"))


class TestPassFail:
    def test_pass_with_ready_records(self, engine):
        report = engine.create(
            readinesses=[
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "READY"),
                _rdy("ctx-2", "env-2", "res-2", "con-2", "cap-2", "UNKNOWN"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is True
        assert pf["readiness_count"] == 2
        assert pf["status"] == "passed"

    def test_empty_report_fails(self, engine):
        report = engine.create(readinesses=[])
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["readiness_count"] == 0
        assert pf["status"] == "failed"

    def test_degraded_fails(self, engine):
        report = engine.create(
            readinesses=[
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "DEGRADED")
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["degraded_count"] == 1

    def test_not_ready_fails(self, engine):
        report = engine.create(
            readinesses=[
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1",
                     "NOT_READY")
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["not_ready_count"] == 1

    def test_duplicate_does_not_fail_when_clean(self, engine):
        report = engine.create(
            readinesses=[
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "READY"),
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "READY"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["duplicate_readiness_count"] == 1
        assert pf["passed"] is True

    def test_evidence_bundle_files_written(self, engine):
        report = engine.create(
            readinesses=[
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "READY")
            ]
        )
        report_dir = engine._report_dir / report["report_id"]
        for name in (
            "execution_readiness_request.json",
            "execution_readiness_result.json",
            "execution_readiness_summary.md",
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
            readinesses=[
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "READY")
            ]
        )
        report_id = created["report_id"]
        appended = engine.append(
            report_id,
            readinesses=[
                _rdy("ctx-2", "env-2", "res-2", "con-2", "cap-2", "READY")
            ],
        )
        assert appended["report_id"] == report_id
        assert appended["readiness_count"] == 2
        caps = {r["capability_id"] for r in appended["readinesses"]}
        assert caps == {"cap-1", "cap-2"}

    def test_append_preserves_raw_metadata(self, engine):
        created = engine.create(
            readinesses=[
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "READY")
            ],
            raw_metadata={"origin": "p0"},
        )
        appended = engine.append(
            created["report_id"],
            readinesses=[
                _rdy("ctx-2", "env-2", "res-2", "con-2", "cap-2", "READY")
            ],
        )
        assert appended["raw_metadata"] == {"origin": "p0"}

    def test_append_missing_report_raises(self, engine):
        with pytest.raises(ValueError, match="Report not found"):
            engine.append("does-not-exist", readinesses=[])


# ---------------------------------------------------------------------------
# Retrieval / exports
# ---------------------------------------------------------------------------


class TestRetrievalExport:
    def test_get_report_round_trip(self, engine):
        created = engine.create(
            readinesses=[
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "READY")
            ]
        )
        loaded = engine.get_report(created["report_id"])
        assert loaded["report_id"] == created["report_id"]
        assert loaded["readiness_count"] == 1

    def test_get_missing_returns_none(self, engine):
        assert engine.get_report("missing-id") is None

    def test_list_reports_sorted(self, engine):
        engine.create(
            readinesses=[
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "READY")
            ]
        )
        engine.create(
            readinesses=[
                _rdy("ctx-2", "env-2", "res-2", "con-2", "cap-2", "READY")
            ]
        )
        assert len(engine.list_reports()) == 2

    def test_export_json_valid(self, engine):
        created = engine.create(
            readinesses=[
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "READY")
            ]
        )
        parsed = json.loads(
            engine.export_report(created["report_id"], fmt="json")
        )
        assert parsed["report_id"] == created["report_id"]

    def test_export_markdown_headings(self, engine):
        created = engine.create(
            readinesses=[
                _rdy(
                    "ctx-1",
                    "env-1",
                    "res-1",
                    "con-1",
                    "cap-122",
                    "READY",
                    checks=[_chk("CONTEXT_CHECK", "PASS")],
                )
            ]
        )
        out = engine.export_report(created["report_id"], fmt="markdown")
        assert "# Execution Readiness Report" in out
        assert "## Readiness Status Counts" in out
        assert "## Check Type Counts" in out
        assert "## Readinesses" in out
        assert "[READY]" in out
        assert "capability=cap-122" in out
        assert "[CONTEXT_CHECK] PASS" in out

    def test_export_csv_rows(self, engine):
        created = engine.create(
            readinesses=[
                _rdy(
                    "ctx-1",
                    "env-1",
                    "res-1",
                    "con-1",
                    "cap-1",
                    "READY",
                    checks=[_chk("CONTEXT_CHECK", "PASS")],
                ),
                _rdy("ctx-2", "env-2", "res-2", "con-2", "cap-2", "READY"),
            ]
        )
        out = engine.export_report(created["report_id"], fmt="csv")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        assert lines[0].startswith("record_kind,")
        # header + 2 readinesses + 1 check
        assert len(lines) == 4
        readiness_rows = [
            ln for ln in lines[1:] if ln.startswith("readiness,")
        ]
        check_rows = [ln for ln in lines[1:] if ln.startswith("check,")]
        assert len(readiness_rows) == 2
        assert len(check_rows) == 1

    def test_export_invalid_format_raises(self, engine):
        created = engine.create(
            readinesses=[
                _rdy("ctx-1", "env-1", "res-1", "con-1", "cap-1", "READY")
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
