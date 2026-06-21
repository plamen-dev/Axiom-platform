"""Session Report Generator v1 — first-class report objects.

Creates durable report artifacts for engineering sessions. Reports
summarize plans, questions, assertions, findings, and recommendations
as evidence-driven communication rather than transient chat context.

Consumes: Session Plans, Session Questions, Assertions, Review Findings,
Validation Results.

Non-goals: no execution, no mutation, no network dependency, no PR
comments, no Git operations, no escalation framework, no automatic
actions, no approvals, no repair loops.
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


class ReportStatus(str, Enum):
    """Status of a session report."""

    DRAFT = "draft"
    FINAL = "final"
    SUPERSEDED = "superseded"


class SectionType(str, Enum):
    """Type of report section."""

    SUMMARY = "summary"
    PLANS = "plans"
    QUESTIONS = "questions"
    ASSERTIONS = "assertions"
    FINDINGS = "findings"
    VALIDATION = "validation"
    RECOMMENDATIONS = "recommendations"
    RATIONALE = "rationale"
    CUSTOM = "custom"


class RecommendationPriority(str, Enum):
    """Priority of a recommendation."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Status ranking for deterministic sorting
_STATUS_RANK: dict[str, int] = {
    ReportStatus.DRAFT.value: 0,
    ReportStatus.FINAL.value: 1,
    ReportStatus.SUPERSEDED.value: 2,
}

# Priority ranking for deterministic sorting
_PRIORITY_RANK: dict[str, int] = {
    RecommendationPriority.CRITICAL.value: 0,
    RecommendationPriority.HIGH.value: 1,
    RecommendationPriority.MEDIUM.value: 2,
    RecommendationPriority.LOW.value: 3,
}

# Section ordering for deterministic export
_SECTION_ORDER: dict[str, int] = {
    SectionType.SUMMARY.value: 0,
    SectionType.PLANS.value: 1,
    SectionType.QUESTIONS.value: 2,
    SectionType.ASSERTIONS.value: 3,
    SectionType.FINDINGS.value: 4,
    SectionType.VALIDATION.value: 5,
    SectionType.RECOMMENDATIONS.value: 6,
    SectionType.RATIONALE.value: 7,
    SectionType.CUSTOM.value: 8,
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ReportRecommendation:
    """A recommendation within a session report."""

    recommendation_id: str = ""
    description: str = ""
    priority: str = "medium"
    rationale: str = ""
    linked_assertion_id: str = ""
    linked_finding_id: str = ""

    def __post_init__(self) -> None:
        if not self.recommendation_id:
            self.recommendation_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "description": self.description,
            "priority": self.priority,
            "rationale": self.rationale,
            "linked_assertion_id": self.linked_assertion_id,
            "linked_finding_id": self.linked_finding_id,
        }


@dataclass
class ReportSection:
    """A section within a session report."""

    section_id: str = ""
    section_type: str = "custom"
    title: str = ""
    content: str = ""
    order: int = 0

    def __post_init__(self) -> None:
        if not self.section_id:
            self.section_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "section_type": self.section_type,
            "title": self.title,
            "content": self.content,
            "order": self.order,
        }


@dataclass
class ReportSummary:
    """Summary statistics for a session report."""

    total_sections: int = 0
    total_recommendations: int = 0
    critical_recommendations: int = 0
    plans_referenced: int = 0
    questions_referenced: int = 0
    assertions_referenced: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_sections": self.total_sections,
            "total_recommendations": self.total_recommendations,
            "critical_recommendations": self.critical_recommendations,
            "plans_referenced": self.plans_referenced,
            "questions_referenced": self.questions_referenced,
            "assertions_referenced": self.assertions_referenced,
        }


