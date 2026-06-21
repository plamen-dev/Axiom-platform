"""Session Review Registry v1 — durable review tracking objects.

Creates a structured registry for review findings and review outcomes
connected to coding sessions, session reports, PRs, validation runs,
and evidence artifacts.

Supports review sources: Devin Review, human review, CI/test failures,
CLI testing, and future automated review agents.

Non-goals: no autonomous review execution, no external review APIs,
no Devin Review replacement, no UI beyond CLI output.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ReviewStatus(str, Enum):
    """Status of a session review."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class FindingSeverity(str, Enum):
    """Severity of a review finding."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingStatus(str, Enum):
    """Status of a review finding."""

    OPEN = "open"
    FIXED = "fixed"
    ACKNOWLEDGED = "acknowledged"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class ReviewSource(str, Enum):
    """Source of a review."""

    DEVIN_REVIEW = "devin_review"
    HUMAN_REVIEW = "human_review"
    CI_FAILURE = "ci_failure"
    CLI_TESTING = "cli_testing"
    AUTOMATED_AGENT = "automated_agent"
    OTHER = "other"


# Status ranking for deterministic sorting
_STATUS_RANK: dict[str, int] = {
    ReviewStatus.OPEN.value: 0,
    ReviewStatus.IN_PROGRESS.value: 1,
    ReviewStatus.RESOLVED.value: 2,
    ReviewStatus.CLOSED.value: 3,
}

# Severity ranking for deterministic sorting
_SEVERITY_RANK: dict[str, int] = {
    FindingSeverity.CRITICAL.value: 0,
    FindingSeverity.HIGH.value: 1,
    FindingSeverity.MEDIUM.value: 2,
    FindingSeverity.LOW.value: 3,
    FindingSeverity.INFO.value: 4,
}

# Finding status ranking for deterministic sorting
_FINDING_STATUS_RANK: dict[str, int] = {
    FindingStatus.OPEN.value: 0,
    FindingStatus.FIXED.value: 1,
    FindingStatus.ACKNOWLEDGED.value: 2,
    FindingStatus.REJECTED.value: 3,
    FindingStatus.DEFERRED.value: 4,
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ReviewResolution:
    """Resolution record for a finding."""

    resolution_id: str = ""
    finding_id: str = ""
    resolution_note: str = ""
    resolved_by: str = ""
    commit_id: str = ""
    resolved_at: str = ""

    def __post_init__(self) -> None:
        if not self.resolution_id:
            self.resolution_id = str(uuid4())
        if not self.resolved_at:
            self.resolved_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "resolution_id": self.resolution_id,
            "finding_id": self.finding_id,
            "resolution_note": self.resolution_note,
            "resolved_by": self.resolved_by,
            "commit_id": self.commit_id,
            "resolved_at": self.resolved_at,
        }


@dataclass
class ReviewFinding:
    """A finding within a session review."""

    finding_id: str = ""
    summary: str = ""
    details: str = ""
    severity: str = "medium"
    source: str = "other"
    file_path: str = ""
    line_number: int = 0
    status: str = "open"
    resolution_note: str = ""
    linked_evidence_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.finding_id:
            self.finding_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "summary": self.summary,
            "details": self.details,
            "severity": self.severity,
            "source": self.source,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "status": self.status,
            "resolution_note": self.resolution_note,
            "linked_evidence_ids": list(self.linked_evidence_ids),
        }


@dataclass
class ReviewEvidenceLink:
    """Links a review to an evidence artifact."""

    link_id: str = ""
    evidence_type: str = ""
    evidence_path: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        if not self.link_id:
            self.link_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "link_id": self.link_id,
            "evidence_type": self.evidence_type,
            "evidence_path": self.evidence_path,
            "description": self.description,
        }


@dataclass
class ReviewSummary:
    """Summary statistics for a session review."""

    total_findings: int = 0
    open_findings: int = 0
    fixed_findings: int = 0
    acknowledged_findings: int = 0
    rejected_findings: int = 0
    deferred_findings: int = 0
    critical_findings: int = 0
    high_findings: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_findings": self.total_findings,
            "open_findings": self.open_findings,
            "fixed_findings": self.fixed_findings,
            "acknowledged_findings": self.acknowledged_findings,
            "rejected_findings": self.rejected_findings,
            "deferred_findings": self.deferred_findings,
            "critical_findings": self.critical_findings,
            "high_findings": self.high_findings,
        }


@dataclass
class SessionReview:
    """A durable session review artifact."""

    review_id: str = ""
    title: str = ""
    source: str = "other"
    status: str = "open"
    severity: str = "medium"
    pr_id: str = ""
    coding_session_id: str = ""
    session_report_id: str = ""
    linked_validation_ids: list[str] = field(default_factory=list)
    linked_evidence_ids: list[str] = field(default_factory=list)
    findings: list[ReviewFinding] = field(default_factory=list)
    resolutions: list[ReviewResolution] = field(default_factory=list)
    evidence_links: list[ReviewEvidenceLink] = field(default_factory=list)
    rationale: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.review_id:
            self.review_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "title": self.title,
            "source": self.source,
            "status": self.status,
            "severity": self.severity,
            "pr_id": self.pr_id,
            "coding_session_id": self.coding_session_id,
            "session_report_id": self.session_report_id,
            "linked_validation_ids": list(self.linked_validation_ids),
            "linked_evidence_ids": list(self.linked_evidence_ids),
            "findings": [f.to_dict() for f in self.findings],
            "resolutions": [r.to_dict() for r in self.resolutions],
            "evidence_links": [e.to_dict() for e in self.evidence_links],
            "rationale": self.rationale,
            "review_summary": self._review_summary(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def _review_summary(self) -> dict[str, Any]:
        open_count = sum(
            1 for f in self.findings if f.status == FindingStatus.OPEN.value
        )
        fixed_count = sum(
            1 for f in self.findings if f.status == FindingStatus.FIXED.value
        )
        ack_count = sum(
            1 for f in self.findings
            if f.status == FindingStatus.ACKNOWLEDGED.value
        )
        rejected_count = sum(
            1 for f in self.findings
            if f.status == FindingStatus.REJECTED.value
        )
        deferred_count = sum(
            1 for f in self.findings
            if f.status == FindingStatus.DEFERRED.value
        )
        critical_count = sum(
            1 for f in self.findings
            if f.severity == FindingSeverity.CRITICAL.value
        )
        high_count = sum(
            1 for f in self.findings
            if f.severity == FindingSeverity.HIGH.value
        )
        return {
            "total_findings": len(self.findings),
            "open_findings": open_count,
            "fixed_findings": fixed_count,
            "acknowledged_findings": ack_count,
            "rejected_findings": rejected_count,
            "deferred_findings": deferred_count,
            "critical_findings": critical_count,
            "high_findings": high_count,
        }


# ---------------------------------------------------------------------------
# Core registry
# ---------------------------------------------------------------------------


class SessionReviewRegistry:
    """Durable registry for session review artifacts."""

    def __init__(
        self,
        artifacts_root: str | None = None,
    ) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._reviews_dir = self._artifacts_root / "session_reviews"
        self._reviews_dir.mkdir(parents=True, exist_ok=True)

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

    def create_review(
        self,
        title: str,
        source: str = "",
        severity: str = "",
        pr_id: str = "",
        coding_session_id: str = "",
        session_report_id: str = "",
        rationale: str = "",
    ) -> dict[str, Any]:
        """Create a new session review."""
        review = SessionReview(
            title=title,
            source=source or ReviewSource.OTHER.value,
            severity=severity or FindingSeverity.MEDIUM.value,
            pr_id=pr_id,
            coding_session_id=coding_session_id,
            session_report_id=session_report_id,
            rationale=rationale,
        )
        self._persist_review(review)
        return review.to_dict()

    def get_review(self, review_id: str) -> dict[str, Any] | None:
        """Get a review by ID."""
        self._validate_id_segment(review_id, "review_id")
        return self._load_review(review_id)

    def list_reviews(
        self,
        status: str = "",
        source: str = "",
    ) -> list[dict[str, Any]]:
        """List all reviews with optional status/source filter."""
        reviews: list[dict[str, Any]] = []
        if not self._reviews_dir.exists():
            return reviews

        for entry in self._reviews_dir.iterdir():
            if not entry.is_dir():
                continue
            review_file = entry / "review.json"
            if not review_file.exists():
                continue
            try:
                data = json.loads(review_file.read_text(encoding="utf-8"))
                if status and data.get("status") != status:
                    continue
                if source and data.get("source") != source:
                    continue
                reviews.append(data)
            except (json.JSONDecodeError, OSError):
                continue

        # Deterministic ordering: status rank → severity rank → created_at
        reviews.sort(
            key=lambda r: (
                _STATUS_RANK.get(r.get("status", ""), 99),
                _SEVERITY_RANK.get(r.get("severity", ""), 99),
                r.get("created_at", ""),
            )
        )
        return reviews

    def add_finding(
        self,
        review_id: str,
        summary: str,
        details: str = "",
        severity: str = "",
        source: str = "",
        file_path: str = "",
        line_number: int = 0,
        linked_evidence_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Add a finding to a review."""
        self._validate_id_segment(review_id, "review_id")
        data = self._load_review(review_id)
        if data is None:
            raise ValueError(f"Review not found: {review_id}")

        finding = ReviewFinding(
            summary=summary,
            details=details,
            severity=severity or FindingSeverity.MEDIUM.value,
            source=source or data.get("source", ReviewSource.OTHER.value),
            file_path=file_path,
            line_number=line_number,
            linked_evidence_ids=linked_evidence_ids or [],
        )
        data["findings"].append(finding.to_dict())
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._recompute_review_summary(data)
        self._write_review(data)
        return finding.to_dict()

    def resolve_finding(
        self,
        review_id: str,
        finding_id: str,
        status: str,
        resolution_note: str = "",
        resolved_by: str = "",
        commit_id: str = "",
    ) -> dict[str, Any]:
        """Resolve a finding within a review."""
        self._validate_id_segment(review_id, "review_id")
        valid_statuses = {s.value for s in FindingStatus} - {
            FindingStatus.OPEN.value
        }
        if status not in valid_statuses:
            raise ValueError(
                f"Invalid resolution status: {status!r}. "
                f"Must be one of: {sorted(valid_statuses)}"
            )

        data = self._load_review(review_id)
        if data is None:
            raise ValueError(f"Review not found: {review_id}")

        finding_found = False
        for f in data["findings"]:
            if f["finding_id"] == finding_id:
                f["status"] = status
                f["resolution_note"] = resolution_note
                finding_found = True
                break

        if not finding_found:
            raise ValueError(f"Finding not found: {finding_id}")

        resolution = ReviewResolution(
            finding_id=finding_id,
            resolution_note=resolution_note,
            resolved_by=resolved_by,
            commit_id=commit_id,
        )
        data["resolutions"].append(resolution.to_dict())
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._recompute_review_summary(data)
        self._write_review(data)
        return resolution.to_dict()

    def update_status(self, review_id: str, status: str) -> dict[str, Any]:
        """Update review status."""
        self._validate_id_segment(review_id, "review_id")
        valid_statuses = {s.value for s in ReviewStatus}
        if status not in valid_statuses:
            raise ValueError(
                f"Invalid status: {status!r}. "
                f"Must be one of: {sorted(valid_statuses)}"
            )

        data = self._load_review(review_id)
        if data is None:
            raise ValueError(f"Review not found: {review_id}")

        data["status"] = status
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_review(data)
        return data

    def export_review(self, review_id: str) -> str:
        """Export a review as markdown."""
        self._validate_id_segment(review_id, "review_id")
        data = self._load_review(review_id)
        if data is None:
            raise ValueError(f"Review not found: {review_id}")

        lines: list[str] = []
        lines.append(f"# Session Review: {data['title']}")
        lines.append("")
        lines.append(f"- Review ID: {data['review_id']}")
        lines.append(f"- Status: {data['status']}")
        lines.append(f"- Source: {data['source']}")
        lines.append(f"- Severity: {data['severity']}")
        if data.get("pr_id"):
            lines.append(f"- PR ID: {data['pr_id']}")
        if data.get("coding_session_id"):
            lines.append(f"- Coding Session: {data['coding_session_id']}")
        if data.get("session_report_id"):
            lines.append(f"- Session Report: {data['session_report_id']}")
        lines.append(f"- Created: {data['created_at']}")
        lines.append("")

        if data.get("rationale"):
            lines.append("## Rationale")
            lines.append("")
            lines.append(data["rationale"])
            lines.append("")

        # Summary
        summary = data.get("review_summary", {})
        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Total Findings: {summary.get('total_findings', 0)}")
        lines.append(f"- Open: {summary.get('open_findings', 0)}")
        lines.append(f"- Fixed: {summary.get('fixed_findings', 0)}")
        lines.append(
            f"- Acknowledged: {summary.get('acknowledged_findings', 0)}"
        )
        lines.append(f"- Critical: {summary.get('critical_findings', 0)}")
        lines.append(f"- High: {summary.get('high_findings', 0)}")
        lines.append("")

        # Findings (sorted by severity rank → status rank)
        findings = data.get("findings", [])
        if findings:
            sorted_findings = sorted(
                findings,
                key=lambda f: (
                    _SEVERITY_RANK.get(f.get("severity", ""), 99),
                    _FINDING_STATUS_RANK.get(f.get("status", ""), 99),
                ),
            )
            lines.append("## Findings")
            lines.append("")
            for f in sorted_findings:
                status_badge = f.get("status", "open").upper()
                sev = f.get("severity", "medium").upper()
                lines.append(
                    f"### [{sev}] {f.get('summary', '')} — {status_badge}"
                )
                lines.append("")
                if f.get("file_path"):
                    loc = f["file_path"]
                    if f.get("line_number"):
                        loc += f":{f['line_number']}"
                    lines.append(f"- Location: `{loc}`")
                if f.get("details"):
                    lines.append(f"- Details: {f['details']}")
                if f.get("resolution_note"):
                    lines.append(f"- Resolution: {f['resolution_note']}")
                lines.append("")

        # Resolutions
        resolutions = data.get("resolutions", [])
        if resolutions:
            lines.append("## Resolutions")
            lines.append("")
            for r in resolutions:
                lines.append(f"- Finding `{r['finding_id'][:12]}…`")
                if r.get("resolution_note"):
                    lines.append(f"  - Note: {r['resolution_note']}")
                if r.get("commit_id"):
                    lines.append(f"  - Commit: `{r['commit_id']}`")
                if r.get("resolved_by"):
                    lines.append(f"  - Resolved by: {r['resolved_by']}")
                lines.append("")

        # Linked IDs
        linked_vals = data.get("linked_validation_ids", [])
        linked_evs = data.get("linked_evidence_ids", [])
        if linked_vals or linked_evs:
            lines.append("## Linked Artifacts")
            lines.append("")
            for v in linked_vals:
                lines.append(f"- Validation: {v}")
            for e in linked_evs:
                lines.append(f"- Evidence: {e}")
            lines.append("")

        return "\n".join(lines)

    def write_evidence(self, review_id: str) -> str:
        """Write evidence bundle for a review."""
        self._validate_id_segment(review_id, "review_id")
        data = self._load_review(review_id)
        if data is None:
            raise ValueError(f"Review not found: {review_id}")

        evidence_dir = self._reviews_dir / review_id
        evidence_dir.mkdir(parents=True, exist_ok=True)

        # review_request.json
        request_data = {
            "review_id": data["review_id"],
            "title": data["title"],
            "source": data["source"],
            "status": data["status"],
            "severity": data["severity"],
        }
        (evidence_dir / "review_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        # review_result.json
        (evidence_dir / "review_result.json").write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )

        # session_review.md
        md = self.export_review(review_id)
        (evidence_dir / "session_review.md").write_text(md, encoding="utf-8")

        # pass_fail.json
        summary = data.get("review_summary", {})
        all_resolved = summary.get("open_findings", 0) == 0
        pass_fail = {
            "passed": all_resolved,
            "review_id": review_id,
            "total_findings": summary.get("total_findings", 0),
            "open_findings": summary.get("open_findings", 0),
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

    def _persist_review(self, review: SessionReview) -> None:
        """Write a new review to disk."""
        review_dir = self._reviews_dir / review.review_id
        review_dir.mkdir(parents=True, exist_ok=True)
        data = review.to_dict()
        (review_dir / "review.json").write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )

    def _load_review(self, review_id: str) -> dict[str, Any] | None:
        """Load a review from disk."""
        review_file = self._reviews_dir / review_id / "review.json"
        if not review_file.exists():
            return None
        return json.loads(review_file.read_text(encoding="utf-8"))

    @staticmethod
    def _recompute_review_summary(data: dict[str, Any]) -> None:
        """Recompute review summary from findings."""
        findings = data.get("findings", [])
        open_count = sum(
            1 for f in findings if f.get("status") == FindingStatus.OPEN.value
        )
        fixed_count = sum(
            1 for f in findings if f.get("status") == FindingStatus.FIXED.value
        )
        ack_count = sum(
            1 for f in findings
            if f.get("status") == FindingStatus.ACKNOWLEDGED.value
        )
        rejected_count = sum(
            1 for f in findings
            if f.get("status") == FindingStatus.REJECTED.value
        )
        deferred_count = sum(
            1 for f in findings
            if f.get("status") == FindingStatus.DEFERRED.value
        )
        critical_count = sum(
            1 for f in findings
            if f.get("severity") == FindingSeverity.CRITICAL.value
        )
        high_count = sum(
            1 for f in findings
            if f.get("severity") == FindingSeverity.HIGH.value
        )
        data["review_summary"] = {
            "total_findings": len(findings),
            "open_findings": open_count,
            "fixed_findings": fixed_count,
            "acknowledged_findings": ack_count,
            "rejected_findings": rejected_count,
            "deferred_findings": deferred_count,
            "critical_findings": critical_count,
            "high_findings": high_count,
        }

    def _write_review(self, data: dict[str, Any]) -> None:
        """Write review data to disk."""
        review_id = data["review_id"]
        review_dir = self._reviews_dir / review_id
        review_dir.mkdir(parents=True, exist_ok=True)
        (review_dir / "review.json").write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )
