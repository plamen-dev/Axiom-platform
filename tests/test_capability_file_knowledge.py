"""Tests for the Capability File Knowledge Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.capability_file_knowledge import (
    CapabilityFileKnowledge,
    CapabilityFileKnowledgeEngine,
    CapabilityFileKnowledgeEvidence,
    CapabilityFileKnowledgeReport,
    CapabilityFileReference,
    CapabilityFileRelationship,
    CapabilityFileRelationshipType,
)


def _rel(capability_id: str, file_path: str, rel_type: str, **kw) -> dict:
    data = {
        "capability_id": capability_id,
        "file_path": file_path,
        "relationship_type": rel_type,
        "summary": kw.get("summary", f"{rel_type} {file_path}"),
    }
    if "relationship_id" in kw:
        data["relationship_id"] = kw["relationship_id"]
    return data


def _ref(capability_id: str, file_path: str, **kw) -> dict:
    data = {"capability_id": capability_id, "file_path": file_path}
    if "file_reference_id" in kw:
        data["file_reference_id"] = kw["file_reference_id"]
    return data


@pytest.fixture
def engine(tmp_path):
    return CapabilityFileKnowledgeEngine(
        artifacts_root=str(tmp_path / "artifacts")
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_reference_round_trip(self):
        r = CapabilityFileReference(
            file_reference_id="fr-1",
            capability_id="cap-122",
            file_path="src/axiom_core/foo.py",
            file_name="foo.py",
            file_extension=".py",
            created_at="2026-01-01T00:00:00+00:00",
        )
        assert CapabilityFileReference.from_dict(r.to_dict()) == r

    def test_reference_gets_id_and_timestamp(self):
        r = CapabilityFileReference(capability_id="a", file_path="b.py")
        assert r.file_reference_id
        assert r.created_at

    def test_relationship_round_trip(self):
        r = CapabilityFileRelationship(
            relationship_id="rl-1",
            capability_id="cap-122",
            file_path="src/foo.py",
            relationship_type="CREATED",
            summary="created file",
        )
        assert CapabilityFileRelationship.from_dict(r.to_dict()) == r

    def test_relationship_gets_id(self):
        r = CapabilityFileRelationship(
            capability_id="a", file_path="b.py", relationship_type="CREATED"
        )
        assert r.relationship_id

    def test_knowledge_round_trip(self):
        k = CapabilityFileKnowledge(
            knowledge_id="k-1",
            capability_id="cap-122",
            file_count=2,
            relationship_count=3,
            affected_directories=["src", "tests"],
            created_at="2026-01-01T00:00:00+00:00",
            raw_payload={"k": "v"},
        )
        assert CapabilityFileKnowledge.from_dict(k.to_dict()) == k

    def test_report_defaults(self):
        report = CapabilityFileKnowledgeReport()
        assert report.report_id
        assert report.created_at
        assert report.file_count == 0
        assert report.schema_version == "1.0"

    def test_evidence_defaults(self):
        ev = CapabilityFileKnowledgeEvidence(report_id="rep-1")
        assert ev.evidence_id
        assert ev.created_at
        assert ev.report_id == "rep-1"

    def test_all_relationship_types_present(self):
        assert {t.value for t in CapabilityFileRelationshipType} == {
            "CREATED",
            "MODIFIED",
            "VALIDATED",
            "TESTED",
            "DEPENDS_ON",
            "REFERENCES",
        }


# ---------------------------------------------------------------------------
# Create / determinism
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_counts(self, engine):
        report = engine.create(
            file_relationships=[
                _rel("cap-122", "src/a.py", "CREATED"),
                _rel("cap-122", "src/b.py", "MODIFIED"),
                _rel("cap-124", "tests/c.py", "TESTED"),
            ]
        )
        assert report["relationship_count"] == 3
        assert report["file_count"] == 3
        assert report["capability_count"] == 2
        assert report["relationship_type_counts"] == {
            "CREATED": 1,
            "MODIFIED": 1,
            "TESTED": 1,
        }

    def test_deterministic_ordering(self, engine):
        report = engine.create(
            file_relationships=[
                _rel("cap-124", "src/z.py", "MODIFIED"),
                _rel("cap-122", "src/b.py", "CREATED"),
                _rel("cap-122", "src/a.py", "CREATED"),
                _rel("cap-122", "src/a.py", "VALIDATED"),
            ]
        )
        order = [
            (r["capability_id"], r["file_path"], r["relationship_type"])
            for r in report["relationships"]
        ]
        assert order == [
            ("cap-122", "src/a.py", "CREATED"),
            ("cap-122", "src/a.py", "VALIDATED"),
            ("cap-122", "src/b.py", "CREATED"),
            ("cap-124", "src/z.py", "MODIFIED"),
        ]

    def test_ordering_is_input_independent(self, engine):
        rels = [
            _rel("a", "src/x.py", "CREATED"),
            _rel("c", "src/y.py", "MODIFIED"),
            _rel("a", "src/z.py", "TESTED"),
        ]
        r1 = engine.create(file_relationships=list(rels))
        r2 = engine.create(file_relationships=list(reversed(rels)))
        key = lambda rep: [  # noqa: E731
            (x["capability_id"], x["file_path"], x["relationship_type"])
            for x in rep["relationships"]
        ]
        assert key(r1) == key(r2)

    def test_schema_version_preserved(self, engine):
        report = engine.create(
            file_relationships=[_rel("a", "src/a.py", "CREATED")]
        )
        assert report["schema_version"] == "1.0"

    def test_raw_metadata_preserved(self, engine):
        report = engine.create(
            file_relationships=[_rel("a", "src/a.py", "CREATED")],
            raw_metadata={"source": "program-0"},
        )
        assert report["raw_metadata"] == {"source": "program-0"}

    def test_knowledge_raw_payload_preserved(self, engine):
        report = engine.create(
            file_relationships=[_rel("cap-122", "src/a.py", "CREATED")],
            knowledge_payloads={"cap-122": {"nested": {"deep": [1, 2]}}},
        )
        knowledge = {k["capability_id"]: k for k in report["knowledge"]}
        assert knowledge["cap-122"]["raw_payload"] == {
            "nested": {"deep": [1, 2]}
        }


# ---------------------------------------------------------------------------
# File normalization
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_backslashes_normalized(self, engine):
        report = engine.create(
            file_relationships=[
                _rel("a", "src\\axiom_core\\foo.py", "CREATED")
            ]
        )
        assert report["relationships"][0]["file_path"] == (
            "src/axiom_core/foo.py"
        )

    def test_leading_dot_slash_stripped(self, engine):
        report = engine.create(
            file_relationships=[_rel("a", "./src/foo.py", "CREATED")]
        )
        assert report["relationships"][0]["file_path"] == "src/foo.py"

    def test_redundant_separators_collapsed(self, engine):
        report = engine.create(
            file_relationships=[_rel("a", "src//foo.py", "CREATED")]
        )
        assert report["relationships"][0]["file_path"] == "src/foo.py"

    def test_reference_name_and_extension_derived(self, engine):
        report = engine.create(
            file_relationships=[
                _rel("a", "src/axiom_core/foo.py", "CREATED")
            ]
        )
        ref = report["references"][0]
        assert ref["file_name"] == "foo.py"
        assert ref["file_extension"] == ".py"

    def test_relationship_type_normalized(self, engine):
        report = engine.create(
            file_relationships=[_rel("a", "src/a.py", "created")]
        )
        assert report["relationships"][0]["relationship_type"] == "CREATED"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_relationship_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid relationship_type"):
            engine.create(
                file_relationships=[_rel("a", "src/a.py", "NONSENSE")]
            )

    def test_missing_capability_rejected(self, engine):
        with pytest.raises(ValueError, match="capability_id is required"):
            engine.create(
                file_relationships=[_rel("", "src/a.py", "CREATED")]
            )

    def test_missing_file_path_rejected(self, engine):
        with pytest.raises(ValueError, match="file_path is required"):
            engine.create(
                file_relationships=[_rel("a", "", "CREATED")]
            )

    def test_missing_relationship_type_rejected(self, engine):
        with pytest.raises(ValueError, match="relationship_type is required"):
            engine.create(
                file_relationships=[_rel("a", "src/a.py", "")]
            )

    def test_reference_missing_capability_rejected(self, engine):
        with pytest.raises(ValueError, match="capability_id is required"):
            engine.create(file_references=[_ref("", "src/a.py")])


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


class TestDuplicateDetection:
    def test_duplicate_relationship_deduped_and_counted(self, engine):
        report = engine.create(
            file_relationships=[
                _rel("a", "src/a.py", "CREATED"),
                _rel("a", "src/a.py", "created"),  # case-insensitive dup
            ]
        )
        assert report["relationship_count"] == 1
        assert report["duplicate_relationship_count"] == 1

    def test_duplicate_after_path_normalization(self, engine):
        report = engine.create(
            file_relationships=[
                _rel("a", "src/a.py", "CREATED"),
                _rel("a", "./src/a.py", "CREATED"),
            ]
        )
        assert report["relationship_count"] == 1
        assert report["duplicate_relationship_count"] == 1

    def test_distinct_types_not_duplicates(self, engine):
        report = engine.create(
            file_relationships=[
                _rel("a", "src/a.py", "CREATED"),
                _rel("a", "src/a.py", "MODIFIED"),
            ]
        )
        assert report["relationship_count"] == 2
        assert report["duplicate_relationship_count"] == 0


# ---------------------------------------------------------------------------
# Directory aggregation
# ---------------------------------------------------------------------------


class TestDirectoryAggregation:
    def test_affected_directories_sorted_unique(self, engine):
        report = engine.create(
            file_relationships=[
                _rel("a", "src/core/a.py", "CREATED"),
                _rel("a", "src/core/b.py", "MODIFIED"),
                _rel("a", "tests/c.py", "TESTED"),
            ]
        )
        assert report["affected_directories"] == ["src/core", "tests"]
        assert report["directory_count"] == 2

    def test_per_capability_directories(self, engine):
        report = engine.create(
            file_relationships=[
                _rel("cap-1", "src/a.py", "CREATED"),
                _rel("cap-2", "tests/b.py", "TESTED"),
            ]
        )
        knowledge = {k["capability_id"]: k for k in report["knowledge"]}
        assert knowledge["cap-1"]["affected_directories"] == ["src"]
        assert knowledge["cap-2"]["affected_directories"] == ["tests"]

    def test_per_capability_counts(self, engine):
        report = engine.create(
            file_relationships=[
                _rel("cap-1", "src/a.py", "CREATED"),
                _rel("cap-1", "src/b.py", "MODIFIED"),
                _rel("cap-2", "tests/c.py", "TESTED"),
            ]
        )
        knowledge = {k["capability_id"]: k for k in report["knowledge"]}
        assert knowledge["cap-1"]["file_count"] == 2
        assert knowledge["cap-1"]["relationship_count"] == 2
        assert knowledge["cap-2"]["file_count"] == 1


# ---------------------------------------------------------------------------
# Reference derivation
# ---------------------------------------------------------------------------


class TestReferences:
    def test_references_derived_from_relationships(self, engine):
        report = engine.create(
            file_relationships=[
                _rel("a", "src/a.py", "CREATED"),
                _rel("a", "src/a.py", "MODIFIED"),
            ]
        )
        # Two relationships on the same file -> one reference.
        assert report["file_count"] == 1
        assert len(report["references"]) == 1

    def test_explicit_reference_merged(self, engine):
        report = engine.create(
            file_relationships=[_rel("a", "src/a.py", "CREATED")],
            file_references=[_ref("a", "src/b.py")],
        )
        paths = sorted(r["file_path"] for r in report["references"])
        assert paths == ["src/a.py", "src/b.py"]


# ---------------------------------------------------------------------------
# Pass/fail
# ---------------------------------------------------------------------------


def _read_pass_fail(engine, report_id: str) -> dict:
    path = engine._report_dir / report_id / "pass_fail.json"
    return json.loads(path.read_text(encoding="utf-8"))


class TestPassFail:
    def test_pass_with_relationships(self, engine):
        report = engine.create(
            file_relationships=[_rel("a", "src/a.py", "CREATED")]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is True
        assert pf["relationship_count"] == 1
        assert pf["status"] == "passed"

    def test_empty_report_fails(self, engine):
        report = engine.create(file_relationships=[])
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["relationship_count"] == 0
        assert pf["status"] == "failed"

    def test_duplicate_fails(self, engine):
        report = engine.create(
            file_relationships=[
                _rel("a", "src/a.py", "CREATED"),
                _rel("a", "src/a.py", "CREATED"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["duplicate_relationship_count"] == 1

    def test_evidence_bundle_files_written(self, engine):
        report = engine.create(
            file_relationships=[_rel("a", "src/a.py", "CREATED")]
        )
        report_dir = engine._report_dir / report["report_id"]
        for name in (
            "capability_file_request.json",
            "capability_file_result.json",
            "capability_file_summary.md",
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
            file_relationships=[_rel("a", "src/a.py", "CREATED")]
        )
        report_id = created["report_id"]
        appended = engine.append(
            report_id,
            file_relationships=[_rel("b", "tests/b.py", "TESTED")],
        )
        assert appended["report_id"] == report_id
        assert appended["relationship_count"] == 2
        caps = {r["capability_id"] for r in appended["relationships"]}
        assert caps == {"a", "b"}

    def test_append_preserves_raw_payload(self, engine):
        created = engine.create(
            file_relationships=[_rel("a", "src/a.py", "CREATED")],
            knowledge_payloads={"a": {"origin": "p0"}},
        )
        appended = engine.append(
            created["report_id"],
            file_relationships=[_rel("a", "src/b.py", "MODIFIED")],
        )
        knowledge = {k["capability_id"]: k for k in appended["knowledge"]}
        assert knowledge["a"]["raw_payload"] == {"origin": "p0"}

    def test_append_missing_report_raises(self, engine):
        with pytest.raises(ValueError, match="Report not found"):
            engine.append("does-not-exist", file_relationships=[])


# ---------------------------------------------------------------------------
# Retrieval / exports
# ---------------------------------------------------------------------------


class TestRetrievalExport:
    def test_get_report_round_trip(self, engine):
        created = engine.create(
            file_relationships=[_rel("a", "src/a.py", "CREATED")]
        )
        loaded = engine.get_report(created["report_id"])
        assert loaded["report_id"] == created["report_id"]
        assert loaded["relationship_count"] == 1

    def test_get_missing_returns_none(self, engine):
        assert engine.get_report("missing-id") is None

    def test_list_reports_sorted(self, engine):
        engine.create(file_relationships=[_rel("a", "src/a.py", "CREATED")])
        engine.create(file_relationships=[_rel("b", "src/b.py", "MODIFIED")])
        assert len(engine.list_reports()) == 2

    def test_export_json_valid(self, engine):
        created = engine.create(
            file_relationships=[_rel("a", "src/a.py", "CREATED")]
        )
        parsed = json.loads(
            engine.export_report(created["report_id"], fmt="json")
        )
        assert parsed["report_id"] == created["report_id"]

    def test_export_markdown_headings(self, engine):
        created = engine.create(
            file_relationships=[_rel("cap-122", "src/a.py", "CREATED")]
        )
        out = engine.export_report(created["report_id"], fmt="markdown")
        assert "# Capability File Knowledge Report" in out
        assert "## Relationship Type Counts" in out
        assert "## Affected Directories" in out
        assert "## File Relationships" in out
        assert "## File References" in out
        assert "[CREATED]" in out
        assert "[cap-122]" in out

    def test_export_csv_rows(self, engine):
        created = engine.create(
            file_relationships=[
                _rel("a", "src/a.py", "CREATED"),
                _rel("a", "src/b.py", "MODIFIED"),
            ]
        )
        out = engine.export_report(created["report_id"], fmt="csv")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        assert lines[0].startswith("record_kind,")
        # header + 2 relationships + 2 references
        assert len(lines) == 5

    def test_export_invalid_format_raises(self, engine):
        created = engine.create(
            file_relationships=[_rel("a", "src/a.py", "CREATED")]
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

    def test_file_path_traversal_preserved_as_data(self, engine):
        # file_path is data, not a filesystem path: ".." is preserved.
        report = engine.create(
            file_relationships=[_rel("a", "../outside/x.py", "REFERENCES")]
        )
        assert report["relationships"][0]["file_path"] == "../outside/x.py"
