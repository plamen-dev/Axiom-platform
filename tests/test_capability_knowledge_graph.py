"""Tests for the Capability Knowledge Graph Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.capability_knowledge_graph import (
    CapabilityGraphEdge,
    CapabilityGraphEdgeType,
    CapabilityGraphNode,
    CapabilityGraphNodeType,
    CapabilityKnowledgeGraph,
    CapabilityKnowledgeGraphEngine,
    CapabilityKnowledgeGraphEvidence,
    CapabilityKnowledgeGraphReport,
)


def _node(node_type: str, source_id: str, **kw) -> dict:
    data = {
        "node_type": node_type,
        "source_id": source_id,
        "label": kw.get("label", f"{node_type}:{source_id}"),
        "summary": kw.get("summary", ""),
    }
    if "node_id" in kw:
        data["node_id"] = kw["node_id"]
    if "raw_payload" in kw:
        data["raw_payload"] = kw["raw_payload"]
    return data


def _edge(
    source_node_id: str,
    target_node_id: str,
    edge_type: str,
    **kw,
) -> dict:
    data = {
        "source_node_id": source_node_id,
        "target_node_id": target_node_id,
        "edge_type": edge_type,
        "summary": kw.get("summary", ""),
    }
    if "edge_id" in kw:
        data["edge_id"] = kw["edge_id"]
    if "raw_payload" in kw:
        data["raw_payload"] = kw["raw_payload"]
    return data


@pytest.fixture
def engine(tmp_path):
    return CapabilityKnowledgeGraphEngine(
        artifacts_root=str(tmp_path / "artifacts")
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_node_round_trip(self):
        n = CapabilityGraphNode(
            node_id="n-1",
            node_type="CAPABILITY",
            source_id="cap-122",
            label="Registry",
            summary="identity layer",
            created_at="2026-01-01T00:00:00+00:00",
            raw_payload={"k": "v"},
        )
        assert CapabilityGraphNode.from_dict(n.to_dict()) == n

    def test_node_gets_id_and_timestamp(self):
        n = CapabilityGraphNode(node_type="CAPABILITY", source_id="cap-1")
        assert n.node_id
        assert n.created_at

    def test_edge_round_trip(self):
        e = CapabilityGraphEdge(
            edge_id="e-1",
            source_node_id="n-1",
            target_node_id="n-2",
            edge_type="BUILDS_ON",
            summary="depends",
            created_at="2026-01-01T00:00:00+00:00",
            raw_payload={"k": "v"},
        )
        assert CapabilityGraphEdge.from_dict(e.to_dict()) == e

    def test_graph_round_trip(self):
        g = CapabilityKnowledgeGraph(
            graph_id="g-1",
            nodes=[CapabilityGraphNode(node_id="n-1", source_id="cap-1")],
            edges=[
                CapabilityGraphEdge(
                    edge_id="e-1",
                    source_node_id="n-1",
                    target_node_id="n-2",
                )
            ],
            created_at="2026-01-01T00:00:00+00:00",
            raw_payload={"k": "v"},
        )
        assert CapabilityKnowledgeGraph.from_dict(g.to_dict()) == g

    def test_report_defaults(self):
        report = CapabilityKnowledgeGraphReport()
        assert report.report_id
        assert report.graph_id
        assert report.created_at
        assert report.node_count == 0
        assert report.schema_version == "1.0"

    def test_evidence_defaults(self):
        ev = CapabilityKnowledgeGraphEvidence(report_id="rep-1")
        assert ev.evidence_id
        assert ev.created_at
        assert ev.report_id == "rep-1"

    def test_all_node_types_present(self):
        assert {t.value for t in CapabilityGraphNodeType} == {
            "CAPABILITY",
            "EVENT",
            "SUMMARY",
            "RELATIONSHIP",
            "IMPACT",
            "FILE",
            "VALIDATION",
            "ARTIFACT",
            "WORKER",
            "UNKNOWN",
        }

    def test_all_edge_types_present(self):
        assert {t.value for t in CapabilityGraphEdgeType} == {
            "BUILDS_ON",
            "ENABLES",
            "RELATES_TO",
            "AFFECTS",
            "VALIDATES",
            "TOUCHES_FILE",
            "PRODUCED_EVENT",
            "HAS_SUMMARY",
            "HAS_IMPACT",
            "HAS_ARTIFACT",
            "CREATED_BY",
            "UNKNOWN",
        }


# ---------------------------------------------------------------------------
# Create / determinism
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_counts(self, engine):
        report = engine.create(
            nodes=[
                _node("CAPABILITY", "cap-122", node_id="n-1"),
                _node("VALIDATION", "val-1", node_id="n-2"),
                _node("FILE", "src/x.py", node_id="n-3"),
            ],
            edges=[
                _edge("n-1", "n-2", "VALIDATES"),
                _edge("n-1", "n-3", "TOUCHES_FILE"),
            ],
        )
        assert report["node_count"] == 3
        assert report["edge_count"] == 2
        assert report["node_type_counts"] == {
            "CAPABILITY": 1,
            "FILE": 1,
            "VALIDATION": 1,
        }
        assert report["edge_type_counts"] == {
            "TOUCHES_FILE": 1,
            "VALIDATES": 1,
        }

    def test_deterministic_node_ordering(self, engine):
        report = engine.create(
            nodes=[
                _node("VALIDATION", "val-1"),
                _node("CAPABILITY", "cap-2"),
                _node("CAPABILITY", "cap-1"),
                _node("FILE", "a.py"),
            ]
        )
        order = [(n["node_type"], n["source_id"]) for n in report["nodes"]]
        assert order == [
            ("CAPABILITY", "cap-1"),
            ("CAPABILITY", "cap-2"),
            ("FILE", "a.py"),
            ("VALIDATION", "val-1"),
        ]

    def test_deterministic_edge_ordering(self, engine):
        report = engine.create(
            nodes=[
                _node("CAPABILITY", "cap-1", node_id="n-1"),
                _node("CAPABILITY", "cap-2", node_id="n-2"),
                _node("CAPABILITY", "cap-3", node_id="n-3"),
            ],
            edges=[
                _edge("n-2", "n-3", "ENABLES"),
                _edge("n-1", "n-3", "RELATES_TO"),
                _edge("n-1", "n-2", "BUILDS_ON"),
            ],
        )
        order = [
            (e["source_node_id"], e["target_node_id"], e["edge_type"])
            for e in report["edges"]
        ]
        assert order == [
            ("n-1", "n-2", "BUILDS_ON"),
            ("n-1", "n-3", "RELATES_TO"),
            ("n-2", "n-3", "ENABLES"),
        ]

    def test_ordering_is_input_independent(self, engine):
        nodes = [
            _node("CAPABILITY", "cap-1", node_id="n-1"),
            _node("FILE", "a.py", node_id="n-2"),
            _node("EVENT", "ev-1", node_id="n-3"),
        ]
        r1 = engine.create(nodes=list(nodes))
        r2 = engine.create(nodes=list(reversed(nodes)))
        key = lambda rep: [  # noqa: E731
            (n["node_type"], n["source_id"]) for n in rep["nodes"]
        ]
        assert key(r1) == key(r2)

    def test_schema_version_preserved(self, engine):
        report = engine.create(nodes=[_node("CAPABILITY", "cap-1")])
        assert report["schema_version"] == "1.0"

    def test_raw_metadata_preserved(self, engine):
        report = engine.create(
            nodes=[_node("CAPABILITY", "cap-1")],
            raw_metadata={"source": "program-0"},
        )
        assert report["raw_metadata"] == {"source": "program-0"}

    def test_node_raw_payload_preserved(self, engine):
        report = engine.create(
            nodes=[
                _node(
                    "CAPABILITY",
                    "cap-1",
                    raw_payload={"nested": {"deep": [1, 2]}},
                )
            ]
        )
        assert report["nodes"][0]["raw_payload"] == {
            "nested": {"deep": [1, 2]}
        }

    def test_edge_raw_payload_preserved(self, engine):
        report = engine.create(
            nodes=[
                _node("CAPABILITY", "cap-1", node_id="n-1"),
                _node("CAPABILITY", "cap-2", node_id="n-2"),
            ],
            edges=[
                _edge(
                    "n-1",
                    "n-2",
                    "BUILDS_ON",
                    raw_payload={"nested": {"deep": [1, 2]}},
                )
            ],
        )
        assert report["edges"][0]["raw_payload"] == {
            "nested": {"deep": [1, 2]}
        }

    def test_graph_raw_payload_preserved(self, engine):
        report = engine.create(
            nodes=[_node("CAPABILITY", "cap-1")],
            graph_raw_payload={"origin": "p0"},
        )
        assert report["graph"]["raw_payload"] == {"origin": "p0"}

    def test_graph_id_consistent(self, engine):
        report = engine.create(nodes=[_node("CAPABILITY", "cap-1")])
        assert report["graph_id"]
        assert report["graph"]["graph_id"] == report["graph_id"]


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_node_type_normalized(self, engine):
        report = engine.create(nodes=[_node("capability", "cap-1")])
        assert report["nodes"][0]["node_type"] == "CAPABILITY"

    def test_edge_type_normalized(self, engine):
        report = engine.create(
            nodes=[
                _node("CAPABILITY", "cap-1", node_id="n-1"),
                _node("CAPABILITY", "cap-2", node_id="n-2"),
            ],
            edges=[_edge("n-1", "n-2", "builds_on")],
        )
        assert report["edges"][0]["edge_type"] == "BUILDS_ON"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_node_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid node_type"):
            engine.create(nodes=[_node("NONSENSE", "cap-1")])

    def test_invalid_edge_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid edge_type"):
            engine.create(
                nodes=[_node("CAPABILITY", "cap-1", node_id="n-1")],
                edges=[_edge("n-1", "n-1", "NONSENSE")],
            )

    def test_missing_source_id_rejected(self, engine):
        with pytest.raises(ValueError, match="source_id is required"):
            engine.create(nodes=[_node("CAPABILITY", "")])

    def test_missing_node_type_rejected(self, engine):
        with pytest.raises(ValueError, match="node_type is required"):
            engine.create(nodes=[_node("", "cap-1")])

    def test_edge_missing_source_node_id_rejected(self, engine):
        with pytest.raises(ValueError, match="source_node_id is required"):
            engine.create(edges=[_edge("", "n-2", "BUILDS_ON")])

    def test_edge_missing_target_node_id_rejected(self, engine):
        with pytest.raises(ValueError, match="target_node_id is required"):
            engine.create(edges=[_edge("n-1", "", "BUILDS_ON")])

    def test_edge_missing_type_rejected(self, engine):
        with pytest.raises(ValueError, match="edge_type is required"):
            engine.create(edges=[_edge("n-1", "n-2", "")])


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


class TestDuplicateDetection:
    def test_duplicate_node_deduped_and_counted(self, engine):
        report = engine.create(
            nodes=[
                _node("CAPABILITY", "cap-1"),
                _node("capability", "cap-1"),
            ]
        )
        assert report["node_count"] == 1
        assert report["duplicate_node_count"] == 1

    def test_distinct_node_type_not_duplicate(self, engine):
        report = engine.create(
            nodes=[
                _node("CAPABILITY", "cap-1"),
                _node("FILE", "cap-1"),
            ]
        )
        assert report["node_count"] == 2
        assert report["duplicate_node_count"] == 0

    def test_duplicate_edge_deduped_and_counted(self, engine):
        report = engine.create(
            nodes=[
                _node("CAPABILITY", "cap-1", node_id="n-1"),
                _node("CAPABILITY", "cap-2", node_id="n-2"),
            ],
            edges=[
                _edge("n-1", "n-2", "BUILDS_ON"),
                _edge("n-1", "n-2", "builds_on"),
            ],
        )
        assert report["edge_count"] == 1
        assert report["duplicate_edge_count"] == 1

    def test_distinct_edge_type_not_duplicate(self, engine):
        report = engine.create(
            nodes=[
                _node("CAPABILITY", "cap-1", node_id="n-1"),
                _node("CAPABILITY", "cap-2", node_id="n-2"),
            ],
            edges=[
                _edge("n-1", "n-2", "BUILDS_ON"),
                _edge("n-1", "n-2", "ENABLES"),
            ],
        )
        assert report["edge_count"] == 2
        assert report["duplicate_edge_count"] == 0


# ---------------------------------------------------------------------------
# Orphan detection
# ---------------------------------------------------------------------------


class TestOrphanDetection:
    def test_orphan_node_detected(self, engine):
        report = engine.create(
            nodes=[
                _node("CAPABILITY", "cap-1", node_id="n-1"),
                _node("CAPABILITY", "cap-2", node_id="n-2"),
                _node("CAPABILITY", "cap-3", node_id="n-3"),
            ],
            edges=[_edge("n-1", "n-2", "BUILDS_ON")],
        )
        assert report["orphan_node_count"] == 1
        assert report["orphan_node_ids"] == ["n-3"]

    def test_no_orphans_when_all_connected(self, engine):
        report = engine.create(
            nodes=[
                _node("CAPABILITY", "cap-1", node_id="n-1"),
                _node("CAPABILITY", "cap-2", node_id="n-2"),
            ],
            edges=[_edge("n-1", "n-2", "BUILDS_ON")],
        )
        assert report["orphan_node_count"] == 0
        assert report["orphan_node_ids"] == []

    def test_all_orphans_when_no_edges(self, engine):
        report = engine.create(
            nodes=[
                _node("CAPABILITY", "cap-1", node_id="n-1"),
                _node("CAPABILITY", "cap-2", node_id="n-2"),
            ]
        )
        assert report["orphan_node_count"] == 2


# ---------------------------------------------------------------------------
# Pass/fail
# ---------------------------------------------------------------------------


def _read_pass_fail(engine, report_id: str) -> dict:
    path = engine._report_dir / report_id / "pass_fail.json"
    return json.loads(path.read_text(encoding="utf-8"))


class TestPassFail:
    def test_pass_with_connected_nodes(self, engine):
        report = engine.create(
            nodes=[
                _node("CAPABILITY", "cap-1", node_id="n-1"),
                _node("CAPABILITY", "cap-2", node_id="n-2"),
            ],
            edges=[_edge("n-1", "n-2", "BUILDS_ON")],
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is True
        assert pf["node_count"] == 2
        assert pf["status"] == "passed"

    def test_empty_report_fails(self, engine):
        report = engine.create(nodes=[])
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["node_count"] == 0
        assert pf["status"] == "failed"

    def test_duplicate_node_fails(self, engine):
        report = engine.create(
            nodes=[
                _node("CAPABILITY", "cap-1", node_id="n-1"),
                _node("CAPABILITY", "cap-1", node_id="n-2"),
            ]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["duplicate_node_count"] == 1

    def test_duplicate_edge_fails(self, engine):
        report = engine.create(
            nodes=[
                _node("CAPABILITY", "cap-1", node_id="n-1"),
                _node("CAPABILITY", "cap-2", node_id="n-2"),
            ],
            edges=[
                _edge("n-1", "n-2", "BUILDS_ON"),
                _edge("n-1", "n-2", "BUILDS_ON"),
            ],
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["duplicate_edge_count"] == 1

    def test_orphan_fails(self, engine):
        report = engine.create(
            nodes=[_node("CAPABILITY", "cap-1", node_id="n-1")]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["orphan_node_count"] == 1

    def test_evidence_bundle_files_written(self, engine):
        report = engine.create(
            nodes=[
                _node("CAPABILITY", "cap-1", node_id="n-1"),
                _node("CAPABILITY", "cap-2", node_id="n-2"),
            ],
            edges=[_edge("n-1", "n-2", "BUILDS_ON")],
        )
        report_dir = engine._report_dir / report["report_id"]
        for name in (
            "capability_graph_request.json",
            "capability_graph_result.json",
            "capability_graph_summary.md",
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
            nodes=[_node("CAPABILITY", "cap-1", node_id="n-1")]
        )
        report_id = created["report_id"]
        appended = engine.append(
            report_id,
            nodes=[_node("CAPABILITY", "cap-2", node_id="n-2")],
        )
        assert appended["report_id"] == report_id
        assert appended["node_count"] == 2
        sources = {n["source_id"] for n in appended["nodes"]}
        assert sources == {"cap-1", "cap-2"}

    def test_append_preserves_graph_id(self, engine):
        created = engine.create(
            nodes=[_node("CAPABILITY", "cap-1", node_id="n-1")]
        )
        appended = engine.append(
            created["report_id"],
            nodes=[_node("CAPABILITY", "cap-2", node_id="n-2")],
        )
        assert appended["graph_id"] == created["graph_id"]

    def test_append_preserves_graph_raw_payload(self, engine):
        created = engine.create(
            nodes=[_node("CAPABILITY", "cap-1", node_id="n-1")],
            graph_raw_payload={"origin": "p0"},
        )
        appended = engine.append(
            created["report_id"],
            nodes=[_node("CAPABILITY", "cap-2", node_id="n-2")],
        )
        assert appended["graph"]["raw_payload"] == {"origin": "p0"}

    def test_append_missing_report_raises(self, engine):
        with pytest.raises(ValueError, match="Report not found"):
            engine.append("does-not-exist", nodes=[])


# ---------------------------------------------------------------------------
# Retrieval / exports
# ---------------------------------------------------------------------------


class TestRetrievalExport:
    def test_get_report_round_trip(self, engine):
        created = engine.create(
            nodes=[_node("CAPABILITY", "cap-1", node_id="n-1")]
        )
        loaded = engine.get_report(created["report_id"])
        assert loaded["report_id"] == created["report_id"]
        assert loaded["node_count"] == 1

    def test_get_missing_returns_none(self, engine):
        assert engine.get_report("missing-id") is None

    def test_list_reports_sorted(self, engine):
        engine.create(nodes=[_node("CAPABILITY", "cap-1")])
        engine.create(nodes=[_node("CAPABILITY", "cap-2")])
        assert len(engine.list_reports()) == 2

    def test_export_json_valid(self, engine):
        created = engine.create(
            nodes=[_node("CAPABILITY", "cap-1", node_id="n-1")]
        )
        parsed = json.loads(
            engine.export_report(created["report_id"], fmt="json")
        )
        assert parsed["report_id"] == created["report_id"]

    def test_export_markdown_headings(self, engine):
        created = engine.create(
            nodes=[
                _node("CAPABILITY", "cap-122", node_id="n-1"),
                _node("VALIDATION", "val-1", node_id="n-2"),
            ],
            edges=[_edge("n-1", "n-2", "VALIDATES")],
        )
        out = engine.export_report(created["report_id"], fmt="markdown")
        assert "# Capability Knowledge Graph Report" in out
        assert "## Node Type Counts" in out
        assert "## Edge Type Counts" in out
        assert "## Nodes" in out
        assert "## Edges" in out
        assert "[CAPABILITY]" in out
        assert "[cap-122]" in out
        assert "--[VALIDATES]-->" in out

    def test_export_csv_rows(self, engine):
        created = engine.create(
            nodes=[
                _node("CAPABILITY", "cap-1", node_id="n-1"),
                _node("CAPABILITY", "cap-2", node_id="n-2"),
            ],
            edges=[_edge("n-1", "n-2", "BUILDS_ON")],
        )
        out = engine.export_report(created["report_id"], fmt="csv")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        assert lines[0].startswith("record_kind,")
        # header + 2 nodes + 1 edge
        assert len(lines) == 4
        node_rows = [ln for ln in lines[1:] if ln.startswith("node,")]
        edge_rows = [ln for ln in lines[1:] if ln.startswith("edge,")]
        assert len(node_rows) == 2
        assert len(edge_rows) == 1

    def test_export_invalid_format_raises(self, engine):
        created = engine.create(nodes=[_node("CAPABILITY", "cap-1")])
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
