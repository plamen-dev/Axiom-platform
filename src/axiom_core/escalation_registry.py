"""Escalation Framework v1 — durable escalation tracking.

Provides a structured mechanism for recording, tracking, and resolving
escalations discovered during discovery and verification activities.
Escalations represent issues requiring elevated attention beyond ordinary
findings: unresolved blockers, conflicts, missing evidence, architectural
concerns, repeated failures, or other conditions requiring elevated attention.

Non-goals: no workflow engine, no automatic escalation routing, no
cross-registry refactoring, no architecture changes, no UI, no approvals.
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


class EscalationStatus(str, Enum):
    """Lifecycle status of an escalation."""

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class EscalationSeverity(str, Enum):
    """Severity level of an escalation."""

    NONE = "none"
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"
    HUMAN_REQUIRED = "human_required"


class EscalationCategory(str, Enum):
    """Category of an escalation."""

    EVIDENCE_GAP = "evidence_gap"
    ARCHITECTURE = "architecture"
    VALIDATION = "validation"
    REPEATED_FAILURE = "repeated_failure"
    DEPENDENCY = "dependency"
    CONFLICT = "conflict"
    OTHER = "other"


# Status ranking for deterministic sorting
_STATUS_RANK: dict[str, int] = {
    EscalationStatus.OPEN.value: 0,
    EscalationStatus.ACKNOWLEDGED.value: 1,
    EscalationStatus.IN_PROGRESS.value: 2,
    EscalationStatus.RESOLVED.value: 3,
    EscalationStatus.CLOSED.value: 4,
}

# Severity ranking for deterministic sorting (most severe first)
_SEVERITY_RANK: dict[str, int] = {
    EscalationSeverity.HUMAN_REQUIRED.value: 0,
    EscalationSeverity.BLOCKER.value: 1,
    EscalationSeverity.WARNING.value: 2,
    EscalationSeverity.INFO.value: 3,
    EscalationSeverity.NONE.value: 4,
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Escalation:
    """A durable escalation artifact."""

    escalation_id: str = ""
    title: str = ""
    description: str = ""
    reason: str = ""
    severity: str = "info"
    category: str = "other"
    source: str = ""
    status: str = "open"
    resolution_notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    resolved_at: str = ""

    def __post_init__(self) -> None:
        if not self.escalation_id:
            self.escalation_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "escalation_id": self.escalation_id,
            "title": self.title,
            "description": self.description,
            "reason": self.reason,
            "severity": self.severity,
            "category": self.category,
            "source": self.source,
            "status": self.status,
            "resolution_notes": self.resolution_notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "resolved_at": self.resolved_at,
        }


# ---------------------------------------------------------------------------
# Core registry
# ---------------------------------------------------------------------------


class EscalationRegistry:
    """Durable registry for escalation artifacts."""

    def __init__(
        self,
        artifacts_root: str | None = None,
    ) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._escalations_dir = self._artifacts_root / "escalations"
        self._escalations_dir.mkdir(parents=True, exist_ok=True)

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

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    def create_escalation(
        self,
        title: str,
        description: str = "",
        reason: str = "",
        severity: str = "",
        category: str = "",
        source: str = "",
    ) -> dict[str, Any]:
        """Create a new escalation."""
        if severity:
            valid_severities = {s.value for s in EscalationSeverity}
            if severity not in valid_severities:
                raise ValueError(
                    f"Invalid severity: {severity!r}. "
                    f"Must be one of: {sorted(valid_severities)}"
                )
        if category:
            valid_categories = {c.value for c in EscalationCategory}
            if category not in valid_categories:
                raise ValueError(
                    f"Invalid category: {category!r}. "
                    f"Must be one of: {sorted(valid_categories)}"
                )

        escalation = Escalation(
            title=title,
            description=description,
            reason=reason,
            severity=severity or EscalationSeverity.INFO.value,
            category=category or EscalationCategory.OTHER.value,
            source=source,
        )
        self._persist_escalation(escalation)
        return escalation.to_dict()

    def get_escalation(self, escalation_id: str) -> dict[str, Any] | None:
        """Get an escalation by ID."""
        self._validate_id_segment(escalation_id, "escalation_id")
        return self._load_escalation(escalation_id)

    def list_escalations(
        self,
        status: str = "",
        severity: str = "",
        category: str = "",
    ) -> list[dict[str, Any]]:
        """List all escalations with optional filters."""
        escalations: list[dict[str, Any]] = []
        if not self._escalations_dir.exists():
            return escalations

        for entry in self._escalations_dir.iterdir():
            if not entry.is_dir():
                continue
            esc_file = entry / "escalation.json"
            if not esc_file.exists():
                continue
            try:
                data = json.loads(esc_file.read_text(encoding="utf-8"))
                if status and data.get("status") != status:
                    continue
                if severity and data.get("severity") != severity:
                    continue
                if category and data.get("category") != category:
                    continue
                escalations.append(data)
            except (json.JSONDecodeError, OSError):
                continue

        # Deterministic ordering: status rank → severity rank → created_at
        escalations.sort(
            key=lambda e: (
                _STATUS_RANK.get(e.get("status", ""), 99),
                _SEVERITY_RANK.get(e.get("severity", ""), 99),
                e.get("created_at", ""),
            )
        )
        return escalations

    def update_status(
        self,
        escalation_id: str,
        status: str,
        resolution_notes: str = "",
    ) -> dict[str, Any]:
        """Update an escalation's status."""
        self._validate_id_segment(escalation_id, "escalation_id")
        data = self._load_escalation(escalation_id)
        if data is None:
            raise ValueError(f"Escalation not found: {escalation_id}")

        valid_statuses = {s.value for s in EscalationStatus}
        if status not in valid_statuses:
            raise ValueError(
                f"Invalid status: {status!r}. "
                f"Must be one of: {sorted(valid_statuses)}"
            )

        now = datetime.now(timezone.utc).isoformat()
        data["status"] = status
        data["updated_at"] = now

        if resolution_notes:
            data["resolution_notes"] = resolution_notes

        if status in {EscalationStatus.RESOLVED.value, EscalationStatus.CLOSED.value}:
            if not data.get("resolved_at"):
                data["resolved_at"] = now

        self._write_escalation(data)
        return data

    def export_escalation(self, escalation_id: str) -> str:
        """Export an escalation as markdown."""
        self._validate_id_segment(escalation_id, "escalation_id")
        data = self._load_escalation(escalation_id)
        if data is None:
            raise ValueError(f"Escalation not found: {escalation_id}")

        lines: list[str] = []
        lines.append(f"# Escalation: {data['title']}")
        lines.append("")
        lines.append(f"- Escalation ID: {data['escalation_id']}")
        lines.append(f"- Status: {data['status']}")
        lines.append(f"- Severity: {data['severity']}")
        lines.append(f"- Category: {data['category']}")
        if data.get("source"):
            lines.append(f"- Source: {data['source']}")
        lines.append(f"- Created: {data['created_at']}")
        if data.get("resolved_at"):
            lines.append(f"- Resolved: {data['resolved_at']}")
        lines.append("")

        if data.get("reason"):
            lines.append("## Reason")
            lines.append("")
            lines.append(data["reason"])
            lines.append("")

        if data.get("description"):
            lines.append("## Description")
            lines.append("")
            lines.append(data["description"])
            lines.append("")

        if data.get("resolution_notes"):
            lines.append("## Resolution")
            lines.append("")
            lines.append(data["resolution_notes"])
            lines.append("")

        return "\n".join(lines)

    def write_evidence(self, escalation_id: str) -> str:
        """Write evidence bundle for an escalation."""
        self._validate_id_segment(escalation_id, "escalation_id")
        data = self._load_escalation(escalation_id)
        if data is None:
            raise ValueError(f"Escalation not found: {escalation_id}")

        evidence_dir = self._escalations_dir / escalation_id
        evidence_dir.mkdir(parents=True, exist_ok=True)

        # escalation_request.json
        request_data = {
            "escalation_id": data["escalation_id"],
            "title": data["title"],
            "severity": data["severity"],
            "category": data["category"],
            "status": data["status"],
        }
        (evidence_dir / "escalation_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        # escalation_result.json
        (evidence_dir / "escalation_result.json").write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )

        # escalation_summary.md
        md = self.export_escalation(escalation_id)
        (evidence_dir / "escalation_summary.md").write_text(md, encoding="utf-8")

        # pass_fail.json
        is_resolved = data.get("status") in {
            EscalationStatus.RESOLVED.value,
            EscalationStatus.CLOSED.value,
        }
        pass_fail = {
            "passed": is_resolved,
            "escalation_id": escalation_id,
            "status": data.get("status", ""),
            "severity": data.get("severity", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

        return str(evidence_dir)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _persist_escalation(self, escalation: Escalation) -> None:
        """Write a new escalation to disk."""
        esc_dir = self._escalations_dir / escalation.escalation_id
        esc_dir.mkdir(parents=True, exist_ok=True)
        data = escalation.to_dict()
        (esc_dir / "escalation.json").write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )

    def _load_escalation(self, escalation_id: str) -> dict[str, Any] | None:
        """Load an escalation from disk."""
        esc_file = self._escalations_dir / escalation_id / "escalation.json"
        if not esc_file.exists():
            return None
        return json.loads(esc_file.read_text(encoding="utf-8"))

    def _write_escalation(self, data: dict[str, Any]) -> None:
        """Write escalation data to disk."""
        escalation_id = data["escalation_id"]
        esc_dir = self._escalations_dir / escalation_id
        esc_dir.mkdir(parents=True, exist_ok=True)
        (esc_dir / "escalation.json").write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )
