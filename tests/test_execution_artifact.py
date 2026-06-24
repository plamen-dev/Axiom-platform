"""Tests for the Execution Artifact Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.execution_artifact import (
    ExecutionArtifact,
    ExecutionArtifactEngine,
    ExecutionArtifactEvidence,
    ExecutionArtifactReference,
    ExecutionArtifactReferenceType,
    ExecutionArtifactReport,
    ExecutionArtifactStatus,
    ExecutionArtifactType,
)


def _artifact(
    result_id: str,
    attempt_id: str,
    capability_id: str,
    artifact_type: str,
    status: str,
    **kw,
) -> dict:
    data = {
        "result_id": result_id,
        "attempt_id": attempt_id,
        "capability_id": capability_id,
        "artifact_type": artifact_type,
        "status": status,
        "summary": kw.get("summary", ""),
    }
    for k in (
        "artifact_id",
        "artifact_path",
        "artifact_url",
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
    return ExecutionArtifactEngine(artifacts_root=str(tmp_path / "artifacts"))


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_reference_round_trip(self):
        r = ExecutionArtifactReference(
            reference_id="r-1",
            reference_type="RESULT",
            reference_value="res-9",
            summary="result ref",
        )
        assert ExecutionArtifactReference.from_dict(r.to_dict()) == r

    def test_artifact_round_trip(self):
        a = ExecutionArtifact(
            artifact_id="art-1",
            result_id="res-1",
            attempt_id="att-1",
            capability_id="cap-1",
            artifact_type="FILE",
            status="CREATED",
            artifact_path="out/file.txt",
            artifact_url="https://example/file",
            references=[
                ExecutionArtifactReference(
                    reference_id="r-1",
                    reference_type="RESULT",
                    reference_value="res-9",
                )
            ],
            summary="created",
            created_at="2026-01-01T00:00:00+00:00",
            raw_payload={"k": "v"},
        )
        assert ExecutionArtifact.from_dict(a.to_dict()) == a

    def test_artifact_gets_id_and_timestamp(self):
        a = ExecutionArtifact(
            result_id="res-1",
            attempt_id="att-1",
            capability_id="cap-1",
            artifact_type="FILE",
            status="CREATED",
        )
        assert a.artifact_id
        assert a.created_at

    def test_report_defaults(self):
        report = ExecutionArtifactReport()
        assert report.report_id
        assert report.created_at
        assert report.artifact_count == 0
        assert report.missing_count == 0
        assert report.invalid_count == 0
        assert report.created_count == 0
        assert report.referenced_count == 0
        assert report.schema_version == "1.0"

    def test_evidence_defaults(self):
        ev = ExecutionArtifactEvidence(report_id="rep-1")
        assert ev.evidence_id
        assert ev.created_at
        assert ev.report_id == "rep-1"

    def test_all_artifact_types_present(self):
        assert {t.value for t in ExecutionArtifactType} == {
            "FILE",
            "REPORT",
            "LOG",
            "SCREENSHOT",
            "RECORDING",
            "EVIDENCE_BUNDLE",
            "TEST_OUTPUT",
            "PR_COMMENT",
            "OTHER",
        }

    def test_all_statuses_present(self):
        assert {t.value for t in ExecutionArtifactStatus} == {
            "CREATED",
            "REFERENCED",
            "MISSING",
            "INVALID",
            "UNKNOWN",
        }

    def test_all_reference_types_present(self):
        assert {t.value for t in ExecutionArtifactReferenceType} == {
            "RESULT",
            "ATTEMPT",
            "CAPABILITY",
            "FILE",
            "URL",
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
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "FILE", "CREATED"),
                _artifact("res-2", "att-2", "cap-2", "REPORT", "REFERENCED"),
                _artifact("res-3", "att-3", "cap-3", "LOG", "UNKNOWN"),
            ]
        )
        assert report["artifact_count"] == 3
        assert report["status_counts"] == {
            "CREATED": 1,
            "REFERENCED": 1,
            "UNKNOWN": 1,
        }
        assert report["artifact_type_counts"] == {
            "FILE": 1,
            "LOG": 1,
            "REPORT": 1,
        }
        assert report["missing_count"] == 0
        assert report["invalid_count"] == 0
        assert report["created_count"] == 1
        assert report["referenced_count"] == 1

    def test_deterministic_ordering(self, engine):
        report = engine.create(
            artifacts=[
                _artifact("res-2", "att-1", "cap-1", "FILE", "CREATED"),
                _artifact("res-1", "att-2", "cap-2", "FILE", "CREATED"),
                _artifact("res-1", "att-1", "cap-1", "FILE", "CREATED"),
            ]
        )
        order = [
            (a["result_id"], a["attempt_id"], a["capability_id"])
            for a in report["artifacts"]
        ]
        assert order == [
            ("res-1", "att-1", "cap-1"),
            ("res-1", "att-2", "cap-2"),
            ("res-2", "att-1", "cap-1"),
        ]

    def test_ordering_is_input_independent(self, engine):
        artifacts = [
            _artifact("res-1", "att-1", "cap-1", "FILE", "CREATED"),
            _artifact("res-2", "att-2", "cap-2", "FILE", "CREATED"),
            _artifact("res-3", "att-3", "cap-3", "FILE", "CREATED"),
        ]
        r1 = engine.create(artifacts=list(artifacts))
        r2 = engine.create(artifacts=list(reversed(artifacts)))
        key = lambda rep: [  # noqa: E731
            (a["result_id"], a["attempt_id"]) for a in rep["artifacts"]
        ]
        assert key(r1) == key(r2)

    def test_references_ordered_deterministically(self, engine):
        report = engine.create(
            artifacts=[
                _artifact(
                    "res-1",
                    "att-1",
                    "cap-1",
                    "FILE",
                    "CREATED",
                    references=[
                        _ref("URL", "u-9"),
                        _ref("ATTEMPT", "att-9"),
                        _ref("RESULT", "res-9"),
                    ],
                )
            ]
        )
        order = [
            (r["reference_type"], r["reference_value"])
            for r in report["artifacts"][0]["references"]
        ]
        assert order == [
            ("ATTEMPT", "att-9"),
            ("RESULT", "res-9"),
            ("URL", "u-9"),
        ]

    def test_schema_version_preserved(self, engine):
        report = engine.create(
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "FILE", "CREATED")
            ]
        )
        assert report["schema_version"] == "1.0"

    def test_raw_metadata_preserved(self, engine):
        report = engine.create(
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "FILE", "CREATED")
            ],
            raw_metadata={"source": "program-0"},
        )
        assert report["raw_metadata"] == {"source": "program-0"}

    def test_artifact_raw_payload_preserved(self, engine):
        report = engine.create(
            artifacts=[
                _artifact(
                    "res-1",
                    "att-1",
                    "cap-1",
                    "FILE",
                    "CREATED",
                    raw_payload={"nested": {"deep": [1, 2]}},
                )
            ]
        )
        assert report["artifacts"][0]["raw_payload"] == {
            "nested": {"deep": [1, 2]}
        }

    def test_path_and_url_preserved(self, engine):
        report = engine.create(
            artifacts=[
                _artifact(
                    "res-1",
                    "att-1",
                    "cap-1",
                    "RECORDING",
                    "CREATED",
                    artifact_path="out/rec.mp4",
                    artifact_url="https://example/rec",
                )
            ]
        )
        a = report["artifacts"][0]
        assert a["artifact_path"] == "out/rec.mp4"
        assert a["artifact_url"] == "https://example/rec"


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_status_normalized(self, engine):
        report = engine.create(
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "FILE", "created")
            ]
        )
        assert report["artifacts"][0]["status"] == "CREATED"

    def test_artifact_type_normalized(self, engine):
        report = engine.create(
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "file", "CREATED")
            ]
        )
        assert report["artifacts"][0]["artifact_type"] == "FILE"

    def test_reference_type_normalized(self, engine):
        report = engine.create(
            artifacts=[
                _artifact(
                    "res-1",
                    "att-1",
                    "cap-1",
                    "FILE",
                    "CREATED",
                    references=[_ref("result", "res-9")],
                )
            ]
        )
        assert (
            report["artifacts"][0]["references"][0]["reference_type"]
            == "RESULT"
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_status_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid status"):
            engine.create(
                artifacts=[
                    _artifact("res-1", "att-1", "cap-1", "FILE", "NONSENSE")
                ]
            )

    def test_invalid_artifact_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid artifact_type"):
            engine.create(
                artifacts=[
                    _artifact("res-1", "att-1", "cap-1", "NOPE", "CREATED")
                ]
            )

    def test_missing_result_id_rejected(self, engine):
        with pytest.raises(ValueError, match="result_id is required"):
            engine.create(
                artifacts=[
                    _artifact("", "att-1", "cap-1", "FILE", "CREATED")
                ]
            )

    def test_missing_attempt_id_rejected(self, engine):
        with pytest.raises(ValueError, match="attempt_id is required"):
            engine.create(
                artifacts=[
                    _artifact("res-1", "", "cap-1", "FILE", "CREATED")
                ]
            )

    def test_missing_capability_id_rejected(self, engine):
        with pytest.raises(ValueError, match="capability_id is required"):
            engine.create(
                artifacts=[
                    _artifact("res-1", "att-1", "", "FILE", "CREATED")
                ]
            )

    def test_missing_artifact_type_rejected(self, engine):
        with pytest.raises(ValueError, match="artifact_type is required"):
            engine.create(
                artifacts=[
                    _artifact("res-1", "att-1", "cap-1", "", "CREATED")
                ]
            )

    def test_missing_status_rejected(self, engine):
        with pytest.raises(ValueError, match="status is required"):
            engine.create(
                artifacts=[
                    _artifact("res-1", "att-1", "cap-1", "FILE", "")
                ]
            )

    def test_invalid_reference_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid reference_type"):
            engine.create(
                artifacts=[
                    _artifact(
                        "res-1",
                        "att-1",
                        "cap-1",
                        "FILE",
                        "CREATED",
                        references=[_ref("NONSENSE", "x")],
                    )
                ]
            )

    def test_missing_reference_value_rejected(self, engine):
        with pytest.raises(ValueError, match="reference_value is required"):
            engine.create(
                artifacts=[
                    _artifact(
                        "res-1",
                        "att-1",
                        "cap-1",
                        "FILE",
                        "CREATED",
                        references=[_ref("RESULT", "")],
                    )
                ]
            )


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


class TestDuplicateDetection:
    def test_duplicate_artifact_deduped_and_counted(self, engine):
        report = engine.create(
            artifacts=[
                _artifact(
                    "res-1", "att-1", "cap-1", "FILE", "CREATED",
                    artifact_path="out/a.txt",
                ),
                _artifact(
                    "res-1", "att-1", "cap-1", "FILE", "MISSING",
                    artifact_path="out/a.txt",
                ),
            ]
        )
        assert report["artifact_count"] == 1
        assert report["duplicate_artifact_count"] == 1

    def test_distinct_artifact_type_not_duplicate(self, engine):
        report = engine.create(
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "FILE", "CREATED"),
                _artifact("res-1", "att-1", "cap-1", "REPORT", "CREATED"),
            ]
        )
        assert report["artifact_count"] == 2
        assert report["duplicate_artifact_count"] == 0

    def test_distinct_path_not_duplicate(self, engine):
        report = engine.create(
            artifacts=[
                _artifact(
                    "res-1", "att-1", "cap-1", "FILE", "CREATED",
                    artifact_path="out/a.txt",
                ),
                _artifact(
                    "res-1", "att-1", "cap-1", "FILE", "CREATED",
                    artifact_path="out/b.txt",
                ),
            ]
        )
        assert report["artifact_count"] == 2
        assert report["duplicate_artifact_count"] == 0

    def test_distinct_result_not_duplicate(self, engine):
        report = engine.create(
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "FILE", "CREATED"),
                _artifact("res-2", "att-1", "cap-1", "FILE", "CREATED"),
            ]
        )
        assert report["artifact_count"] == 2
        assert report["duplicate_artifact_count"] == 0


# ---------------------------------------------------------------------------
# Missing / invalid / created / referenced detection
# ---------------------------------------------------------------------------


class TestMissingInvalidDetection:
    def test_missing_detected(self, engine):
        report = engine.create(
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "FILE", "MISSING"),
                _artifact("res-2", "att-2", "cap-2", "FILE", "CREATED"),
            ]
        )
        assert report["missing_count"] == 1
        assert report["invalid_count"] == 0

    def test_invalid_detected(self, engine):
        report = engine.create(
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "FILE", "INVALID"),
                _artifact("res-2", "att-2", "cap-2", "FILE", "CREATED"),
            ]
        )
        assert report["invalid_count"] == 1
        assert report["missing_count"] == 0

    def test_created_and_referenced_counted(self, engine):
        report = engine.create(
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "FILE", "CREATED"),
                _artifact("res-2", "att-2", "cap-2", "FILE", "REFERENCED"),
            ]
        )
        assert report["created_count"] == 1
        assert report["referenced_count"] == 1


# ---------------------------------------------------------------------------
# Pass/fail
# ---------------------------------------------------------------------------


def _read_pass_fail(engine, report_id: str) -> dict:
    path = engine._report_dir / report_id / "pass_fail.json"
    return json.loads(path.read_text(encoding="utf-8"))


class TestPassFail:
    def test_pass_with_clean_artifacts(self, engine):
        report = engine.create(
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "FILE", "CREATED"),
                _artifact("res-2", "att-2", "cap-2", "FILE", "REFERENCED"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is True
        assert pf["artifact_count"] == 2
        assert pf["status"] == "passed"

    def test_empty_report_fails(self, engine):
        report = engine.create(artifacts=[])
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["artifact_count"] == 0
        assert pf["status"] == "failed"

    def test_missing_fails(self, engine):
        report = engine.create(
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "FILE", "MISSING")
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["missing_count"] == 1

    def test_invalid_fails(self, engine):
        report = engine.create(
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "FILE", "INVALID")
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["invalid_count"] == 1

    def test_referenced_does_not_fail(self, engine):
        report = engine.create(
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "FILE", "REFERENCED"),
                _artifact("res-2", "att-2", "cap-2", "FILE", "CREATED"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is True

    def test_unknown_does_not_fail(self, engine):
        report = engine.create(
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "FILE", "UNKNOWN"),
                _artifact("res-2", "att-2", "cap-2", "FILE", "CREATED"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is True

    def test_duplicate_does_not_fail_when_clean(self, engine):
        report = engine.create(
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "FILE", "CREATED"),
                _artifact("res-1", "att-1", "cap-1", "FILE", "CREATED"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["duplicate_artifact_count"] == 1
        assert pf["passed"] is True

    def test_evidence_bundle_files_written(self, engine):
        report = engine.create(
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "FILE", "CREATED")
            ]
        )
        report_dir = engine._report_dir / report["report_id"]
        for name in (
            "execution_artifact_request.json",
            "execution_artifact_result.json",
            "execution_artifact_summary.md",
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
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "FILE", "CREATED")
            ]
        )
        report_id = created["report_id"]
        appended = engine.append(
            report_id,
            artifacts=[
                _artifact("res-2", "att-2", "cap-2", "FILE", "CREATED")
            ],
        )
        assert appended["report_id"] == report_id
        assert appended["artifact_count"] == 2
        results = {a["result_id"] for a in appended["artifacts"]}
        assert results == {"res-1", "res-2"}

    def test_append_preserves_raw_metadata(self, engine):
        created = engine.create(
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "FILE", "CREATED")
            ],
            raw_metadata={"origin": "p0"},
        )
        appended = engine.append(
            created["report_id"],
            artifacts=[
                _artifact("res-2", "att-2", "cap-2", "FILE", "CREATED")
            ],
        )
        assert appended["raw_metadata"] == {"origin": "p0"}

    def test_append_missing_report_raises(self, engine):
        with pytest.raises(ValueError, match="Report not found"):
            engine.append("does-not-exist", artifacts=[])


# ---------------------------------------------------------------------------
# Retrieval / exports
# ---------------------------------------------------------------------------


class TestRetrievalExport:
    def test_get_report_round_trip(self, engine):
        created = engine.create(
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "FILE", "CREATED")
            ]
        )
        loaded = engine.get_report(created["report_id"])
        assert loaded["report_id"] == created["report_id"]
        assert loaded["artifact_count"] == 1

    def test_get_missing_returns_none(self, engine):
        assert engine.get_report("missing-id") is None

    def test_list_reports_sorted(self, engine):
        engine.create(
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "FILE", "CREATED")
            ]
        )
        engine.create(
            artifacts=[
                _artifact("res-2", "att-2", "cap-2", "FILE", "CREATED")
            ]
        )
        assert len(engine.list_reports()) == 2

    def test_export_json_valid(self, engine):
        created = engine.create(
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "FILE", "CREATED")
            ]
        )
        parsed = json.loads(
            engine.export_report(created["report_id"], fmt="json")
        )
        assert parsed["report_id"] == created["report_id"]

    def test_export_markdown_headings(self, engine):
        created = engine.create(
            artifacts=[
                _artifact(
                    "res-1",
                    "att-1",
                    "cap-122",
                    "LOG",
                    "MISSING",
                    artifact_path="out/run.log",
                    references=[_ref("RESULT", "res-9")],
                )
            ]
        )
        out = engine.export_report(created["report_id"], fmt="markdown")
        assert "# Execution Artifact Report" in out
        assert "## Status Counts" in out
        assert "## Artifact Type Counts" in out
        assert "## Artifacts" in out
        assert "[MISSING]" in out
        assert "[LOG]" in out
        assert "capability=cap-122" in out
        assert "location=out/run.log" in out
        assert "[RESULT] res-9" in out

    def test_export_csv_rows(self, engine):
        created = engine.create(
            artifacts=[
                _artifact(
                    "res-1",
                    "att-1",
                    "cap-1",
                    "FILE",
                    "CREATED",
                    references=[_ref("RESULT", "res-9")],
                ),
                _artifact("res-2", "att-2", "cap-2", "FILE", "CREATED"),
            ]
        )
        out = engine.export_report(created["report_id"], fmt="csv")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        assert lines[0].startswith("record_kind,")
        # header + 2 artifacts + 1 reference
        assert len(lines) == 4
        artifact_rows = [
            ln for ln in lines[1:] if ln.startswith("artifact,")
        ]
        reference_rows = [
            ln for ln in lines[1:] if ln.startswith("reference,")
        ]
        assert len(artifact_rows) == 2
        assert len(reference_rows) == 1

    def test_export_invalid_format_raises(self, engine):
        created = engine.create(
            artifacts=[
                _artifact("res-1", "att-1", "cap-1", "FILE", "CREATED")
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
