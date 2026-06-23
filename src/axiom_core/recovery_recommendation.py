"""Recovery Recommendation Framework v1.

Provides deterministic representation of recommended recovery actions on top of
the Failure Classification Framework. Where a failure classification records
*why* an outcome failed, a recovery recommendation records *what should be done*
about it: a recommended action type, priority, summary, and rationale, with
evidence bundles.

Non-goals: no automatic repair execution, no schedulers, no worker
orchestration, no autonomous execution, no approvals, no workflow routing,
no merge behavior.
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

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RecoveryRecommendationType(str, Enum):
    RETRY = "retry"
    REPAIR = "repair"
    ROLLBACK = "rollback"
    ESCALATE = "escalate"
    IGNORE = "ignore"
    INVESTIGATE = "investigate"


class RecoveryPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


_VALID_TYPES = {t.value for t in RecoveryRecommendationType}
_VALID_PRIORITIES = {p.value for p in RecoveryPriority}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class RecoveryRecommendation:
    """A single recommended recovery action for a failure classification."""

    recommendation_id: str = ""
    classification_id: str = ""
    recommendation_type: str = "investigate"
    priority: str = "normal"
    summary: str = ""
    rationale: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.recommendation_id:
            self.recommendation_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "classification_id": self.classification_id,
            "recommendation_type": self.recommendation_type,
            "priority": self.priority,
            "summary": self.summary,
            "rationale": self.rationale,
            "created_at": self.created_at,
        }


@dataclass
class RecoveryRecommendationReport:
    """Report summarizing a set of recovery recommendations."""

    report_id: str = ""
    recommendation_count: int = 0
    low_count: int = 0
    normal_count: int = 0
    high_count: int = 0
    critical_count: int = 0
    created_at: str = ""
    recommendations: list[RecoveryRecommendation] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "recommendation_count": self.recommendation_count,
            "low_count": self.low_count,
            "normal_count": self.normal_count,
            "high_count": self.high_count,
            "critical_count": self.critical_count,
            "created_at": self.created_at,
            "recommendations": [r.to_dict() for r in self.recommendations],
        }


@dataclass
class RecoveryRecommendationEvidence:
    """Evidence record for a recovery recommendation report."""

    evidence_id: str = ""
    report_id: str = ""
    summary: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.evidence_id:
            self.evidence_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "report_id": self.report_id,
            "summary": self.summary,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class RecoveryRecommendationEngine:
    """Manages recovery recommendation reports deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "recovery_recommendations"
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
        if not str(target).startswith(str(sandbox) + "/") and target != sandbox:
            raise ValueError(f"Resolved path escapes artifacts root: {report_id!r}")
        return target

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(
        self, recommendations: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Create a recovery recommendation report from a list of recommendations."""
        recommendations = recommendations or []

        recommendation_objects: list[RecoveryRecommendation] = []
        for r_data in recommendations:
            recommendation_type = r_data.get("recommendation_type", "investigate")
            if recommendation_type not in _VALID_TYPES:
                raise ValueError(
                    f"Invalid recommendation_type: {recommendation_type!r}. "
                    f"Valid: {sorted(_VALID_TYPES)}"
                )
            priority = r_data.get("priority", "normal")
            if priority not in _VALID_PRIORITIES:
                raise ValueError(
                    f"Invalid priority: {priority!r}. "
                    f"Valid: {sorted(_VALID_PRIORITIES)}"
                )
            classification_id = r_data.get("classification_id", "")
            if not classification_id:
                raise ValueError(
                    "classification_id is required for a recovery recommendation"
                )
            recommendation_objects.append(
                RecoveryRecommendation(
                    classification_id=classification_id,
                    recommendation_type=recommendation_type,
                    priority=priority,
                    summary=r_data.get("summary", ""),
                    rationale=r_data.get("rationale", ""),
                    created_at=r_data.get("created_at", ""),
                )
            )

        # Deterministic ordering: chronological by created_at, then
        # classification_id, then recommendation_id for stability.
        recommendation_objects.sort(
            key=lambda r: (r.created_at, r.classification_id, r.recommendation_id)
        )

        low = sum(1 for r in recommendation_objects if r.priority == "low")
        normal = sum(1 for r in recommendation_objects if r.priority == "normal")
        high = sum(1 for r in recommendation_objects if r.priority == "high")
        critical = sum(1 for r in recommendation_objects if r.priority == "critical")

        report = RecoveryRecommendationReport(
            recommendation_count=len(recommendation_objects),
            low_count=low,
            normal_count=normal,
            high_count=high,
            critical_count=critical,
            recommendations=recommendation_objects,
        )

        self._persist(report)
        self._write_evidence(report)

        return report.to_dict()

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
            if not str(resolved).startswith(str(sandbox) + "/") and resolved != sandbox:
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
            raise ValueError(
                f"Recovery recommendation report not found: {report_id}"
            )
        return self._generate_export_md(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, report: RecoveryRecommendationReport) -> None:
        report_dir = self._safe_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
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

    def _write_evidence(self, report: RecoveryRecommendationReport) -> None:
        evidence_dir = self._safe_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "recommendations": [r.to_dict() for r in report.recommendations]
        }
        (evidence_dir / "recovery_recommendation_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "recovery_recommendation_result.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_export_md(report.to_dict())
        (evidence_dir / "recovery_recommendation_summary.md").write_text(
            md, encoding="utf-8"
        )

        evidence = RecoveryRecommendationEvidence(
            report_id=report.report_id,
            summary=(
                f"{report.recommendation_count} recommendations, "
                f"{report.critical_count} critical, "
                f"{report.high_count} high"
            ),
        )

        # A recovery recommendation report passes when no recommendation is
        # critical priority.
        passed = report.critical_count == 0
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "evidence_id": evidence.evidence_id,
            "recommendation_count": report.recommendation_count,
            "low_count": report.low_count,
            "normal_count": report.normal_count,
            "high_count": report.high_count,
            "critical_count": report.critical_count,
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

        lines.append("# Recovery Recommendation Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        lines.append("## Priority Counts")
        lines.append("")
        lines.append(f"- Recommendations: {data.get('recommendation_count', 0)}")
        lines.append(f"- Low: {data.get('low_count', 0)}")
        lines.append(f"- Normal: {data.get('normal_count', 0)}")
        lines.append(f"- High: {data.get('high_count', 0)}")
        lines.append(f"- Critical: {data.get('critical_count', 0)}")
        lines.append("")

        recommendations = data.get("recommendations", [])

        if recommendations:
            type_counts: dict[str, int] = {}
            for r in recommendations:
                rec_type = r.get("recommendation_type", "investigate")
                type_counts[rec_type] = type_counts.get(rec_type, 0) + 1

            lines.append("## Type Counts")
            lines.append("")
            for rec_type in sorted(type_counts):
                lines.append(f"- {rec_type.upper()}: {type_counts[rec_type]}")
            lines.append("")

            lines.append("## Recommendations")
            lines.append("")
            for r in recommendations:
                rec_type = r.get("recommendation_type", "").upper()
                priority = r.get("priority", "").upper()
                classification_id = r.get("classification_id", "")
                summary = r.get("summary", "")
                line = f"- [{priority}] [{rec_type}] {classification_id}"
                if summary:
                    line += f" — {summary}"
                lines.append(line)
            lines.append("")

        return "\n".join(lines)
