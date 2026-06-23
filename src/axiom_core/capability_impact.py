"""Capability Impact Framework v1.

The first formal *impact* layer for capabilities. Where the Global Capability
Registry establishes identity, the Capability Summary establishes understanding,
and the Capability Relationship Framework establishes relationships, this layer
establishes *meaning*: what a capability changed, what it affects, and what new
opportunities it enables.

Relationships provide context; impact provides meaning. This framework captures,
per capability, a deterministic, append-only list of typed impacts (in named
impact areas) plus a list of prioritized opportunities, with preserved raw
payloads and schema versioning.

It is deliberately *structure only*. Non-goals: no graph engine, no graph
queries, no visualization, no dashboards, no Organizational Twin, no automatic
opportunity generation, no worker orchestration, no network calls. The
registry/summary/relationship layers are consumed read-only; nothing is mutated.
"""

from __future__ import annotations

import csv
import io
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CapabilityImpactType(str, Enum):
    ENABLED = "ENABLED"
    IMPROVED = "IMPROVED"
    AUTOMATED = "AUTOMATED"
    SIMPLIFIED = "SIMPLIFIED"
    VALIDATED = "VALIDATED"
    DOCUMENTED = "DOCUMENTED"
    CONNECTED = "CONNECTED"
    EXTENDED = "EXTENDED"


class CapabilityImpactArea(str, Enum):
    ENGINEERING = "ENGINEERING"
    OPERATIONS = "OPERATIONS"
    KNOWLEDGE = "KNOWLEDGE"
    TESTING = "TESTING"
    WORKERS = "WORKERS"
    GOVERNANCE = "GOVERNANCE"
    ORGANIZATION = "ORGANIZATION"


