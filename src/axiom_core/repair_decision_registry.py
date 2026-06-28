"""Repair Decision Framework v1 — durable repair decision tracking.

Repair decisions are first-class objects representing the disposition of
repair proposals. They provide durable records of whether a proposed repair
was accepted, rejected, deferred, or superseded without performing any
automatic actions.

Non-goals: no automatic execution, no patch application, no approvals,
no conflict resolution, no architecture changes, no workflow engines.
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

from axiom_core.artifact_paths import is_within_sandbox

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RepairDecisionStatus(str, Enum):
    """Status of a repair decision."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    SUPERSEDED = "superseded"


class RepairDecisionSource(str, Enum):
    """Source that triggered the repair decision."""

    REPAIR_PROPOSAL = "repair_proposal"
    ESCALATION = "escalation"
    REVIEW_FINDING = "review_finding"
    VALIDATION = "validation"


class RepairDecisionReason(str, Enum):
    """Reason classification for a repair decision."""

    TECHNICAL = "technical"
    POLICY = "policy"
    RISK = "risk"
    DUPLICATE = "duplicate"
    HUMAN_JUDGMENT = "human_judgment"
    OTHER = "other"


# Status ranking for deterministic sorting
_STATUS_RANK: dict[str, int] = {
    RepairDecisionStatus.ACCEPTED.value: 0,
    RepairDecisionStatus.REJECTED.value: 1,
    RepairDecisionStatus.DEFERRED.value: 2,
    RepairDecisionStatus.SUPERSEDED.value: 3,
}

