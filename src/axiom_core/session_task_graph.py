"""Session Task Graph v1 — durable task dependency tracking.

Task graphs are first-class objects representing task dependencies and
relationships inside an autonomous coding session.  They provide durable
structure and traceability without executing tasks or performing scheduling.

Non-goals: no automatic scheduling, no task execution, no approvals,
no workflow orchestration.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SessionTaskType(str, Enum):
    """Type of session task."""

    IMPLEMENTATION = "implementation"
    VALIDATION = "validation"
    REVIEW = "review"
    REPAIR = "repair"
    REPORTING = "reporting"
    OTHER = "other"


class SessionTaskStatus(str, Enum):
    """Status of a session task."""

    CREATED = "created"
    READY = "ready"
    BLOCKED = "blocked"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class DependencyType(str, Enum):
    """Type of task dependency."""

    PARENT_CHILD = "parent_child"
    REQUIRES = "requires"
    BLOCKS = "blocks"
    RELATED = "related"


# Status ranking for deterministic sorting
_STATUS_RANK: dict[str, int] = {
    SessionTaskStatus.BLOCKED.value: 0,
    SessionTaskStatus.IN_PROGRESS.value: 1,
    SessionTaskStatus.READY.value: 2,
    SessionTaskStatus.CREATED.value: 3,
    SessionTaskStatus.COMPLETED.value: 4,
    SessionTaskStatus.FAILED.value: 5,
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SessionTask:
    """A durable session task artifact."""

    task_id: str = ""
    parent_task_id: str = ""
    title: str = ""
    description: str = ""
    task_type: str = "other"
    status: str = "created"
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.task_id:
            self.task_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "parent_task_id": self.parent_task_id,
            "title": self.title,
            "description": self.description,
            "task_type": self.task_type,
            "status": self.status,
            "created_at": self.created_at,
        }


@dataclass
class SessionTaskDependency:
    """A durable task dependency record."""

    dependency_id: str = ""
    source_task_id: str = ""
    target_task_id: str = ""
    dependency_type: str = "related"
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.dependency_id:
            self.dependency_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "dependency_id": self.dependency_id,
            "source_task_id": self.source_task_id,
            "target_task_id": self.target_task_id,
            "dependency_type": self.dependency_type,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Core registry
# ---------------------------------------------------------------------------


class SessionTaskGraphRegistry:
    """Durable registry for session task graph artifacts."""

    def __init__(
        self,
        artifacts_root: str | None = None,
    ) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._tasks_dir = self._artifacts_root / "session_tasks"
        self._tasks_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"{name} must not be empty or whitespace")
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(
                f"{name} must not contain '..', '/', or '\\': {value!r}"
            )

    def _safe_task_path(self, task_id: str) -> Path:
        """Resolve and validate the task directory stays inside the sandbox."""
        target = (self._tasks_dir / task_id).resolve()
        sandbox = self._tasks_dir.resolve()
        if not str(target).startswith(str(sandbox) + "/") and target != sandbox:
            raise ValueError(
                f"Resolved path escapes artifacts root: {task_id!r}"
            )
        return target

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    def create_task(
        self,
        title: str,
        parent_task_id: str = "",
        description: str = "",
        task_type: str = "",
        status: str = "",
    ) -> dict[str, Any]:
        """Create a new session task."""
        if task_type:
            valid_types = {t.value for t in SessionTaskType}
            if task_type not in valid_types:
                raise ValueError(
                    f"Invalid task_type: {task_type!r}. "
                    f"Must be one of: {sorted(valid_types)}"
                )
        if status:
            valid_statuses = {s.value for s in SessionTaskStatus}
            if status not in valid_statuses:
                raise ValueError(
                    f"Invalid status: {status!r}. "
                    f"Must be one of: {sorted(valid_statuses)}"
                )

        task = SessionTask(
            title=title,
            parent_task_id=parent_task_id,
            description=description,
            task_type=task_type or SessionTaskType.OTHER.value,
            status=status or SessionTaskStatus.CREATED.value,
        )
        self._persist_task(task)
        return task.to_dict()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Get a session task by ID."""
        self._validate_id_segment(task_id, "task_id")
        return self._load_task(task_id)

    def list_tasks(
        self,
        task_type: str = "",
        status: str = "",
        parent_task_id: str = "",
    ) -> list[dict[str, Any]]:
        """List all session tasks with optional filters."""
        tasks: list[dict[str, Any]] = []
        if not self._tasks_dir.exists():
            return tasks

        sandbox = self._tasks_dir.resolve()
        for entry in self._tasks_dir.iterdir():
            if not entry.is_dir():
                continue
            resolved = entry.resolve()
            if not str(resolved).startswith(str(sandbox) + "/") and resolved != sandbox:
                continue
            task_file = entry / "task.json"
            if not task_file.exists():
                continue
            try:
                data = json.loads(task_file.read_text(encoding="utf-8"))
                if task_type and data.get("task_type") != task_type:
                    continue
                if status and data.get("status") != status:
                    continue
                if parent_task_id and data.get("parent_task_id") != parent_task_id:
                    continue
                tasks.append(data)
            except (json.JSONDecodeError, OSError):
                continue

        # Deterministic ordering: status rank → created_at
        tasks.sort(
            key=lambda t: (
                _STATUS_RANK.get(t.get("status", ""), 99),
                t.get("created_at", ""),
            )
        )
        return tasks

    def add_dependency(
        self,
        source_task_id: str,
        target_task_id: str,
        dependency_type: str = "",
    ) -> dict[str, Any]:
        """Add a dependency between two tasks."""
        self._validate_id_segment(source_task_id, "source_task_id")
        self._validate_id_segment(target_task_id, "target_task_id")

        if source_task_id == target_task_id:
            raise ValueError("A task cannot depend on itself")

        if dependency_type:
            valid_types = {d.value for d in DependencyType}
            if dependency_type not in valid_types:
                raise ValueError(
                    f"Invalid dependency_type: {dependency_type!r}. "
                    f"Must be one of: {sorted(valid_types)}"
                )

        source = self._load_task(source_task_id)
        if source is None:
            raise ValueError(f"Source task not found: {source_task_id}")
        target = self._load_task(target_task_id)
        if target is None:
            raise ValueError(f"Target task not found: {target_task_id}")

        dep = SessionTaskDependency(
            source_task_id=source_task_id,
            target_task_id=target_task_id,
            dependency_type=dependency_type or DependencyType.RELATED.value,
        )

        # Check for cycles before persisting
        existing_deps = self._load_all_dependencies()
        existing_deps.append(dep.to_dict())
        if self._has_cycle(existing_deps):
            raise ValueError(
                f"Adding dependency {source_task_id} → {target_task_id} "
                f"would create a cycle"
            )

        self._persist_dependency(source_task_id, dep)
        return dep.to_dict()

    def get_dependencies(self, task_id: str) -> list[dict[str, Any]]:
        """Get all dependencies for a task."""
        self._validate_id_segment(task_id, "task_id")
        task_dir = self._safe_task_path(task_id)
        deps_file = task_dir / "dependencies.json"
        if not deps_file.exists():
            return []
        try:
            return json.loads(deps_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def export_task(self, task_id: str) -> str:
        """Export a session task as markdown."""
        self._validate_id_segment(task_id, "task_id")
        data = self._load_task(task_id)
        if data is None:
            raise ValueError(f"Session task not found: {task_id}")

        lines: list[str] = []
        lines.append(f"# Task: {data['title']}")
        lines.append("")
        lines.append(f"- Task ID: {data['task_id']}")
        if data.get("parent_task_id"):
            lines.append(f"- Parent: {data['parent_task_id']}")
        lines.append(f"- Type: {data['task_type']}")
        lines.append(f"- Status: {data['status']}")
        lines.append(f"- Created: {data['created_at']}")
        lines.append("")

        if data.get("description"):
            lines.append("## Description")
            lines.append("")
            lines.append(data["description"])
            lines.append("")

        deps = self.get_dependencies(task_id)
        if deps:
            lines.append("## Dependencies")
            lines.append("")
            for d in deps:
                lines.append(
                    f"- {d['dependency_type']}: "
                    f"{d['source_task_id'][:12]}… → {d['target_task_id'][:12]}…"
                )
            lines.append("")

        return "\n".join(lines)

    def write_evidence(self, task_id: str) -> str:
        """Write evidence bundle for a session task."""
        self._validate_id_segment(task_id, "task_id")
        data = self._load_task(task_id)
        if data is None:
            raise ValueError(f"Session task not found: {task_id}")

        evidence_dir = self._safe_task_path(task_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        # session_task_request.json
        request_data = {
            "task_id": data["task_id"],
            "title": data["title"],
            "task_type": data["task_type"],
            "status": data["status"],
        }
        if data.get("parent_task_id"):
            request_data["parent_task_id"] = data["parent_task_id"]
        (evidence_dir / "session_task_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        # session_task_result.json
        result_data = dict(data)
        result_data["dependencies"] = self.get_dependencies(task_id)
        (evidence_dir / "session_task_result.json").write_text(
            json.dumps(result_data, indent=2, default=str),
            encoding="utf-8",
        )

        # session_task_summary.md
        md = self.export_task(task_id)
        (evidence_dir / "session_task_summary.md").write_text(
            md, encoding="utf-8",
        )

        # pass_fail.json
        is_done = data.get("status") in (
            SessionTaskStatus.COMPLETED.value,
            SessionTaskStatus.FAILED.value,
        )
        is_success = data.get("status") == SessionTaskStatus.COMPLETED.value
        pass_fail = {
            "passed": is_success,
            "task_id": task_id,
            "status": data.get("status", ""),
            "is_terminal": is_done,
            "title": data.get("title", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

        return str(evidence_dir)

    # ------------------------------------------------------------------
    # Cycle detection
    # ------------------------------------------------------------------

    @staticmethod
    def _has_cycle(deps: list[dict[str, Any]]) -> bool:
        """Detect cycles in the dependency graph using DFS."""
        graph: dict[str, list[str]] = {}
        for d in deps:
            src = d.get("source_task_id", "")
            tgt = d.get("target_task_id", "")
            if src not in graph:
                graph[src] = []
            graph[src].append(tgt)
            if tgt not in graph:
                graph[tgt] = []

        visited: set[str] = set()
        in_stack: set[str] = set()

        def _dfs(node: str) -> bool:
            visited.add(node)
            in_stack.add(node)
            for neighbour in graph.get(node, []):
                if neighbour in in_stack:
                    return True
                if neighbour not in visited and _dfs(neighbour):
                    return True
            in_stack.discard(node)
            return False

        for node in graph:
            if node not in visited:
                if _dfs(node):
                    return True
        return False

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _persist_task(self, task: SessionTask) -> None:
        """Write a new task to disk."""
        task_dir = self._safe_task_path(task.task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        data = task.to_dict()
        (task_dir / "task.json").write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )

    def _load_task(self, task_id: str) -> dict[str, Any] | None:
        """Load a task from disk."""
        task_dir = self._safe_task_path(task_id)
        task_file = task_dir / "task.json"
        if not task_file.exists():
            return None
        return json.loads(task_file.read_text(encoding="utf-8"))

    def _persist_dependency(
        self, task_id: str, dep: SessionTaskDependency,
    ) -> None:
        """Append a dependency to the task's dependency list."""
        task_dir = self._safe_task_path(task_id)
        deps_file = task_dir / "dependencies.json"
        deps: list[dict[str, Any]] = []
        if deps_file.exists():
            try:
                deps = json.loads(deps_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                deps = []
        deps.append(dep.to_dict())
        deps_file.write_text(
            json.dumps(deps, indent=2, default=str),
            encoding="utf-8",
        )

    def _load_all_dependencies(self) -> list[dict[str, Any]]:
        """Load all dependencies across all tasks."""
        all_deps: list[dict[str, Any]] = []
        if not self._tasks_dir.exists():
            return all_deps

        sandbox = self._tasks_dir.resolve()
        for entry in self._tasks_dir.iterdir():
            if not entry.is_dir():
                continue
            resolved = entry.resolve()
            if not str(resolved).startswith(str(sandbox) + "/") and resolved != sandbox:
                continue
            deps_file = entry / "dependencies.json"
            if not deps_file.exists():
                continue
            try:
                deps = json.loads(deps_file.read_text(encoding="utf-8"))
                all_deps.extend(deps)
            except (json.JSONDecodeError, OSError):
                continue
        return all_deps
