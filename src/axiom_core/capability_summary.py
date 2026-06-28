"""Capability Summary Framework v1.

The first understanding layer on top of the Global Capability Registry
(identity) and the Capability Event Timeline (memory). Where the registry says
*what* a capability is and the timeline says *what happened*, the summary layer
says *what it means*: a human-readable purpose/summary/architectural
significance plus a deeper narrative (context, rationale, risks, lessons,
future opportunities).

Summaries and narratives are append-only and ordered deterministically. Raw
payloads and schema versions are preserved verbatim.

Non-goals: no GitHub API, no metadata ingestion, no orchestration, no routing,
no planning, no repair loops, no graph engine.
"""

from __future__ import annotations

import csv
import io
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from axiom_core.artifact_paths import is_within_sandbox

SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class CapabilitySummary:
    """A concise, human-readable understanding of a capability."""

    capability_id: str = ""
    capability_name: str = ""
    purpose: str = ""
    summary: str = ""
    architectural_significance: str = ""
    created_at: str = ""
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "capability_name": self.capability_name,
            "purpose": self.purpose,
            "summary": self.summary,
            "architectural_significance": self.architectural_significance,
            "created_at": self.created_at,
            "raw_metadata": dict(self.raw_metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilitySummary:
        return cls(
            capability_id=data.get("capability_id", ""),
            capability_name=data.get("capability_name", ""),
            purpose=data.get("purpose", ""),
            summary=data.get("summary", ""),
            architectural_significance=data.get(
                "architectural_significance", ""
            ),
            created_at=data.get("created_at", ""),
            raw_metadata=dict(data.get("raw_metadata", {})),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )


@dataclass
class CapabilityNarrative:
    """A deeper narrative behind a capability."""

    narrative_id: str = ""
    capability_id: str = ""
    context: str = ""
    rationale: str = ""
    risks: str = ""
    lessons: str = ""
    future_opportunities: str = ""
    created_at: str = ""
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.narrative_id:
            self.narrative_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "narrative_id": self.narrative_id,
            "capability_id": self.capability_id,
            "context": self.context,
            "rationale": self.rationale,
            "risks": self.risks,
            "lessons": self.lessons,
            "future_opportunities": self.future_opportunities,
            "created_at": self.created_at,
            "raw_metadata": dict(self.raw_metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityNarrative:
        return cls(
            narrative_id=data.get("narrative_id", ""),
            capability_id=data.get("capability_id", ""),
            context=data.get("context", ""),
            rationale=data.get("rationale", ""),
            risks=data.get("risks", ""),
            lessons=data.get("lessons", ""),
            future_opportunities=data.get("future_opportunities", ""),
            created_at=data.get("created_at", ""),
            raw_metadata=dict(data.get("raw_metadata", {})),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )


@dataclass
class CapabilitySummaryReport:
    """An append-only, deterministically ordered understanding report."""

    report_id: str = ""
    summaries: list[CapabilitySummary] = field(default_factory=list)
    narratives: list[CapabilityNarrative] = field(default_factory=list)
    summary_count: int = 0
    narrative_count: int = 0
    capability_counts: dict[str, int] = field(default_factory=dict)
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
            "summaries": [s.to_dict() for s in self.summaries],
            "narratives": [n.to_dict() for n in self.narratives],
            "summary_count": self.summary_count,
            "narrative_count": self.narrative_count,
            "capability_counts": dict(self.capability_counts),
            "created_at": self.created_at,
            "raw_metadata": dict(self.raw_metadata),
            "schema_version": self.schema_version,
        }


@dataclass
class CapabilitySummaryEvidence:
    """Evidence record for a capability summary report."""

    evidence_id: str = ""
    report_id: str = ""
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
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class CapabilitySummaryEngine:
    """Manages capability summary reports deterministically (append-only)."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "capability_summary"
        self._report_dir.mkdir(parents=True, exist_ok=True)

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
        if not is_within_sandbox(target, sandbox):
            raise ValueError(
                f"Resolved path escapes artifacts root: {report_id!r}"
            )
        return target

    @staticmethod
    def _summary_sort_key(s: CapabilitySummary) -> tuple:
        return (s.created_at, s.capability_id, s.capability_name)

    @staticmethod
    def _narrative_sort_key(n: CapabilityNarrative) -> tuple:
        return (n.created_at, n.capability_id, n.narrative_id)

    @staticmethod
    def _build_summary(data: dict[str, Any]) -> CapabilitySummary:
        capability_id = data.get("capability_id", "")
        if not capability_id or not str(capability_id).strip():
            raise ValueError("capability_id is required for a summary")
        capability_name = data.get("capability_name", "")
        if not capability_name or not str(capability_name).strip():
            raise ValueError("capability_name is required for a summary")
        return CapabilitySummary.from_dict(data)

    @staticmethod
    def _build_narrative(data: dict[str, Any]) -> CapabilityNarrative:
        capability_id = data.get("capability_id", "")
        if not capability_id or not str(capability_id).strip():
            raise ValueError("capability_id is required for a narrative")
        return CapabilityNarrative.from_dict(data)

    def _assemble(self, report: CapabilitySummaryReport) -> dict[str, Any]:
        report.summaries.sort(key=self._summary_sort_key)
        report.narratives.sort(key=self._narrative_sort_key)
        report.summary_count = len(report.summaries)
        report.narrative_count = len(report.narratives)

        counts: dict[str, int] = {}
        for s in report.summaries:
            counts[s.capability_id] = counts.get(s.capability_id, 0) + 1
        for n in report.narratives:
            counts[n.capability_id] = counts.get(n.capability_id, 0) + 1
        report.capability_counts = {k: counts[k] for k in sorted(counts)}

        return report.to_dict()

    # ------------------------------------------------------------------
    # Create / Append (append-only)
    # ------------------------------------------------------------------

    def create(
        self,
        summaries: list[dict[str, Any]] | None = None,
        narratives: list[dict[str, Any]] | None = None,
        raw_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new capability summary report."""
        report = CapabilitySummaryReport(raw_metadata=dict(raw_metadata or {}))
        report.summaries = [self._build_summary(s) for s in (summaries or [])]
        report.narratives = [
            self._build_narrative(n) for n in (narratives or [])
        ]

        assembled = self._assemble(report)
        self._persist(assembled)
        self._write_evidence(assembled)
        return assembled

    def append(
        self,
        report_id: str,
        summaries: list[dict[str, Any]] | None = None,
        narratives: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Append summaries/narratives to a report (append-only; no removal)."""
        self._validate_id_segment(report_id, "report_id")
        existing = self._load_report(report_id)
        if existing is None:
            raise ValueError(f"Report not found: {report_id}")

        report = CapabilitySummaryReport(
            report_id=existing["report_id"],
            created_at=existing.get("created_at", ""),
            raw_metadata=dict(existing.get("raw_metadata", {})),
            schema_version=existing.get("schema_version", SCHEMA_VERSION),
        )
        # Preserve existing items verbatim (append-only).
        report.summaries = [
            CapabilitySummary.from_dict(s)
            for s in existing.get("summaries", [])
        ]
        report.narratives = [
            CapabilityNarrative.from_dict(n)
            for n in existing.get("narratives", [])
        ]
        report.summaries.extend(
            self._build_summary(s) for s in (summaries or [])
        )
        report.narratives.extend(
            self._build_narrative(n) for n in (narratives or [])
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
            "summaries": report.get("summaries", []),
            "narratives": report.get("narratives", []),
            "raw_metadata": report.get("raw_metadata", {}),
        }
        (evidence_dir / "capability_summary_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "capability_summary_result.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "capability_summary_summary.md").write_text(
            self._generate_export_md(report), encoding="utf-8"
        )

        # Dedicated human-readable understanding documents.
        (evidence_dir / "capability_summary.md").write_text(
            self._generate_summary_md(report), encoding="utf-8"
        )
        (evidence_dir / "capability_narrative.md").write_text(
            self._generate_narrative_md(report), encoding="utf-8"
        )

        evidence = CapabilitySummaryEvidence(report_id=report["report_id"])

        # A report passes when it carries at least one summary (understanding
        # exists). An empty report fails.
        summary_count = report.get("summary_count", 0)
        passed = summary_count > 0
        pass_fail = {
            "passed": passed,
            "report_id": report["report_id"],
            "evidence_id": evidence.evidence_id,
            "summary_count": summary_count,
            "narrative_count": report.get("narrative_count", 0),
            "capability_counts": dict(report.get("capability_counts", {})),
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

    @staticmethod
    def _generate_summary_md(data: dict[str, Any]) -> str:
        lines: list[str] = []
        lines.append("# Capability Summary")
        lines.append("")
        for s in data.get("summaries", []):
            name = s.get("capability_name", "")
            cap_id = s.get("capability_id", "")
            lines.append(f"## {name} [{cap_id}]")
            lines.append("")
            lines.append(f"- Purpose: {s.get('purpose', '')}")
            lines.append(f"- Summary: {s.get('summary', '')}")
            lines.append(
                f"- Architectural Significance: "
                f"{s.get('architectural_significance', '')}"
            )
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _generate_narrative_md(data: dict[str, Any]) -> str:
        lines: list[str] = []
        lines.append("# Capability Narrative")
        lines.append("")
        for n in data.get("narratives", []):
            cap_id = n.get("capability_id", "")
            lines.append(f"## [{cap_id}]")
            lines.append("")
            lines.append(f"- Context: {n.get('context', '')}")
            lines.append(f"- Rationale: {n.get('rationale', '')}")
            lines.append(f"- Risks: {n.get('risks', '')}")
            lines.append(f"- Lessons: {n.get('lessons', '')}")
            lines.append(
                f"- Future Opportunities: "
                f"{n.get('future_opportunities', '')}"
            )
            lines.append("")
        return "\n".join(lines)

    def _generate_export_md(self, data: dict[str, Any]) -> str:
        lines: list[str] = []

        lines.append("# Capability Summary Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append(f"- Schema Version: {data.get('schema_version', '')}")
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Summaries: {data.get('summary_count', 0)}")
        lines.append(f"- Narratives: {data.get('narrative_count', 0)}")
        lines.append("")

        capability_counts = data.get("capability_counts", {})
        lines.append("## Capability Counts")
        lines.append("")
        for cap_id in sorted(capability_counts):
            lines.append(f"- {cap_id}: {capability_counts[cap_id]}")
        lines.append("")

        # Embed the dedicated summary + narrative documents.
        lines.append(self._generate_summary_md(data))
        lines.append(self._generate_narrative_md(data))

        return "\n".join(lines)

    @staticmethod
    def _generate_export_csv(data: dict[str, Any]) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "record_type",
                "capability_id",
                "capability_name",
                "purpose_or_context",
                "created_at",
                "schema_version",
            ]
        )
        for s in data.get("summaries", []):
            writer.writerow(
                [
                    "summary",
                    s.get("capability_id", ""),
                    s.get("capability_name", ""),
                    s.get("purpose", ""),
                    s.get("created_at", ""),
                    s.get("schema_version", ""),
                ]
            )
        for n in data.get("narratives", []):
            writer.writerow(
                [
                    "narrative",
                    n.get("capability_id", ""),
                    "",
                    n.get("context", ""),
                    n.get("created_at", ""),
                    n.get("schema_version", ""),
                ]
            )
        return buf.getvalue()
