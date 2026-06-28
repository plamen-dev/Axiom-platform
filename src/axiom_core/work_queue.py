"""Work Queue Framework v1.

Provides a deterministic work queue on top of capability skills.
Represents and manages pending work as an ordered queue of work items
with explicit priority and status, plus evidence bundles.

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


class WorkPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class WorkStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"


# Higher rank sorts first (descending) for deterministic priority ordering.
_PRIORITY_RANK = {
    WorkPriority.CRITICAL.value: 0,
    WorkPriority.HIGH.value: 1,
    WorkPriority.NORMAL.value: 2,
    WorkPriority.LOW.value: 3,
}

_VALID_PRIORITIES = {p.value for p in WorkPriority}
_VALID_STATUSES = {s.value for s in WorkStatus}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class WorkItem:
    """A single unit of pending work."""

    work_id: str = ""
    title: str = ""
    description: str = ""
    priority: str = "normal"
    status: str = "pending"
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.work_id:
            self.work_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_id": self.work_id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "status": self.status,
            "created_at": self.created_at,
        }


@dataclass
class WorkQueue:
    """A queue of work items."""

    queue_id: str = ""
    work_items: list[WorkItem] = field(default_factory=list)
    item_count: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.queue_id:
            self.queue_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue_id": self.queue_id,
            "work_items": [w.to_dict() for w in self.work_items],
            "item_count": self.item_count,
            "created_at": self.created_at,
        }


@dataclass
class WorkQueueReport:
    """Report summarizing a work queue's status counts."""

    report_id: str = ""
    queue_id: str = ""
    pending_count: int = 0
    running_count: int = 0
    blocked_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "queue_id": self.queue_id,
            "pending_count": self.pending_count,
            "running_count": self.running_count,
            "blocked_count": self.blocked_count,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class WorkQueueEngine:
    """Manages work queues deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "work_queue"
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

    def create(self, work_items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Create a work queue report from a list of work items."""
        work_items = work_items or []

        item_objects: list[WorkItem] = []
        for w_data in work_items:
            priority = w_data.get("priority", "normal")
            if priority not in _VALID_PRIORITIES:
                raise ValueError(
                    f"Invalid priority: {priority!r}. Valid: {sorted(_VALID_PRIORITIES)}"
                )
            status = w_data.get("status", "pending")
            if status not in _VALID_STATUSES:
                raise ValueError(
                    f"Invalid status: {status!r}. Valid: {sorted(_VALID_STATUSES)}"
                )
            item_objects.append(
                WorkItem(
                    title=w_data.get("title", ""),
                    description=w_data.get("description", ""),
                    priority=priority,
                    status=status,
                    created_at=w_data.get("created_at", ""),
                )
            )

        # Deterministic ordering: priority rank (critical first), then
        # created_at, then work_id for stability.
        item_objects.sort(
            key=lambda w: (_PRIORITY_RANK[w.priority], w.created_at, w.work_id)
        )

        queue = WorkQueue(
            work_items=item_objects,
            item_count=len(item_objects),
        )

        report = WorkQueueReport(
            queue_id=queue.queue_id,
            pending_count=sum(1 for w in item_objects if w.status == "pending"),
            running_count=sum(1 for w in item_objects if w.status == "running"),
            blocked_count=sum(1 for w in item_objects if w.status == "blocked"),
            completed_count=sum(1 for w in item_objects if w.status == "completed"),
            failed_count=sum(1 for w in item_objects if w.status == "failed"),
        )

        self._persist(report, queue)
        self._write_evidence(report, queue)

        result = report.to_dict()
        result["queue"] = queue.to_dict()
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
            raise ValueError(f"Work queue report not found: {report_id}")
        return self._generate_export_md(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, report: WorkQueueReport, queue: WorkQueue) -> None:
        report_dir = self._safe_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)

        data = report.to_dict()
        data["queue"] = queue.to_dict()

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

    def _write_evidence(self, report: WorkQueueReport, queue: WorkQueue) -> None:
        evidence_dir = self._safe_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {"work_items": [w.to_dict() for w in queue.work_items]}
        (evidence_dir / "work_queue_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        result_data = report.to_dict()
        result_data["queue"] = queue.to_dict()
        (evidence_dir / "work_queue_result.json").write_text(
            json.dumps(result_data, indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_export_md(result_data)
        (evidence_dir / "work_queue_summary.md").write_text(md, encoding="utf-8")

        # A queue passes when no work item has failed.
        passed = report.failed_count == 0
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "queue_id": report.queue_id,
            "item_count": queue.item_count,
            "failed_count": report.failed_count,
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

        lines.append("# Work Queue Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Queue ID: {data.get('queue_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        lines.append("## Status Counts")
        lines.append("")
        lines.append(f"- Pending: {data.get('pending_count', 0)}")
        lines.append(f"- Running: {data.get('running_count', 0)}")
        lines.append(f"- Blocked: {data.get('blocked_count', 0)}")
        lines.append(f"- Completed: {data.get('completed_count', 0)}")
        lines.append(f"- Failed: {data.get('failed_count', 0)}")
        lines.append("")

        queue = data.get("queue", {})
        work_items = queue.get("work_items", [])
        if work_items:
            lines.append("## Work Items")
            lines.append("")
            for w in work_items:
                priority = w.get("priority", "").upper()
                status = w.get("status", "").upper()
                title = w.get("title", "")
                description = w.get("description", "")
                desc_part = f": {description}" if description else ""
                lines.append(f"- [{priority}] [{status}] {title}{desc_part}")
            lines.append("")

        return "\n".join(lines)
