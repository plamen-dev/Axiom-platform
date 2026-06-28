"""Work Item Dependency Framework v1.

Provides a deterministic dependency graph on top of work queues.
Represents relationships and blocking dependencies between work items,
with cycle detection and evidence bundles.

Non-goals: no schedulers, no worker orchestration, no autonomous planning.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from axiom_core.artifact_paths import is_within_sandbox

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class WorkDependencyType(str, Enum):
    REQUIRES = "requires"
    BLOCKS = "blocks"
    RELATED_TO = "related_to"
    SUPERSEDES = "supersedes"


class WorkDependencyStatus(str, Enum):
    ACTIVE = "active"
    SATISFIED = "satisfied"
    BLOCKED = "blocked"
    INVALID = "invalid"


_VALID_TYPES = {t.value for t in WorkDependencyType}
_VALID_STATUSES = {s.value for s in WorkDependencyStatus}

# Dependency types that impose an ordering edge for cycle detection.
_ORDERING_TYPES = {
    WorkDependencyType.REQUIRES.value,
    WorkDependencyType.BLOCKS.value,
    WorkDependencyType.SUPERSEDES.value,
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class WorkDependency:
    """A single directed dependency between two work items."""

    dependency_id: str = ""
    source_work_id: str = ""
    target_work_id: str = ""
    dependency_type: str = "requires"
    status: str = "active"
    rationale: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.dependency_id:
            self.dependency_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "dependency_id": self.dependency_id,
            "source_work_id": self.source_work_id,
            "target_work_id": self.target_work_id,
            "dependency_type": self.dependency_type,
            "status": self.status,
            "rationale": self.rationale,
            "created_at": self.created_at,
        }


@dataclass
class WorkDependencyGraph:
    """A graph of work dependencies."""

    graph_id: str = ""
    dependencies: list[WorkDependency] = field(default_factory=list)
    node_count: int = 0
    edge_count: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.graph_id:
            self.graph_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "dependencies": [d.to_dict() for d in self.dependencies],
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "created_at": self.created_at,
        }


@dataclass
class WorkDependencyReport:
    """Report summarizing a dependency graph."""

    report_id: str = ""
    graph_id: str = ""
    blocked_count: int = 0
    invalid_count: int = 0
    summary: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "graph_id": self.graph_id,
            "blocked_count": self.blocked_count,
            "invalid_count": self.invalid_count,
            "summary": self.summary,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------


def _ordering_adjacency(dependencies: list[WorkDependency]) -> dict[str, list[str]]:
    """Build a sorted adjacency map over ordering edge types only."""
    adjacency: dict[str, list[str]] = {}
    for dep in dependencies:
        if dep.dependency_type not in _ORDERING_TYPES:
            continue
        adjacency.setdefault(dep.source_work_id, []).append(dep.target_work_id)
        adjacency.setdefault(dep.target_work_id, [])
    for node in adjacency:
        adjacency[node].sort()
    return adjacency


def _reachable(adjacency: dict[str, list[str]], start: str) -> set[str]:
    """Return the set of nodes reachable from ``start`` (excluding start itself
    unless it is reachable via a cycle)."""
    seen: set[str] = set()
    stack = list(adjacency.get(start, []))
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adjacency.get(node, []))
    return seen


def cycle_dependency_ids(dependencies: list[WorkDependency]) -> set[str]:
    """Return the ids of every ordering dependency that participates in a cycle.

    An ordering edge (u -> v) lies on a cycle iff ``u`` is reachable from ``v``.
    This covers multiple independent cycles, not just the first one found.
    """
    adjacency = _ordering_adjacency(dependencies)
    cycle_ids: set[str] = set()
    for dep in dependencies:
        if dep.dependency_type not in _ORDERING_TYPES:
            continue
        if dep.source_work_id in _reachable(adjacency, dep.target_work_id):
            cycle_ids.add(dep.dependency_id)
    return cycle_ids


def detect_cycle(dependencies: list[WorkDependency]) -> list[str]:
    """Detect a representative cycle among ordering dependencies.

    Returns a list of work_ids forming a cycle (deterministic), or an empty
    list if the graph is acyclic. Only ordering edge types contribute. Use
    :func:`cycle_dependency_ids` to enumerate every edge in any cycle.
    """
    adjacency = _ordering_adjacency(dependencies)

    white, gray, black = 0, 1, 2
    color: dict[str, int] = {node: white for node in adjacency}

    def visit(node: str, stack: list[str]) -> list[str]:
        color[node] = gray
        stack.append(node)
        for neighbour in adjacency[node]:
            if color.get(neighbour, white) == gray:
                idx = stack.index(neighbour)
                return stack[idx:] + [neighbour]
            if color.get(neighbour, white) == white:
                found = visit(neighbour, stack)
                if found:
                    return found
        color[node] = black
        stack.pop()
        return []

    for node in sorted(adjacency):
        if color[node] == white:
            cycle = visit(node, [])
            if cycle:
                return cycle
    return []


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class WorkDependencyEngine:
    """Manages work dependency graphs deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "work_dependencies"
        self._report_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"{name} must not be empty or whitespace")
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(f"{name} must not contain '..', '/', or '\\': {value!r}")

    def _safe_path(self, report_id: str) -> Path:
        target = (self._report_dir / report_id).resolve()
        sandbox = self._report_dir.resolve()
        if not is_within_sandbox(target, sandbox):
            raise ValueError(f"Resolved path escapes artifacts root: {report_id!r}")
        return target

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(
        self, dependencies: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Create a dependency graph report from a list of dependencies."""
        dependencies = dependencies or []

        dep_objects: list[WorkDependency] = []
        for d_data in dependencies:
            dep_type = d_data.get("dependency_type", "requires")
            if dep_type not in _VALID_TYPES:
                raise ValueError(
                    f"Invalid dependency_type: {dep_type!r}. Valid: {sorted(_VALID_TYPES)}"
                )
            status = d_data.get("status", "active")
            if status not in _VALID_STATUSES:
                raise ValueError(
                    f"Invalid status: {status!r}. Valid: {sorted(_VALID_STATUSES)}"
                )
            source = d_data.get("source_work_id", "")
            target = d_data.get("target_work_id", "")
            if not source or not target:
                raise ValueError(
                    "source_work_id and target_work_id are required"
                )
            dep_objects.append(
                WorkDependency(
                    source_work_id=source,
                    target_work_id=target,
                    dependency_type=dep_type,
                    status=status,
                    rationale=d_data.get("rationale", ""),
                    created_at=d_data.get("created_at", ""),
                )
            )

        # Deterministic ordering by source, target, type, then dependency_id.
        dep_objects.sort(
            key=lambda d: (
                d.source_work_id,
                d.target_work_id,
                d.dependency_type,
                d.dependency_id,
            )
        )

        cycle = detect_cycle(dep_objects)
        # Every dependency participating in any cycle is marked invalid, not
        # only those in the first cycle discovered.
        cycle_ids = cycle_dependency_ids(dep_objects)
        for dep in dep_objects:
            if dep.dependency_id in cycle_ids:
                dep.status = "invalid"

        nodes: set[str] = set()
        for dep in dep_objects:
            nodes.add(dep.source_work_id)
            nodes.add(dep.target_work_id)

        graph = WorkDependencyGraph(
            dependencies=dep_objects,
            node_count=len(nodes),
            edge_count=len(dep_objects),
        )

        blocked_count = sum(1 for d in dep_objects if d.status == "blocked")
        invalid_count = sum(1 for d in dep_objects if d.status == "invalid")

        summary_parts = [
            f"{graph.node_count} nodes",
            f"{graph.edge_count} edges",
            f"{blocked_count} blocked",
            f"{invalid_count} invalid",
        ]
        if cycle:
            summary_parts.append("cycle detected: " + " -> ".join(cycle))
        summary = ", ".join(summary_parts)

        report = WorkDependencyReport(
            graph_id=graph.graph_id,
            blocked_count=blocked_count,
            invalid_count=invalid_count,
            summary=summary,
        )

        self._persist(report, graph, cycle)
        self._write_evidence(report, graph, cycle)

        result = report.to_dict()
        result["graph"] = graph.to_dict()
        result["cycle"] = cycle
        result["has_cycle"] = bool(cycle)
        return result

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
            if not is_within_sandbox(resolved, sandbox):
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

    def export_report(self, report_id: str) -> str:
        self._validate_id_segment(report_id, "report_id")
        data = self._load_report(report_id)
        if data is None:
            raise ValueError(f"Work dependency report not found: {report_id}")
        return self._generate_export_md(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(
        self,
        report: WorkDependencyReport,
        graph: WorkDependencyGraph,
        cycle: list[str],
    ) -> None:
        report_dir = self._safe_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)

        data = report.to_dict()
        data["graph"] = graph.to_dict()
        data["cycle"] = cycle
        data["has_cycle"] = bool(cycle)

        (report_dir / "report.json").write_text(
            json.dumps(data, indent=2, default=str),
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

    def _write_evidence(
        self,
        report: WorkDependencyReport,
        graph: WorkDependencyGraph,
        cycle: list[str],
    ) -> None:
        evidence_dir = self._safe_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "dependencies": [d.to_dict() for d in graph.dependencies]
        }
        (evidence_dir / "work_dependency_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        result_data = report.to_dict()
        result_data["graph"] = graph.to_dict()
        result_data["cycle"] = cycle
        result_data["has_cycle"] = bool(cycle)
        (evidence_dir / "work_dependency_result.json").write_text(
            json.dumps(result_data, indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_export_md(result_data)
        (evidence_dir / "work_dependency_summary.md").write_text(md, encoding="utf-8")

        # A graph passes when there are no cycles and no invalid dependencies.
        passed = not cycle and report.invalid_count == 0
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "graph_id": report.graph_id,
            "edge_count": graph.edge_count,
            "blocked_count": report.blocked_count,
            "invalid_count": report.invalid_count,
            "has_cycle": bool(cycle),
            "cycle": cycle,
            "status": "passed" if passed else "failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _generate_export_md(data: dict[str, Any]) -> str:
        lines: list[str] = []

        lines.append("# Work Dependency Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Graph ID: {data.get('graph_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append(f"- Summary: {data.get('summary', '')}")
        lines.append("")

        graph = data.get("graph", {})
        lines.append("## Graph")
        lines.append("")
        lines.append(f"- Nodes: {graph.get('node_count', 0)}")
        lines.append(f"- Edges: {graph.get('edge_count', 0)}")
        lines.append(f"- Blocked: {data.get('blocked_count', 0)}")
        lines.append(f"- Invalid: {data.get('invalid_count', 0)}")
        lines.append(f"- Has Cycle: {data.get('has_cycle', False)}")
        cycle = data.get("cycle", [])
        if cycle:
            lines.append(f"- Cycle: {' -> '.join(cycle)}")
        lines.append("")

        dependencies = graph.get("dependencies", [])
        if dependencies:
            lines.append("## Dependencies")
            lines.append("")
            for d in dependencies:
                dep_type = d.get("dependency_type", "").upper()
                status = d.get("status", "").upper()
                source = d.get("source_work_id", "")
                target = d.get("target_work_id", "")
                rationale = d.get("rationale", "")
                rat_part = f": {rationale}" if rationale else ""
                lines.append(
                    f"- [{dep_type}] [{status}] {source} -> {target}{rat_part}"
                )
            lines.append("")

        return "\n".join(lines)
