"""Repository Self-Model adapter (Integration Milestone M1).

Pipes the existing ``code-inventory`` producer into the existing capability
knowledge-graph and capability-relationship consumers so Axiom can answer real
repository dependency questions from its own populated graph rather than from an
ad-hoc script or manual source parsing.

This module is an *adapter / exporter only*. It introduces **no** new framework,
registry, object family, engine, or evidence system:

* the producer is :class:`axiom_core.codebase_inventory.CodebaseInventory`;
* the destinations are the existing
  :class:`~axiom_core.capability_knowledge_graph.CapabilityKnowledgeGraphEngine`
  and :class:`~axiom_core.capability_relationship.CapabilityRelationshipEngine`.

It only builds plain ``dict`` payloads (nodes / edges / relationships) and hands
them to those engines' existing ``create()`` APIs. All output is deterministic:
modules and edges are sorted and deduplicated by the producer, and the consumer
engines deterministically order, dedupe, and detect orphans.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from axiom_core.capability_knowledge_graph import (
    CapabilityKnowledgeGraphEngine,
)
from axiom_core.capability_relationship import CapabilityRelationshipEngine
from axiom_core.codebase_inventory import CodebaseInventory

# Mapping from structural inventory concepts onto the *existing* enum values
# accepted by the consumer engines (no new types are introduced):
#   module        -> CAPABILITY graph node
#   import edge    -> BUILDS_ON  graph edge  (importer builds on imported)
#   import edge    -> DEPENDS_ON relationship (importer depends on imported)
GRAPH_NODE_TYPE = "CAPABILITY"
GRAPH_EDGE_TYPE = "BUILDS_ON"
RELATIONSHIP_TYPE = "DEPENDS_ON"

_SOURCE_TAG = "code-inventory"
_MILESTONE_TAG = "M1-self-model"


class SelfModelBuilder:
    """Builds a deterministic repository self-model and populates the consumers.

    The builder is a thin coordinator: it reads structural truth from
    ``code-inventory`` and emits payloads for the existing graph/relationship
    engines. It holds no persistent state and defines no new object model.
    """

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root).resolve()
        self._inventory = CodebaseInventory(self.repo_root)

    # ------------------------------------------------------------------
    # Build (producer -> deterministic self-model)
    # ------------------------------------------------------------------

    def build(self) -> dict[str, Any]:
        """Return the deterministic self-model from ``code-inventory``.

        Keys: ``modules`` (sorted module names), ``edges`` (sorted
        ``(importer, imported)`` tuples), ``line_counts`` and ``symbol_counts``
        (per module, for node summaries).
        """
        files, symbols, _ = self._inventory.scan()

        modules: set[str] = set()
        line_counts: dict[str, int] = {}
        path_to_module: dict[str, str] = {}
        for f in files:
            if f.module_name and f.path.startswith("src/"):
                modules.add(f.module_name)
                line_counts[f.module_name] = f.line_count
                path_to_module[f.path] = f.module_name

        symbol_counts: dict[str, int] = {}
        for s in symbols:
            module = path_to_module.get(s.file_path)
            if module is not None:
                symbol_counts[module] = symbol_counts.get(module, 0) + 1

        edges = self._inventory.extract_import_edges()

        return {
            "modules": sorted(modules),
            "edges": edges,
            "line_counts": line_counts,
            "symbol_counts": symbol_counts,
        }

    # ------------------------------------------------------------------
    # Adapt (self-model -> existing consumer payloads)
    # ------------------------------------------------------------------

    def graph_payload(self, model: dict[str, Any] | None = None) -> dict[str, Any]:
        """Convert the self-model into capability-knowledge-graph payload."""
        model = model or self.build()
        nodes = [
            {
                "node_id": m,
                "node_type": GRAPH_NODE_TYPE,
                "source_id": m,
                "label": m,
                "summary": (
                    f"{model['line_counts'].get(m, 0)} loc, "
                    f"{model['symbol_counts'].get(m, 0)} symbols"
                ),
                "raw_payload": {"module": m, "kind": "module"},
            }
            for m in model["modules"]
        ]
        edges = [
            {
                "source_node_id": src,
                "target_node_id": dst,
                "edge_type": GRAPH_EDGE_TYPE,
                "summary": f"{src} imports {dst}",
                "raw_payload": {"importer": src, "imported": dst},
            }
            for src, dst in model["edges"]
        ]
        return {"nodes": nodes, "edges": edges, "modules": model["modules"]}

    def relationship_payload(
        self, model: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Convert the self-model into capability-relationship payload."""
        model = model or self.build()
        relationships = [
            {
                "source_capability_id": src,
                "target_capability_id": dst,
                "relationship_type": RELATIONSHIP_TYPE,
                "summary": f"{src} depends on {dst}",
            }
            for src, dst in model["edges"]
        ]
        return {
            "relationships": relationships,
            "known_capability_ids": model["modules"],
        }

    # ------------------------------------------------------------------
    # Populate (hand payloads to the existing engines)
    # ------------------------------------------------------------------

    def populate_graph(
        self,
        artifacts_root: str | None = None,
        model: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Populate the existing capability knowledge graph; return its report."""
        payload = self.graph_payload(model)
        engine = CapabilityKnowledgeGraphEngine(artifacts_root=artifacts_root)
        return engine.create(
            nodes=payload["nodes"],
            edges=payload["edges"],
            raw_metadata={"source": _SOURCE_TAG, "milestone": _MILESTONE_TAG},
        )

    def populate_relationships(
        self,
        artifacts_root: str | None = None,
        model: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Populate the existing capability relationships; return its report."""
        payload = self.relationship_payload(model)
        engine = CapabilityRelationshipEngine(artifacts_root=artifacts_root)
        return engine.create(
            relationships=payload["relationships"],
            known_capability_ids=payload["known_capability_ids"],
            raw_metadata={"source": _SOURCE_TAG, "milestone": _MILESTONE_TAG},
        )


# ---------------------------------------------------------------------------
# Queries over a populated graph report (answers come from the graph itself)
# ---------------------------------------------------------------------------


def graph_modules(report: dict[str, Any]) -> list[str]:
    """All module nodes in a populated graph report (sorted)."""
    return sorted(n.get("source_id", "") for n in report.get("nodes", []))


def graph_imports(report: dict[str, Any]) -> list[tuple[str, str]]:
    """All ``(importer, imported)`` edges in a populated graph report (sorted)."""
    return sorted(
        (e.get("source_node_id", ""), e.get("target_node_id", ""))
        for e in report.get("edges", [])
    )


def graph_isolated(report: dict[str, Any]) -> list[str]:
    """Modules with no import edges (orphan/island detection), sorted."""
    return sorted(report.get("orphan_node_ids", []))


def graph_dependencies(report: dict[str, Any], module: str) -> list[str]:
    """Modules that ``module`` imports (what it depends on), sorted."""
    return sorted(
        e.get("target_node_id", "")
        for e in report.get("edges", [])
        if e.get("source_node_id", "") == module
    )


def graph_dependents(report: dict[str, Any], module: str) -> list[str]:
    """Modules that import ``module`` (what depends on it), sorted."""
    return sorted(
        e.get("source_node_id", "")
        for e in report.get("edges", [])
        if e.get("target_node_id", "") == module
    )
