"""Capability Knowledge Graph Framework v1.

The first graph-ready capability knowledge layer. Where the Global Capability
Registry establishes identity, the Capability Event Timeline establishes memory,
the Capability Summary establishes understanding, and the Relationship/Impact/
File/Validation layers establish context, meaning, location, and verification,
this layer unifies them into a deterministic set of graph *nodes* and *edges*.

Per report it captures a deterministic, append-only graph: nodes that reference
the originating capability-knowledge objects (by node_type + source_id) and
edges that connect them, aggregated with node/edge type counts, duplicate node
and edge detection, and orphan-node detection (nodes connected by no edge),
with preserved raw payloads and schema versioning.

It is deliberately *structure only*. Non-goals: no graph database, no graph
query language, no visualization, no dashboard, no Operator Cockpit UI, no
automatic graph discovery, no autonomous reasoning, no network calls, no
architecture changes. The upstream knowledge layers are consumed read-only;
nothing is mutated.
"""

from __future__ import annotations

import csv
import io
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CapabilityGraphNodeType(str, Enum):
    CAPABILITY = "CAPABILITY"
    EVENT = "EVENT"
    SUMMARY = "SUMMARY"
    RELATIONSHIP = "RELATIONSHIP"
    IMPACT = "IMPACT"
    FILE = "FILE"
    VALIDATION = "VALIDATION"
    ARTIFACT = "ARTIFACT"
    WORKER = "WORKER"
    UNKNOWN = "UNKNOWN"


class CapabilityGraphEdgeType(str, Enum):
    BUILDS_ON = "BUILDS_ON"
    ENABLES = "ENABLES"
    RELATES_TO = "RELATES_TO"
    AFFECTS = "AFFECTS"
    VALIDATES = "VALIDATES"
    TOUCHES_FILE = "TOUCHES_FILE"
    PRODUCED_EVENT = "PRODUCED_EVENT"
    HAS_SUMMARY = "HAS_SUMMARY"
    HAS_IMPACT = "HAS_IMPACT"
    HAS_ARTIFACT = "HAS_ARTIFACT"
    CREATED_BY = "CREATED_BY"
    UNKNOWN = "UNKNOWN"


