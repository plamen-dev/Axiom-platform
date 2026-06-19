"""Review Finding Ingestion v1 — durable engineering memory for review feedback.

Converts review feedback into persistent, categorized findings with pattern
tracking and history preservation.

Chain: Work Item -> Implementation Plan -> Patch Proposal -> Patch Review
      -> Patch Application -> Code Validation -> PR Draft -> Review Findings
      (this module)

Non-goals: no automatic repair, no learning loops, no patch generation,
no PR creation, no code modification, no GitHub API, no network dependency.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from axiom_core.database import (
    create_db_engine,
    get_session,
    init_db,
    make_session_factory,
)
from axiom_core.models import Base

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ReviewCategory(str, Enum):
    """Classification of review finding type."""

    BUG = "bug"
    FLAG = "flag"
    SECURITY = "security"
    ARCHITECTURE = "architecture"
    PERFORMANCE = "performance"
    STYLE = "style"
    INFORMATIONAL = "informational"


class ReviewSeverity(str, Enum):
    """Impact severity of a review finding."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"


class ReviewFindingStatus(str, Enum):
    """Lifecycle status of a review finding."""

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    WONT_FIX = "wont_fix"
    DUPLICATE = "duplicate"


class ReviewPatternKind(str, Enum):
    """Known recurring review finding patterns."""

    TRUTHINESS_BUG = "truthiness_bug"
    ENUM_SERIALIZATION = "enum_serialization"
    PERSISTENCE_DEFECT = "persistence_defect"
    EVIDENCE_FAILURE = "evidence_failure"
    SILENT_EXCEPTION = "silent_exception"
    DUPLICATED_LOGIC = "duplicated_logic"
    PATH_TRAVERSAL = "path_traversal"
    COMMAND_INJECTION = "command_injection"
    STAGE_ORDERING = "stage_ordering"
    OTHER = "other"


# ---------------------------------------------------------------------------
# ORM Rows
# ---------------------------------------------------------------------------


class ReviewFindingRow(Base):
    """SQLAlchemy row for review findings."""

    __tablename__ = "review_findings"

    finding_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    pattern: Mapped[str] = mapped_column(String(50), nullable=True, index=True)
    source_pr: Mapped[str] = mapped_column(String(200), nullable=True)
    source_file: Mapped[str] = mapped_column(String(500), nullable=True)
    source_line: Mapped[str] = mapped_column(String(20), nullable=True)
    draft_id: Mapped[str] = mapped_column(String(200), nullable=True)
    validation_run_id: Mapped[str] = mapped_column(String(200), nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=True)
    resolution: Mapped[str] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(50), nullable=False)


