"""Tests for the Capability Relationship Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.capability_relationship import (
    CapabilityRelationship,
    CapabilityRelationshipEngine,
    CapabilityRelationshipEvidence,
    CapabilityRelationshipReference,
    CapabilityRelationshipReport,
    CapabilityRelationshipType,
)


def _rel(source: str, target: str, rel_type: str, **kw) -> dict:
    data = {
        "source_capability_id": source,
        "target_capability_id": target,
        "relationship_type": rel_type,
        "confidence": kw.get("confidence", 1.0),
        "summary": kw.get("summary", f"{source}->{target}"),
    }
    if "created_at" in kw:
        data["created_at"] = kw["created_at"]
    if "relationship_id" in kw:
        data["relationship_id"] = kw["relationship_id"]
    if "raw_payload" in kw:
        data["raw_payload"] = kw["raw_payload"]
    return data


@pytest.fixture
def engine(tmp_path):
    return CapabilityRelationshipEngine(
        artifacts_root=str(tmp_path / "artifacts")
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_relationship_round_trip(self):
        r = CapabilityRelationship(
            relationship_id="r-1",
            source_capability_id="cap-122",
            target_capability_id="cap-123",
            relationship_type="BUILDS_ON",
            confidence=0.9,
            summary="timeline builds on registry",
            created_at="2026-01-01T00:00:00+00:00",
            raw_payload={"k": "v"},
        )
        restored = CapabilityRelationship.from_dict(r.to_dict())
        assert restored == r

    def test_relationship_gets_id_and_timestamp(self):
        r = CapabilityRelationship(
            source_capability_id="a", target_capability_id="b"
        )
        assert r.relationship_id
        assert r.created_at

    def test_reference_round_trip(self):
        ref = CapabilityRelationshipReference(
            reference_id="ref-1",
            source_capability_id="a",
            target_capability_id="b",
            relationship_type="ENABLES",
        )
        assert ref.to_dict()["relationship_type"] == "ENABLES"

    def test_reference_gets_id(self):
        ref = CapabilityRelationshipReference(
            source_capability_id="a", target_capability_id="b"
        )
        assert ref.reference_id

    def test_report_defaults(self):
        report = CapabilityRelationshipReport()
        assert report.report_id
        assert report.created_at
        assert report.relationship_count == 0
        assert report.schema_version == "1.0"

    def test_evidence_defaults(self):
        ev = CapabilityRelationshipEvidence(report_id="rep-1")
        assert ev.evidence_id
        assert ev.created_at
        assert ev.report_id == "rep-1"

    def test_all_relationship_types_present(self):
        assert {t.value for t in CapabilityRelationshipType} == {
            "BUILDS_ON",
            "ENABLES",
            "RELATED_TO",
            "DEPENDS_ON",
            "SUPERSEDES",
            "DERIVED_FROM",
            "AFFECTS",
            "VALIDATES",
            "REPAIRS",
        }


# ---------------------------------------------------------------------------
# Create / determinism
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_counts(self, engine):
        report = engine.create(
            relationships=[
                _rel("cap-123", "cap-122", "BUILDS_ON"),
                _rel("cap-124", "cap-122", "DEPENDS_ON"),
            ]
        )
        assert report["relationship_count"] == 2
        assert report["relationship_type_counts"] == {
            "BUILDS_ON": 1,
            "DEPENDS_ON": 1,
        }

    def test_deterministic_ordering(self, engine):
        # Adversarial input order; expected sorted by (source, target, type).
        report = engine.create(
            relationships=[
                _rel("cap-126", "cap-125", "BUILDS_ON"),
                _rel("cap-122", "cap-121", "ENABLES"),
                _rel("cap-124", "cap-122", "DEPENDS_ON"),
                _rel("cap-122", "cap-121", "AFFECTS"),
            ]
        )
        order = [
            (
                r["source_capability_id"],
                r["target_capability_id"],
                r["relationship_type"],
            )
            for r in report["relationships"]
        ]
        assert order == [
            ("cap-122", "cap-121", "AFFECTS"),
            ("cap-122", "cap-121", "ENABLES"),
            ("cap-124", "cap-122", "DEPENDS_ON"),
            ("cap-126", "cap-125", "BUILDS_ON"),
        ]

    def test_ordering_is_input_independent(self, engine):
        rels = [
            _rel("a", "b", "ENABLES"),
            _rel("c", "d", "BUILDS_ON"),
            _rel("a", "c", "RELATED_TO"),
        ]
        r1 = engine.create(relationships=list(rels))
        r2 = engine.create(relationships=list(reversed(rels)))
        key = lambda rep: [  # noqa: E731
            (
                x["source_capability_id"],
                x["target_capability_id"],
                x["relationship_type"],
            )
            for x in rep["relationships"]
        ]
        assert key(r1) == key(r2)

    def test_raw_payload_preserved(self, engine):
        report = engine.create(
            relationships=[
                _rel(
                    "a",
                    "b",
                    "BUILDS_ON",
                    raw_payload={"nested": {"deep": [1, 2, 3]}},
                )
            ],
            raw_metadata={"source": "program-0"},
        )
        assert report["relationships"][0]["raw_payload"] == {
            "nested": {"deep": [1, 2, 3]}
        }
        assert report["raw_metadata"] == {"source": "program-0"}

    def test_schema_version_preserved(self, engine):
        report = engine.create(
            relationships=[_rel("a", "b", "BUILDS_ON")]
        )
        assert report["schema_version"] == "1.0"
        assert report["relationships"][0]["schema_version"] == "1.0"

    def test_references_projection_built(self, engine):
        report = engine.create(
            relationships=[_rel("a", "b", "ENABLES")]
        )
        assert len(report["references"]) == 1
        ref = report["references"][0]
        assert ref["source_capability_id"] == "a"
        assert ref["target_capability_id"] == "b"
        assert ref["relationship_type"] == "ENABLES"
        assert ref["reference_id"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_type_normalized_to_uppercase(self, engine):
        report = engine.create(
            relationships=[_rel("a", "b", "builds_on")]
        )
        assert report["relationships"][0]["relationship_type"] == "BUILDS_ON"

    def test_invalid_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid relationship_type"):
            engine.create(relationships=[_rel("a", "b", "NONSENSE")])

    def test_missing_source_rejected(self, engine):
        with pytest.raises(ValueError, match="source_capability_id"):
            engine.create(relationships=[_rel("", "b", "BUILDS_ON")])

    def test_missing_target_rejected(self, engine):
        with pytest.raises(ValueError, match="target_capability_id"):
            engine.create(relationships=[_rel("a", "", "BUILDS_ON")])

    def test_missing_type_rejected(self, engine):
        with pytest.raises(ValueError, match="relationship_type is required"):
            engine.create(relationships=[_rel("a", "b", "")])

    def test_confidence_clamped(self, engine):
        report = engine.create(
            relationships=[
                _rel("a", "b", "BUILDS_ON", confidence=5.0),
                _rel("a", "c", "BUILDS_ON", confidence=-3.0),
            ]
        )
        confidences = sorted(
            r["confidence"] for r in report["relationships"]
        )
        assert confidences == [0.0, 1.0]

    def test_non_numeric_confidence_rejected(self, engine):
        with pytest.raises(ValueError, match="confidence must be a number"):
            engine.create(
                relationships=[_rel("a", "b", "BUILDS_ON", confidence="hi")]
            )


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


class TestDuplicates:
    def test_duplicate_edges_deduped_and_counted(self, engine):
        report = engine.create(
            relationships=[
                _rel("a", "b", "BUILDS_ON"),
                _rel("a", "b", "BUILDS_ON"),
                _rel("a", "b", "BUILDS_ON"),
            ]
        )
        assert report["relationship_count"] == 1
        assert report["duplicate_relationship_count"] == 2

    def test_duplicate_differs_by_type_not_duplicate(self, engine):
        report = engine.create(
            relationships=[
                _rel("a", "b", "BUILDS_ON"),
                _rel("a", "b", "ENABLES"),
            ]
        )
        assert report["relationship_count"] == 2
        assert report["duplicate_relationship_count"] == 0

    def test_duplicates_fail_pass_fail(self, engine):
        report = engine.create(
            relationships=[
                _rel("a", "b", "BUILDS_ON"),
                _rel("a", "b", "BUILDS_ON"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["duplicate_relationship_count"] == 1
        assert pf["status"] == "failed"


# ---------------------------------------------------------------------------
# Orphan detection
# ---------------------------------------------------------------------------


class TestOrphans:
    def test_orphan_detected(self, engine):
        report = engine.create(
            relationships=[_rel("a", "b", "BUILDS_ON")],
            known_capability_ids=["a", "b", "c", "d"],
        )
        assert report["orphan_capability_ids"] == ["c", "d"]
        assert report["orphan_capability_count"] == 2

    def test_no_orphans_when_all_connected(self, engine):
        report = engine.create(
            relationships=[
                _rel("a", "b", "BUILDS_ON"),
                _rel("b", "c", "ENABLES"),
            ],
            known_capability_ids=["a", "b", "c"],
        )
        assert report["orphan_capability_count"] == 0

    def test_orphans_empty_without_known_ids(self, engine):
        report = engine.create(
            relationships=[_rel("a", "b", "BUILDS_ON")]
        )
        assert report["orphan_capability_count"] == 0

    def test_known_ids_deduped_and_sorted(self, engine):
        report = engine.create(
            relationships=[_rel("a", "b", "BUILDS_ON")],
            known_capability_ids=["z", "a", "z", "m"],
        )
        assert report["known_capability_ids"] == ["a", "m", "z"]


# ---------------------------------------------------------------------------
# Pass/fail
# ---------------------------------------------------------------------------


def _read_pass_fail(engine, report_id: str) -> dict:
    path = (
        engine._report_dir / report_id / "pass_fail.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


class TestPassFail:
    def test_pass_with_relationships(self, engine):
        report = engine.create(
            relationships=[_rel("a", "b", "BUILDS_ON")]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is True
        assert pf["relationship_count"] == 1

    def test_empty_report_fails(self, engine):
        report = engine.create(relationships=[])
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["relationship_count"] == 0

    def test_evidence_bundle_files_written(self, engine):
        report = engine.create(
            relationships=[_rel("a", "b", "BUILDS_ON")]
        )
        report_dir = engine._report_dir / report["report_id"]
        for name in (
            "capability_relationship_request.json",
            "capability_relationship_result.json",
            "capability_relationship_summary.md",
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
            relationships=[_rel("a", "b", "BUILDS_ON")]
        )
        report_id = created["report_id"]
        appended = engine.append(
            report_id,
            relationships=[_rel("b", "c", "ENABLES")],
        )
        assert appended["report_id"] == report_id
        assert appended["relationship_count"] == 2
        edges = {
            (r["source_capability_id"], r["target_capability_id"])
            for r in appended["relationships"]
        }
        assert edges == {("a", "b"), ("b", "c")}

    def test_append_merges_known_ids(self, engine):
        created = engine.create(
            relationships=[_rel("a", "b", "BUILDS_ON")],
            known_capability_ids=["a", "b", "c"],
        )
        appended = engine.append(
            created["report_id"],
            relationships=[_rel("b", "c", "ENABLES")],
            known_capability_ids=["d"],
        )
        assert appended["orphan_capability_ids"] == ["d"]

    def test_append_missing_report_raises(self, engine):
        with pytest.raises(ValueError, match="Report not found"):
            engine.append("does-not-exist", relationships=[])


# ---------------------------------------------------------------------------
# Retrieval / exports
# ---------------------------------------------------------------------------


class TestRetrievalExport:
    def test_get_report_round_trip(self, engine):
        created = engine.create(
            relationships=[_rel("a", "b", "BUILDS_ON")]
        )
        loaded = engine.get_report(created["report_id"])
        assert loaded["report_id"] == created["report_id"]
        assert loaded["relationship_count"] == 1

    def test_get_missing_returns_none(self, engine):
        assert engine.get_report("missing-id") is None

    def test_list_reports_sorted(self, engine):
        engine.create(
            relationships=[_rel("a", "b", "BUILDS_ON")],
            raw_metadata={"created_at": "x"},
        )
        engine.create(relationships=[_rel("c", "d", "ENABLES")])
        reports = engine.list_reports()
        assert len(reports) == 2

    def test_export_json_valid(self, engine):
        created = engine.create(
            relationships=[_rel("a", "b", "BUILDS_ON")]
        )
        out = engine.export_report(created["report_id"], fmt="json")
        parsed = json.loads(out)
        assert parsed["report_id"] == created["report_id"]

    def test_export_markdown_headings(self, engine):
        created = engine.create(
            relationships=[_rel("a", "b", "BUILDS_ON")],
            known_capability_ids=["a", "b", "c"],
        )
        out = engine.export_report(created["report_id"], fmt="markdown")
        assert "# Capability Relationship Report" in out
        assert "## Relationship Type Counts" in out
        assert "## Relationships" in out
        assert "## Orphan Capabilities" in out
        assert "--[BUILDS_ON]-->" in out

    def test_export_csv_rows(self, engine):
        created = engine.create(
            relationships=[
                _rel("a", "b", "BUILDS_ON"),
                _rel("a", "c", "ENABLES"),
            ]
        )
        out = engine.export_report(created["report_id"], fmt="csv")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        assert lines[0].startswith("source_capability_id,")
        assert len(lines) == 3

    def test_export_invalid_format_raises(self, engine):
        created = engine.create(
            relationships=[_rel("a", "b", "BUILDS_ON")]
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
