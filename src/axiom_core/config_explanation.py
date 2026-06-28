"""Configuration Explanation Framework v1.

Generates deterministic, human-readable explanations from configuration
validation reports and repair recommendations. Explains why conclusions
were reached without performing any mutations.

Non-goals: no automatic repair execution, no mutation, no approvals,
no workflow engines, no schedulers.
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

from axiom_core.artifact_paths import is_within_sandbox

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ConfigurationExplanationType(str, Enum):
    VALIDATION_EXPLANATION = "validation_explanation"
    REPAIR_EXPLANATION = "repair_explanation"
    CONFIGURATION_SUMMARY = "configuration_summary"
    WARNING_EXPLANATION = "warning_explanation"
    ERROR_EXPLANATION = "error_explanation"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ConfigurationExplanationSection:
    """A section within an explanation report."""

    title: str = ""
    content: str = ""
    references: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content,
            "references": self.references,
        }


@dataclass
class ConfigurationExplanation:
    """A single explanation entry."""

    explanation_id: str = ""
    config_id: str = ""
    explanation_type: ConfigurationExplanationType = (
        ConfigurationExplanationType.CONFIGURATION_SUMMARY
    )
    summary: str = ""
    rationale: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.explanation_id:
            self.explanation_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "explanation_id": self.explanation_id,
            "config_id": self.config_id,
            "explanation_type": self.explanation_type.value,
            "summary": self.summary,
            "rationale": self.rationale,
            "created_at": self.created_at,
        }


@dataclass
class ConfigurationExplanationReport:
    """Report containing all explanations for a configuration."""

    report_id: str = ""
    config_id: str = ""
    explanation_count: int = 0
    sections: list[ConfigurationExplanationSection] = field(default_factory=list)
    explanations: list[ConfigurationExplanation] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "config_id": self.config_id,
            "explanation_count": self.explanation_count,
            "sections": [s.to_dict() for s in self.sections],
            "explanations": [e.to_dict() for e in self.explanations],
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Explanation engine
# ---------------------------------------------------------------------------


class ConfigurationExplanationEngine:
    """Generates explanations from validation and repair reports."""

    def __init__(
        self,
        artifacts_root: str | None = None,
    ) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._explanations_dir = self._artifacts_root / "config_explanations"
        self._explanations_dir.mkdir(parents=True, exist_ok=True)

    def _safe_explanation_path(self, report_id: str) -> Path:
        target = (self._explanations_dir / report_id).resolve()
        sandbox = self._explanations_dir.resolve()
        if not is_within_sandbox(target, sandbox):
            raise ValueError(
                f"Resolved path escapes artifacts root: {report_id!r}"
            )
        return target

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"{name} must not be empty or whitespace")
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(
                f"{name} must not contain '..', '/', or '\\': {value!r}"
            )

    def explain(
        self,
        validation_report: dict[str, Any] | None = None,
        repair_report: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate explanations from validation/repair reports."""
        config_id = ""
        if validation_report:
            config_id = validation_report.get("config_id", "")
        elif repair_report:
            config_id = repair_report.get("config_id", "")
        elif config:
            config_id = config.get("config_id", "")

        explanations: list[ConfigurationExplanation] = []
        sections: list[ConfigurationExplanationSection] = []

        if config:
            exp, sec = self._explain_configuration(config, config_id)
            explanations.append(exp)
            sections.append(sec)

        if validation_report:
            exps, secs = self._explain_validation(validation_report, config_id)
            explanations.extend(exps)
            sections.extend(secs)

        if repair_report:
            exps, secs = self._explain_repair(repair_report, config_id)
            explanations.extend(exps)
            sections.extend(secs)

        report = ConfigurationExplanationReport(
            config_id=config_id,
            explanation_count=len(explanations),
            sections=sections,
            explanations=explanations,
        )

        self._persist_report(report)
        self._write_evidence(report)

        return report.to_dict()

    def _explain_configuration(
        self,
        config: dict[str, Any],
        config_id: str,
    ) -> tuple[ConfigurationExplanation, ConfigurationExplanationSection]:
        entry_count = config.get("entry_count", 0)
        file_name = config.get("file_name", "unknown")

        explanation = ConfigurationExplanation(
            config_id=config_id,
            explanation_type=ConfigurationExplanationType.CONFIGURATION_SUMMARY,
            summary=f"Configuration '{file_name}' contains {entry_count} entries.",
            rationale=(
                f"The configuration file was parsed successfully with "
                f"{entry_count} key-value entries."
            ),
        )

        entries = config.get("entries", [])
        keys = [e.get("key", "") for e in entries]
        content = (
            f"File: {file_name}\n"
            f"Entry count: {entry_count}\n"
            f"Keys: {', '.join(keys) if keys else '(none)'}"
        )

        section = ConfigurationExplanationSection(
            title="Configuration Summary",
            content=content,
            references=[f"config_id:{config_id}"],
        )

        return explanation, section

    def _explain_validation(
        self,
        validation_report: dict[str, Any],
        config_id: str,
    ) -> tuple[list[ConfigurationExplanation], list[ConfigurationExplanationSection]]:
        explanations: list[ConfigurationExplanation] = []
        sections: list[ConfigurationExplanationSection] = []

        valid = validation_report.get("valid", True)
        violations = validation_report.get("violations", [])
        error_count = validation_report.get("error_count", 0)
        warning_count = validation_report.get("warning_count", 0)
        report_id = validation_report.get("report_id", "")

        if valid:
            explanations.append(ConfigurationExplanation(
                config_id=config_id,
                explanation_type=ConfigurationExplanationType.VALIDATION_EXPLANATION,
                summary="Validation passed with no violations.",
                rationale="All rules were satisfied by the configuration entries.",
            ))
            sections.append(ConfigurationExplanationSection(
                title="Validation Result",
                content="All validation rules passed. No violations detected.",
                references=[f"validation_report_id:{report_id}"],
            ))
        else:
            explanations.append(ConfigurationExplanation(
                config_id=config_id,
                explanation_type=ConfigurationExplanationType.VALIDATION_EXPLANATION,
                summary=(
                    f"Validation failed with {error_count} error(s) "
                    f"and {warning_count} warning(s)."
                ),
                rationale=(
                    f"The configuration did not satisfy all rules. "
                    f"{len(violations)} violation(s) were detected."
                ),
            ))

            violation_lines: list[str] = []
            for v in violations:
                key = v.get("key", "")
                message = v.get("message", "")
                severity = v.get("severity", "error")
                violation_lines.append(f"[{severity.upper()}] {key}: {message}")

                if severity == "error":
                    explanations.append(ConfigurationExplanation(
                        config_id=config_id,
                        explanation_type=ConfigurationExplanationType.ERROR_EXPLANATION,
                        summary=f"Error on key '{key}': {message}",
                        rationale=f"Key '{key}' violated a validation rule: {message}",
                    ))
                elif severity == "warning":
                    explanations.append(ConfigurationExplanation(
                        config_id=config_id,
                        explanation_type=ConfigurationExplanationType.WARNING_EXPLANATION,
                        summary=f"Warning on key '{key}': {message}",
                        rationale=f"Key '{key}' triggered a warning: {message}",
                    ))

            sections.append(ConfigurationExplanationSection(
                title="Validation Violations",
                content="\n".join(violation_lines),
                references=[f"validation_report_id:{report_id}"],
            ))

        return explanations, sections

    def _explain_repair(
        self,
        repair_report: dict[str, Any],
        config_id: str,
    ) -> tuple[list[ConfigurationExplanation], list[ConfigurationExplanationSection]]:
        explanations: list[ConfigurationExplanation] = []
        sections: list[ConfigurationExplanationSection] = []

        recommendations = repair_report.get("recommendations", [])
        repairable_count = repair_report.get("repairable_count", 0)
        unrepairable_count = repair_report.get("unrepairable_count", 0)
        repair_report_id = repair_report.get("report_id", "")

        if not recommendations:
            explanations.append(ConfigurationExplanation(
                config_id=config_id,
                explanation_type=ConfigurationExplanationType.REPAIR_EXPLANATION,
                summary="No repair recommendations generated.",
                rationale="There were no violations requiring repair.",
            ))
            sections.append(ConfigurationExplanationSection(
                title="Repair Recommendations",
                content="No repair recommendations were generated.",
                references=[f"repair_report_id:{repair_report_id}"],
            ))
            return explanations, sections

        summary_text = (
            f"{repairable_count} repairable, "
            f"{unrepairable_count} unrepairable recommendation(s)."
        )
        explanations.append(ConfigurationExplanation(
            config_id=config_id,
            explanation_type=ConfigurationExplanationType.REPAIR_EXPLANATION,
            summary=f"Repair analysis complete: {summary_text}",
            rationale=(
                f"Each validation violation was analyzed for repair feasibility. "
                f"{repairable_count} can be repaired; "
                f"{unrepairable_count} cannot be automatically repaired."
            ),
        ))

        rec_lines: list[str] = []
        for rec in recommendations:
            action = rec.get("action", "no_action").upper()
            key = rec.get("key", "")
            rationale = rec.get("rationale", "")
            rec_lines.append(f"[{action}] {key}: {rationale}")

        sections.append(ConfigurationExplanationSection(
            title="Repair Recommendations",
            content="\n".join(rec_lines),
            references=[f"repair_report_id:{repair_report_id}"],
        ))

        return explanations, sections

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        self._validate_id_segment(report_id, "report_id")
        return self._load_report(report_id)

    def list_reports(self) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        if not self._explanations_dir.exists():
            return reports

        sandbox = self._explanations_dir.resolve()
        for entry in self._explanations_dir.iterdir():
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
            raise ValueError(f"Explanation report not found: {report_id}")
        return self._generate_summary(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_report(self, report: ConfigurationExplanationReport) -> None:
        report_dir = self._safe_explanation_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def _load_report(self, report_id: str) -> dict[str, Any] | None:
        report_dir = self._safe_explanation_path(report_id)
        report_file = report_dir / "report.json"
        if not report_file.exists():
            return None
        return json.loads(report_file.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def _write_evidence(self, report: ConfigurationExplanationReport) -> str:
        evidence_dir = self._safe_explanation_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "report_id": report.report_id,
            "config_id": report.config_id,
            "explanation_count": report.explanation_count,
        }
        (evidence_dir / "config_explanation_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "config_explanation_result.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_summary(report.to_dict())
        (evidence_dir / "config_explanation_summary.md").write_text(
            md, encoding="utf-8",
        )

        pass_fail = {
            "passed": True,
            "report_id": report.report_id,
            "config_id": report.config_id,
            "explanation_count": report.explanation_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

        return str(evidence_dir)

    @staticmethod
    def _generate_summary(data: dict[str, Any]) -> str:
        lines: list[str] = []
        explanation_count = data.get("explanation_count", 0)

        lines.append("# Configuration Explanation Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Config ID: {data.get('config_id', '')}")
        lines.append(f"- Explanation count: {explanation_count}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        sections = data.get("sections", [])
        if sections:
            for sec in sections:
                lines.append(f"## {sec.get('title', 'Section')}")
                lines.append("")
                lines.append(sec.get("content", ""))
                refs = sec.get("references", [])
                if refs:
                    lines.append("")
                    lines.append(f"References: {', '.join(refs)}")
                lines.append("")
        else:
            lines.append("## Sections")
            lines.append("")
            lines.append("No sections generated.")
            lines.append("")

        explanations = data.get("explanations", [])
        if explanations:
            lines.append("## Explanations")
            lines.append("")
            for exp in explanations:
                exp_type = exp.get("explanation_type", "").upper()
                summary = exp.get("summary", "")
                rationale = exp.get("rationale", "")
                lines.append(f"- [{exp_type}] {summary}")
                if rationale:
                    lines.append(f"  - Rationale: {rationale}")
            lines.append("")

        return "\n".join(lines)
