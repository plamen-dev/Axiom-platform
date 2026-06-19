"""Self-Improvement Loop v1 — Axiom studies its own engineering history.

Consumes review findings, work items, code inventory, patch proposals,
and validation results to generate improvement candidates without
automatic modification.

Chain: Review Findings -> Patterns -> Improvement Candidates

Non-goals: no automatic code changes, no autonomous patch application,
no autonomous approval, no self-modification, no GitHub API, no network.
"""

from __future__ import annotations

import json
import logging
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

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ImprovementPriority(str, Enum):
    """Priority ranking for improvement candidates."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNSET = "unset"


class ImprovementCategory(str, Enum):
    """Classification of improvement type."""

    REPEATED_BUG_CLASS = "repeated_bug_class"
    MISSING_TEST = "missing_test"
    DUPLICATED_PATTERN = "duplicated_pattern"
    CANDIDATE_HELPER = "candidate_helper"
    KNOWLEDGE_UPDATE = "knowledge_update"
    SKILL_UPDATE = "skill_update"
    PLAYBOOK_UPDATE = "playbook_update"


class ImprovementStatus(str, Enum):
    """Lifecycle status of an improvement candidate."""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    IMPLEMENTED = "implemented"
    DEFERRED = "deferred"


# ---------------------------------------------------------------------------
# ORM Rows
# ---------------------------------------------------------------------------


class ImprovementCandidateRow(Base):
    """SQLAlchemy row for improvement candidates."""

    __tablename__ = "improvement_candidates"

    candidate_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    source_findings_json: Mapped[str] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=True)
    recommendation: Mapped[str] = mapped_column(Text, nullable=True)
    target_files_json: Mapped[str] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(50), nullable=False)


class ImprovementPatternRow(Base):
    """Persistent record of detected improvement patterns."""

    __tablename__ = "improvement_patterns"

    pattern_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    pattern_kind: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
    )
    occurrence_count: Mapped[str] = mapped_column(String(10), nullable=False)
    source_findings_json: Mapped[str] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(50), nullable=False)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class ImprovementEvidence:
    """Evidence supporting an improvement candidate."""

    def __init__(
        self,
        evidence_type: str = "",
        reference_id: str = "",
        description: str = "",
        timestamp: str | None = None,
    ) -> None:
        self.evidence_type = evidence_type
        self.reference_id = reference_id
        self.description = description
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_type": self.evidence_type,
            "reference_id": self.reference_id,
            "description": self.description,
            "timestamp": self.timestamp,
        }


class ImprovementPattern:
    """A detected recurring pattern across review findings."""

    def __init__(
        self,
        pattern_id: str = "",
        pattern_kind: str = "",
        occurrence_count: int = 0,
        source_findings: list[str] | None = None,
        description: str = "",
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.pattern_id = pattern_id or str(uuid4())
        self.pattern_kind = pattern_kind
        self.occurrence_count = occurrence_count
        self.source_findings = source_findings or []
        self.description = description
        self.created_at = created_at or now
        self.updated_at = updated_at or now

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "pattern_kind": self.pattern_kind,
            "occurrence_count": self.occurrence_count,
            "source_findings": self.source_findings,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ImprovementCandidate:
    """A proposed improvement derived from engineering history analysis."""

    def __init__(
        self,
        candidate_id: str = "",
        title: str = "",
        description: str = "",
        category: str = "knowledge_update",
        priority: str = "unset",
        status: str = "proposed",
        source_findings: list[str] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        recommendation: str = "",
        target_files: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.candidate_id = candidate_id or str(uuid4())
        self.title = title
        self.description = description
        self.category = category
        self.priority = priority
        self.status = status
        self.source_findings = source_findings or []
        self.evidence = evidence or []
        self.recommendation = recommendation
        self.target_files = target_files or []
        self.metadata = metadata or {}
        self.created_at = created_at or now
        self.updated_at = updated_at or now

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "priority": self.priority,
            "status": self.status,
            "source_findings": self.source_findings,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
            "target_files": self.target_files,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImprovementCandidate:
        return cls(
            candidate_id=data.get("candidate_id", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            category=data.get("category", "knowledge_update"),
            priority=data.get("priority", "unset"),
            status=data.get("status", "proposed"),
            source_findings=data.get("source_findings", []),
            evidence=data.get("evidence", []),
            recommendation=data.get("recommendation", ""),
            target_files=data.get("target_files", []),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


# ---------------------------------------------------------------------------
# SelfImprovementLoop
# ---------------------------------------------------------------------------


# Priority mapping: review pattern kind -> improvement priority
_PATTERN_PRIORITY: dict[str, str] = {
    "path_traversal": ImprovementPriority.CRITICAL.value,
    "command_injection": ImprovementPriority.CRITICAL.value,
    "persistence_defect": ImprovementPriority.HIGH.value,
    "truthiness_bug": ImprovementPriority.HIGH.value,
    "evidence_failure": ImprovementPriority.MEDIUM.value,
    "silent_exception": ImprovementPriority.MEDIUM.value,
    "enum_serialization": ImprovementPriority.MEDIUM.value,
    "duplicated_logic": ImprovementPriority.LOW.value,
    "stage_ordering": ImprovementPriority.LOW.value,
    "other": ImprovementPriority.UNSET.value,
}

# Category mapping: review pattern kind -> improvement category
_PATTERN_CATEGORY: dict[str, str] = {
    "path_traversal": ImprovementCategory.REPEATED_BUG_CLASS.value,
    "command_injection": ImprovementCategory.REPEATED_BUG_CLASS.value,
    "persistence_defect": ImprovementCategory.REPEATED_BUG_CLASS.value,
    "truthiness_bug": ImprovementCategory.REPEATED_BUG_CLASS.value,
    "evidence_failure": ImprovementCategory.MISSING_TEST.value,
    "silent_exception": ImprovementCategory.MISSING_TEST.value,
    "enum_serialization": ImprovementCategory.CANDIDATE_HELPER.value,
    "duplicated_logic": ImprovementCategory.DUPLICATED_PATTERN.value,
    "stage_ordering": ImprovementCategory.KNOWLEDGE_UPDATE.value,
    "other": ImprovementCategory.KNOWLEDGE_UPDATE.value,
}

# Recommendation templates per pattern kind
_PATTERN_RECOMMENDATIONS: dict[str, str] = {
    "path_traversal": (
        "Add _validate_id_segment() calls on all ID segments extracted from "
        "artifact data before path construction. Add regression tests for "
        "crafted artifact IDs containing '../'."
    ),
    "command_injection": (
        "Use shlex.quote() on all file paths before shell command "
        "interpolation. Use shlex.split() instead of str.split() for "
        "command parsing."
    ),
    "persistence_defect": (
        "Ensure updated_at is set on every persist/update operation. "
        "Consolidate persist + side-effect into single transactions."
    ),
    "truthiness_bug": (
        "Use explicit comparisons (is None, == '') instead of truthiness "
        "checks. Add test cases for empty string and zero values."
    ),
    "evidence_failure": (
        "Write evidence files before the final result JSON so partial "
        "failures still produce artifacts. Verify all evidence paths exist."
    ),
    "silent_exception": (
        "Replace bare except/pass with specific exception types and "
        "logging. Add test cases that verify exceptions are not silenced."
    ),
    "enum_serialization": (
        "Create a shared enum serialization helper that uses .value "
        "consistently. Add test cases for round-trip serialization."
    ),
    "duplicated_logic": (
        "Extract duplicated logic into shared utility functions. "
        "Identify common patterns across modules for consolidation."
    ),
    "stage_ordering": (
        "Document deterministic ordering requirements. Add tests that "
        "verify stage ordering is stable across runs."
    ),
}


class SelfImprovementLoop:
    """Studies engineering history and generates improvement candidates.

    Safety:
    - No automatic code changes
    - No autonomous patch application
    - No autonomous approval
    - No self-modification
    - No GitHub API, no network dependency

    Consumes: ReviewFindingRegistry, WorkItemRegistry, CodeInventory,
    PatchProposalRegistry, ValidationResults (all read-only).
    """

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
        if not value:
            return
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(
                f"Invalid {label}: must not contain '..', '/', or '\\\\'",
            )

    # -- public API ---------------------------------------------------------

    def run_analysis(self) -> dict[str, Any]:
        """Run the self-improvement analysis loop.

        Returns a summary dict with patterns, candidates, and evidence.
        Does NOT modify any code or create patches.
        """
        run_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # 1. Gather review findings
        findings = self._gather_findings()

        # 2. Detect repeated patterns
        patterns = self._detect_patterns(findings)

        # 3. Generate improvement candidates
        candidates = self._generate_candidates(patterns, findings)

        # 4. Persist patterns and candidates (single transaction)
        self._persist_all(patterns, candidates)

        # 5. Write evidence bundle
        result = {
            "run_id": run_id,
            "timestamp": now,
            "total_findings_analyzed": len(findings),
            "patterns_detected": len(patterns),
            "candidates_generated": len(candidates),
            "patterns": [p.to_dict() for p in patterns],
            "candidates": [c.to_dict() for c in candidates],
            "summary": self._build_summary(patterns, candidates),
        }

        self._write_evidence_bundle(run_id, result)
        return result

    def list_candidates(
        self,
        category: str = "",
        priority: str = "",
        status: str = "",
    ) -> list[ImprovementCandidate]:
        """List improvement candidates with optional filters."""
        with get_session(self._session_factory) as session:
            query = session.query(ImprovementCandidateRow)
            if category:
                query = query.filter(
                    ImprovementCandidateRow.category == category,
                )
            if priority:
                query = query.filter(
                    ImprovementCandidateRow.priority == priority,
                )
            if status:
                query = query.filter(
                    ImprovementCandidateRow.status == status,
                )
            query = query.order_by(ImprovementCandidateRow.created_at)
            return [self._row_to_candidate(row) for row in query.all()]

    def get_candidate(self, candidate_id: str) -> ImprovementCandidate | None:
        """Get a specific candidate by ID."""
        self._validate_id_segment(candidate_id, "candidate_id")
        with get_session(self._session_factory) as session:
            row = session.get(ImprovementCandidateRow, candidate_id)
            if not row:
                return None
            return self._row_to_candidate(row)

    def list_patterns(self) -> list[ImprovementPattern]:
        """List detected improvement patterns."""
        with get_session(self._session_factory) as session:
            rows = (
                session.query(ImprovementPatternRow)
                .order_by(ImprovementPatternRow.created_at)
                .all()
            )
            return [self._row_to_pattern(row) for row in rows]

    # -- analysis helpers ---------------------------------------------------

    def _gather_findings(self) -> list[dict[str, Any]]:
        """Gather all review findings from the registry.

        Reuses the same db_path to avoid creating a redundant DB engine.
        """
        try:
            from axiom_core.review_finding_registry import ReviewFindingRegistry
            registry = ReviewFindingRegistry(db_path=self._db_path)
            findings = registry.list_findings()
            return [f.to_dict() for f in findings]
        except Exception:
            _logger.debug("Failed to gather review findings", exc_info=True)
            return []

    def _detect_patterns(
        self, findings: list[dict[str, Any]],
    ) -> list[ImprovementPattern]:
        """Detect repeated patterns across findings."""
        pattern_groups: dict[str, list[str]] = {}
        for finding in findings:
            pattern = finding.get("pattern", "other")
            finding_id = finding.get("finding_id", "")
            if pattern not in pattern_groups:
                pattern_groups[pattern] = []
            pattern_groups[pattern].append(finding_id)

        patterns: list[ImprovementPattern] = []
        for kind in sorted(pattern_groups.keys()):
            finding_ids = pattern_groups[kind]
            if kind == "other" and len(finding_ids) < 3:
                continue
            if kind != "other" and len(finding_ids) < 2:
                continue
            patterns.append(ImprovementPattern(
                pattern_kind=kind,
                occurrence_count=len(finding_ids),
                source_findings=finding_ids,
                description=(
                    f"Pattern '{kind}' detected {len(finding_ids)} time(s) "
                    f"across review findings."
                ),
            ))
        return patterns

    def _generate_candidates(
        self,
        patterns: list[ImprovementPattern],
        findings: list[dict[str, Any]],
    ) -> list[ImprovementCandidate]:
        """Generate improvement candidates from detected patterns."""
        candidates: list[ImprovementCandidate] = []

        # Generate from patterns
        for pattern in patterns:
            priority = _PATTERN_PRIORITY.get(
                pattern.pattern_kind, ImprovementPriority.UNSET.value,
            )
            category = _PATTERN_CATEGORY.get(
                pattern.pattern_kind, ImprovementCategory.KNOWLEDGE_UPDATE.value,
            )
            recommendation = _PATTERN_RECOMMENDATIONS.get(
                pattern.pattern_kind, "",
            )

            candidate = ImprovementCandidate(
                title=self._generate_title(pattern),
                description=(
                    f"Detected {pattern.occurrence_count} occurrence(s) of "
                    f"'{pattern.pattern_kind}' across review findings. "
                    f"This recurring pattern suggests a systematic improvement."
                ),
                category=category,
                priority=priority,
                source_findings=pattern.source_findings,
                evidence=[
                    ImprovementEvidence(
                        evidence_type="pattern_analysis",
                        reference_id=pattern.pattern_id,
                        description=pattern.description,
                    ).to_dict(),
                ],
                recommendation=recommendation,
                target_files=self._suggest_target_files(
                    pattern.pattern_kind, findings,
                ),
            )
            candidates.append(candidate)

        # Generate missing-test candidates from findings with no test coverage
        test_candidates = self._detect_missing_tests(findings)
        candidates.extend(test_candidates)

        # Generate knowledge/skill/playbook recommendations
        update_candidates = self._detect_update_recommendations(patterns)
        candidates.extend(update_candidates)

        return candidates

    def _generate_title(self, pattern: ImprovementPattern) -> str:
        """Generate a descriptive title for a pattern-based candidate."""
        kind = pattern.pattern_kind
        count = pattern.occurrence_count
        titles: dict[str, str] = {
            "path_traversal": f"Add systematic path traversal validation ({count} occurrences)",
            "command_injection": f"Add systematic command injection prevention ({count} occurrences)",
            "persistence_defect": f"Fix recurring persistence defects ({count} occurrences)",
            "truthiness_bug": f"Replace truthiness checks with explicit comparisons ({count} occurrences)",
            "evidence_failure": f"Improve evidence artifact reliability ({count} occurrences)",
            "silent_exception": f"Eliminate silent exception handling ({count} occurrences)",
            "enum_serialization": f"Standardize enum serialization ({count} occurrences)",
            "duplicated_logic": f"Extract duplicated logic into shared helpers ({count} occurrences)",
            "stage_ordering": f"Document and enforce stage ordering ({count} occurrences)",
        }
        return titles.get(kind, f"Address recurring '{kind}' pattern ({count} occurrences)")

    def _suggest_target_files(
        self,
        pattern_kind: str,
        findings: list[dict[str, Any]],
    ) -> list[str]:
        """Suggest target files based on findings with matching pattern."""
        files: list[str] = []
        seen: set[str] = set()
        for finding in findings:
            if finding.get("pattern") == pattern_kind:
                source_file = finding.get("source_file", "")
                if source_file and source_file not in seen:
                    files.append(source_file)
                    seen.add(source_file)
        return sorted(files)

    def _detect_missing_tests(
        self, findings: list[dict[str, Any]],
    ) -> list[ImprovementCandidate]:
        """Detect findings suggesting missing test coverage."""
        candidates: list[ImprovementCandidate] = []
        bug_findings = [
            f for f in findings
            if f.get("category") in ("bug", "security")
            and f.get("status") != "duplicate"
        ]
        if len(bug_findings) >= 2:
            candidates.append(ImprovementCandidate(
                title=f"Add regression tests for {len(bug_findings)} bug/security findings",
                description=(
                    f"{len(bug_findings)} bug or security findings suggest "
                    f"gaps in test coverage. Each resolved finding should have "
                    f"a corresponding regression test."
                ),
                category=ImprovementCategory.MISSING_TEST.value,
                priority=ImprovementPriority.HIGH.value,
                source_findings=[f.get("finding_id", "") for f in bug_findings],
                recommendation=(
                    "Create regression tests for each resolved bug/security "
                    "finding. Group tests by pattern kind for organization."
                ),
            ))
        return candidates

    def _detect_update_recommendations(
        self, patterns: list[ImprovementPattern],
    ) -> list[ImprovementCandidate]:
        """Generate knowledge/skill/playbook update recommendations."""
        candidates: list[ImprovementCandidate] = []

        security_patterns = [
            p for p in patterns
            if p.pattern_kind in ("path_traversal", "command_injection")
        ]
        if security_patterns:
            candidates.append(ImprovementCandidate(
                title="Update knowledge: security validation patterns",
                description=(
                    "Recurring security patterns detected. Update knowledge "
                    "base with validated security patterns for path traversal "
                    "and command injection prevention."
                ),
                category=ImprovementCategory.KNOWLEDGE_UPDATE.value,
                priority=ImprovementPriority.HIGH.value,
                recommendation=(
                    "Add knowledge notes documenting _validate_id_segment() "
                    "and shlex.quote() patterns as required security measures."
                ),
            ))

        if len(patterns) >= 3:
            candidates.append(ImprovementCandidate(
                title="Update skill: review finding checklist",
                description=(
                    f"{len(patterns)} recurring patterns detected. Update "
                    f"the testing skill with a pre-submission checklist "
                    f"covering the most common patterns."
                ),
                category=ImprovementCategory.SKILL_UPDATE.value,
                priority=ImprovementPriority.MEDIUM.value,
                recommendation=(
                    "Add a pre-submission review checklist to the "
                    "testing-axiom-cli SKILL.md covering the top pattern "
                    "kinds detected in this analysis."
                ),
            ))

        if any(p.occurrence_count >= 3 for p in patterns):
            candidates.append(ImprovementCandidate(
                title="Update playbook: recurring pattern prevention",
                description=(
                    "One or more patterns have 3+ occurrences, suggesting "
                    "a systemic issue. Create a playbook for preventing "
                    "these patterns during development."
                ),
                category=ImprovementCategory.PLAYBOOK_UPDATE.value,
                priority=ImprovementPriority.MEDIUM.value,
                recommendation=(
                    "Create a development playbook with pattern-specific "
                    "checklists for the most frequent recurring issues."
                ),
            ))

        return candidates

    def _build_summary(
        self,
        patterns: list[ImprovementPattern],
        candidates: list[ImprovementCandidate],
    ) -> dict[str, Any]:
        """Build a human-readable summary of the analysis."""
        categories: dict[str, int] = {}
        priorities: dict[str, int] = {}
        for c in candidates:
            categories[c.category] = categories.get(c.category, 0) + 1
            priorities[c.priority] = priorities.get(c.priority, 0) + 1

        return {
            "patterns_by_kind": {
                p.pattern_kind: p.occurrence_count for p in patterns
            },
            "candidates_by_category": categories,
            "candidates_by_priority": priorities,
            "top_recommendation": (
                candidates[0].recommendation if candidates else ""
            ),
        }

    # -- evidence bundle writing --------------------------------------------

    def _write_evidence_bundle(
        self, run_id: str, result: dict[str, Any],
    ) -> None:
        """Write evidence artifacts for an analysis run."""
        run_dir = self._artifacts_root / "self_improvement" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc).isoformat()

        # improvement_request.json
        request_data = {
            "run_id": run_id,
            "requested_at": now,
            "analysis_type": "self_improvement_v1",
        }
        (run_dir / "improvement_request.json").write_text(
            json.dumps(request_data, indent=2), encoding="utf-8",
        )

        # improvement_result.json
        (run_dir / "improvement_result.json").write_text(
            json.dumps(result, indent=2, default=str), encoding="utf-8",
        )

        # improvement_summary.md
        summary_lines = [
            "# Self-Improvement Analysis Summary",
            "",
            f"**Run ID:** {run_id}",
            f"**Timestamp:** {now}",
            f"**Findings analyzed:** {result.get('total_findings_analyzed', 0)}",
            f"**Patterns detected:** {result.get('patterns_detected', 0)}",
            f"**Candidates generated:** {result.get('candidates_generated', 0)}",
            "",
            "## Patterns",
            "",
        ]
        for p in result.get("patterns", []):
            summary_lines.append(
                f"- **{p['pattern_kind']}**: {p['occurrence_count']} occurrence(s)",
            )
        summary_lines.extend(["", "## Improvement Candidates", ""])
        for c in result.get("candidates", []):
            summary_lines.append(
                f"- [{c['priority']}] [{c['category']}] {c['title']}",
            )
        if result.get("summary", {}).get("top_recommendation"):
            summary_lines.extend([
                "",
                "## Top Recommendation",
                "",
                result["summary"]["top_recommendation"],
            ])
        (run_dir / "improvement_summary.md").write_text(
            "\n".join(summary_lines) + "\n", encoding="utf-8",
        )

        # pass_fail.json
        pass_fail = {
            "run_id": run_id,
            "passed": True,
            "candidates_count": result.get("candidates_generated", 0),
            "timestamp": now,
        }
        (run_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2), encoding="utf-8",
        )

    # -- persistence --------------------------------------------------------

    def _persist_all(
        self,
        patterns: list[ImprovementPattern],
        candidates: list[ImprovementCandidate],
    ) -> None:
        """Persist all patterns and candidates in a single transaction."""
        with get_session(self._session_factory) as session:
            for pattern in patterns:
                session.add(ImprovementPatternRow(
                    pattern_id=pattern.pattern_id,
                    pattern_kind=pattern.pattern_kind,
                    occurrence_count=str(pattern.occurrence_count),
                    source_findings_json=json.dumps(
                        pattern.source_findings, default=str,
                    ),
                    description=pattern.description,
                    created_at=pattern.created_at,
                    updated_at=pattern.updated_at,
                ))
            for candidate in candidates:
                session.add(ImprovementCandidateRow(
                    candidate_id=candidate.candidate_id,
                    title=candidate.title,
                    description=candidate.description,
                    category=candidate.category,
                    priority=candidate.priority,
                    status=candidate.status,
                    source_findings_json=json.dumps(
                        candidate.source_findings, default=str,
                    ),
                    evidence_json=json.dumps(
                        candidate.evidence, default=str,
                    ),
                    recommendation=candidate.recommendation,
                    target_files_json=json.dumps(
                        candidate.target_files, default=str,
                    ),
                    metadata_json=json.dumps(
                        candidate.metadata, default=str,
                    ),
                    created_at=candidate.created_at,
                    updated_at=candidate.updated_at,
                ))
            session.commit()

    @staticmethod
    def _row_to_candidate(row: ImprovementCandidateRow) -> ImprovementCandidate:
        return ImprovementCandidate(
            candidate_id=row.candidate_id,
            title=row.title,
            description=row.description or "",
            category=row.category,
            priority=row.priority,
            status=row.status,
            source_findings=(
                json.loads(row.source_findings_json)
                if row.source_findings_json else []
            ),
            evidence=(
                json.loads(row.evidence_json) if row.evidence_json else []
            ),
            recommendation=row.recommendation or "",
            target_files=(
                json.loads(row.target_files_json)
                if row.target_files_json else []
            ),
            metadata=(
                json.loads(row.metadata_json) if row.metadata_json else {}
            ),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _row_to_pattern(row: ImprovementPatternRow) -> ImprovementPattern:
        return ImprovementPattern(
            pattern_id=row.pattern_id,
            pattern_kind=row.pattern_kind,
            occurrence_count=int(row.occurrence_count),
            source_findings=(
                json.loads(row.source_findings_json)
                if row.source_findings_json else []
            ),
            description=row.description or "",
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