class CapabilityOpportunityPriority(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    STRATEGIC = "STRATEGIC"


_VALID_IMPACT_TYPES = {t.value for t in CapabilityImpactType}
_VALID_IMPACT_AREAS = {a.value for a in CapabilityImpactArea}
_VALID_PRIORITIES = {p.value for p in CapabilityOpportunityPriority}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class CapabilityImpact:
    """A typed impact a capability had on a named impact area."""

    impact_id: str = ""
    capability_id: str = ""
    impact_type: str = ""
    impact_area: str = ""
    impact_summary: str = ""
    significance: str = ""
    created_at: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.impact_id:
            self.impact_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "impact_id": self.impact_id,
            "capability_id": self.capability_id,
            "impact_type": self.impact_type,
            "impact_area": self.impact_area,
            "impact_summary": self.impact_summary,
            "significance": self.significance,
            "created_at": self.created_at,
            "raw_payload": dict(self.raw_payload),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityImpact:
        return cls(
            impact_id=data.get("impact_id", ""),
            capability_id=data.get("capability_id", ""),
            impact_type=data.get("impact_type", ""),
            impact_area=data.get("impact_area", ""),
            impact_summary=data.get("impact_summary", ""),
            significance=data.get("significance", ""),
            created_at=data.get("created_at", ""),
            raw_payload=dict(data.get("raw_payload", {})),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )


@dataclass
class CapabilityOpportunity:
    """A prioritized opportunity a capability enables."""

    opportunity_id: str = ""
    capability_id: str = ""
    title: str = ""
    description: str = ""
    priority: str = CapabilityOpportunityPriority.NORMAL.value
    related_capability_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.opportunity_id:
            self.opportunity_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "opportunity_id": self.opportunity_id,
            "capability_id": self.capability_id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "related_capability_ids": list(self.related_capability_ids),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityOpportunity:
        return cls(
            opportunity_id=data.get("opportunity_id", ""),
            capability_id=data.get("capability_id", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            priority=data.get(
                "priority", CapabilityOpportunityPriority.NORMAL.value
            ),
            related_capability_ids=list(
                data.get("related_capability_ids", [])
            ),
        )


@dataclass
class CapabilityImpactReport:
    """A deterministic, append-only impact + opportunity report."""

    report_id: str = ""
    impacts: list[CapabilityImpact] = field(default_factory=list)
    opportunities: list[CapabilityOpportunity] = field(default_factory=list)
    impact_count: int = 0
    impact_type_counts: dict[str, int] = field(default_factory=dict)
    impact_area_counts: dict[str, int] = field(default_factory=dict)
    opportunity_count: int = 0
    strategic_opportunity_count: int = 0
    created_at: str = ""
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "impacts": [i.to_dict() for i in self.impacts],
            "opportunities": [o.to_dict() for o in self.opportunities],
            "impact_count": self.impact_count,
            "impact_type_counts": dict(self.impact_type_counts),
            "impact_area_counts": dict(self.impact_area_counts),
            "opportunity_count": self.opportunity_count,
            "strategic_opportunity_count": self.strategic_opportunity_count,
            "created_at": self.created_at,
            "raw_metadata": dict(self.raw_metadata),
            "schema_version": self.schema_version,
        }


@dataclass
class CapabilityImpactEvidence:
    """Evidence record for a capability impact report."""

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


class CapabilityImpactEngine:
    """Manages capability impact reports deterministically.

    Impacts and opportunities are ordered deterministically and the report is
    append-only. The registry/summary/relationship layers are *consumed*
    read-only; nothing is mutated. Impacts are not deduplicated (multiple
    impacts of the same type/area on a capability are legitimate); ordering is
    fully input-independent.
    """

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "capability_impacts"
        self._report_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Path safety
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"{name} must not be empty or whitespace")
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(
                f"{name} must not contain '..', '/', or '\\': {value!r}"
            )

    def _safe_path(self, report_id: str) -> Path:
        target = (self._report_dir / report_id).resolve()
        sandbox = self._report_dir.resolve()
        if not str(target).startswith(str(sandbox) + "/") and target != sandbox:
            raise ValueError(
                f"Resolved path escapes artifacts root: {report_id!r}"
            )
        return target

    # ------------------------------------------------------------------
    # Building / validation
    # ------------------------------------------------------------------

    @staticmethod
    def _impact_sort_key(i: CapabilityImpact) -> tuple:
        return (
            i.capability_id,
            i.impact_area,
            i.impact_type,
            i.impact_id,
        )

    @staticmethod
    def _opportunity_sort_key(o: CapabilityOpportunity) -> tuple:
        return (
            o.capability_id,
            o.title,
            o.opportunity_id,
        )

    @staticmethod
    def _build_impact(data: dict[str, Any]) -> CapabilityImpact:
        capability_id = data.get("capability_id", "")
        if not capability_id or not str(capability_id).strip():
            raise ValueError("capability_id is required for an impact")

        impact_type_raw = data.get("impact_type", "")
        if not impact_type_raw or not str(impact_type_raw).strip():
            raise ValueError("impact_type is required for an impact")
        impact_type = str(impact_type_raw).strip().upper()
        if impact_type not in _VALID_IMPACT_TYPES:
            raise ValueError(
                f"Invalid impact_type: {impact_type_raw!r}. "
                f"Valid: {sorted(_VALID_IMPACT_TYPES)}"
            )

        impact_area_raw = data.get("impact_area", "")
        if not impact_area_raw or not str(impact_area_raw).strip():
            raise ValueError("impact_area is required for an impact")
        impact_area = str(impact_area_raw).strip().upper()
        if impact_area not in _VALID_IMPACT_AREAS:
            raise ValueError(
                f"Invalid impact_area: {impact_area_raw!r}. "
                f"Valid: {sorted(_VALID_IMPACT_AREAS)}"
            )

        normalized = dict(data)
        normalized["capability_id"] = str(capability_id)
        normalized["impact_type"] = impact_type
        normalized["impact_area"] = impact_area
        return CapabilityImpact.from_dict(normalized)

    @staticmethod
    def _build_opportunity(data: dict[str, Any]) -> CapabilityOpportunity:
        capability_id = data.get("capability_id", "")
        if not capability_id or not str(capability_id).strip():
            raise ValueError("capability_id is required for an opportunity")

        title = data.get("title", "")
        if not title or not str(title).strip():
            raise ValueError("title is required for an opportunity")

        priority_raw = data.get(
            "priority", CapabilityOpportunityPriority.NORMAL.value
        )
        priority = str(priority_raw).strip().upper()
        if priority not in _VALID_PRIORITIES:
            raise ValueError(
                f"Invalid priority: {priority_raw!r}. "
                f"Valid: {sorted(_VALID_PRIORITIES)}"
            )

        related = sorted(
            {str(c) for c in data.get("related_capability_ids", []) if c}
        )

        normalized = dict(data)
        normalized["capability_id"] = str(capability_id)
        normalized["title"] = str(title)
        normalized["priority"] = priority
        normalized["related_capability_ids"] = related
        return CapabilityOpportunity.from_dict(normalized)

    def _assemble(self, report: CapabilityImpactReport) -> dict[str, Any]:
        report.impacts.sort(key=self._impact_sort_key)
        report.opportunities.sort(key=self._opportunity_sort_key)

        report.impact_count = len(report.impacts)
        report.opportunity_count = len(report.opportunities)

        type_counts: dict[str, int] = {}
        area_counts: dict[str, int] = {}
        for i in report.impacts:
            type_counts[i.impact_type] = type_counts.get(i.impact_type, 0) + 1
            area_counts[i.impact_area] = area_counts.get(i.impact_area, 0) + 1
        report.impact_type_counts = {
            k: type_counts[k] for k in sorted(type_counts)
        }
        report.impact_area_counts = {
            k: area_counts[k] for k in sorted(area_counts)
        }

        report.strategic_opportunity_count = sum(
            1
            for o in report.opportunities
            if o.priority == CapabilityOpportunityPriority.STRATEGIC.value
        )

        return report.to_dict()

    # ------------------------------------------------------------------
    # Create / Append (append-only)
    # ------------------------------------------------------------------

    def create(
        self,
        impacts: list[dict[str, Any]] | None = None,
        opportunities: list[dict[str, Any]] | None = None,
        raw_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new capability impact report."""
        report = CapabilityImpactReport(
            raw_metadata=dict(raw_metadata or {}),
        )
        report.impacts = [self._build_impact(i) for i in (impacts or [])]
        report.opportunities = [
            self._build_opportunity(o) for o in (opportunities or [])
        ]
        assembled = self._assemble(report)
        self._persist(assembled)
        self._write_evidence(assembled)
        return assembled

    def append(
        self,
        report_id: str,
        impacts: list[dict[str, Any]] | None = None,
        opportunities: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Append impacts/opportunities to a report (append-only)."""
        self._validate_id_segment(report_id, "report_id")
        existing = self._load_report(report_id)
        if existing is None:
            raise ValueError(f"Report not found: {report_id}")

        report = CapabilityImpactReport(
            report_id=existing["report_id"],
            created_at=existing.get("created_at", ""),
            raw_metadata=dict(existing.get("raw_metadata", {})),
            schema_version=existing.get("schema_version", SCHEMA_VERSION),
        )
        # Preserve existing impacts/opportunities verbatim (append-only).
        report.impacts = [
            CapabilityImpact.from_dict(i)
            for i in existing.get("impacts", [])
        ]
        report.impacts.extend(
            self._build_impact(i) for i in (impacts or [])
        )
        report.opportunities = [
            CapabilityOpportunity.from_dict(o)
            for o in existing.get("opportunities", [])
        ]
        report.opportunities.extend(
            self._build_opportunity(o) for o in (opportunities or [])
        )

        assembled = self._assemble(report)
        self._persist(assembled)
        self._write_evidence(assembled)
        return assembled

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
            if (
                not str(resolved).startswith(str(sandbox) + "/")
                and resolved != sandbox
            ):
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

    def export_report(self, report_id: str, fmt: str = "markdown") -> str:
        self._validate_id_segment(report_id, "report_id")
        data = self._load_report(report_id)
        if data is None:
            raise ValueError(f"Report not found: {report_id}")
        fmt = (fmt or "markdown").lower()
        if fmt == "json":
            return json.dumps(data, indent=2, default=str)
        if fmt == "csv":
            return self._generate_export_csv(data)
        if fmt == "markdown":
            return self._generate_export_md(data)
        raise ValueError(
            f"Invalid export format: {fmt!r}. "
            "Valid: ['csv', 'json', 'markdown']"
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, report: dict[str, Any]) -> None:
        report_dir = self._safe_path(report["report_id"])
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(
            json.dumps(report, indent=2, default=str),
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

    def _write_evidence(self, report: dict[str, Any]) -> None:
        evidence_dir = self._safe_path(report["report_id"])
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "report_id": report["report_id"],
            "impacts": report.get("impacts", []),
            "opportunities": report.get("opportunities", []),
            "raw_metadata": report.get("raw_metadata", {}),
        }
        (evidence_dir / "capability_impact_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "capability_impact_result.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "capability_impact_summary.md").write_text(
            self._generate_export_md(report), encoding="utf-8"
        )

        impact_count = report.get("impact_count", 0)
        opportunity_count = report.get("opportunity_count", 0)
        strategic_count = report.get("strategic_opportunity_count", 0)
        evidence = CapabilityImpactEvidence(
            report_id=report["report_id"],
            summary=(
                f"{impact_count} impact(s), "
                f"{opportunity_count} opportunity(ies), "
                f"{strategic_count} strategic"
            ),
        )

        # A report passes when it carries at least one impact.
        passed = impact_count > 0
        pass_fail = {
            "passed": passed,
            "report_id": report["report_id"],
            "evidence_id": evidence.evidence_id,
            "impact_count": impact_count,
            "opportunity_count": opportunity_count,
            "strategic_opportunity_count": strategic_count,
            "impact_type_counts": dict(report.get("impact_type_counts", {})),
            "impact_area_counts": dict(report.get("impact_area_counts", {})),
            "schema_version": report.get("schema_version", SCHEMA_VERSION),
            "status": "passed" if passed else "failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Exporters
    # ------------------------------------------------------------------

    def _generate_export_md(self, data: dict[str, Any]) -> str:
        lines: list[str] = []

        lines.append("# Capability Impact Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append(f"- Schema Version: {data.get('schema_version', '')}")
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Impacts: {data.get('impact_count', 0)}")
        lines.append(f"- Opportunities: {data.get('opportunity_count', 0)}")
        lines.append(
            f"- Strategic Opportunities: "
            f"{data.get('strategic_opportunity_count', 0)}"
        )
        lines.append("")

        type_counts = data.get("impact_type_counts", {})
        lines.append("## Impact Type Counts")
        lines.append("")
        for impact_type in sorted(type_counts):
            lines.append(f"- {impact_type}: {type_counts[impact_type]}")
        lines.append("")

        area_counts = data.get("impact_area_counts", {})
        lines.append("## Impact Area Counts")
        lines.append("")
        for area in sorted(area_counts):
            lines.append(f"- {area}: {area_counts[area]}")
        lines.append("")

        lines.append("## Impacts")
        lines.append("")
        for i in data.get("impacts", []):
            cap = i.get("capability_id", "")
            itype = i.get("impact_type", "")
            area = i.get("impact_area", "")
            summary = i.get("impact_summary", "")
            lines.append(f"- [{cap}] [{itype}] [{area}] {summary}")
        lines.append("")

        lines.append("## Opportunities")
        lines.append("")
        for o in data.get("opportunities", []):
            cap = o.get("capability_id", "")
            priority = o.get("priority", "")
            title = o.get("title", "")
            lines.append(f"- [{priority}] [{cap}] {title}")
        lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _generate_export_csv(data: dict[str, Any]) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "record_kind",
                "capability_id",
                "impact_type",
                "impact_area",
                "priority",
                "summary_or_title",
                "significance",
                "created_at",
                "schema_version",
            ]
        )
        for i in data.get("impacts", []):
            writer.writerow(
                [
                    "impact",
                    i.get("capability_id", ""),
                    i.get("impact_type", ""),
                    i.get("impact_area", ""),
                    "",
                    i.get("impact_summary", ""),
                    i.get("significance", ""),
                    i.get("created_at", ""),
                    i.get("schema_version", ""),
                ]
            )
        for o in data.get("opportunities", []):
            writer.writerow(
                [
                    "opportunity",
                    o.get("capability_id", ""),
                    "",
                    "",
                    o.get("priority", ""),
                    o.get("title", ""),
                    "",
                    "",
                    "",
                ]
            )
        return buf.getvalue()