_VALID_NODE_TYPES = {t.value for t in CapabilityGraphNodeType}
_VALID_EDGE_TYPES = {t.value for t in CapabilityGraphEdgeType}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class CapabilityGraphNode:
    """A single node in the capability knowledge graph."""

    node_id: str = ""
    node_type: str = ""
    source_id: str = ""
    label: str = ""
    summary: str = ""
    created_at: str = ""
    schema_version: str = SCHEMA_VERSION
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.node_id:
            self.node_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "source_id": self.source_id,
            "label": self.label,
            "summary": self.summary,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "raw_payload": dict(self.raw_payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityGraphNode:
        return cls(
            node_id=data.get("node_id", ""),
            node_type=data.get("node_type", ""),
            source_id=data.get("source_id", ""),
            label=data.get("label", ""),
            summary=data.get("summary", ""),
            created_at=data.get("created_at", ""),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            raw_payload=dict(data.get("raw_payload", {})),
        )


@dataclass
class CapabilityGraphEdge:
    """A single directed edge in the capability knowledge graph."""

    edge_id: str = ""
    source_node_id: str = ""
    target_node_id: str = ""
    edge_type: str = ""
    summary: str = ""
    created_at: str = ""
    schema_version: str = SCHEMA_VERSION
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.edge_id:
            self.edge_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "edge_type": self.edge_type,
            "summary": self.summary,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "raw_payload": dict(self.raw_payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityGraphEdge:
        return cls(
            edge_id=data.get("edge_id", ""),
            source_node_id=data.get("source_node_id", ""),
            target_node_id=data.get("target_node_id", ""),
            edge_type=data.get("edge_type", ""),
            summary=data.get("summary", ""),
            created_at=data.get("created_at", ""),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            raw_payload=dict(data.get("raw_payload", {})),
        )


@dataclass
class CapabilityKnowledgeGraph:
    """A deterministic graph unifying capability knowledge nodes and edges."""

    graph_id: str = ""
    nodes: list[CapabilityGraphNode] = field(default_factory=list)
    edges: list[CapabilityGraphEdge] = field(default_factory=list)
    created_at: str = ""
    schema_version: str = SCHEMA_VERSION
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.graph_id:
            self.graph_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "raw_payload": dict(self.raw_payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityKnowledgeGraph:
        return cls(
            graph_id=data.get("graph_id", ""),
            nodes=[
                CapabilityGraphNode.from_dict(n)
                for n in data.get("nodes", [])
            ],
            edges=[
                CapabilityGraphEdge.from_dict(e)
                for e in data.get("edges", [])
            ],
            created_at=data.get("created_at", ""),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            raw_payload=dict(data.get("raw_payload", {})),
        )


@dataclass
class CapabilityKnowledgeGraphReport:
    """A deterministic, append-only capability knowledge graph report."""

    report_id: str = ""
    graph_id: str = ""
    nodes: list[CapabilityGraphNode] = field(default_factory=list)
    edges: list[CapabilityGraphEdge] = field(default_factory=list)
    node_count: int = 0
    edge_count: int = 0
    node_type_counts: dict[str, int] = field(default_factory=dict)
    edge_type_counts: dict[str, int] = field(default_factory=dict)
    duplicate_node_count: int = 0
    duplicate_edge_count: int = 0
    orphan_node_count: int = 0
    orphan_node_ids: list[str] = field(default_factory=list)
    created_at: str = ""
    graph_raw_payload: dict[str, Any] = field(default_factory=dict)
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.graph_id:
            self.graph_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        graph = CapabilityKnowledgeGraph(
            graph_id=self.graph_id,
            nodes=self.nodes,
            edges=self.edges,
            created_at=self.created_at,
            schema_version=self.schema_version,
            raw_payload=dict(self.graph_raw_payload),
        )
        return {
            "report_id": self.report_id,
            "graph_id": self.graph_id,
            "graph": graph.to_dict(),
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "node_type_counts": dict(self.node_type_counts),
            "edge_type_counts": dict(self.edge_type_counts),
            "duplicate_node_count": self.duplicate_node_count,
            "duplicate_edge_count": self.duplicate_edge_count,
            "orphan_node_count": self.orphan_node_count,
            "orphan_node_ids": list(self.orphan_node_ids),
            "created_at": self.created_at,
            "raw_metadata": dict(self.raw_metadata),
            "schema_version": self.schema_version,
        }


@dataclass
class CapabilityKnowledgeGraphEvidence:
    """Evidence record for a capability knowledge graph report."""

    evidence_id: str = ""
    report_id: str = ""
    summary: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.evidence_id:
            self.evidence_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "report_id": self.report_id,
            "summary": self.summary,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class CapabilityKnowledgeGraphEngine:
    """Manages capability knowledge graph reports deterministically.

    Nodes and edges are validated, deduplicated, ordered deterministically, and
    aggregated with node/edge type counts and orphan-node detection. Reports are
    append-only. The upstream capability-knowledge layers are *consumed*
    read-only; nothing is mutated.
    """

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "capability_knowledge_graph"
        self._report_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Path safety (for report_id only)
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"{name} must not be empty or whitespace")
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(
                f"{name} must not contain '..', '/', or '\\': {value!r}"
            )

    def _safe_path(self, report_id: str) -> Path:
        target = (self._report_dir / report_id).resolve()
        sandbox = self._report_dir.resolve()
        if not str(target).startswith(str(sandbox) + "/") and target != sandbox:
            raise ValueError(
                f"Resolved path escapes artifacts root: {report_id!r}"
            )
        return target

    # ------------------------------------------------------------------
    # Sort keys
    # ------------------------------------------------------------------

    @staticmethod
    def _node_sort_key(n: CapabilityGraphNode) -> tuple:
        return (n.node_type, n.source_id, n.label, n.node_id)

    @staticmethod
    def _edge_sort_key(e: CapabilityGraphEdge) -> tuple:
        return (
            e.source_node_id,
            e.target_node_id,
            e.edge_type,
            e.edge_id,
        )

    # ------------------------------------------------------------------
    # Building / validation
    # ------------------------------------------------------------------

    @staticmethod
    def _build_node(data: dict[str, Any]) -> CapabilityGraphNode:
        source_id = data.get("source_id", "")
        if not source_id or not str(source_id).strip():
            raise ValueError("source_id is required for a node")

        ntype_raw = data.get("node_type", "")
        if not ntype_raw or not str(ntype_raw).strip():
            raise ValueError("node_type is required for a node")
        ntype = str(ntype_raw).strip().upper()
        if ntype not in _VALID_NODE_TYPES:
            raise ValueError(
                f"Invalid node_type: {ntype_raw!r}. "
                f"Valid: {sorted(_VALID_NODE_TYPES)}"
            )

        normalized = dict(data)
        normalized["source_id"] = str(source_id)
        normalized["node_type"] = ntype
        return CapabilityGraphNode.from_dict(normalized)

    @staticmethod
    def _build_edge(data: dict[str, Any]) -> CapabilityGraphEdge:
        source_node_id = data.get("source_node_id", "")
        if not source_node_id or not str(source_node_id).strip():
            raise ValueError("source_node_id is required for an edge")
        target_node_id = data.get("target_node_id", "")
        if not target_node_id or not str(target_node_id).strip():
            raise ValueError("target_node_id is required for an edge")

        etype_raw = data.get("edge_type", "")
        if not etype_raw or not str(etype_raw).strip():
            raise ValueError("edge_type is required for an edge")
        etype = str(etype_raw).strip().upper()
        if etype not in _VALID_EDGE_TYPES:
            raise ValueError(
                f"Invalid edge_type: {etype_raw!r}. "
                f"Valid: {sorted(_VALID_EDGE_TYPES)}"
            )

        normalized = dict(data)
        normalized["source_node_id"] = str(source_node_id)
        normalized["target_node_id"] = str(target_node_id)
        normalized["edge_type"] = etype
        return CapabilityGraphEdge.from_dict(normalized)

    def _assemble(
        self,
        report: CapabilityKnowledgeGraphReport,
    ) -> dict[str, Any]:
        # Duplicate node detection: same (node_type, source_id).
        # Keep first; count duplicates; drop the rest.
        seen_nodes: set[tuple[str, str]] = set()
        deduped_nodes: list[CapabilityGraphNode] = []
        duplicate_nodes = 0
        for n in sorted(report.nodes, key=self._node_sort_key):
            key = (n.node_type, n.source_id)
            if key in seen_nodes:
                duplicate_nodes += 1
                continue
            seen_nodes.add(key)
            deduped_nodes.append(n)
        report.nodes = deduped_nodes
        report.duplicate_node_count = duplicate_nodes

        # Duplicate edge detection: same
        # (source_node_id, target_node_id, edge_type). Keep first; drop rest.
        seen_edges: set[tuple[str, str, str]] = set()
        deduped_edges: list[CapabilityGraphEdge] = []
        duplicate_edges = 0
        for e in sorted(report.edges, key=self._edge_sort_key):
            key = (e.source_node_id, e.target_node_id, e.edge_type)
            if key in seen_edges:
                duplicate_edges += 1
                continue
            seen_edges.add(key)
            deduped_edges.append(e)
        report.edges = deduped_edges
        report.duplicate_edge_count = duplicate_edges

        # Orphan node detection: nodes connected by no surviving edge.
        connected: set[str] = set()
        for e in report.edges:
            connected.add(e.source_node_id)
            connected.add(e.target_node_id)
        orphan_ids = sorted(
            n.node_id for n in report.nodes if n.node_id not in connected
        )
        report.orphan_node_ids = orphan_ids
        report.orphan_node_count = len(orphan_ids)

        node_type_counts: dict[str, int] = {}
        for n in report.nodes:
            node_type_counts[n.node_type] = (
                node_type_counts.get(n.node_type, 0) + 1
            )
        edge_type_counts: dict[str, int] = {}
        for e in report.edges:
            edge_type_counts[e.edge_type] = (
                edge_type_counts.get(e.edge_type, 0) + 1
            )

        report.node_type_counts = {
            k: node_type_counts[k] for k in sorted(node_type_counts)
        }
        report.edge_type_counts = {
            k: edge_type_counts[k] for k in sorted(edge_type_counts)
        }
        report.node_count = len(report.nodes)
        report.edge_count = len(report.edges)

        return report.to_dict()

    # ------------------------------------------------------------------
    # Create / Append (append-only)
    # ------------------------------------------------------------------

    def create(
        self,
        nodes: list[dict[str, Any]] | None = None,
        edges: list[dict[str, Any]] | None = None,
        graph_raw_payload: dict[str, Any] | None = None,
        raw_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new capability knowledge graph report."""
        report = CapabilityKnowledgeGraphReport(
            graph_raw_payload=dict(graph_raw_payload or {}),
            raw_metadata=dict(raw_metadata or {}),
        )
        report.nodes = [self._build_node(n) for n in (nodes or [])]
        report.edges = [self._build_edge(e) for e in (edges or [])]
        assembled = self._assemble(report)
        self._persist(assembled)
        self._write_evidence(assembled)
        return assembled

    def append(
        self,
        report_id: str,
        nodes: list[dict[str, Any]] | None = None,
        edges: list[dict[str, Any]] | None = None,
        graph_raw_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append nodes/edges to an existing report (append-only)."""
        self._validate_id_segment(report_id, "report_id")
        existing = self._load_report(report_id)
        if existing is None:
            raise ValueError(f"Report not found: {report_id}")

        merged_payload = dict(
            existing.get("graph", {}).get("raw_payload", {})
        )
        merged_payload.update(graph_raw_payload or {})

        report = CapabilityKnowledgeGraphReport(
            report_id=existing["report_id"],
            graph_id=existing.get("graph_id", ""),
            created_at=existing.get("created_at", ""),
            graph_raw_payload=merged_payload,
            raw_metadata=dict(existing.get("raw_metadata", {})),
            schema_version=existing.get("schema_version", SCHEMA_VERSION),
        )
        report.nodes = [
            CapabilityGraphNode.from_dict(n)
            for n in existing.get("nodes", [])
        ]
        report.nodes.extend(self._build_node(n) for n in (nodes or []))
        report.edges = [
            CapabilityGraphEdge.from_dict(e)
            for e in existing.get("edges", [])
        ]
        report.edges.extend(self._build_edge(e) for e in (edges or []))

        assembled = self._assemble(report)
        self._persist(assembled)
        self._write_evidence(assembled)
        return assembled

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        self._validate_id_segment(report_id, "report_id")
        return self._load_report(report_id)

    def list_reports(self) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        if not self._report_dir.exists():
            return reports

        sandbox = self._report_dir.resolve()
        for entry in self._report_dir.iterdir():
            if not entry.is_dir():
                continue
            resolved = entry.resolve()
            if (
                not str(resolved).startswith(str(sandbox) + "/")
                and resolved != sandbox
            ):
                continue
            report_file = entry / "report.json"
            if not report_file.exists():
                continue
            try:
                data = json.loads(report_file.read_text(encoding="utf-8"))
                reports.append(data)
            except (json.JSONDecodeError, OSError):
                continue

        reports.sort(key=lambda r: r.get("created_at", ""))
        return reports

    def export_report(self, report_id: str, fmt: str = "markdown") -> str:
        self._validate_id_segment(report_id, "report_id")
        data = self._load_report(report_id)
        if data is None:
            raise ValueError(f"Report not found: {report_id}")
        fmt = (fmt or "markdown").lower()
        if fmt == "json":
            return json.dumps(data, indent=2, default=str)
        if fmt == "csv":
            return self._generate_export_csv(data)
        if fmt == "markdown":
            return self._generate_export_md(data)
        raise ValueError(
            f"Invalid export format: {fmt!r}. "
            "Valid: ['csv', 'json', 'markdown']"
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, report: dict[str, Any]) -> None:
        report_dir = self._safe_path(report["report_id"])
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

    def _load_report(self, report_id: str) -> dict[str, Any] | None:
        report_dir = self._safe_path(report_id)
        report_file = report_dir / "report.json"
        if not report_file.exists():
            return None
        return json.loads(report_file.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def _write_evidence(self, report: dict[str, Any]) -> None:
        evidence_dir = self._safe_path(report["report_id"])
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "report_id": report["report_id"],
            "graph_id": report.get("graph_id", ""),
            "nodes": report.get("nodes", []),
            "edges": report.get("edges", []),
            "raw_metadata": report.get("raw_metadata", {}),
        }
        (evidence_dir / "capability_graph_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "capability_graph_result.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "capability_graph_summary.md").write_text(
            self._generate_export_md(report), encoding="utf-8"
        )

        node_count = report.get("node_count", 0)
        edge_count = report.get("edge_count", 0)
        duplicate_node_count = report.get("duplicate_node_count", 0)
        duplicate_edge_count = report.get("duplicate_edge_count", 0)
        orphan_node_count = report.get("orphan_node_count", 0)
        evidence = CapabilityKnowledgeGraphEvidence(
            report_id=report["report_id"],
            summary=(
                f"{node_count} node(s), "
                f"{edge_count} edge(s), "
                f"{orphan_node_count} orphan(s), "
                f"{duplicate_node_count} duplicate node(s), "
                f"{duplicate_edge_count} duplicate edge(s)"
            ),
        )

        # A report passes when it carries at least one node, no duplicate nodes
        # or edges were detected, and no nodes are orphaned.
        passed = (
            node_count > 0
            and duplicate_node_count == 0
            and duplicate_edge_count == 0
            and orphan_node_count == 0
        )
        pass_fail = {
            "passed": passed,
            "report_id": report["report_id"],
            "graph_id": report.get("graph_id", ""),
            "evidence_id": evidence.evidence_id,
            "node_count": node_count,
            "edge_count": edge_count,
            "duplicate_node_count": duplicate_node_count,
            "duplicate_edge_count": duplicate_edge_count,
            "orphan_node_count": orphan_node_count,
            "node_type_counts": dict(report.get("node_type_counts", {})),
            "edge_type_counts": dict(report.get("edge_type_counts", {})),
            "schema_version": report.get("schema_version", SCHEMA_VERSION),
            "status": "passed" if passed else "failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Exporters
    # ------------------------------------------------------------------

    def _generate_export_md(self, data: dict[str, Any]) -> str:
        lines: list[str] = []

        lines.append("# Capability Knowledge Graph Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Graph ID: {data.get('graph_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append(f"- Schema Version: {data.get('schema_version', '')}")
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Nodes: {data.get('node_count', 0)}")
        lines.append(f"- Edges: {data.get('edge_count', 0)}")
        lines.append(f"- Orphan Nodes: {data.get('orphan_node_count', 0)}")
        lines.append(
            f"- Duplicate Nodes: {data.get('duplicate_node_count', 0)}"
        )
        lines.append(
            f"- Duplicate Edges: {data.get('duplicate_edge_count', 0)}"
        )
        lines.append("")

        node_type_counts = data.get("node_type_counts", {})
        lines.append("## Node Type Counts")
        lines.append("")
        for ntype in sorted(node_type_counts):
            lines.append(f"- {ntype}: {node_type_counts[ntype]}")
        lines.append("")

        edge_type_counts = data.get("edge_type_counts", {})
        lines.append("## Edge Type Counts")
        lines.append("")
        for etype in sorted(edge_type_counts):
            lines.append(f"- {etype}: {edge_type_counts[etype]}")
        lines.append("")

        lines.append("## Nodes")
        lines.append("")
        for n in data.get("nodes", []):
            ntype = n.get("node_type", "")
            source_id = n.get("source_id", "")
            label = n.get("label", "")
            lines.append(f"- [{ntype}] [{source_id}] {label}")
        lines.append("")

        lines.append("## Edges")
        lines.append("")
        for e in data.get("edges", []):
            src = e.get("source_node_id", "")
            tgt = e.get("target_node_id", "")
            etype = e.get("edge_type", "")
            lines.append(f"- [{src}] --[{etype}]--> [{tgt}]")
        lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _generate_export_csv(data: dict[str, Any]) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "record_kind",
                "node_id",
                "node_type",
                "source_id",
                "label",
                "edge_id",
                "source_node_id",
                "target_node_id",
                "edge_type",
                "summary",
            ]
        )
        for n in data.get("nodes", []):
            writer.writerow(
                [
                    "node",
                    n.get("node_id", ""),
                    n.get("node_type", ""),
                    n.get("source_id", ""),
                    n.get("label", ""),
                    "",
                    "",
                    "",
                    "",
                    n.get("summary", ""),
                ]
            )
        for e in data.get("edges", []):
            writer.writerow(
                [
                    "edge",
                    "",
                    "",
                    "",
                    "",
                    e.get("edge_id", ""),
                    e.get("source_node_id", ""),
                    e.get("target_node_id", ""),
                    e.get("edge_type", ""),
                    e.get("summary", ""),
                ]
            )
        return buf.getvalue()
