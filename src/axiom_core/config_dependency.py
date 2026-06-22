"""Configuration Dependency Framework v1.

Provides deterministic configuration dependency capabilities on top of batch
execution. Represents and validates dependencies between configuration objects,
scenarios, and execution steps.

Non-goals: no autonomous scheduling, no worker orchestration, no workflow
engines, no external graph systems.
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

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ConfigurationDependencyType(str, Enum):
    REQUIRES = "requires"
    BLOCKS = "blocks"
    RELATED_TO = "related_to"
    SUPERSEDES = "supersedes"


class ConfigurationDependencyStatus(str, Enum):
    ACTIVE = "active"
    SATISFIED = "satisfied"
    BLOCKED = "blocked"
    INVALID = "invalid"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ConfigurationDependency:
    """A dependency between two configuration objects."""

    dependency_id: str = ""
    source_id: str = ""
    target_id: str = ""
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
            "source_id": self.source_id,
            "target_id": self.target_id,
            "dependency_type": self.dependency_type,
            "status": self.status,
            "rationale": self.rationale,
            "created_at": self.created_at,
        }


@dataclass
class ConfigurationDependencyGraph:
    """A graph of configuration dependencies."""

    graph_id: str = ""
    dependencies: list[ConfigurationDependency] = field(default_factory=list)
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
class ConfigurationDependencyReport:
    """Report summarizing a dependency graph."""

    report_id: str = ""
    graph_id: str = ""
    dependency_summary: str = ""
    blocked_count: int = 0
    invalid_count: int = 0
    graph: ConfigurationDependencyGraph | None = None
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
            "dependency_summary": self.dependency_summary,
            "blocked_count": self.blocked_count,
            "invalid_count": self.invalid_count,
            "graph": self.graph.to_dict() if self.graph else None,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Dependency engine
# ---------------------------------------------------------------------------


class ConfigurationDependencyEngine:
    """Manages configuration dependencies deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._dep_dir = self._artifacts_root / "config_dependencies"
        self._dep_dir.mkdir(parents=True, exist_ok=True)

    def _safe_dep_path(self, report_id: str) -> Path:
        target = (self._dep_dir / report_id).resolve()
        sandbox = self._dep_dir.resolve()
        if not str(target).startswith(str(sandbox) + "/") and target != sandbox:
            raise ValueError(f"Resolved path escapes artifacts root: {report_id!r}")
        return target

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"{name} must not be empty or whitespace")
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(f"{name} must not contain '..', '/', or '\\': {value!r}")

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(
        self,
        dependencies: list[dict[str, Any]] | None = None,
        known_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a dependency graph from a list of dependency dicts."""
        dependencies = dependencies or []
        known_ids = set(known_ids) if known_ids is not None else None

        dep_objects: list[ConfigurationDependency] = []
        for dep_data in sorted(
            dependencies, key=lambda d: (d.get("source_id", ""), d.get("target_id", ""))
        ):
            dep = ConfigurationDependency(
                source_id=dep_data.get("source_id", ""),
                target_id=dep_data.get("target_id", ""),
                dependency_type=dep_data.get("dependency_type", "requires"),
                status=dep_data.get("status", "active"),
                rationale=dep_data.get("rationale", ""),
            )

            if known_ids is not None:
                if dep.source_id and dep.source_id not in known_ids:
                    dep.status = ConfigurationDependencyStatus.INVALID.value
                if dep.target_id and dep.target_id not in known_ids:
                    dep.status = ConfigurationDependencyStatus.INVALID.value

            dep_objects.append(dep)

        nodes: set[str] = set()
        for d in dep_objects:
            if d.source_id:
                nodes.add(d.source_id)
            if d.target_id:
                nodes.add(d.target_id)

        cycles = self._detect_cycles(dep_objects)
        if cycles:
            for dep in dep_objects:
                if dep.source_id in cycles or dep.target_id in cycles:
                    dep.status = ConfigurationDependencyStatus.BLOCKED.value

        graph = ConfigurationDependencyGraph(
            dependencies=dep_objects,
            node_count=len(nodes),
            edge_count=len(dep_objects),
        )

        blocked_count = sum(
            1 for d in dep_objects if d.status == ConfigurationDependencyStatus.BLOCKED.value
        )
        invalid_count = sum(
            1 for d in dep_objects if d.status == ConfigurationDependencyStatus.INVALID.value
        )

        summary = (
            f"Graph '{graph.graph_id}': "
            f"{graph.node_count} nodes, {graph.edge_count} edges, "
            f"{blocked_count} blocked, {invalid_count} invalid."
        )

        report = ConfigurationDependencyReport(
            graph_id=graph.graph_id,
            dependency_summary=summary,
            blocked_count=blocked_count,
            invalid_count=invalid_count,
            graph=graph,
        )

        self._persist_report(report)
        self._write_evidence(report)

        return report.to_dict()

    @staticmethod
    def _detect_cycles(deps: list[ConfigurationDependency]) -> set[str]:
        """Detect cycles using DFS. Returns node IDs involved in cycles."""
        adjacency: dict[str, list[str]] = {}
        for d in deps:
            if d.dependency_type in (
                ConfigurationDependencyType.REQUIRES.value,
                ConfigurationDependencyType.BLOCKS.value,
            ):
                adjacency.setdefault(d.source_id, []).append(d.target_id)
                if d.target_id not in adjacency:
                    adjacency[d.target_id] = []

        visited: set[str] = set()
        in_stack: set[str] = set()
        cycle_nodes: set[str] = set()

        def dfs(node: str, path: list[str]) -> None:
            if node in in_stack:
                idx = path.index(node) if node in path else 0
                cycle_nodes.update(path[idx:])
                return
            if node in visited:
                return
            visited.add(node)
            in_stack.add(node)
            path.append(node)
            for neighbor in adjacency.get(node, []):
                dfs(neighbor, path)
            path.pop()
            in_stack.discard(node)

        for node in list(adjacency.keys()):
            if node not in visited:
                dfs(node, [])

        return cycle_nodes

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        self._validate_id_segment(report_id, "report_id")
        return self._load_report(report_id)

    def list_reports(self) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        if not self._dep_dir.exists():
            return reports

        sandbox = self._dep_dir.resolve()
        for entry in self._dep_dir.iterdir():
            if not entry.is_dir():
                continue
            resolved = entry.resolve()
            if not str(resolved).startswith(str(sandbox) + "/") and resolved != sandbox:
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
            raise ValueError(f"Dependency report not found: {report_id}")
        return self._generate_summary(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_report(self, report: ConfigurationDependencyReport) -> None:
        report_dir = self._safe_dep_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def _load_report(self, report_id: str) -> dict[str, Any] | None:
        report_dir = self._safe_dep_path(report_id)
        report_file = report_dir / "report.json"
        if not report_file.exists():
            return None
        return json.loads(report_file.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def _write_evidence(self, report: ConfigurationDependencyReport) -> None:
        evidence_dir = self._safe_dep_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "graph_id": report.graph_id,
            "dependencies": (
                [d.to_dict() for d in report.graph.dependencies] if report.graph else []
            ),
        }
        (evidence_dir / "config_dependency_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        result_data = report.to_dict()
        (evidence_dir / "config_dependency_result.json").write_text(
            json.dumps(result_data, indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_summary(report.to_dict())
        (evidence_dir / "config_dependency_summary.md").write_text(
            md,
            encoding="utf-8",
        )

        passed = report.blocked_count == 0 and report.invalid_count == 0
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "graph_id": report.graph_id,
            "blocked_count": report.blocked_count,
            "invalid_count": report.invalid_count,
            "status": "passed" if passed else "failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _generate_summary(data: dict[str, Any]) -> str:
        lines: list[str] = []

        lines.append("# Configuration Dependency Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Graph ID: {data.get('graph_id', '')}")
        lines.append(f"- Summary: {data.get('dependency_summary', '')}")
        lines.append(f"- Blocked: {data.get('blocked_count', 0)}")
        lines.append(f"- Invalid: {data.get('invalid_count', 0)}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        graph = data.get("graph")
        if graph:
            lines.append("## Graph")
            lines.append("")
            lines.append(f"- Nodes: {graph.get('node_count', 0)}")
            lines.append(f"- Edges: {graph.get('edge_count', 0)}")
            lines.append("")

            deps = graph.get("dependencies", [])
            if deps:
                lines.append("## Dependencies")
                lines.append("")
                for dep in deps:
                    status = dep.get("status", "").upper()
                    dtype = dep.get("dependency_type", "")
                    lines.append(
                        f"- [{status}] {dep.get('source_id', '')} "
                        f"--{dtype}--> {dep.get('target_id', '')}"
                    )
                    if dep.get("rationale"):
                        lines.append(f"  Rationale: {dep['rationale']}")
                lines.append("")

        return "\n".join(lines)
