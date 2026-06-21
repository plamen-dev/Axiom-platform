"""Repair Proposal Framework v1 — durable repair proposal tracking.

Repair proposals are first-class objects representing candidate fixes for
escalations, review findings, validation failures, or assertion failures.
They provide structured, non-executing recommendations and evidence without
performing any automatic actions.

Non-goals: no automatic repair execution, no patch application, no approvals,
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

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RepairProposalType(str, Enum):
    """Type of repair being proposed."""

    CODE_CHANGE = "code_change"
    TEST_CHANGE = "test_change"
    CONFIGURATION = "configuration"
    DOCUMENTATION = "documentation"
    OTHER = "other"


class RepairProposalStatus(str, Enum):
    """Status of a repair proposal."""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class RepairProposalSource(str, Enum):
    """Source that triggered the repair proposal."""

    ESCALATION = "escalation"
    ASSERTION = "assertion"
    REVIEW_FINDING = "review_finding"
    VALIDATION = "validation"


# Status ranking for deterministic sorting
_STATUS_RANK: dict[str, int] = {
    RepairProposalStatus.PROPOSED.value: 0,
    RepairProposalStatus.ACCEPTED.value: 1,
    RepairProposalStatus.REJECTED.value: 2,
}

# Type ranking for deterministic sorting
_TYPE_RANK: dict[str, int] = {
    RepairProposalType.CODE_CHANGE.value: 0,
    RepairProposalType.TEST_CHANGE.value: 1,
    RepairProposalType.CONFIGURATION.value: 2,
    RepairProposalType.DOCUMENTATION.value: 3,
    RepairProposalType.OTHER.value: 4,
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class RepairProposal:
    """A durable repair proposal artifact."""

    proposal_id: str = ""
    escalation_id: str = ""
    title: str = ""
    description: str = ""
    source: str = "escalation"
    proposal_type: str = "other"
    status: str = "proposed"
    rationale: str = ""
    recommendations: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.proposal_id:
            self.proposal_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "escalation_id": self.escalation_id,
            "title": self.title,
            "description": self.description,
            "source": self.source,
            "proposal_type": self.proposal_type,
            "status": self.status,
            "rationale": self.rationale,
            "recommendations": self.recommendations,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Core registry
# ---------------------------------------------------------------------------


class RepairProposalRegistry:
    """Durable registry for repair proposal artifacts."""

    def __init__(
        self,
        artifacts_root: str | None = None,
    ) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._proposals_dir = self._artifacts_root / "repair_proposals"
        self._proposals_dir.mkdir(parents=True, exist_ok=True)

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

    def create_proposal(
        self,
        title: str,
        escalation_id: str = "",
        description: str = "",
        source: str = "",
        proposal_type: str = "",
        rationale: str = "",
        recommendations: str = "",
    ) -> dict[str, Any]:
        """Create a new repair proposal."""
        if source:
            valid_sources = {s.value for s in RepairProposalSource}
            if source not in valid_sources:
                raise ValueError(
                    f"Invalid source: {source!r}. "
                    f"Must be one of: {sorted(valid_sources)}"
                )
        if proposal_type:
            valid_types = {t.value for t in RepairProposalType}
            if proposal_type not in valid_types:
                raise ValueError(
                    f"Invalid proposal_type: {proposal_type!r}. "
                    f"Must be one of: {sorted(valid_types)}"
                )

        proposal = RepairProposal(
            escalation_id=escalation_id,
            title=title,
            description=description,
            source=source or RepairProposalSource.ESCALATION.value,
            proposal_type=proposal_type or RepairProposalType.OTHER.value,
            rationale=rationale,
            recommendations=recommendations,
        )
        self._persist_proposal(proposal)
        return proposal.to_dict()

    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        """Get a repair proposal by ID."""
        self._validate_id_segment(proposal_id, "proposal_id")
        return self._load_proposal(proposal_id)

    def list_proposals(
        self,
        status: str = "",
        proposal_type: str = "",
        source: str = "",
    ) -> list[dict[str, Any]]:
        """List all repair proposals with optional filters."""
        proposals: list[dict[str, Any]] = []
        if not self._proposals_dir.exists():
            return proposals

        for entry in self._proposals_dir.iterdir():
            if not entry.is_dir():
                continue
            prop_file = entry / "proposal.json"
            if not prop_file.exists():
                continue
            try:
                data = json.loads(prop_file.read_text(encoding="utf-8"))
                if status and data.get("status") != status:
                    continue
                if proposal_type and data.get("proposal_type") != proposal_type:
                    continue
                if source and data.get("source") != source:
                    continue
                proposals.append(data)
            except (json.JSONDecodeError, OSError):
                continue

        # Deterministic ordering: status rank → type rank → created_at
        proposals.sort(
            key=lambda p: (
                _STATUS_RANK.get(p.get("status", ""), 99),
                _TYPE_RANK.get(p.get("proposal_type", ""), 99),
                p.get("created_at", ""),
            )
        )
        return proposals

    def export_proposal(self, proposal_id: str) -> str:
        """Export a repair proposal as markdown."""
        self._validate_id_segment(proposal_id, "proposal_id")
        data = self._load_proposal(proposal_id)
        if data is None:
            raise ValueError(f"Repair proposal not found: {proposal_id}")

        lines: list[str] = []
        lines.append(f"# Repair Proposal: {data['title']}")
        lines.append("")
        lines.append(f"- Proposal ID: {data['proposal_id']}")
        lines.append(f"- Status: {data['status']}")
        lines.append(f"- Type: {data['proposal_type']}")
        lines.append(f"- Source: {data['source']}")
        if data.get("escalation_id"):
            lines.append(f"- Escalation ID: {data['escalation_id']}")
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

        if data.get("recommendations"):
            lines.append("## Recommendations")
            lines.append("")
            lines.append(data["recommendations"])
            lines.append("")

        return "\n".join(lines)

    def write_evidence(self, proposal_id: str) -> str:
        """Write evidence bundle for a repair proposal."""
        self._validate_id_segment(proposal_id, "proposal_id")
        data = self._load_proposal(proposal_id)
        if data is None:
            raise ValueError(f"Repair proposal not found: {proposal_id}")

        evidence_dir = self._proposals_dir / proposal_id
        evidence_dir.mkdir(parents=True, exist_ok=True)

        # repair_proposal_request.json
        request_data = {
            "proposal_id": data["proposal_id"],
            "title": data["title"],
            "source": data["source"],
            "proposal_type": data["proposal_type"],
            "status": data["status"],
        }
        (evidence_dir / "repair_proposal_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        # repair_proposal_result.json
        (evidence_dir / "repair_proposal_result.json").write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )

        # repair_proposal_summary.md
        md = self.export_proposal(proposal_id)
        (evidence_dir / "repair_proposal_summary.md").write_text(
            md, encoding="utf-8",
        )

        # pass_fail.json
        is_accepted = data.get("status") == RepairProposalStatus.ACCEPTED.value
        pass_fail = {
            "passed": is_accepted,
            "proposal_id": proposal_id,
            "status": data.get("status", ""),
            "proposal_type": data.get("proposal_type", ""),
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

    def _persist_proposal(self, proposal: RepairProposal) -> None:
        """Write a new proposal to disk."""
        prop_dir = self._proposals_dir / proposal.proposal_id
        prop_dir.mkdir(parents=True, exist_ok=True)
        data = proposal.to_dict()
        (prop_dir / "proposal.json").write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )

    def _load_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        """Load a proposal from disk."""
        prop_file = self._proposals_dir / proposal_id / "proposal.json"
        if not prop_file.exists():
            return None
        return json.loads(prop_file.read_text(encoding="utf-8"))
