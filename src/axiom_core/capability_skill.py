"""Capability Skill Framework v1.

Provides deterministic skill accumulation on top of capability history.
Identifies recurring successful patterns and reusable capability experience
from historical execution, failure, repair, and confidence records.

Non-goals: no autonomous learning engines, no schedulers,
no workflow orchestration.
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

from axiom_core.artifact_paths import is_within_sandbox

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CapabilitySkillType(str, Enum):
    EXECUTION_PATTERN = "execution_pattern"
    FAILURE_PATTERN = "failure_pattern"
    REPAIR_PATTERN = "repair_pattern"
    RECOVERY_PATTERN = "recovery_pattern"
    SUCCESS_PATTERN = "success_pattern"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CapabilitySkillObservation:
    """A single observation supporting a skill."""

    observation_id: str = ""
    skill_id: str = ""
    source_id: str = ""
    summary: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.observation_id:
            self.observation_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "skill_id": self.skill_id,
            "source_id": self.source_id,
            "summary": self.summary,
            "created_at": self.created_at,
        }


@dataclass
class CapabilitySkill:
    """A reusable skill accumulated for a capability."""

    skill_id: str = ""
    capability_id: str = ""
    name: str = ""
    description: str = ""
    skill_type: str = "execution_pattern"
    confidence_score: float = 0.0
    observations: list[CapabilitySkillObservation] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.skill_id:
            self.skill_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "capability_id": self.capability_id,
            "name": self.name,
            "description": self.description,
            "skill_type": self.skill_type,
            "confidence_score": self.confidence_score,
            "observations": [o.to_dict() for o in self.observations],
            "created_at": self.created_at,
        }


@dataclass
class CapabilitySkillReport:
    """Report summarizing accumulated skills for a capability."""

    report_id: str = ""
    capability_id: str = ""
    skill_count: int = 0
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
            "skill_count": self.skill_count,
            "summary": self.summary,
            "created_at": self.created_at,
        }


@dataclass
class CapabilitySkillEvidence:
    """Evidence bundle for a capability skill report."""

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

_VALID_SKILL_TYPES = {t.value for t in CapabilitySkillType}

# A skill report passes when its skills are, on average, confident enough to be
# treated as reusable experience. An empty report has nothing to assess and
# therefore passes.
_MIN_AVG_CONFIDENCE = 0.5


class CapabilitySkillEngine:
    """Manages capability skill reports deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "capability_skills"
        self._report_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"{name} must not be empty or whitespace")
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(f"{name} must not contain '..', '/', or '\\': {value!r}")

    @staticmethod
    def _validate_confidence(value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"confidence_score must be a number in [0.0, 1.0]: {value!r}")
        score = float(value)
        if score < 0.0 or score > 1.0:
            raise ValueError(f"confidence_score must be within [0.0, 1.0]: {score!r}")
        return score

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
        skills: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a capability skill report from a list of skills."""
        skills = skills or []

        skill_objects: list[CapabilitySkill] = []
        for s_data in skills:
            skill_type = s_data.get("skill_type", "execution_pattern")
            if skill_type not in _VALID_SKILL_TYPES:
                raise ValueError(
                    f"Invalid skill_type: {skill_type!r}. Valid: {sorted(_VALID_SKILL_TYPES)}"
                )
            confidence_score = self._validate_confidence(s_data.get("confidence_score", 0.0))

            skill = CapabilitySkill(
                capability_id=s_data.get("capability_id", capability_id),
                name=s_data.get("name", ""),
                description=s_data.get("description", ""),
                skill_type=skill_type,
                confidence_score=confidence_score,
            )

            observations: list[CapabilitySkillObservation] = []
            for o_data in s_data.get("observations", []) or []:
                observations.append(
                    CapabilitySkillObservation(
                        skill_id=skill.skill_id,
                        source_id=o_data.get("source_id", ""),
                        summary=o_data.get("summary", ""),
                        created_at=o_data.get("created_at", ""),
                    )
                )
            # Chronological ordering by created_at, then observation_id.
            observations.sort(key=lambda o: (o.created_at, o.observation_id))
            skill.observations = observations

            skill_objects.append(skill)

        # Deterministic ordering by skill_type, then name, then skill_id.
        skill_objects.sort(key=lambda s: (s.skill_type, s.name, s.skill_id))

        summary = self._generate_summary(capability_id, skill_objects)

        report = CapabilitySkillReport(
            capability_id=capability_id,
            skill_count=len(skill_objects),
            summary=summary,
        )

        evidence = CapabilitySkillEvidence(
            report_id=report.report_id,
            summary=summary,
        )

        self._persist(report, skill_objects, evidence)
        self._write_evidence(report, skill_objects)

        result = report.to_dict()
        result["skills"] = [s.to_dict() for s in skill_objects]
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
            raise ValueError(f"Skill report not found: {report_id}")
        return self._generate_export_md(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(
        self,
        report: CapabilitySkillReport,
        skills: list[CapabilitySkill],
        evidence: CapabilitySkillEvidence,
    ) -> None:
        report_dir = self._safe_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)

        data = report.to_dict()
        data["skills"] = [s.to_dict() for s in skills]
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
        report: CapabilitySkillReport,
        skills: list[CapabilitySkill],
    ) -> None:
        evidence_dir = self._safe_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "capability_id": report.capability_id,
            "skills": [s.to_dict() for s in skills],
        }
        (evidence_dir / "capability_skill_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        result_data = report.to_dict()
        result_data["skills"] = [s.to_dict() for s in skills]
        (evidence_dir / "capability_skill_result.json").write_text(
            json.dumps(result_data, indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_export_md(result_data)
        (evidence_dir / "capability_skill_summary.md").write_text(md, encoding="utf-8")

        average_confidence = self._average_confidence(skills)
        passed = not skills or average_confidence >= _MIN_AVG_CONFIDENCE
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "capability_id": report.capability_id,
            "skill_count": report.skill_count,
            "average_confidence": average_confidence,
            "min_average_confidence": _MIN_AVG_CONFIDENCE,
            "status": "passed" if passed else "failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _average_confidence(skills: list[CapabilitySkill]) -> float:
        if not skills:
            return 0.0
        total = sum(s.confidence_score for s in skills)
        return round(total / len(skills), 6)

    @staticmethod
    def _generate_summary(capability_id: str, skills: list[CapabilitySkill]) -> str:
        return (
            f"Capability {capability_id}: {len(skills)} skill(s) accumulated "
            f"deterministically"
        )

    @staticmethod
    def _generate_export_md(data: dict[str, Any]) -> str:
        lines: list[str] = []

        lines.append("# Capability Skill Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Capability ID: {data.get('capability_id', '')}")
        lines.append(f"- Skill Count: {data.get('skill_count', 0)}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        summary = data.get("summary", "")
        if summary:
            lines.append(f"{summary}")
            lines.append("")

        skills = data.get("skills", [])
        if skills:
            lines.append("## Skills")
            lines.append("")
            for s in skills:
                stype = s.get("skill_type", "").upper()
                name = s.get("name", "")
                score = s.get("confidence_score", 0.0)
                lines.append(f"### {name} [{stype}] (confidence {score})")
                description = s.get("description", "")
                if description:
                    lines.append("")
                    lines.append(description)
                observations = s.get("observations", [])
                if observations:
                    lines.append("")
                    lines.append("Observations:")
                    for o in observations:
                        source = o.get("source_id", "")
                        osummary = o.get("summary", "")
                        created = o.get("created_at", "")
                        source_part = f" <- {source}" if source else ""
                        lines.append(f"- [{created}]{source_part}: {osummary}")
                lines.append("")

        return "\n".join(lines)
