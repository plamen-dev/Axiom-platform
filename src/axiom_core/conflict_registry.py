"""Conflict Resolution Framework v1 — durable conflict tracking.

Conflicts are first-class objects representing disagreements or
incompatibilities between repair proposals, decisions, assertions,
validation results, review findings, or escalations. The framework
records conflicts, classifies them, persists them, exports them, and
generates evidence without resolving them automatically.

Non-goals: no automatic conflict resolution, no automatic execution,
no patch application, no approvals, no architecture changes, no
workflow engines.
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


class ConflictType(str, Enum):
    """Type of conflict."""

    PROPOSAL_CONFLICT = "proposal_conflict"
    DECISION_CONFLICT = "decision_conflict"
    ASSERTION_CONFLICT = "assertion_conflict"
    VALIDATION_CONFLICT = "validation_conflict"
    REVIEW_FINDING_CONFLICT = "review_finding_conflict"
    ESCALATION_CONFLICT = "escalation_conflict"
    OTHER = "other"


class ConflictSeverity(str, Enum):
    """Severity level of a conflict."""

    NONE = "none"
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"
    HUMAN_REQUIRED = "human_required"


class ConflictStatus(str, Enum):
    """Status of a conflict."""

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    CLOSED = "closed"


class ConflictSource(str, Enum):
    """Source that triggered the conflict."""

    REPAIR_DECISION = "repair_decision"
    REPAIR_PROPOSAL = "repair_proposal"
    ESCALATION = "escalation"
    ASSERTION = "assertion"
    REVIEW_FINDING = "review_finding"
    VALIDATION = "validation"
    OTHER = "other"


# Status ranking for deterministic sorting
_STATUS_RANK: dict[str, int] = {
    ConflictStatus.OPEN.value: 0,
    ConflictStatus.ACKNOWLEDGED.value: 1,
    ConflictStatus.RESOLVED.value: 2,
    ConflictStatus.CLOSED.value: 3,
}

# Severity ranking for deterministic sorting
_SEVERITY_RANK: dict[str, int] = {
    ConflictSeverity.HUMAN_REQUIRED.value: 0,
    ConflictSeverity.BLOCKER.value: 1,
    ConflictSeverity.WARNING.value: 2,
    ConflictSeverity.INFO.value: 3,
    ConflictSeverity.NONE.value: 4,
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Conflict:
    """A durable conflict artifact."""

    conflict_id: str = ""
    title: str = ""
    description: str = ""
    conflict_type: str = "other"
    severity: str = "info"
    status: str = "open"
    source: str = "other"
    left_ref: str = ""
    right_ref: str = ""
    rationale: str = ""
    recommendation: str = ""
    created_at: str = ""
    resolved_at: str = ""
    resolution_notes: str = ""

    def __post_init__(self) -> None:
        if not self.conflict_id:
            self.conflict_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "title": self.title,
            "description": self.description,
            "conflict_type": self.conflict_type,
            "severity": self.severity,
            "status": self.status,
            "source": self.source,
            "left_ref": self.left_ref,
            "right_ref": self.right_ref,
            "rationale": self.rationale,
            "recommendation": self.recommendation,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "resolution_notes": self.resolution_notes,
        }


# ---------------------------------------------------------------------------
# Core registry
# ---------------------------------------------------------------------------


class ConflictRegistry:
    """Durable registry for conflict artifacts."""

    def __init__(
        self,
        artifacts_root: str | None = None,
    ) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._conflicts_dir = self._artifacts_root / "conflicts"
        self._conflicts_dir.mkdir(parents=True, exist_ok=True)

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

    def _safe_conflict_path(self, conflict_id: str) -> Path:
        """Resolve and validate the conflict directory stays inside the sandbox."""
        target = (self._conflicts_dir / conflict_id).resolve()
        sandbox = self._conflicts_dir.resolve()
        if not str(target).startswith(str(sandbox) + "/") and target != sandbox:
            raise ValueError(
                f"Resolved path escapes artifacts root: {conflict_id!r}"
            )
        return target

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    def create_conflict(
        self,
        title: str,
        description: str = "",
        conflict_type: str = "",
        severity: str = "",
        source: str = "",
        left_ref: str = "",
        right_ref: str = "",
        rationale: str = "",
        recommendation: str = "",
    ) -> dict[str, Any]:
        """Create a new conflict."""
        if conflict_type:
            valid_types = {t.value for t in ConflictType}
            if conflict_type not in valid_types:
                raise ValueError(
                    f"Invalid conflict_type: {conflict_type!r}. "
                    f"Must be one of: {sorted(valid_types)}"
                )
        if severity:
            valid_severities = {s.value for s in ConflictSeverity}
            if severity not in valid_severities:
                raise ValueError(
                    f"Invalid severity: {severity!r}. "
                    f"Must be one of: {sorted(valid_severities)}"
                )
        if source:
            valid_sources = {s.value for s in ConflictSource}
            if source not in valid_sources:
                raise ValueError(
                    f"Invalid source: {source!r}. "
                    f"Must be one of: {sorted(valid_sources)}"
                )

        conflict = Conflict(
            title=title,
            description=description,
            conflict_type=conflict_type or ConflictType.OTHER.value,
            severity=severity or ConflictSeverity.INFO.value,
            source=source or ConflictSource.OTHER.value,
            left_ref=left_ref,
            right_ref=right_ref,
            rationale=rationale,
            recommendation=recommendation,
        )
        self._persist_conflict(conflict)
        return conflict.to_dict()

    def get_conflict(self, conflict_id: str) -> dict[str, Any] | None:
        """Get a conflict by ID."""
        self._validate_id_segment(conflict_id, "conflict_id")
        return self._load_conflict(conflict_id)

    def list_conflicts(
        self,
        status: str = "",
        severity: str = "",
        conflict_type: str = "",
        source: str = "",
    ) -> list[dict[str, Any]]:
        """List all conflicts with optional filters."""
        conflicts: list[dict[str, Any]] = []
        if not self._conflicts_dir.exists():
            return conflicts

        sandbox = self._conflicts_dir.resolve()
        for entry in self._conflicts_dir.iterdir():
            if not entry.is_dir():
                continue
            resolved = entry.resolve()
            if not str(resolved).startswith(str(sandbox) + "/") and resolved != sandbox:
                continue
            conf_file = entry / "conflict.json"
            if not conf_file.exists():
                continue
            try:
                data = json.loads(conf_file.read_text(encoding="utf-8"))
                if status and data.get("status") != status:
                    continue
                if severity and data.get("severity") != severity:
                    continue
                if conflict_type and data.get("conflict_type") != conflict_type:
                    continue
                if source and data.get("source") != source:
                    continue
                conflicts.append(data)
            except (json.JSONDecodeError, OSError):
                continue

        # Deterministic ordering: status rank → severity rank → created_at
        conflicts.sort(
            key=lambda c: (
                _STATUS_RANK.get(c.get("status", ""), 99),
                _SEVERITY_RANK.get(c.get("severity", ""), 99),
                c.get("created_at", ""),
            )
        )
        return conflicts

    def export_conflict(self, conflict_id: str) -> str:
        """Export a conflict as markdown."""
        self._validate_id_segment(conflict_id, "conflict_id")
        data = self._load_conflict(conflict_id)
        if data is None:
            raise ValueError(f"Conflict not found: {conflict_id}")

        lines: list[str] = []
        lines.append(f"# Conflict: {data['title']}")
        lines.append("")
        lines.append(f"- Conflict ID: {data['conflict_id']}")
        lines.append(f"- Status: {data['status']}")
        lines.append(f"- Severity: {data['severity']}")
        lines.append(f"- Type: {data['conflict_type']}")
        lines.append(f"- Source: {data['source']}")
        if data.get("left_ref"):
            lines.append(f"- Left Ref: {data['left_ref']}")
        if data.get("right_ref"):
            lines.append(f"- Right Ref: {data['right_ref']}")
        lines.append(f"- Created: {data['created_at']}")
        if data.get("resolved_at"):
            lines.append(f"- Resolved: {data['resolved_at']}")
        lines.append("")

        if data.get("rationale"):
            lines.append("## Rationale")
            lines.append("")
            lines.append(data["rationale"])
            lines.append("")

        if data.get("description"):
            lines.append("## Description")
            lines.append("")
            lines.append(data["description"])
            lines.append("")

        if data.get("recommendation"):
            lines.append("## Recommendation")
            lines.append("")
            lines.append(data["recommendation"])
            lines.append("")

        if data.get("resolution_notes"):
            lines.append("## Resolution Notes")
            lines.append("")
            lines.append(data["resolution_notes"])
            lines.append("")

        return "\n".join(lines)

    def write_evidence(self, conflict_id: str) -> str:
        """Write evidence bundle for a conflict."""
        self._validate_id_segment(conflict_id, "conflict_id")
        data = self._load_conflict(conflict_id)
        if data is None:
            raise ValueError(f"Conflict not found: {conflict_id}")

        evidence_dir = self._safe_conflict_path(conflict_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        # conflict_request.json
        request_data = {
            "conflict_id": data["conflict_id"],
            "title": data["title"],
            "conflict_type": data["conflict_type"],
            "severity": data["severity"],
            "status": data["status"],
            "source": data["source"],
        }
        (evidence_dir / "conflict_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        # conflict_result.json
        (evidence_dir / "conflict_result.json").write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )

        # conflict_summary.md
        md = self.export_conflict(conflict_id)
        (evidence_dir / "conflict_summary.md").write_text(
            md, encoding="utf-8",
        )

        # pass_fail.json
        is_resolved = data.get("status") in (
            ConflictStatus.RESOLVED.value,
            ConflictStatus.CLOSED.value,
        )
        pass_fail = {
            "passed": is_resolved,
            "conflict_id": conflict_id,
            "status": data.get("status", ""),
            "severity": data.get("severity", ""),
            "conflict_type": data.get("conflict_type", ""),
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

    def _persist_conflict(self, conflict: Conflict) -> None:
        """Write a new conflict to disk."""
        conf_dir = self._safe_conflict_path(conflict.conflict_id)
        conf_dir.mkdir(parents=True, exist_ok=True)
        data = conflict.to_dict()
        (conf_dir / "conflict.json").write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )

    def _load_conflict(self, conflict_id: str) -> dict[str, Any] | None:
        """Load a conflict from disk."""
        conf_dir = self._safe_conflict_path(conflict_id)
        conf_file = conf_dir / "conflict.json"
        if not conf_file.exists():
            return None
        return json.loads(conf_file.read_text(encoding="utf-8"))
