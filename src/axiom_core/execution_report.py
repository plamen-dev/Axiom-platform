"""Execution Report Framework v1.

The execution-report layer continues the autonomous engineering roadmap on top
of the Execution Artifact Framework, the Execution Result Framework, the
Execution Attempt Framework v2, and the Capability Knowledge Graph. Where the
artifact layer represents *material evidence or output associated with a
result*, this layer represents *structured, human- and machine-readable reports
that summarize execution outcomes, artifacts, failures, and evidence*: for a
given capability / attempt / result, what type of report it is
(execution_summary, validation_summary, failure_summary, artifact_summary,
review_summary, final_summary, other), what status it reached (created,
complete, partial, failed, unknown), its ordered sections, and which upstream
objects it references.

Per summary it captures a deterministic, append-only set of execution reports,
ordered deterministically, with ordered sections, aggregated with status
counts, report-type counts, failed-/partial-/complete detection, and
duplicate-report detection, with preserved raw payloads and schema versioning.

It is deliberately *observational and declarative only*. Non-goals: no
execution, no orchestration, no scheduling, no report publishing, no dashboard,
no worker assignment, no autonomous behavior, no network calls, no architecture
changes. The upstream result / artifact / attempt / graph layers are consumed
read-only; nothing is mutated.
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


class ExecutionReportType(str, Enum):
    EXECUTION_SUMMARY = "EXECUTION_SUMMARY"
    VALIDATION_SUMMARY = "VALIDATION_SUMMARY"
    FAILURE_SUMMARY = "FAILURE_SUMMARY"
    ARTIFACT_SUMMARY = "ARTIFACT_SUMMARY"
    REVIEW_SUMMARY = "REVIEW_SUMMARY"
    FINAL_SUMMARY = "FINAL_SUMMARY"
    OTHER = "OTHER"


class ExecutionReportStatus(str, Enum):
    CREATED = "CREATED"
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class ExecutionReportSectionType(str, Enum):
    OVERVIEW = "OVERVIEW"
    RESULT = "RESULT"
    ARTIFACTS = "ARTIFACTS"
    FAILURES = "FAILURES"
    VALIDATION = "VALIDATION"
    RISKS = "RISKS"
    NEXT_STEPS = "NEXT_STEPS"
    OTHER = "OTHER"


class ExecutionReportReferenceType(str, Enum):
    RESULT = "RESULT"
    ARTIFACT = "ARTIFACT"
    ATTEMPT = "ATTEMPT"
    CAPABILITY = "CAPABILITY"
    FILE = "FILE"
    VALIDATION = "VALIDATION"
    KNOWLEDGE_NODE = "KNOWLEDGE_NODE"
    OTHER = "OTHER"


_VALID_REPORT_TYPES = {t.value for t in ExecutionReportType}
_VALID_STATUSES = {t.value for t in ExecutionReportStatus}
_VALID_SECTION_TYPES = {t.value for t in ExecutionReportSectionType}
_VALID_REFERENCE_TYPES = {t.value for t in ExecutionReportReferenceType}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class ExecutionReportSection:
    """A single ordered section within an execution report."""

    section_id: str = ""
    section_type: str = ""
    title: str = ""
    content: str = ""
    order_index: int = 0

    def __post_init__(self) -> None:
        if not self.section_id:
            self.section_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "section_type": self.section_type,
            "title": self.title,
            "content": self.content,
            "order_index": self.order_index,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionReportSection:
        return cls(
            section_id=data.get("section_id", ""),
            section_type=data.get("section_type", ""),
            title=data.get("title", ""),
            content=data.get("content", ""),
            order_index=int(data.get("order_index", 0)),
        )


@dataclass
class ExecutionReportReference:
    """A single reference from an execution report to an upstream object."""

    reference_id: str = ""
    reference_type: str = ""
    reference_value: str = ""
    summary: str = ""

    def __post_init__(self) -> None:
        if not self.reference_id:
            self.reference_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_id": self.reference_id,
            "reference_type": self.reference_type,
            "reference_value": self.reference_value,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionReportReference:
        return cls(
            reference_id=data.get("reference_id", ""),
            reference_type=data.get("reference_type", ""),
            reference_value=data.get("reference_value", ""),
            summary=data.get("summary", ""),
        )


@dataclass
class ExecutionReport:
    """A single structured execution report."""

    report_id: str = ""
    capability_id: str = ""
    attempt_id: str = ""
    result_id: str = ""
    report_type: str = ""
    status: str = ""
    sections: list[ExecutionReportSection] = field(default_factory=list)
    references: list[ExecutionReportReference] = field(default_factory=list)
    summary: str = ""
    created_at: str = ""
    schema_version: str = SCHEMA_VERSION
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "capability_id": self.capability_id,
            "attempt_id": self.attempt_id,
            "result_id": self.result_id,
            "report_type": self.report_type,
            "status": self.status,
            "sections": [s.to_dict() for s in self.sections],
            "references": [r.to_dict() for r in self.references],
            "summary": self.summary,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "raw_payload": dict(self.raw_payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionReport:
        return cls(
            report_id=data.get("report_id", ""),
            capability_id=data.get("capability_id", ""),
            attempt_id=data.get("attempt_id", ""),
            result_id=data.get("result_id", ""),
            report_type=data.get("report_type", ""),
            status=data.get("status", ""),
            sections=[
                ExecutionReportSection.from_dict(s)
                for s in data.get("sections", [])
            ],
            references=[
                ExecutionReportReference.from_dict(r)
                for r in data.get("references", [])
            ],
            summary=data.get("summary", ""),
            created_at=data.get("created_at", ""),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            raw_payload=dict(data.get("raw_payload", {})),
        )


@dataclass
class ExecutionReportSummary:
    """A deterministic, append-only aggregate of execution reports."""

    summary_id: str = ""
    reports: list[ExecutionReport] = field(default_factory=list)
    report_count: int = 0
    section_count: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    report_type_counts: dict[str, int] = field(default_factory=dict)
    failed_count: int = 0
    partial_count: int = 0
    complete_count: int = 0
    duplicate_report_count: int = 0
    created_at: str = ""
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.summary_id:
            self.summary_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary_id": self.summary_id,
            "reports": [r.to_dict() for r in self.reports],
            "report_count": self.report_count,
            "section_count": self.section_count,
            "status_counts": dict(self.status_counts),
            "report_type_counts": dict(self.report_type_counts),
            "failed_count": self.failed_count,
            "partial_count": self.partial_count,
            "complete_count": self.complete_count,
            "duplicate_report_count": self.duplicate_report_count,
            "created_at": self.created_at,
            "raw_metadata": dict(self.raw_metadata),
            "schema_version": self.schema_version,
        }


@dataclass
class ExecutionReportEvidence:
    """Evidence record for an execution report summary."""

    evidence_id: str = ""
    summary_id: str = ""
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
            "summary_id": self.summary_id,
            "summary": self.summary,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class ExecutionReportEngine:
    """Manages execution report summaries deterministically.

    Execution reports are validated, deduplicated, ordered deterministically
    (with ordered sections), and aggregated with status counts, report-type
    counts, and failed/partial/complete detection. Summaries are append-only.
    The upstream result / artifact / attempt / graph layers are *consumed*
    read-only; nothing is mutated. No report is published.
    """

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "execution_report"
        self._report_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Path safety (for summary_id only)
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"{name} must not be empty or whitespace")
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(
                f"{name} must not contain '..', '/', or '\\': {value!r}"
            )

    def _safe_path(self, summary_id: str) -> Path:
        target = (self._report_dir / summary_id).resolve()
        sandbox = self._report_dir.resolve()
        if not str(target).startswith(str(sandbox) + "/") and target != sandbox:
            raise ValueError(
                f"Resolved path escapes artifacts root: {summary_id!r}"
            )
        return target

    # ------------------------------------------------------------------
    # Sort keys
    # ------------------------------------------------------------------

    @staticmethod
    def _report_sort_key(r: ExecutionReport) -> tuple:
        return (
            r.capability_id,
            r.attempt_id,
            r.result_id,
            r.report_type,
            r.status,
            r.report_id,
        )

    @staticmethod
    def _section_sort_key(s: ExecutionReportSection) -> tuple:
        return (s.order_index, s.section_type, s.title, s.section_id)

    @staticmethod
    def _reference_sort_key(r: ExecutionReportReference) -> tuple:
        return (r.reference_type, r.reference_value, r.reference_id)

    # ------------------------------------------------------------------
    # Building / validation
    # ------------------------------------------------------------------

    @classmethod
    def _build_section(cls, data: dict[str, Any]) -> ExecutionReportSection:
        stype_raw = data.get("section_type", "")
        if not stype_raw or not str(stype_raw).strip():
            raise ValueError("section_type is required for a section")
        stype = str(stype_raw).strip().upper()
        if stype not in _VALID_SECTION_TYPES:
            raise ValueError(
                f"Invalid section_type: {stype_raw!r}. "
                f"Valid: {sorted(_VALID_SECTION_TYPES)}"
            )

        normalized = dict(data)
        normalized["section_type"] = stype
        return ExecutionReportSection.from_dict(normalized)

    @classmethod
    def _build_reference(
        cls, data: dict[str, Any]
    ) -> ExecutionReportReference:
        rtype_raw = data.get("reference_type", "")
        if not rtype_raw or not str(rtype_raw).strip():
            raise ValueError("reference_type is required for a reference")
        rtype = str(rtype_raw).strip().upper()
        if rtype not in _VALID_REFERENCE_TYPES:
            raise ValueError(
                f"Invalid reference_type: {rtype_raw!r}. "
                f"Valid: {sorted(_VALID_REFERENCE_TYPES)}"
            )
        rvalue = data.get("reference_value", "")
        if not rvalue or not str(rvalue).strip():
            raise ValueError("reference_value is required for a reference")

        normalized = dict(data)
        normalized["reference_type"] = rtype
        normalized["reference_value"] = str(rvalue)
        return ExecutionReportReference.from_dict(normalized)

    @classmethod
    def _build_report(cls, data: dict[str, Any]) -> ExecutionReport:
        capability_id = data.get("capability_id", "")
        if not capability_id or not str(capability_id).strip():
            raise ValueError(
                "capability_id is required for an execution report"
            )
        attempt_id = data.get("attempt_id", "")
        if not attempt_id or not str(attempt_id).strip():
            raise ValueError("attempt_id is required for an execution report")
        result_id = data.get("result_id", "")
        if not result_id or not str(result_id).strip():
            raise ValueError("result_id is required for an execution report")

        report_type_raw = data.get("report_type", "")
        if not report_type_raw or not str(report_type_raw).strip():
            raise ValueError("report_type is required for an execution report")
        report_type = str(report_type_raw).strip().upper()
        if report_type not in _VALID_REPORT_TYPES:
            raise ValueError(
                f"Invalid report_type: {report_type_raw!r}. "
                f"Valid: {sorted(_VALID_REPORT_TYPES)}"
            )

        status_raw = data.get("status", "")
        if not status_raw or not str(status_raw).strip():
            raise ValueError("status is required for an execution report")
        status = str(status_raw).strip().upper()
        if status not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid status: {status_raw!r}. "
                f"Valid: {sorted(_VALID_STATUSES)}"
            )

        sections = sorted(
            (cls._build_section(s) for s in data.get("sections", [])),
            key=cls._section_sort_key,
        )
        references = sorted(
            (cls._build_reference(r) for r in data.get("references", [])),
            key=cls._reference_sort_key,
        )

        normalized = dict(data)
        normalized["capability_id"] = str(capability_id)
        normalized["attempt_id"] = str(attempt_id)
        normalized["result_id"] = str(result_id)
        normalized["report_type"] = report_type
        normalized["status"] = status
        normalized.pop("sections", None)
        normalized.pop("references", None)
        report = ExecutionReport.from_dict(normalized)
        report.sections = sections
        report.references = references
        return report

    def _assemble(self, summary: ExecutionReportSummary) -> dict[str, Any]:
        # Duplicate report detection: same
        # (capability_id, attempt_id, result_id, report_type). Keep first.
        seen: set[tuple[str, str, str, str]] = set()
        deduped: list[ExecutionReport] = []
        duplicates = 0
        for r in sorted(summary.reports, key=self._report_sort_key):
            key = (
                r.capability_id,
                r.attempt_id,
                r.result_id,
                r.report_type,
            )
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            deduped.append(r)
        summary.reports = deduped
        summary.duplicate_report_count = duplicates

        status_counts: dict[str, int] = {}
        report_type_counts: dict[str, int] = {}
        section_count = 0
        for r in summary.reports:
            status_counts[r.status] = status_counts.get(r.status, 0) + 1
            report_type_counts[r.report_type] = (
                report_type_counts.get(r.report_type, 0) + 1
            )
            section_count += len(r.sections)

        summary.status_counts = {
            k: status_counts[k] for k in sorted(status_counts)
        }
        summary.report_type_counts = {
            k: report_type_counts[k] for k in sorted(report_type_counts)
        }
        summary.failed_count = status_counts.get(
            ExecutionReportStatus.FAILED.value, 0
        )
        summary.partial_count = status_counts.get(
            ExecutionReportStatus.PARTIAL.value, 0
        )
        summary.complete_count = status_counts.get(
            ExecutionReportStatus.COMPLETE.value, 0
        )
        summary.report_count = len(summary.reports)
        summary.section_count = section_count

        return summary.to_dict()

    # ------------------------------------------------------------------
    # Create / Append (append-only)
    # ------------------------------------------------------------------

    def create(
        self,
        reports: list[dict[str, Any]] | None = None,
        raw_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new execution report summary."""
        summary = ExecutionReportSummary(
            raw_metadata=dict(raw_metadata or {}),
        )
        summary.reports = [self._build_report(r) for r in (reports or [])]
        assembled = self._assemble(summary)
        self._persist(assembled)
        self._write_evidence(assembled)
        return assembled

    def append(
        self,
        summary_id: str,
        reports: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Append execution reports to an existing summary (append-only)."""
        self._validate_id_segment(summary_id, "summary_id")
        existing = self._load_summary(summary_id)
        if existing is None:
            raise ValueError(f"Report not found: {summary_id}")

        summary = ExecutionReportSummary(
            summary_id=existing["summary_id"],
            created_at=existing.get("created_at", ""),
            raw_metadata=dict(existing.get("raw_metadata", {})),
            schema_version=existing.get("schema_version", SCHEMA_VERSION),
        )
        summary.reports = [
            ExecutionReport.from_dict(r)
            for r in existing.get("reports", [])
        ]
        summary.reports.extend(
            self._build_report(r) for r in (reports or [])
        )

        assembled = self._assemble(summary)
        self._persist(assembled)
        self._write_evidence(assembled)
        return assembled

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_report(self, summary_id: str) -> dict[str, Any] | None:
        self._validate_id_segment(summary_id, "summary_id")
        return self._load_summary(summary_id)

    def list_reports(self) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        if not self._report_dir.exists():
            return summaries

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
                summaries.append(data)
            except (json.JSONDecodeError, OSError):
                continue

        summaries.sort(key=lambda r: r.get("created_at", ""))
        return summaries

    def export_report(self, summary_id: str, fmt: str = "markdown") -> str:
        self._validate_id_segment(summary_id, "summary_id")
        data = self._load_summary(summary_id)
        if data is None:
            raise ValueError(f"Report not found: {summary_id}")
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

    def _persist(self, summary: dict[str, Any]) -> None:
        summary_dir = self._safe_path(summary["summary_id"])
        summary_dir.mkdir(parents=True, exist_ok=True)
        (summary_dir / "report.json").write_text(
            json.dumps(summary, indent=2, default=str),
            encoding="utf-8",
        )

    def _load_summary(self, summary_id: str) -> dict[str, Any] | None:
        summary_dir = self._safe_path(summary_id)
        report_file = summary_dir / "report.json"
        if not report_file.exists():
            return None
        return json.loads(report_file.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def _write_evidence(self, summary: dict[str, Any]) -> None:
        evidence_dir = self._safe_path(summary["summary_id"])
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "summary_id": summary["summary_id"],
            "reports": summary.get("reports", []),
            "raw_metadata": summary.get("raw_metadata", {}),
        }
        (evidence_dir / "execution_report_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_report_result.json").write_text(
            json.dumps(summary, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_report_summary.md").write_text(
            self._generate_export_md(summary), encoding="utf-8"
        )

        report_count = summary.get("report_count", 0)
        section_count = summary.get("section_count", 0)
        failed_count = summary.get("failed_count", 0)
        partial_count = summary.get("partial_count", 0)
        complete_count = summary.get("complete_count", 0)
        duplicate_report_count = summary.get("duplicate_report_count", 0)
        evidence = ExecutionReportEvidence(
            summary_id=summary["summary_id"],
            summary=(
                f"{report_count} report(s), "
                f"{section_count} section(s), "
                f"{failed_count} failed, "
                f"{partial_count} partial, "
                f"{complete_count} complete, "
                f"{duplicate_report_count} duplicate(s)"
            ),
        )

        # A summary passes when it carries at least one report and no report is
        # failed.
        passed = report_count > 0 and failed_count == 0
        pass_fail = {
            "passed": passed,
            "summary_id": summary["summary_id"],
            "evidence_id": evidence.evidence_id,
            "report_count": report_count,
            "section_count": section_count,
            "failed_count": failed_count,
            "partial_count": partial_count,
            "complete_count": complete_count,
            "duplicate_report_count": duplicate_report_count,
            "status_counts": dict(summary.get("status_counts", {})),
            "report_type_counts": dict(summary.get("report_type_counts", {})),
            "schema_version": summary.get("schema_version", SCHEMA_VERSION),
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

        lines.append("# Execution Report Summary")
        lines.append("")
        lines.append(f"- Summary ID: {data.get('summary_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append(f"- Schema Version: {data.get('schema_version', '')}")
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Reports: {data.get('report_count', 0)}")
        lines.append(f"- Sections: {data.get('section_count', 0)}")
        lines.append(f"- Failed: {data.get('failed_count', 0)}")
        lines.append(f"- Partial: {data.get('partial_count', 0)}")
        lines.append(f"- Complete: {data.get('complete_count', 0)}")
        lines.append(
            f"- Duplicate Reports: {data.get('duplicate_report_count', 0)}"
        )
        lines.append("")

        status_counts = data.get("status_counts", {})
        lines.append("## Status Counts")
        lines.append("")
        for status in sorted(status_counts):
            lines.append(f"- {status}: {status_counts[status]}")
        lines.append("")

        report_type_counts = data.get("report_type_counts", {})
        lines.append("## Report Type Counts")
        lines.append("")
        for report_type in sorted(report_type_counts):
            lines.append(
                f"- {report_type}: {report_type_counts[report_type]}"
            )
        lines.append("")

        lines.append("## Reports")
        lines.append("")
        for r in data.get("reports", []):
            report_type = r.get("report_type", "")
            status = r.get("status", "")
            capability_id = r.get("capability_id", "")
            attempt_id = r.get("attempt_id", "")
            result_id = r.get("result_id", "")
            lines.append(
                f"- [{status}] [{report_type}] "
                f"capability={capability_id} attempt={attempt_id} "
                f"result={result_id}"
            )
            for sec in r.get("sections", []):
                stype = sec.get("section_type", "")
                title = sec.get("title", "")
                order_index = sec.get("order_index", 0)
                lines.append(f"  - [{order_index}] [{stype}] {title}")
            for ref in r.get("references", []):
                rtype = ref.get("reference_type", "")
                rvalue = ref.get("reference_value", "")
                lines.append(f"  - [{rtype}] {rvalue}")
        lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _generate_export_csv(data: dict[str, Any]) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "record_kind",
                "report_id",
                "capability_id",
                "attempt_id",
                "result_id",
                "report_type",
                "status",
                "section_id",
                "section_type",
                "title",
                "order_index",
                "reference_id",
                "reference_type",
                "reference_value",
                "summary",
            ]
        )
        for r in data.get("reports", []):
            writer.writerow(
                [
                    "report",
                    r.get("report_id", ""),
                    r.get("capability_id", ""),
                    r.get("attempt_id", ""),
                    r.get("result_id", ""),
                    r.get("report_type", ""),
                    r.get("status", ""),
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    r.get("summary", ""),
                ]
            )
            for sec in r.get("sections", []):
                writer.writerow(
                    [
                        "section",
                        r.get("report_id", ""),
                        "",
                        "",
                        "",
                        "",
                        "",
                        sec.get("section_id", ""),
                        sec.get("section_type", ""),
                        sec.get("title", ""),
                        sec.get("order_index", 0),
                        "",
                        "",
                        "",
                        sec.get("content", ""),
                    ]
                )
            for ref in r.get("references", []):
                writer.writerow(
                    [
                        "reference",
                        r.get("report_id", ""),
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        ref.get("reference_id", ""),
                        ref.get("reference_type", ""),
                        ref.get("reference_value", ""),
                        ref.get("summary", ""),
                    ]
                )
        return buf.getvalue()
