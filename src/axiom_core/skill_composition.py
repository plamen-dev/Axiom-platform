"""Skill Composition Framework v1.

Provides deterministic skill composition on top of capability skills and
session memory. Where prior frameworks each accumulate isolated skills and
short-term memory, skill composition preserves reusable combinations of skills
(ordered elements) representing higher-order experience, with evidence bundles.

Non-goals: no autonomous learning, no schedulers, no worker orchestration, no
approvals, no workflow routing, no merge behavior.
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


class SkillCompositionType(str, Enum):
    EXECUTION_SEQUENCE = "execution_sequence"
    FAILURE_RECOVERY_SEQUENCE = "failure_recovery_sequence"
    VALIDATION_SEQUENCE = "validation_sequence"
    REVIEW_SEQUENCE = "review_sequence"
    CUSTOM_SEQUENCE = "custom_sequence"


_VALID_TYPES = {t.value for t in SkillCompositionType}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SkillCompositionElement:
    """A single ordered element referencing a skill within a composition."""

    element_id: str = ""
    skill_id: str = ""
    order_index: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.element_id:
            self.element_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "skill_id": self.skill_id,
            "order_index": self.order_index,
            "created_at": self.created_at,
        }


@dataclass
class SkillComposition:
    """A reusable, ordered combination of skills."""

    composition_id: str = ""
    name: str = ""
    composition_type: str = "custom_sequence"
    elements: list[SkillCompositionElement] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.composition_id:
            self.composition_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "composition_id": self.composition_id,
            "name": self.name,
            "composition_type": self.composition_type,
            "elements": [e.to_dict() for e in self.elements],
            "created_at": self.created_at,
        }


@dataclass
class SkillCompositionReport:
    """Report summarizing a set of skill compositions."""

    report_id: str = ""
    composition_count: int = 0
    composition_type_counts: dict[str, int] = field(default_factory=dict)
    created_at: str = ""
    compositions: list[SkillComposition] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "composition_count": self.composition_count,
            "composition_type_counts": dict(self.composition_type_counts),
            "created_at": self.created_at,
            "compositions": [c.to_dict() for c in self.compositions],
        }


@dataclass
class SkillCompositionEvidence:
    """Evidence record for a skill composition report."""

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


class SkillCompositionEngine:
    """Manages skill composition reports deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "skill_compositions"
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
        self, compositions: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Create a skill composition report from a list of compositions."""
        compositions = compositions or []

        composition_objects: list[SkillComposition] = []
        for c_data in compositions:
            composition_type = c_data.get("composition_type", "custom_sequence")
            if composition_type not in _VALID_TYPES:
                raise ValueError(
                    f"Invalid composition_type: {composition_type!r}. "
                    f"Valid: {sorted(_VALID_TYPES)}"
                )
            name = c_data.get("name", "")
            if not name or not name.strip():
                raise ValueError("name is required for a skill composition")

            element_objects: list[SkillCompositionElement] = []
            for el_data in c_data.get("elements", []):
                skill_id = el_data.get("skill_id", "")
                if not skill_id:
                    raise ValueError(
                        "skill_id is required for a skill composition element"
                    )
                element_objects.append(
                    SkillCompositionElement(
                        skill_id=skill_id,
                        order_index=int(el_data.get("order_index", 0)),
                        created_at=el_data.get("created_at", ""),
                    )
                )

            # Deterministic element ordering: by order_index, then skill_id,
            # then element_id for stability.
            element_objects.sort(
                key=lambda el: (el.order_index, el.skill_id, el.element_id)
            )

            composition_objects.append(
                SkillComposition(
                    name=name,
                    composition_type=composition_type,
                    elements=element_objects,
                    created_at=c_data.get("created_at", ""),
                )
            )

        # Deterministic ordering: chronological by created_at, then name, then
        # composition_id for stability.
        composition_objects.sort(
            key=lambda c: (c.created_at, c.name, c.composition_id)
        )

        composition_type_counts: dict[str, int] = {}
        for c in composition_objects:
            composition_type_counts[c.composition_type] = (
                composition_type_counts.get(c.composition_type, 0) + 1
            )
        # Deterministic, sorted key ordering for reproducible output.
        composition_type_counts = {
            k: composition_type_counts[k] for k in sorted(composition_type_counts)
        }

        report = SkillCompositionReport(
            composition_count=len(composition_objects),
            composition_type_counts=composition_type_counts,
            compositions=composition_objects,
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
            raise ValueError(f"Skill composition report not found: {report_id}")
        return self._generate_export_md(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, report: SkillCompositionReport) -> None:
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

    def _write_evidence(self, report: SkillCompositionReport) -> None:
        evidence_dir = self._safe_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {"compositions": [c.to_dict() for c in report.compositions]}
        (evidence_dir / "skill_composition_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "skill_composition_result.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_export_md(report.to_dict())
        (evidence_dir / "skill_composition_summary.md").write_text(
            md, encoding="utf-8"
        )

        empty_count = sum(1 for c in report.compositions if not c.elements)
        evidence = SkillCompositionEvidence(
            report_id=report.report_id,
            summary=(
                f"{report.composition_count} compositions, "
                f"{len(report.composition_type_counts)} composition types, "
                f"{empty_count} empty compositions"
            ),
        )

        # A skill composition report passes when every composition records at
        # least one ordered element (no empty compositions).
        passed = empty_count == 0
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "evidence_id": evidence.evidence_id,
            "composition_count": report.composition_count,
            "composition_type_counts": dict(report.composition_type_counts),
            "empty_count": empty_count,
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

        lines.append("# Skill Composition Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        lines.append("## Composition Summary")
        lines.append("")
        lines.append(f"- Compositions: {data.get('composition_count', 0)}")
        lines.append("")

        composition_type_counts = data.get("composition_type_counts", {})
        lines.append("## Type Counts")
        lines.append("")
        for composition_type in sorted(composition_type_counts):
            lines.append(
                f"- {composition_type.upper()}: "
                f"{composition_type_counts[composition_type]}"
            )
        lines.append("")

        compositions = data.get("compositions", [])
        if compositions:
            lines.append("## Compositions")
            lines.append("")
            for c in compositions:
                composition_type = c.get("composition_type", "").upper()
                name = c.get("name", "")
                lines.append(f"### [{composition_type}] {name}")
                lines.append("")
                for el in c.get("elements", []):
                    order_index = el.get("order_index", 0)
                    skill_id = el.get("skill_id", "")
                    lines.append(f"- {order_index}. {skill_id}")
                lines.append("")

        return "\n".join(lines)