# Reason ranking for deterministic sorting
_REASON_RANK: dict[str, int] = {
    RepairDecisionReason.TECHNICAL.value: 0,
    RepairDecisionReason.POLICY.value: 1,
    RepairDecisionReason.RISK.value: 2,
    RepairDecisionReason.DUPLICATE.value: 3,
    RepairDecisionReason.HUMAN_JUDGMENT.value: 4,
    RepairDecisionReason.OTHER.value: 5,
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class RepairDecision:
    """A durable repair decision artifact."""

    decision_id: str = ""
    proposal_id: str = ""
    title: str = ""
    description: str = ""
    source: str = "repair_proposal"
    status: str = "accepted"
    reason: str = "other"
    rationale: str = ""
    notes: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.decision_id:
            self.decision_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "proposal_id": self.proposal_id,
            "title": self.title,
            "description": self.description,
            "source": self.source,
            "status": self.status,
            "reason": self.reason,
            "rationale": self.rationale,
            "notes": self.notes,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Core registry
# ---------------------------------------------------------------------------


class RepairDecisionRegistry:
    """Durable registry for repair decision artifacts."""

    def __init__(
        self,
        artifacts_root: str | None = None,
    ) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._decisions_dir = self._artifacts_root / "repair_decisions"
        self._decisions_dir.mkdir(parents=True, exist_ok=True)

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

    def _safe_decision_path(self, decision_id: str) -> Path:
        """Resolve and validate the decision directory stays inside the sandbox."""
        target = (self._decisions_dir / decision_id).resolve()
        sandbox = self._decisions_dir.resolve()
        if not is_within_sandbox(target, sandbox):
            raise ValueError(
                f"Resolved path escapes artifacts root: {decision_id!r}"
            )
        return target

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    def create_decision(
        self,
        title: str,
        proposal_id: str = "",
        description: str = "",
        source: str = "",
        status: str = "",
        reason: str = "",
        rationale: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        """Create a new repair decision."""
        if source:
            valid_sources = {s.value for s in RepairDecisionSource}
            if source not in valid_sources:
                raise ValueError(
                    f"Invalid source: {source!r}. "
                    f"Must be one of: {sorted(valid_sources)}"
                )
        if status:
            valid_statuses = {s.value for s in RepairDecisionStatus}
            if status not in valid_statuses:
                raise ValueError(
                    f"Invalid status: {status!r}. "
                    f"Must be one of: {sorted(valid_statuses)}"
                )
        if reason:
            valid_reasons = {r.value for r in RepairDecisionReason}
            if reason not in valid_reasons:
                raise ValueError(
                    f"Invalid reason: {reason!r}. "
                    f"Must be one of: {sorted(valid_reasons)}"
                )

        decision = RepairDecision(
            proposal_id=proposal_id,
            title=title,
            description=description,
            source=source or RepairDecisionSource.REPAIR_PROPOSAL.value,
            status=status or RepairDecisionStatus.ACCEPTED.value,
            reason=reason or RepairDecisionReason.OTHER.value,
            rationale=rationale,
            notes=notes,
        )
        self._persist_decision(decision)
        return decision.to_dict()

    def get_decision(self, decision_id: str) -> dict[str, Any] | None:
        """Get a repair decision by ID."""
        self._validate_id_segment(decision_id, "decision_id")
        return self._load_decision(decision_id)

    def list_decisions(
        self,
        status: str = "",
        reason: str = "",
        source: str = "",
    ) -> list[dict[str, Any]]:
        """List all repair decisions with optional filters."""
        decisions: list[dict[str, Any]] = []
        if not self._decisions_dir.exists():
            return decisions

        for entry in self._decisions_dir.iterdir():
            if not entry.is_dir():
                continue
            dec_file = entry / "decision.json"
            if not dec_file.exists():
                continue
            try:
                data = json.loads(dec_file.read_text(encoding="utf-8"))
                if status and data.get("status") != status:
                    continue
                if reason and data.get("reason") != reason:
                    continue
                if source and data.get("source") != source:
                    continue
                decisions.append(data)
            except (json.JSONDecodeError, OSError):
                continue

        # Deterministic ordering: status rank → reason rank → created_at
        decisions.sort(
            key=lambda d: (
                _STATUS_RANK.get(d.get("status", ""), 99),
                _REASON_RANK.get(d.get("reason", ""), 99),
                d.get("created_at", ""),
            )
        )
        return decisions

    def export_decision(self, decision_id: str) -> str:
        """Export a repair decision as markdown."""
        self._validate_id_segment(decision_id, "decision_id")
        data = self._load_decision(decision_id)
        if data is None:
            raise ValueError(f"Repair decision not found: {decision_id}")

        lines: list[str] = []
        lines.append(f"# Repair Decision: {data['title']}")
        lines.append("")
        lines.append(f"- Decision ID: {data['decision_id']}")
        lines.append(f"- Status: {data['status']}")
        lines.append(f"- Reason: {data['reason']}")
        lines.append(f"- Source: {data['source']}")
        if data.get("proposal_id"):
            lines.append(f"- Proposal ID: {data['proposal_id']}")
        lines.append(f"- Created: {data['created_at']}")
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

        if data.get("notes"):
            lines.append("## Notes")
            lines.append("")
            lines.append(data["notes"])
            lines.append("")

        return "\n".join(lines)

    def write_evidence(self, decision_id: str) -> str:
        """Write evidence bundle for a repair decision."""
        self._validate_id_segment(decision_id, "decision_id")
        data = self._load_decision(decision_id)
        if data is None:
            raise ValueError(f"Repair decision not found: {decision_id}")

        evidence_dir = self._safe_decision_path(decision_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        # repair_decision_request.json
        request_data = {
            "decision_id": data["decision_id"],
            "title": data["title"],
            "source": data["source"],
            "status": data["status"],
            "reason": data["reason"],
        }
        (evidence_dir / "repair_decision_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        # repair_decision_result.json
        (evidence_dir / "repair_decision_result.json").write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )

        # repair_decision_summary.md
        md = self.export_decision(decision_id)
        (evidence_dir / "repair_decision_summary.md").write_text(
            md, encoding="utf-8",
        )

        # pass_fail.json
        is_accepted = data.get("status") == RepairDecisionStatus.ACCEPTED.value
        pass_fail = {
            "passed": is_accepted,
            "decision_id": decision_id,
            "status": data.get("status", ""),
            "reason": data.get("reason", ""),
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

    def _persist_decision(self, decision: RepairDecision) -> None:
        """Write a new decision to disk."""
        dec_dir = self._safe_decision_path(decision.decision_id)
        dec_dir.mkdir(parents=True, exist_ok=True)
        data = decision.to_dict()
        (dec_dir / "decision.json").write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )

    def _load_decision(self, decision_id: str) -> dict[str, Any] | None:
        """Load a decision from disk."""
        dec_dir = self._safe_decision_path(decision_id)
        dec_file = dec_dir / "decision.json"
        if not dec_file.exists():
            return None
        return json.loads(dec_file.read_text(encoding="utf-8"))
