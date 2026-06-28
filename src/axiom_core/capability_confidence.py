"""Capability Confidence Framework v1.

Provides deterministic confidence measurement on top of execution reports,
failures, and repair outcomes. Measures capability reliability.

Non-goals: no autonomous execution, no schedulers,
no workflow orchestration.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from axiom_core.artifact_paths import is_within_sandbox

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CapabilityConfidenceLevel(str, Enum):
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CapabilityConfidenceFactors:
    """Factors contributing to confidence score."""

    execution_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    repair_count: int = 0
    recovery_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_count": self.execution_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "repair_count": self.repair_count,
            "recovery_count": self.recovery_count,
        }


@dataclass
class CapabilityConfidence:
    """Confidence measurement for a capability."""

    confidence_id: str = ""
    capability_id: str = ""
    score: float = 0.0
    confidence_level: str = "very_low"
    factors: CapabilityConfidenceFactors | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.confidence_id:
            self.confidence_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if self.factors is None:
            self.factors = CapabilityConfidenceFactors()

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence_id": self.confidence_id,
            "capability_id": self.capability_id,
            "score": self.score,
            "confidence_level": self.confidence_level,
            "factors": self.factors.to_dict() if self.factors else {},
            "created_at": self.created_at,
        }


@dataclass
class CapabilityConfidenceReport:
    """Report summarizing confidence measurement."""

    report_id: str = ""
    capability_id: str = ""
    score: float = 0.0
    confidence_level: str = "very_low"
    summary: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "capability_id": self.capability_id,
            "score": self.score,
            "confidence_level": self.confidence_level,
            "summary": self.summary,
            "created_at": self.created_at,
        }


@dataclass
class CapabilityConfidenceEvidence:
    """Evidence bundle for confidence measurement."""

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

_VALID_LEVELS = {lv.value for lv in CapabilityConfidenceLevel}


def _compute_score(factors: CapabilityConfidenceFactors) -> float:
    """Compute a deterministic confidence score from factors.

    Score is the success ratio adjusted for repairs and recoveries.
    Range: 0.0 to 1.0.
    """
    if factors.execution_count == 0:
        return 0.0

    base = factors.success_count / factors.execution_count

    # Recovery bonus: recoveries partially offset failures
    if factors.failure_count > 0 and factors.recovery_count > 0:
        recovery_ratio = min(factors.recovery_count / factors.failure_count, 1.0)
        base += recovery_ratio * 0.1

    return min(round(base, 4), 1.0)


def _level_from_score(score: float) -> str:
    """Map a score to a confidence level deterministically."""
    if score >= 0.9:
        return CapabilityConfidenceLevel.VERY_HIGH.value
    if score >= 0.7:
        return CapabilityConfidenceLevel.HIGH.value
    if score >= 0.5:
        return CapabilityConfidenceLevel.MEDIUM.value
    if score >= 0.3:
        return CapabilityConfidenceLevel.LOW.value
    return CapabilityConfidenceLevel.VERY_LOW.value


class CapabilityConfidenceEngine:
    """Manages capability confidence reports deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "capability_confidence"
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

    def create(
        self,
        capability_id: str = "",
        execution_count: int = 0,
        success_count: int = 0,
        failure_count: int = 0,
        repair_count: int = 0,
        recovery_count: int = 0,
    ) -> dict[str, Any]:
        """Create a confidence report from execution factors."""
        factors = CapabilityConfidenceFactors(
            execution_count=execution_count,
            success_count=success_count,
            failure_count=failure_count,
            repair_count=repair_count,
            recovery_count=recovery_count,
        )

        score = _compute_score(factors)
        level = _level_from_score(score)

        confidence = CapabilityConfidence(
            capability_id=capability_id,
            score=score,
            confidence_level=level,
            factors=factors,
        )

        summary_text = (
            f"Capability {capability_id}: score={score}, level={level}, "
            f"executions={execution_count}, successes={success_count}, "
            f"failures={failure_count}, repairs={repair_count}, "
            f"recoveries={recovery_count}"
        )

        report = CapabilityConfidenceReport(
            capability_id=capability_id,
            score=score,
            confidence_level=level,
            summary=summary_text,
        )

        evidence = CapabilityConfidenceEvidence(
            report_id=report.report_id,
            summary=summary_text,
        )

        self._persist(report, confidence, evidence)
        self._write_evidence(report, confidence)

        result = report.to_dict()
        result["confidence"] = confidence.to_dict()
        result["evidence"] = evidence.to_dict()
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
            raise ValueError(f"Confidence report not found: {report_id}")
        return self._generate_export_md(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(
        self,
        report: CapabilityConfidenceReport,
        confidence: CapabilityConfidence,
        evidence: CapabilityConfidenceEvidence,
    ) -> None:
        report_dir = self._safe_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)

        data = report.to_dict()
        data["confidence"] = confidence.to_dict()
        data["evidence"] = evidence.to_dict()

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

    def _write_evidence(
        self,
        report: CapabilityConfidenceReport,
        confidence: CapabilityConfidence,
    ) -> None:
        evidence_dir = self._safe_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "capability_id": confidence.capability_id,
            "factors": confidence.factors.to_dict() if confidence.factors else {},
        }
        (evidence_dir / "capability_confidence_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        result_data = report.to_dict()
        result_data["confidence"] = confidence.to_dict()
        (evidence_dir / "capability_confidence_result.json").write_text(
            json.dumps(result_data, indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_export_md(result_data)
        (evidence_dir / "capability_confidence_summary.md").write_text(md, encoding="utf-8")

        passed = confidence.score >= 0.3
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "capability_id": confidence.capability_id,
            "score": confidence.score,
            "confidence_level": confidence.confidence_level,
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

        lines.append("# Capability Confidence Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Capability ID: {data.get('capability_id', '')}")
        lines.append(f"- Score: {data.get('score', 0.0)}")
        lines.append(f"- Level: {data.get('confidence_level', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        confidence = data.get("confidence", {})
        factors = confidence.get("factors", {})
        if factors:
            lines.append("## Factors")
            lines.append("")
            lines.append(f"- Executions: {factors.get('execution_count', 0)}")
            lines.append(f"- Successes: {factors.get('success_count', 0)}")
            lines.append(f"- Failures: {factors.get('failure_count', 0)}")
            lines.append(f"- Repairs: {factors.get('repair_count', 0)}")
            lines.append(f"- Recoveries: {factors.get('recovery_count', 0)}")
            lines.append("")

        summary = data.get("summary", "")
        if summary:
            lines.append("## Summary")
            lines.append("")
            lines.append(summary)
            lines.append("")

        return "\n".join(lines)
