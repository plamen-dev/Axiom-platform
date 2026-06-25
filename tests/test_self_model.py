"""Tests for the repository self-model adapter (Integration Milestone M1).

The adapter pipes the existing ``code-inventory`` producer into the existing
capability knowledge-graph and capability-relationship engines. These tests use
a fixed, hand-built subgraph fixture so node / edge / orphan counts and the
relationship mapping are deterministic and independent of the real repo.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from axiom_core.codebase_inventory import CodebaseInventory
from axiom_core.self_model import (
    GRAPH_EDGE_TYPE,
    GRAPH_NODE_TYPE,
    RELATIONSHIP_TYPE,
    SelfModelBuilder,
    graph_dependencies,
    graph_dependents,
    graph_imports,
    graph_isolated,
    graph_modules,
)


@pytest.fixture
def fixed_repo(tmp_path: Path) -> Path:
    """A tiny fixed repository with a known import subgraph.

    Modules (4):  pkg.a, pkg.b, pkg.c, pkg.island
    Edges (2):    pkg.a -> pkg.b, pkg.b -> pkg.c
    Isolated (1): pkg.island (imports nothing internal, imported by nobody)
    External imports (``os``) and a relative import are ignored.
    """
    src = tmp_path / "src" / "pkg"
    src.mkdir(parents=True)
    (src / "a.py").write_text(
        "import os\nfrom pkg.b import thing\n\n\ndef use():\n    return thing\n",
        encoding="utf-8",
    )
    (src / "b.py").write_text(
        "import pkg.c\n\nthing = 1\n", encoding="utf-8"
    )
    (src / "c.py").write_text("VALUE = 42\n", encoding="utf-8")
    (src / "island.py").write_text(
        "import json\n\n\ndef alone():\n    return json\n", encoding="utf-8"
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Producer: import-edge extraction
# ---------------------------------------------------------------------------


def test_extract_import_edges_fixed_subgraph(fixed_repo: Path) -> None:
    edges = CodebaseInventory(fixed_repo).extract_import_edges()
    assert edges == [("pkg.a", "pkg.b"), ("pkg.b", "pkg.c")]


def test_extract_import_edges_is_deterministic(fixed_repo: Path) -> None:
    inv = CodebaseInventory(fixed_repo)
    assert inv.extract_import_edges() == inv.extract_import_edges()


def test_extract_import_edges_ignores_external_and_self(fixed_repo: Path) -> None:
    edges = CodebaseInventory(fixed_repo).extract_import_edges()
    flat = {t for e in edges for t in e}
    assert "os" not in flat
    assert "json" not in flat
    assert all(src != dst for src, dst in edges)


def test_extract_import_edges_from_package_import_form(tmp_path: Path) -> None:
    src = tmp_path / "src" / "pkg"
    src.mkdir(parents=True)
    (src / "child.py").write_text("VALUE = 1\n", encoding="utf-8")
    (src / "user.py").write_text(
        "from pkg import child\n", encoding="utf-8"
    )
    edges = CodebaseInventory(tmp_path).extract_import_edges()
    assert edges == [("pkg.user", "pkg.child")]


# ---------------------------------------------------------------------------
# Adapter: self-model build + payload mapping
# ---------------------------------------------------------------------------


def test_build_modules_and_edges(fixed_repo: Path) -> None:
    model = SelfModelBuilder(fixed_repo).build()
    assert model["modules"] == ["pkg.a", "pkg.b", "pkg.c", "pkg.island"]
    assert model["edges"] == [("pkg.a", "pkg.b"), ("pkg.b", "pkg.c")]


def test_graph_payload_mapping(fixed_repo: Path) -> None:
    payload = SelfModelBuilder(fixed_repo).graph_payload()
    assert {n["node_type"] for n in payload["nodes"]} == {GRAPH_NODE_TYPE}
    assert {e["edge_type"] for e in payload["edges"]} == {GRAPH_EDGE_TYPE}
    # node_id == source_id == module name so edges resolve by module name
    assert all(n["node_id"] == n["source_id"] for n in payload["nodes"])
    assert {(e["source_node_id"], e["target_node_id"]) for e in payload["edges"]} == {
        ("pkg.a", "pkg.b"),
        ("pkg.b", "pkg.c"),
    }


def test_relationship_payload_mapping(fixed_repo: Path) -> None:
    payload = SelfModelBuilder(fixed_repo).relationship_payload()
    assert {r["relationship_type"] for r in payload["relationships"]} == {
        RELATIONSHIP_TYPE
    }
    assert payload["known_capability_ids"] == [
        "pkg.a",
        "pkg.b",
        "pkg.c",
        "pkg.island",
    ]
    assert {
        (r["source_capability_id"], r["target_capability_id"])
        for r in payload["relationships"]
    } == {("pkg.a", "pkg.b"), ("pkg.b", "pkg.c")}


# ---------------------------------------------------------------------------
# Consumers: populate existing engines + counts / orphan detection
# ---------------------------------------------------------------------------


def test_populate_graph_counts_and_orphans(
    fixed_repo: Path, tmp_path: Path
) -> None:
    art = tmp_path / "artifacts"
    report = SelfModelBuilder(fixed_repo).populate_graph(artifacts_root=str(art))
    assert report["node_count"] == 4
    assert report["edge_count"] == 2
    assert report["orphan_node_count"] == 1
    assert report["orphan_node_ids"] == ["pkg.island"]
    assert report["node_type_counts"] == {GRAPH_NODE_TYPE: 4}
    assert report["edge_type_counts"] == {GRAPH_EDGE_TYPE: 2}
    assert report["raw_metadata"]["source"] == "code-inventory"


def test_populate_relationships_counts_and_orphans(
    fixed_repo: Path, tmp_path: Path
) -> None:
    art = tmp_path / "artifacts"
    report = SelfModelBuilder(fixed_repo).populate_relationships(
        artifacts_root=str(art)
    )
    assert report["relationship_count"] == 2
    assert report["relationship_type_counts"] == {RELATIONSHIP_TYPE: 2}
    assert report["orphan_capability_count"] == 1
    assert report["orphan_capability_ids"] == ["pkg.island"]


def test_populate_is_deterministic(fixed_repo: Path, tmp_path: Path) -> None:
    builder = SelfModelBuilder(fixed_repo)
    r1 = builder.populate_graph(artifacts_root=str(tmp_path / "a1"))
    r2 = builder.populate_graph(artifacts_root=str(tmp_path / "a2"))
    nodes1 = [(n["source_id"], n["node_type"]) for n in r1["nodes"]]
    nodes2 = [(n["source_id"], n["node_type"]) for n in r2["nodes"]]
    edges1 = [(e["source_node_id"], e["target_node_id"]) for e in r1["edges"]]
    edges2 = [(e["source_node_id"], e["target_node_id"]) for e in r2["edges"]]
    assert nodes1 == nodes2
    assert edges1 == edges2


# ---------------------------------------------------------------------------
# Queries over the populated graph (answers come from the graph itself)
# ---------------------------------------------------------------------------


def test_queries_answer_dependency_questions(
    fixed_repo: Path, tmp_path: Path
) -> None:
    art = tmp_path / "artifacts"
    builder = SelfModelBuilder(fixed_repo)
    builder.populate_graph(artifacts_root=str(art))
    # Re-read from the persisted report to prove answers come from the graph.
    from axiom_core.capability_knowledge_graph import (
        CapabilityKnowledgeGraphEngine,
    )

    engine = CapabilityKnowledgeGraphEngine(artifacts_root=str(art))
    report = engine.list_reports()[0]

    assert graph_modules(report) == ["pkg.a", "pkg.b", "pkg.c", "pkg.island"]
    assert graph_imports(report) == [("pkg.a", "pkg.b"), ("pkg.b", "pkg.c")]
    assert graph_isolated(report) == ["pkg.island"]
    assert graph_dependencies(report, "pkg.b") == ["pkg.c"]
    assert graph_dependents(report, "pkg.b") == ["pkg.a"]
    assert graph_dependencies(report, "pkg.island") == []
    assert graph_dependents(report, "pkg.island") == []


def test_before_after_graph_can_answer(
    fixed_repo: Path, tmp_path: Path
) -> None:
    """Before: an empty/sample graph cannot answer; after: it can."""
    empty_report: dict = {"nodes": [], "edges": [], "orphan_node_ids": []}
    assert graph_modules(empty_report) == []
    assert graph_dependents(empty_report, "pkg.b") == []

    art = tmp_path / "artifacts"
    after = SelfModelBuilder(fixed_repo).populate_graph(artifacts_root=str(art))
    assert graph_modules(after) == ["pkg.a", "pkg.b", "pkg.c", "pkg.island"]
    assert graph_dependents(after, "pkg.b") == ["pkg.a"]