class ReviewHistoryRow(Base):
    """Audit log for review finding status changes."""

    __tablename__ = "review_finding_history"

    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    finding_id: Mapped[str] = mapped_column(
        String(200), nullable=False, index=True,
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[str] = mapped_column(String(100), nullable=True)
    new_value: Mapped[str] = mapped_column(String(100), nullable=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=True)
    timestamp: Mapped[str] = mapped_column(String(50), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=True)


class ReviewPatternRow(Base):
    """Persistent record of detected review patterns."""

    __tablename__ = "review_patterns"

    pattern_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    kind: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    finding_id: Mapped[str] = mapped_column(
        String(200), nullable=False, index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class ReviewPattern:
    """A detected recurring pattern in review findings."""

    def __init__(
        self,
        pattern_id: str = "",
        kind: str = "other",
        finding_id: str = "",
        description: str = "",
        created_at: str | None = None,
    ) -> None:
        self.pattern_id = pattern_id or str(uuid4())
        self.kind = kind
        self.finding_id = finding_id
        self.description = description
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "kind": self.kind,
            "finding_id": self.finding_id,
            "description": self.description,
            "created_at": self.created_at,
        }


class ReviewHistory:
    """An audit entry for a review finding status change."""

    def __init__(
        self,
        event_id: str = "",
        finding_id: str = "",
        action: str = "",
        old_value: str | None = None,
        new_value: str | None = None,
        actor: str | None = None,
        timestamp: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.event_id = event_id or str(uuid4())
        self.finding_id = finding_id
        self.action = action
        self.old_value = old_value
        self.new_value = new_value
        self.actor = actor
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "finding_id": self.finding_id,
            "action": self.action,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "actor": self.actor,
            "timestamp": self.timestamp,
            "details": self.details,
        }


class ReviewFinding:
    """A single review finding record."""

    def __init__(
        self,
        finding_id: str = "",
        title: str = "",
        description: str = "",
        category: str = "informational",
        severity: str = "informational",
        status: str = "open",
        pattern: str = "other",
        source_pr: str = "",
        source_file: str = "",
        source_line: str = "",
        draft_id: str = "",
        validation_run_id: str = "",
        evidence: list[dict[str, Any]] | None = None,
        resolution: str = "",
        metadata: dict[str, Any] | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.finding_id = finding_id or str(uuid4())
        self.title = title
        self.description = description
        self.category = category
        self.severity = severity
        self.status = status
        self.pattern = pattern
        self.source_pr = source_pr
        self.source_file = source_file
        self.source_line = source_line
        self.draft_id = draft_id
        self.validation_run_id = validation_run_id
        self.evidence = evidence or []
        self.resolution = resolution
        self.metadata = metadata or {}
        self.created_at = created_at or now
        self.updated_at = updated_at or now

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "severity": self.severity,
            "status": self.status,
            "pattern": self.pattern,
            "source_pr": self.source_pr,
            "source_file": self.source_file,
            "source_line": self.source_line,
            "draft_id": self.draft_id,
            "validation_run_id": self.validation_run_id,
            "evidence": self.evidence,
            "resolution": self.resolution,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReviewFinding:
        return cls(
            finding_id=data.get("finding_id", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            category=data.get("category", "informational"),
            severity=data.get("severity", "informational"),
            status=data.get("status", "open"),
            pattern=data.get("pattern", "other"),
            source_pr=data.get("source_pr", ""),
            source_file=data.get("source_file", ""),
            source_line=data.get("source_line", ""),
            draft_id=data.get("draft_id", ""),
            validation_run_id=data.get("validation_run_id", ""),
            evidence=data.get("evidence", []),
            resolution=data.get("resolution", ""),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


# ---------------------------------------------------------------------------
# ReviewFindingRegistry
# ---------------------------------------------------------------------------


class ReviewFindingRegistry:
    """Persists review findings, patterns, and history in SQLite.

    Safety:
    - No automatic repair, no code modification
    - No patch application, no GitHub API
    - No network dependency, no merge behavior
    - Read-only consumption of upstream evidence bundles

    Non-goals: no learning loops, no patch generation, no PR creation.
    """

    # Pattern keyword detection for auto-classification.
    # Keywords are matched against lowercased text, so must be lowercase.
    # Use multi-word phrases to reduce false positives from generic words.
    _PATTERN_KEYWORDS: dict[str, list[str]] = {
        ReviewPatternKind.TRUTHINESS_BUG.value: [
            "truthiness", "truthy check", "falsy check", "bool check",
        ],
        ReviewPatternKind.ENUM_SERIALIZATION.value: [
            "enum serial", "enum .value", "enum string",
        ],
        ReviewPatternKind.PERSISTENCE_DEFECT.value: [
            "persist defect", "updated_at", "missing persist", "write defect",
        ],
        ReviewPatternKind.EVIDENCE_FAILURE.value: [
            "evidence failure", "evidence missing", "artifact missing",
            "pass_fail", "bundle missing",
        ],
        ReviewPatternKind.SILENT_EXCEPTION.value: [
            "silent exception", "swallow exception", "bare except",
            "pass except",
        ],
        ReviewPatternKind.DUPLICATED_LOGIC.value: [
            "duplicated logic", "duplicated code", "redundant logic",
        ],
        ReviewPatternKind.PATH_TRAVERSAL.value: [
            "path traversal", "directory traversal", "cwe-22", "../",
        ],
        ReviewPatternKind.COMMAND_INJECTION.value: [
            "command injection", "shell inject", "cwe-88",
            "shlex.quote missing",
        ],
        ReviewPatternKind.STAGE_ORDERING.value: [
            "stage order", "stage ordering", "deterministic order",
        ],
    }

    def __init__(
        self,
        db_path: str | None = None,
        artifacts_root: str | None = None,
    ) -> None:
        self._db_path = db_path or os.environ.get("AXIOM_DB_PATH")
        self._artifacts_root = Path(
            artifacts_root or os.environ.get("AXIOM_ARTIFACTS_ROOT", "artifacts"),
        )
        self._init_db()

    def _init_db(self) -> None:
        engine = create_db_engine(self._db_path)
        init_db(engine)
        self._session_factory = make_session_factory(engine)

    # -- ID validation ------------------------------------------------------

    @staticmethod
    def _validate_id_segment(value: str, label: str) -> None:
        """Reject path-traversal attempts in ID segments."""
        if not value:
            return
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(
                f"Invalid {label}: must not contain '..', '/', or '\\\\'",
            )

    # -- public API ---------------------------------------------------------

    def create_finding(
        self,
        title: str,
        description: str = "",
        category: str = "informational",
        severity: str = "informational",
        pattern: str = "",
        source_pr: str = "",
        source_file: str = "",
        source_line: str = "",
        draft_id: str = "",
        validation_run_id: str = "",
        evidence: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ReviewFinding:
        """Create and persist a new review finding."""
        if not title:
            raise ValueError("Finding title is required")

        # Validate enum values
        try:
            ReviewCategory(category)
        except ValueError:
            valid = ", ".join(c.value for c in ReviewCategory)
            raise ValueError(
                f"Invalid category '{category}'. Valid: {valid}",
            )

        try:
            ReviewSeverity(severity)
        except ValueError:
            valid = ", ".join(s.value for s in ReviewSeverity)
            raise ValueError(
                f"Invalid severity '{severity}'. Valid: {valid}",
            )

        if not pattern:
            pattern = self._detect_pattern(title, description)

        finding = ReviewFinding(
            title=title,
            description=description,
            category=category,
            severity=severity,
            pattern=pattern,
            source_pr=source_pr,
            source_file=source_file,
            source_line=source_line,
            draft_id=draft_id,
            validation_run_id=validation_run_id,
            evidence=evidence or [],
            metadata=metadata or {},
        )

        self._persist_finding(finding)
        self._record_history(
            finding.finding_id, "created", None, finding.status,
            details={"category": category, "severity": severity},
        )

        if pattern != "other":
            self._persist_pattern(ReviewPattern(
                kind=pattern,
                finding_id=finding.finding_id,
                description=f"Auto-detected from: {title}",
            ))

        return finding

    def get_finding(self, finding_id: str) -> ReviewFinding | None:
        """Get a finding by ID. Returns None if not found."""
        self._validate_id_segment(finding_id, "finding_id")
        with get_session(self._session_factory) as session:
            row = session.get(ReviewFindingRow, finding_id)
            if not row:
                return None
            return self._row_to_finding(row)

    def list_findings(
        self,
        category: str = "",
        severity: str = "",
        status: str = "",
        pattern: str = "",
    ) -> list[ReviewFinding]:
        """List findings with optional filters."""
        with get_session(self._session_factory) as session:
            query = session.query(ReviewFindingRow)
            if category:
                query = query.filter(ReviewFindingRow.category == category)
            if severity:
                query = query.filter(ReviewFindingRow.severity == severity)
            if status:
                query = query.filter(ReviewFindingRow.status == status)
            if pattern:
                query = query.filter(ReviewFindingRow.pattern == pattern)
            query = query.order_by(ReviewFindingRow.created_at)
            return [self._row_to_finding(row) for row in query.all()]

    def update_finding(
        self,
        finding_id: str,
        status: str = "",
        resolution: str = "",
        severity: str = "",
        category: str = "",
    ) -> ReviewFinding:
        """Update a finding's status, resolution, severity, or category."""
        self._validate_id_segment(finding_id, "finding_id")
        if not status and not resolution and not severity and not category:
            raise ValueError("No changes specified")

        with get_session(self._session_factory) as session:
            row = session.get(ReviewFindingRow, finding_id)
            if not row:
                raise ValueError(f"Finding not found: {finding_id}")

            now = datetime.now(timezone.utc).isoformat()

            if status:
                try:
                    ReviewFindingStatus(status)
                except ValueError:
                    valid = ", ".join(s.value for s in ReviewFindingStatus)
                    raise ValueError(
                        f"Invalid status '{status}'. Valid: {valid}",
                    )
                old_status = row.status
                row.status = status
                self._record_history(
                    finding_id, "status_change", old_status, status,
                    session=session,
                )

            if resolution:
                row.resolution = resolution

            if severity:
                try:
                    ReviewSeverity(severity)
                except ValueError:
                    valid = ", ".join(s.value for s in ReviewSeverity)
                    raise ValueError(
                        f"Invalid severity '{severity}'. Valid: {valid}",
                    )
                old_severity = row.severity
                row.severity = severity
                self._record_history(
                    finding_id, "severity_change", old_severity, severity,
                    session=session,
                )

            if category:
                try:
                    ReviewCategory(category)
                except ValueError:
                    valid = ", ".join(c.value for c in ReviewCategory)
                    raise ValueError(
                        f"Invalid category '{category}'. Valid: {valid}",
                    )
                old_category = row.category
                row.category = category
                self._record_history(
                    finding_id, "category_change", old_category, category,
                    session=session,
                )

            row.updated_at = now
            session.commit()
            return self._row_to_finding(row)

    def merge_duplicate(
        self, finding_id: str, duplicate_of_id: str,
    ) -> ReviewFinding:
        """Mark a finding as duplicate of another."""
        self._validate_id_segment(finding_id, "finding_id")
        self._validate_id_segment(duplicate_of_id, "duplicate_of_id")

        if finding_id == duplicate_of_id:
            raise ValueError("Cannot mark finding as duplicate of itself")

        with get_session(self._session_factory) as session:
            row = session.get(ReviewFindingRow, finding_id)
            if not row:
                raise ValueError(f"Finding not found: {finding_id}")

            target = session.get(ReviewFindingRow, duplicate_of_id)
            if not target:
                raise ValueError(f"Target finding not found: {duplicate_of_id}")

            old_status = row.status
            row.status = ReviewFindingStatus.DUPLICATE.value
            row.resolution = f"Duplicate of {duplicate_of_id}"
            row.updated_at = datetime.now(timezone.utc).isoformat()
            self._record_history(
                finding_id, "duplicate_merge", old_status,
                ReviewFindingStatus.DUPLICATE.value,
                details={"duplicate_of": duplicate_of_id},
                session=session,
            )
            session.commit()
            return self._row_to_finding(row)

    def get_history(self, finding_id: str) -> list[ReviewHistory]:
        """Get the full audit history for a finding."""
        self._validate_id_segment(finding_id, "finding_id")
        with get_session(self._session_factory) as session:
            rows = (
                session.query(ReviewHistoryRow)
                .filter(ReviewHistoryRow.finding_id == finding_id)
                .order_by(ReviewHistoryRow.timestamp)
                .all()
            )
            return [
                ReviewHistory(
                    event_id=r.event_id,
                    finding_id=r.finding_id,
                    action=r.action,
                    old_value=r.old_value,
                    new_value=r.new_value,
                    actor=r.actor,
                    timestamp=r.timestamp,
                    details=json.loads(r.details_json) if r.details_json else {},
                )
                for r in rows
            ]

    def list_patterns(self, kind: str = "") -> list[ReviewPattern]:
        """List detected patterns, optionally filtered by kind."""
        with get_session(self._session_factory) as session:
            query = session.query(ReviewPatternRow)
            if kind:
                query = query.filter(ReviewPatternRow.kind == kind)
            query = query.order_by(ReviewPatternRow.created_at)
            return [
                ReviewPattern(
                    pattern_id=r.pattern_id,
                    kind=r.kind,
                    finding_id=r.finding_id,
                    description=r.description or "",
                    created_at=r.created_at,
                )
                for r in query.all()
            ]

    def ingest_from_evidence(
        self,
        source_dir: str = "",
        draft_id: str = "",
    ) -> list[ReviewFinding]:
        """Ingest review findings from evidence bundles.

        Scans PR draft artifacts and validation runs for findings to ingest.
        Returns the list of newly created findings.
        """
        self._validate_id_segment(draft_id, "draft_id")
        findings: list[ReviewFinding] = []

        if draft_id:
            draft_data = self._load_draft(draft_id)
            if draft_data:
                findings.extend(self._ingest_from_draft(draft_data))

        if source_dir:
            source_path = Path(source_dir)
            if source_path.exists() and source_path.is_dir():
                findings.extend(self._ingest_from_directory(source_path))

        # Write evidence bundle for this ingestion run
        if findings:
            run_id = str(uuid4())
            self._write_evidence_bundle(run_id, findings)

        return findings

    # -- evidence bundle writing --------------------------------------------

    def _write_evidence_bundle(
        self, run_id: str, findings: list[ReviewFinding],
    ) -> None:
        """Write evidence artifacts for an ingestion run."""
        run_dir = self._artifacts_root / "review_findings" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc).isoformat()

        # review_request.json
        request_data = {
            "run_id": run_id,
            "findings_count": len(findings),
            "requested_at": now,
        }
        (run_dir / "review_request.json").write_text(
            json.dumps(request_data, indent=2), encoding="utf-8",
        )

        # review_result.json
        result_data = {
            "run_id": run_id,
            "findings": [f.to_dict() for f in findings],
            "total_findings": len(findings),
            "categories": self._count_by_field(findings, "category"),
            "severities": self._count_by_field(findings, "severity"),
            "patterns": self._count_by_field(findings, "pattern"),
            "completed_at": now,
        }
        (run_dir / "review_result.json").write_text(
            json.dumps(result_data, indent=2, default=str), encoding="utf-8",
        )

        # review_summary.md
        summary_lines = [
            "# Review Finding Ingestion Summary",
            "",
            f"**Run ID:** {run_id}",
            f"**Findings ingested:** {len(findings)}",
            f"**Timestamp:** {now}",
            "",
            "## Categories",
            "",
        ]
        for cat, count in sorted(self._count_by_field(findings, "category").items()):
            summary_lines.append(f"- {cat}: {count}")
        summary_lines.extend(["", "## Severities", ""])
        for sev, count in sorted(self._count_by_field(findings, "severity").items()):
            summary_lines.append(f"- {sev}: {count}")
        summary_lines.extend(["", "## Findings", ""])
        for f in findings:
            summary_lines.append(
                f"- [{f.severity}] [{f.category}] {f.title} ({f.finding_id[:12]}...)",
            )
        (run_dir / "review_summary.md").write_text(
            "\n".join(summary_lines) + "\n", encoding="utf-8",
        )

        # pass_fail.json
        pass_fail = {
            "run_id": run_id,
            "passed": True,
            "findings_count": len(findings),
            "timestamp": now,
        }
        (run_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2), encoding="utf-8",
        )

    @staticmethod
    def _count_by_field(
        findings: list[ReviewFinding], field: str,
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in findings:
            val = getattr(f, field, "unknown")
            counts[val] = counts.get(val, 0) + 1
        return counts

    # -- ingestion helpers --------------------------------------------------

    def _load_draft(self, draft_id: str) -> dict[str, Any]:
        """Load PR draft from artifact directory."""
        result_file = (
            self._artifacts_root / "pr_drafts" / draft_id / "pr_result.json"
        )
        if not result_file.exists():
            return {}
        try:
            return json.loads(result_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _ingest_from_draft(
        self, draft_data: dict[str, Any],
    ) -> list[ReviewFinding]:
        """Extract findings from PR draft metadata."""
        findings: list[ReviewFinding] = []
        limitations = draft_data.get("known_limitations", [])
        draft_id = draft_data.get("draft_id", "")

        for limitation in limitations:
            finding = self.create_finding(
                title=f"Known limitation: {limitation}",
                description=limitation,
                category=ReviewCategory.INFORMATIONAL.value,
                severity=ReviewSeverity.LOW.value,
                draft_id=draft_id,
            )
            findings.append(finding)

        return findings

    def _ingest_from_directory(
        self, source_path: Path,
    ) -> list[ReviewFinding]:
        """Scan a directory for review finding JSON files."""
        findings: list[ReviewFinding] = []
        for json_file in sorted(source_path.glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "title" in item:
                            finding = self.create_finding(**self._sanitize_input(item))
                            findings.append(finding)
                elif isinstance(data, dict) and "title" in data:
                    finding = self.create_finding(**self._sanitize_input(data))
                    findings.append(finding)
            except (json.JSONDecodeError, OSError, ValueError, TypeError):
                continue
        return findings

    @staticmethod
    def _sanitize_input(data: dict[str, Any]) -> dict[str, Any]:
        """Extract only safe fields for create_finding."""
        allowed_keys = {
            "title", "description", "category", "severity", "pattern",
            "source_pr", "source_file", "source_line", "draft_id",
            "validation_run_id", "evidence", "metadata",
        }
        return {k: v for k, v in data.items() if k in allowed_keys}

    # -- pattern detection --------------------------------------------------

    def _detect_pattern(self, title: str, description: str) -> str:
        """Auto-detect pattern kind from title and description text."""
        text = f"{title} {description}".lower()
        for kind, keywords in self._PATTERN_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text:
                    return kind
        return ReviewPatternKind.OTHER.value

    # -- persistence --------------------------------------------------------

    def _persist_finding(self, finding: ReviewFinding) -> None:
        """Write a finding to SQLite."""
        with get_session(self._session_factory) as session:
            row = ReviewFindingRow(
                finding_id=finding.finding_id,
                title=finding.title,
                description=finding.description,
                category=finding.category,
                severity=finding.severity,
                status=finding.status,
                pattern=finding.pattern,
                source_pr=finding.source_pr,
                source_file=finding.source_file,
                source_line=finding.source_line,
                draft_id=finding.draft_id,
                validation_run_id=finding.validation_run_id,
                evidence_json=json.dumps(finding.evidence, default=str),
                resolution=finding.resolution,
                metadata_json=json.dumps(finding.metadata, default=str),
                created_at=finding.created_at,
                updated_at=finding.updated_at,
            )
            session.add(row)
            session.commit()

    def _persist_pattern(self, pattern: ReviewPattern) -> None:
        """Write a pattern record to SQLite."""
        with get_session(self._session_factory) as session:
            row = ReviewPatternRow(
                pattern_id=pattern.pattern_id,
                kind=pattern.kind,
                finding_id=pattern.finding_id,
                description=pattern.description,
                created_at=pattern.created_at,
            )
            session.add(row)
            session.commit()

    def _record_history(
        self,
        finding_id: str,
        action: str,
        old_value: str | None,
        new_value: str | None,
        actor: str | None = None,
        details: dict[str, Any] | None = None,
        session: Any = None,
    ) -> None:
        """Record a history entry."""
        entry = ReviewHistoryRow(
            event_id=str(uuid4()),
            finding_id=finding_id,
            action=action,
            old_value=old_value,
            new_value=new_value,
            actor=actor or "system",
            timestamp=datetime.now(timezone.utc).isoformat(),
            details_json=json.dumps(details or {}, default=str),
        )
        if session:
            session.add(entry)
        else:
            with get_session(self._session_factory) as s:
                s.add(entry)
                s.commit()

    @staticmethod
    def _row_to_finding(row: ReviewFindingRow) -> ReviewFinding:
        """Convert a DB row to a ReviewFinding."""
        return ReviewFinding(
            finding_id=row.finding_id,
            title=row.title,
            description=row.description or "",
            category=row.category,
            severity=row.severity,
            status=row.status,
            pattern=row.pattern or "other",
            source_pr=row.source_pr or "",
            source_file=row.source_file or "",
            source_line=row.source_line or "",
            draft_id=row.draft_id or "",
            validation_run_id=row.validation_run_id or "",
            evidence=json.loads(row.evidence_json) if row.evidence_json else [],
            resolution=row.resolution or "",
            metadata=json.loads(row.metadata_json) if row.metadata_json else {},
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