@dataclass
class SessionReport:
    """A durable session report artifact."""

    report_id: str = ""
    title: str = ""
    status: str = "draft"
    session_id: str = ""
    plan_id: str = ""
    work_item_id: str = ""
    sections: list[ReportSection] = field(default_factory=list)
    recommendations: list[ReportRecommendation] = field(default_factory=list)
    linked_plan_ids: list[str] = field(default_factory=list)
    linked_question_ids: list[str] = field(default_factory=list)
    linked_assertion_ids: list[str] = field(default_factory=list)
    rationale: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "title": self.title,
            "status": self.status,
            "session_id": self.session_id,
            "plan_id": self.plan_id,
            "work_item_id": self.work_item_id,
            "sections": [s.to_dict() for s in self.sections],
            "recommendations": [r.to_dict() for r in self.recommendations],
            "linked_plan_ids": list(self.linked_plan_ids),
            "linked_question_ids": list(self.linked_question_ids),
            "linked_assertion_ids": list(self.linked_assertion_ids),
            "rationale": self.rationale,
            "report_summary": self._report_summary(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def _report_summary(self) -> dict[str, Any]:
        critical = sum(
            1 for r in self.recommendations
            if r.priority == RecommendationPriority.CRITICAL.value
        )
        return {
            "total_sections": len(self.sections),
            "total_recommendations": len(self.recommendations),
            "critical_recommendations": critical,
            "plans_referenced": len(self.linked_plan_ids),
            "questions_referenced": len(self.linked_question_ids),
            "assertions_referenced": len(self.linked_assertion_ids),
        }


# ---------------------------------------------------------------------------
# Core registry
# ---------------------------------------------------------------------------


class SessionReportGenerator:
    """Durable generator for session report artifacts."""

    def __init__(
        self,
        artifacts_root: str = "",
    ) -> None:
        self._artifacts_root = artifacts_root or os.environ.get(
            "AXIOM_ARTIFACTS_ROOT", "artifacts",
        )
        self._reports_dir = Path(self._artifacts_root) / "session_reports"
        self._reports_dir.mkdir(parents=True, exist_ok=True)

    # -- ID validation ------------------------------------------------------

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            msg = f"{name} must not be empty"
            raise ValueError(msg)
        if ".." in value or "/" in value or "\\" in value:
            msg = f"{name} must not contain '..', '/', or '\\': {value!r}"
            raise ValueError(msg)

    # -- Create report ------------------------------------------------------

    def create_report(
        self,
        title: str,
        session_id: str = "",
        plan_id: str = "",
        work_item_id: str = "",
        rationale: str = "",
        sections: list[dict[str, Any]] | None = None,
        recommendations: list[dict[str, Any]] | None = None,
        linked_plan_ids: list[str] | None = None,
        linked_question_ids: list[str] | None = None,
        linked_assertion_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new session report."""
        report_sections = [
            ReportSection(
                section_type=s.get("section_type", "custom"),
                title=s.get("title", ""),
                content=s.get("content", ""),
                order=i + 1,
            )
            for i, s in enumerate(sections or [])
        ]
        report_recs = [
            ReportRecommendation(
                description=r.get("description", ""),
                priority=r.get("priority", "medium"),
                rationale=r.get("rationale", ""),
                linked_assertion_id=r.get("linked_assertion_id", ""),
                linked_finding_id=r.get("linked_finding_id", ""),
            )
            for r in (recommendations or [])
        ]

        report = SessionReport(
            title=title,
            session_id=session_id,
            plan_id=plan_id,
            work_item_id=work_item_id,
            rationale=rationale,
            sections=report_sections,
            recommendations=report_recs,
            linked_plan_ids=linked_plan_ids or [],
            linked_question_ids=linked_question_ids or [],
            linked_assertion_ids=linked_assertion_ids or [],
        )
        self._persist_report(report)
        return report.to_dict()

    # -- Get report ---------------------------------------------------------

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        """Get a report by ID."""
        self._validate_id_segment(report_id, "report_id")
        return self._load_report(report_id)

    # -- List reports -------------------------------------------------------

    def list_reports(
        self,
        status: str = "",
    ) -> list[dict[str, Any]]:
        """List all reports, optionally filtered by status."""
        reports: list[dict[str, Any]] = []
        if not self._reports_dir.exists():
            return reports

        for entry in sorted(self._reports_dir.iterdir()):
            if not entry.is_dir():
                continue
            r_file = entry / "report.json"
            if not r_file.exists():
                continue
            try:
                data = json.loads(r_file.read_text(encoding="utf-8"))
                if status and data.get("status") != status:
                    continue
                reports.append(data)
            except (json.JSONDecodeError, OSError):
                _logger.warning("Could not read report %s", entry.name)

        reports.sort(
            key=lambda r: (
                _STATUS_RANK.get(r.get("status", ""), 99),
                r.get("created_at", ""),
            ),
        )
        return reports

    # -- Update status ------------------------------------------------------

    _VALID_STATUSES = frozenset(s.value for s in ReportStatus)

    def update_status(
        self,
        report_id: str,
        status: str,
    ) -> dict[str, Any] | None:
        """Update report status."""
        self._validate_id_segment(report_id, "report_id")
        if status not in self._VALID_STATUSES:
            msg = f"Invalid status {status!r}, expected one of {sorted(self._VALID_STATUSES)}"
            raise ValueError(msg)
        report = self._load_report(report_id)
        if report is None:
            return None
        report["status"] = status
        report["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_report(report_id, report)
        return report

    # -- Add section --------------------------------------------------------

    def add_section(
        self,
        report_id: str,
        section_type: str = "custom",
        title: str = "",
        content: str = "",
    ) -> dict[str, Any] | None:
        """Add a section to a report."""
        self._validate_id_segment(report_id, "report_id")
        report = self._load_report(report_id)
        if report is None:
            return None
        existing = report.get("sections", [])
        max_order = max((s.get("order", 0) for s in existing), default=0)
        section = ReportSection(
            section_type=section_type,
            title=title,
            content=content,
            order=max_order + 1,
        )
        existing.append(section.to_dict())
        report["sections"] = existing
        report["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_report(report_id, report)
        return report

    # -- Add recommendation -------------------------------------------------

    def add_recommendation(
        self,
        report_id: str,
        description: str,
        priority: str = "medium",
        rationale: str = "",
        linked_assertion_id: str = "",
        linked_finding_id: str = "",
    ) -> dict[str, Any] | None:
        """Add a recommendation to a report."""
        self._validate_id_segment(report_id, "report_id")
        report = self._load_report(report_id)
        if report is None:
            return None
        rec = ReportRecommendation(
            description=description,
            priority=priority,
            rationale=rationale,
            linked_assertion_id=linked_assertion_id,
            linked_finding_id=linked_finding_id,
        )
        report.setdefault("recommendations", []).append(rec.to_dict())
        report["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_report(report_id, report)
        return report

    # -- Export report -------------------------------------------------------

    def export_report(self, report_id: str) -> str:
        """Export report as markdown."""
        self._validate_id_segment(report_id, "report_id")
        report = self._load_report(report_id)
        if report is None:
            msg = f"Report not found: {report_id}"
            raise ValueError(msg)

        lines = [
            f"# Session Report: {report.get('title', '')}\n",
            f"- Report ID: {report_id}",
            f"- Status: {report.get('status', '')}",
        ]

        if report.get("session_id"):
            lines.append(f"- Session ID: {report['session_id']}")
        if report.get("plan_id"):
            lines.append(f"- Plan ID: {report['plan_id']}")
        if report.get("work_item_id"):
            lines.append(f"- Work Item ID: {report['work_item_id']}")
        lines.append(f"- Created: {report.get('created_at', '')}")

        if report.get("rationale"):
            lines.append(f"\n## Rationale\n\n{report['rationale']}")

        sections = report.get("sections", [])
        if sections:
            for s in sorted(
                sections,
                key=lambda x: (
                    _SECTION_ORDER.get(x.get("section_type", ""), 99),
                    x.get("order", 0),
                ),
            ):
                section_title = s.get("title") or s.get("section_type", "Section")
                lines.append(f"\n## {section_title}\n")
                if s.get("content"):
                    lines.append(s["content"])

        recs = report.get("recommendations", [])
        if recs:
            lines.append("\n## Recommendations\n")
            for r in sorted(
                recs,
                key=lambda x: _PRIORITY_RANK.get(
                    x.get("priority", "medium"), 99,
                ),
            ):
                lines.append(
                    f"- [{r.get('priority', 'medium')}] "
                    f"{r.get('description', '')}",
                )
                if r.get("rationale"):
                    lines.append(f"  Rationale: {r['rationale']}")

        linked_plans = report.get("linked_plan_ids", [])
        linked_questions = report.get("linked_question_ids", [])
        linked_assertions = report.get("linked_assertion_ids", [])
        if linked_plans or linked_questions or linked_assertions:
            lines.append("\n## References\n")
            if linked_plans:
                lines.append(f"- Plans: {', '.join(linked_plans)}")
            if linked_questions:
                lines.append(f"- Questions: {', '.join(linked_questions)}")
            if linked_assertions:
                lines.append(f"- Assertions: {', '.join(linked_assertions)}")

        summary = report.get("report_summary", {})
        lines.append(
            f"\n## Summary\n\n"
            f"- Sections: {summary.get('total_sections', 0)}\n"
            f"- Recommendations: {summary.get('total_recommendations', 0)}\n"
            f"- Critical: {summary.get('critical_recommendations', 0)}",
        )

        return "\n".join(lines) + "\n"

    # -- Evidence writing ---------------------------------------------------

    def write_evidence(self, report_id: str) -> str:
        """Write evidence bundle for a report."""
        self._validate_id_segment(report_id, "report_id")
        report = self._load_report(report_id)
        if report is None:
            msg = f"Report not found: {report_id}"
            raise ValueError(msg)

        evidence_dir = self._reports_dir / report_id
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "report_id": report_id,
            "title": report.get("title", ""),
            "status": report.get("status", ""),
            "session_id": report.get("session_id", ""),
            "plan_id": report.get("plan_id", ""),
            "work_item_id": report.get("work_item_id", ""),
            "created_at": report.get("created_at", ""),
        }
        (evidence_dir / "report_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
        )

        (evidence_dir / "report_result.json").write_text(
            json.dumps(report, indent=2, default=str),
        )

        (evidence_dir / "session_report.md").write_text(
            self.export_report(report_id),
        )

        summary = report.get("report_summary", {})
        pass_fail = {
            "passed": report.get("status") in (
                ReportStatus.DRAFT.value,
                ReportStatus.FINAL.value,
            ),
            "report_id": report_id,
            "status": report.get("status", ""),
            "total_sections": summary.get("total_sections", 0),
            "total_recommendations": summary.get("total_recommendations", 0),
            "critical_recommendations": summary.get("critical_recommendations", 0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
        )

        return str(evidence_dir)

    # -- Internal helpers ---------------------------------------------------

    def _persist_report(self, report: SessionReport) -> None:
        r_dir = self._reports_dir / report.report_id
        r_dir.mkdir(parents=True, exist_ok=True)
        (r_dir / "report.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
        )

    def _load_report(self, report_id: str) -> dict[str, Any] | None:
        r_path = self._reports_dir / report_id / "report.json"
        if not r_path.exists():
            return None
        return json.loads(r_path.read_text(encoding="utf-8"))

    @staticmethod
    def _recompute_report_summary(data: dict[str, Any]) -> None:
        """Recalculate report_summary from current state."""
        sections = data.get("sections", [])
        recs = data.get("recommendations", [])
        critical = sum(
            1 for r in recs
            if r.get("priority") == RecommendationPriority.CRITICAL.value
        )
        data["report_summary"] = {
            "total_sections": len(sections),
            "total_recommendations": len(recs),
            "critical_recommendations": critical,
            "plans_referenced": len(data.get("linked_plan_ids", [])),
            "questions_referenced": len(data.get("linked_question_ids", [])),
            "assertions_referenced": len(data.get("linked_assertion_ids", [])),
        }

    def _write_report(
        self, report_id: str, data: dict[str, Any],
    ) -> None:
        self._recompute_report_summary(data)
        r_dir = self._reports_dir / report_id
        r_dir.mkdir(parents=True, exist_ok=True)
        (r_dir / "report.json").write_text(
            json.dumps(data, indent=2, default=str),
        )
