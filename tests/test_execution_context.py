"""Tests for the Execution Context Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.execution_context import (
    ExecutionContext,
    ExecutionContextEngine,
    ExecutionContextEvidence,
    ExecutionContextReference,
    ExecutionContextReferenceType,
    ExecutionContextReport,
    ExecutionContextState,
    ExecutionContextType,
)


def _ctx(
    work_id: str,
    capability_id: str,
    context_type: str,
    state: str,
    **kw,
) -> dict:
    data = {
        "work_id": work_id,
        "capability_id": capability_id,
        "context_type": context_type,
        "state": state,
        "chain_id": kw.get("chain_id", ""),
        "summary": kw.get("summary", ""),
    }
    if "context_id" in kw:
        data["context_id"] = kw["context_id"]
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
    return ExecutionContextEngine(artifacts_root=str(tmp_path / "artifacts"))


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_reference_round_trip(self):
        r = ExecutionContextReference(
            reference_id="r-1",
            reference_type="CAPABILITY",
            reference_value="cap-122",
            summary="identity",
        )
        assert ExecutionContextReference.from_dict(r.to_dict()) == r

    def test_context_round_trip(self):
        c = ExecutionContext(
            context_id="c-1",
            work_id="w-1",
            capability_id="cap-1",
            chain_id="chain-1",
            context_type="IMPLEMENTATION",
            state="READY",
            references=[
                ExecutionContextReference(
                    reference_id="r-1",
                    reference_type="CHAIN",
                    reference_value="chain-1",
                )
            ],
            summary="impl",
            created_at="2026-01-01T00:00:00+00:00",
            raw_payload={"k": "v"},
        )
        assert ExecutionContext.from_dict(c.to_dict()) == c

    def test_context_gets_id_and_timestamp(self):
        c = ExecutionContext(
            work_id="w-1",
            capability_id="cap-1",
            context_type="IMPLEMENTATION",
            state="READY",
        )
        assert c.context_id
        assert c.created_at

    def test_report_defaults(self):
        report = ExecutionContextReport()
        assert report.report_id
        assert report.created_at
        assert report.context_count == 0
        assert report.schema_version == "1.0"

    def test_evidence_defaults(self):
        ev = ExecutionContextEvidence(report_id="rep-1")
        assert ev.evidence_id
        assert ev.created_at
        assert ev.report_id == "rep-1"

    def test_all_context_types_present(self):
        assert {t.value for t in ExecutionContextType} == {
            "IMPLEMENTATION",
            "VALIDATION",
            "REPAIR",
            "REVIEW",
            "REPORTING",
            "INVESTIGATION",
            "OTHER",
        }

    def test_all_states_present(self):
        assert {t.value for t in ExecutionContextState} == {
            "READY",
            "BLOCKED",
            "RUNNING",
            "COMPLETED",
            "FAILED",
            "UNKNOWN",
        }

    def test_all_reference_types_present(self):
        assert {t.value for t in ExecutionContextReferenceType} == {
            "CAPABILITY",
            "WORK_ITEM",
            "CHAIN",
            "FILE",
            "VALIDATION",
            "GRAPH_NODE",
            "GRAPH_EDGE",
            "ARTIFACT",
            "OTHER",
        }


# ---------------------------------------------------------------------------
# Create / determinism
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_counts(self, engine):
        report = engine.create(
            contexts=[
                _ctx("w-1", "cap-1", "IMPLEMENTATION", "READY"),
                _ctx("w-1", "cap-2", "VALIDATION", "COMPLETED"),
                _ctx("w-2", "cap-3", "REPAIR", "RUNNING"),
            ]
        )
        assert report["context_count"] == 3
        assert report["state_counts"] == {
            "COMPLETED": 1,
            "READY": 1,
            "RUNNING": 1,
        }
        assert report["context_type_counts"] == {
            "IMPLEMENTATION": 1,
            "REPAIR": 1,
            "VALIDATION": 1,
        }
        assert report["blocked_count"] == 0
        assert report["failed_count"] == 0

    def test_deterministic_ordering(self, engine):
        report = engine.create(
            contexts=[
                _ctx("w-2", "cap-1", "IMPLEMENTATION", "READY"),
                _ctx("w-1", "cap-2", "VALIDATION", "READY"),
                _ctx("w-1", "cap-1", "IMPLEMENTATION", "READY"),
            ]
        )
        order = [
            (c["work_id"], c["capability_id"], c["context_type"])
            for c in report["contexts"]
        ]
        assert order == [
            ("w-1", "cap-1", "IMPLEMENTATION"),
            ("w-1", "cap-2", "VALIDATION"),
            ("w-2", "cap-1", "IMPLEMENTATION"),
        ]

    def test_ordering_is_input_independent(self, engine):
        contexts = [
            _ctx("w-1", "cap-1", "IMPLEMENTATION", "READY"),
            _ctx("w-2", "cap-2", "VALIDATION", "RUNNING"),
            _ctx("w-3", "cap-3", "REPAIR", "COMPLETED"),
        ]
        r1 = engine.create(contexts=list(contexts))
        r2 = engine.create(contexts=list(reversed(contexts)))
        key = lambda rep: [  # noqa: E731
            (c["work_id"], c["capability_id"]) for c in rep["contexts"]
        ]
        assert key(r1) == key(r2)

    def test_references_ordered_deterministically(self, engine):
        report = engine.create(
            contexts=[
                _ctx(
                    "w-1",
                    "cap-1",
                    "IMPLEMENTATION",
                    "READY",
                    references=[
                        _ref("FILE", "src/z.py"),
                        _ref("CAPABILITY", "cap-122"),
                        _ref("CHAIN", "chain-1"),
                    ],
                )
            ]
        )
        order = [
            (r["reference_type"], r["reference_value"])
            for r in report["contexts"][0]["references"]
        ]
        assert order == [
            ("CAPABILITY", "cap-122"),
            ("CHAIN", "chain-1"),
            ("FILE", "src/z.py"),
        ]

    def test_schema_version_preserved(self, engine):
        report = engine.create(
            contexts=[_ctx("w-1", "cap-1", "IMPLEMENTATION", "READY")]
        )
        assert report["schema_version"] == "1.0"

    def test_raw_metadata_preserved(self, engine):
        report = engine.create(
            contexts=[_ctx("w-1", "cap-1", "IMPLEMENTATION", "READY")],
            raw_metadata={"source": "program-0"},
        )
        assert report["raw_metadata"] == {"source": "program-0"}

    def test_context_raw_payload_preserved(self, engine):
        report = engine.create(
            contexts=[
                _ctx(
                    "w-1",
                    "cap-1",
                    "IMPLEMENTATION",
                    "READY",
                    raw_payload={"nested": {"deep": [1, 2]}},
                )
            ]
        )
        assert report["contexts"][0]["raw_payload"] == {
            "nested": {"deep": [1, 2]}
        }

    def test_chain_id_preserved(self, engine):
        report = engine.create(
            contexts=[
                _ctx(
                    "w-1",
                    "cap-1",
                    "IMPLEMENTATION",
                    "READY",
                    chain_id="chain-9",
                )
            ]
        )
        assert report["contexts"][0]["chain_id"] == "chain-9"


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_context_type_normalized(self, engine):
        report = engine.create(
            contexts=[_ctx("w-1", "cap-1", "implementation", "READY")]
        )
        assert report["contexts"][0]["context_type"] == "IMPLEMENTATION"

    def test_state_normalized(self, engine):
        report = engine.create(
            contexts=[_ctx("w-1", "cap-1", "IMPLEMENTATION", "ready")]
        )
        assert report["contexts"][0]["state"] == "READY"

    def test_reference_type_normalized(self, engine):
        report = engine.create(
            contexts=[
                _ctx(
                    "w-1",
                    "cap-1",
                    "IMPLEMENTATION",
                    "READY",
                    references=[_ref("capability", "cap-122")],
                )
            ]
        )
        assert (
            report["contexts"][0]["references"][0]["reference_type"]
            == "CAPABILITY"
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_context_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid context_type"):
            engine.create(
                contexts=[_ctx("w-1", "cap-1", "NONSENSE", "READY")]
            )

    def test_invalid_state_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid state"):
            engine.create(
                contexts=[_ctx("w-1", "cap-1", "IMPLEMENTATION", "NOPE")]
            )

    def test_missing_work_id_rejected(self, engine):
        with pytest.raises(ValueError, match="work_id is required"):
            engine.create(
                contexts=[_ctx("", "cap-1", "IMPLEMENTATION", "READY")]
            )

    def test_missing_capability_id_rejected(self, engine):
        with pytest.raises(ValueError, match="capability_id is required"):
            engine.create(
                contexts=[_ctx("w-1", "", "IMPLEMENTATION", "READY")]
            )

    def test_missing_context_type_rejected(self, engine):
        with pytest.raises(ValueError, match="context_type is required"):
            engine.create(contexts=[_ctx("w-1", "cap-1", "", "READY")])

    def test_missing_state_rejected(self, engine):
        with pytest.raises(ValueError, match="state is required"):
            engine.create(
                contexts=[_ctx("w-1", "cap-1", "IMPLEMENTATION", "")]
            )

    def test_invalid_reference_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid reference_type"):
            engine.create(
                contexts=[
                    _ctx(
                        "w-1",
                        "cap-1",
                        "IMPLEMENTATION",
                        "READY",
                        references=[_ref("NONSENSE", "x")],
                    )
                ]
            )

    def test_missing_reference_value_rejected(self, engine):
        with pytest.raises(ValueError, match="reference_value is required"):
            engine.create(
                contexts=[
                    _ctx(
                        "w-1",
                        "cap-1",
                        "IMPLEMENTATION",
                        "READY",
                        references=[_ref("CAPABILITY", "")],
                    )
                ]
            )


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


class TestDuplicateDetection:
    def test_duplicate_context_deduped_and_counted(self, engine):
        report = engine.create(
            contexts=[
                _ctx("w-1", "cap-1", "IMPLEMENTATION", "READY"),
                _ctx("w-1", "cap-1", "implementation", "RUNNING"),
            ]
        )
        assert report["context_count"] == 1
        assert report["duplicate_context_count"] == 1

    def test_distinct_context_type_not_duplicate(self, engine):
        report = engine.create(
            contexts=[
                _ctx("w-1", "cap-1", "IMPLEMENTATION", "READY"),
                _ctx("w-1", "cap-1", "VALIDATION", "READY"),
            ]
        )
        assert report["context_count"] == 2
        assert report["duplicate_context_count"] == 0

    def test_distinct_chain_not_duplicate(self, engine):
        report = engine.create(
            contexts=[
                _ctx(
                    "w-1", "cap-1", "IMPLEMENTATION", "READY", chain_id="c-1"
                ),
                _ctx(
                    "w-1", "cap-1", "IMPLEMENTATION", "READY", chain_id="c-2"
                ),
            ]
        )
        assert report["context_count"] == 2
        assert report["duplicate_context_count"] == 0


# ---------------------------------------------------------------------------
# Blocked / failed detection
# ---------------------------------------------------------------------------


class TestBlockedFailedDetection:
    def test_blocked_detected(self, engine):
        report = engine.create(
            contexts=[
                _ctx("w-1", "cap-1", "IMPLEMENTATION", "BLOCKED"),
                _ctx("w-1", "cap-2", "VALIDATION", "READY"),
            ]
        )
        assert report["blocked_count"] == 1
        assert report["failed_count"] == 0

    def test_failed_detected(self, engine):
        report = engine.create(
            contexts=[
                _ctx("w-1", "cap-1", "IMPLEMENTATION", "FAILED"),
                _ctx("w-1", "cap-2", "VALIDATION", "COMPLETED"),
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
    def test_pass_with_clean_contexts(self, engine):
        report = engine.create(
            contexts=[
                _ctx("w-1", "cap-1", "IMPLEMENTATION", "READY"),
                _ctx("w-1", "cap-2", "VALIDATION", "COMPLETED"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is True
        assert pf["context_count"] == 2
        assert pf["status"] == "passed"

    def test_empty_report_fails(self, engine):
        report = engine.create(contexts=[])
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["context_count"] == 0
        assert pf["status"] == "failed"

    def test_blocked_fails(self, engine):
        report = engine.create(
            contexts=[_ctx("w-1", "cap-1", "IMPLEMENTATION", "BLOCKED")]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["blocked_count"] == 1

    def test_failed_fails(self, engine):
        report = engine.create(
            contexts=[_ctx("w-1", "cap-1", "IMPLEMENTATION", "FAILED")]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["failed_count"] == 1

    def test_duplicate_does_not_fail_when_clean(self, engine):
        report = engine.create(
            contexts=[
                _ctx("w-1", "cap-1", "IMPLEMENTATION", "READY"),
                _ctx("w-1", "cap-1", "IMPLEMENTATION", "READY"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["duplicate_context_count"] == 1
        assert pf["passed"] is True

    def test_evidence_bundle_files_written(self, engine):
        report = engine.create(
            contexts=[_ctx("w-1", "cap-1", "IMPLEMENTATION", "READY")]
        )
        report_dir = engine._report_dir / report["report_id"]
        for name in (
            "execution_context_request.json",
            "execution_context_result.json",
            "execution_context_summary.md",
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
            contexts=[_ctx("w-1", "cap-1", "IMPLEMENTATION", "READY")]
        )
        report_id = created["report_id"]
        appended = engine.append(
            report_id,
            contexts=[_ctx("w-1", "cap-2", "VALIDATION", "READY")],
        )
        assert appended["report_id"] == report_id
        assert appended["context_count"] == 2
        caps = {c["capability_id"] for c in appended["contexts"]}
        assert caps == {"cap-1", "cap-2"}

    def test_append_preserves_raw_metadata(self, engine):
        created = engine.create(
            contexts=[_ctx("w-1", "cap-1", "IMPLEMENTATION", "READY")],
            raw_metadata={"origin": "p0"},
        )
        appended = engine.append(
            created["report_id"],
            contexts=[_ctx("w-1", "cap-2", "VALIDATION", "READY")],
        )
        assert appended["raw_metadata"] == {"origin": "p0"}

    def test_append_missing_report_raises(self, engine):
        with pytest.raises(ValueError, match="Report not found"):
            engine.append("does-not-exist", contexts=[])


# ---------------------------------------------------------------------------
# Retrieval / exports
# ---------------------------------------------------------------------------


class TestRetrievalExport:
    def test_get_report_round_trip(self, engine):
        created = engine.create(
            contexts=[_ctx("w-1", "cap-1", "IMPLEMENTATION", "READY")]
        )
        loaded = engine.get_report(created["report_id"])
        assert loaded["report_id"] == created["report_id"]
        assert loaded["context_count"] == 1

    def test_get_missing_returns_none(self, engine):
        assert engine.get_report("missing-id") is None

    def test_list_reports_sorted(self, engine):
        engine.create(contexts=[_ctx("w-1", "cap-1", "IMPLEMENTATION", "READY")])
        engine.create(contexts=[_ctx("w-2", "cap-2", "VALIDATION", "READY")])
        assert len(engine.list_reports()) == 2

    def test_export_json_valid(self, engine):
        created = engine.create(
            contexts=[_ctx("w-1", "cap-1", "IMPLEMENTATION", "READY")]
        )
        parsed = json.loads(
            engine.export_report(created["report_id"], fmt="json")
        )
        assert parsed["report_id"] == created["report_id"]

    def test_export_markdown_headings(self, engine):
        created = engine.create(
            contexts=[
                _ctx(
                    "w-1",
                    "cap-122",
                    "IMPLEMENTATION",
                    "READY",
                    references=[_ref("CHAIN", "chain-1")],
                )
            ]
        )
        out = engine.export_report(created["report_id"], fmt="markdown")
        assert "# Execution Context Report" in out
        assert "## State Counts" in out
        assert "## Context Type Counts" in out
        assert "## Contexts" in out
        assert "[READY]" in out
        assert "[IMPLEMENTATION]" in out
        assert "capability=cap-122" in out
        assert "[CHAIN] chain-1" in out

    def test_export_csv_rows(self, engine):
        created = engine.create(
            contexts=[
                _ctx(
                    "w-1",
                    "cap-1",
                    "IMPLEMENTATION",
                    "READY",
                    references=[_ref("CHAIN", "chain-1")],
                ),
                _ctx("w-1", "cap-2", "VALIDATION", "COMPLETED"),
            ]
        )
        out = engine.export_report(created["report_id"], fmt="csv")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        assert lines[0].startswith("record_kind,")
        # header + 2 contexts + 1 reference
        assert len(lines) == 4
        context_rows = [ln for ln in lines[1:] if ln.startswith("context,")]
        reference_rows = [
            ln for ln in lines[1:] if ln.startswith("reference,")
        ]
        assert len(context_rows) == 2
        assert len(reference_rows) == 1

    def test_export_invalid_format_raises(self, engine):
        created = engine.create(
            contexts=[_ctx("w-1", "cap-1", "IMPLEMENTATION", "READY")]
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
