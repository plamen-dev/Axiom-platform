"""Execution Readiness Framework v1.

The execution-readiness layer continues the autonomous engineering roadmap on
top of the Execution Context Framework, the Execution Environment Framework, the
Execution Resource Framework, and the Execution Constraint Framework. Where the
Execution Context layer represents the *state in which execution occurs*, the
Execution Environment layer represents the *location where execution is expected
to happen*, the Execution Resource layer represents the *resources execution
requires*, and the Execution Constraint layer represents the *limitations
execution must obey*, this layer determines *whether execution is ready to
proceed*: for a given context / environment / resource / constraint / capability,
what its readiness status is (ready, not ready, degraded, unknown), which
readiness checks were evaluated (context, environment, resource, constraint,
validation, ...), and how those checks resolved.

Per report it captures a deterministic, append-only set of execution readiness
records, aggregated with readiness-status counts, check-type counts,
degraded- and not-ready detection, and duplicate-readiness detection, with
preserved raw payloads and schema versioning.

It is deliberately *observational and evaluative only*. Non-goals: no execution,
no orchestration, no scheduling, no optimization, no worker assignment, no
autonomous execution, no network calls, no architecture changes. The upstream
context / environment / resource / constraint layers are consumed read-only;
nothing is mutated.
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


class ExecutionReadinessStatus(str, Enum):
    READY = "READY"
    NOT_READY = "NOT_READY"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


class ExecutionReadinessCheckType(str, Enum):
    CONTEXT_CHECK = "CONTEXT_CHECK"
    ENVIRONMENT_CHECK = "ENVIRONMENT_CHECK"
    RESOURCE_CHECK = "RESOURCE_CHECK"
    CONSTRAINT_CHECK = "CONSTRAINT_CHECK"
    VALIDATION_CHECK = "VALIDATION_CHECK"
    OTHER = "OTHER"


_VALID_READINESS_STATUSES = {t.value for t in ExecutionReadinessStatus}
_VALID_CHECK_TYPES = {t.value for t in ExecutionReadinessCheckType}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class ExecutionReadinessCheck:
    """A single readiness check evaluated for an execution readiness record."""

    check_id: str = ""
    check_type: str = ""
    status: str = ""
    summary: str = ""

    def __post_init__(self) -> None:
        if not self.check_id:
            self.check_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "check_type": self.check_type,
            "status": self.status,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionReadinessCheck:
        return cls(
            check_id=data.get("check_id", ""),
            check_type=data.get("check_type", ""),
            status=data.get("status", ""),
            summary=data.get("summary", ""),
        )


@dataclass
class ExecutionReadiness:
    """A single execution readiness record."""

    readiness_id: str = ""
    context_id: str = ""
    environment_id: str = ""
    resource_id: str = ""
    constraint_id: str = ""
    capability_id: str = ""
    readiness_status: str = ""
    checks: list[ExecutionReadinessCheck] = field(default_factory=list)
    summary: str = ""
    created_at: str = ""
    schema_version: str = SCHEMA_VERSION
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.readiness_id:
            self.readiness_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "readiness_id": self.readiness_id,
            "context_id": self.context_id,
            "environment_id": self.environment_id,
            "resource_id": self.resource_id,
            "constraint_id": self.constraint_id,
            "capability_id": self.capability_id,
            "readiness_status": self.readiness_status,
            "checks": [c.to_dict() for c in self.checks],
            "summary": self.summary,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "raw_payload": dict(self.raw_payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionReadiness:
        return cls(
            readiness_id=data.get("readiness_id", ""),
            context_id=data.get("context_id", ""),
            environment_id=data.get("environment_id", ""),
            resource_id=data.get("resource_id", ""),
            constraint_id=data.get("constraint_id", ""),
            capability_id=data.get("capability_id", ""),
            readiness_status=data.get("readiness_status", ""),
            checks=[
                ExecutionReadinessCheck.from_dict(c)
                for c in data.get("checks", [])
            ],
            summary=data.get("summary", ""),
            created_at=data.get("created_at", ""),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            raw_payload=dict(data.get("raw_payload", {})),
        )


@dataclass
class ExecutionReadinessReport:
    """A deterministic, append-only execution readiness report."""

    report_id: str = ""
    readinesses: list[ExecutionReadiness] = field(default_factory=list)
    readiness_count: int = 0
    readiness_status_counts: dict[str, int] = field(default_factory=dict)
    check_type_counts: dict[str, int] = field(default_factory=dict)
    check_count: int = 0
    ready_count: int = 0
    degraded_count: int = 0
    not_ready_count: int = 0
    duplicate_readiness_count: int = 0
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
            "readinesses": [r.to_dict() for r in self.readinesses],
            "readiness_count": self.readiness_count,
            "readiness_status_counts": dict(self.readiness_status_counts),
            "check_type_counts": dict(self.check_type_counts),
            "check_count": self.check_count,
            "ready_count": self.ready_count,
            "degraded_count": self.degraded_count,
            "not_ready_count": self.not_ready_count,
            "duplicate_readiness_count": self.duplicate_readiness_count,
            "created_at": self.created_at,
            "raw_metadata": dict(self.raw_metadata),
            "schema_version": self.schema_version,
        }


@dataclass
class ExecutionReadinessEvidence:
    """Evidence record for an execution readiness report."""

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


class ExecutionReadinessEngine:
    """Manages execution readiness reports deterministically.

    Execution readiness records are validated, deduplicated, ordered
    deterministically, and aggregated with readiness-status counts, check-type
    counts, and degraded/not-ready detection. Reports are append-only. The
    upstream context / environment / resource / constraint layers are *consumed*
    read-only; nothing is mutated.
    """

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "execution_readiness"
        self._report_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Path safety (for report_id only)
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
    # Sort keys
    # ------------------------------------------------------------------

    @staticmethod
    def _readiness_sort_key(r: ExecutionReadiness) -> tuple:
        return (
            r.context_id,
            r.environment_id,
            r.resource_id,
            r.constraint_id,
            r.capability_id,
            r.readiness_status,
            r.readiness_id,
        )

    @staticmethod
    def _check_sort_key(c: ExecutionReadinessCheck) -> tuple:
        return (c.check_type, c.status, c.check_id)

    # ------------------------------------------------------------------
    # Building / validation
    # ------------------------------------------------------------------

    @classmethod
    def _build_check(cls, data: dict[str, Any]) -> ExecutionReadinessCheck:
        ctype_raw = data.get("check_type", "")
        if not ctype_raw or not str(ctype_raw).strip():
            raise ValueError("check_type is required for a readiness check")
        ctype = str(ctype_raw).strip().upper()
        if ctype not in _VALID_CHECK_TYPES:
            raise ValueError(
                f"Invalid check_type: {ctype_raw!r}. "
                f"Valid: {sorted(_VALID_CHECK_TYPES)}"
            )
        status_raw = data.get("status", "")
        if not status_raw or not str(status_raw).strip():
            raise ValueError("status is required for a readiness check")

        normalized = dict(data)
        normalized["check_type"] = ctype
        normalized["status"] = str(status_raw).strip().upper()
        return ExecutionReadinessCheck.from_dict(normalized)

    @classmethod
    def _build_readiness(cls, data: dict[str, Any]) -> ExecutionReadiness:
        context_id = data.get("context_id", "")
        if not context_id or not str(context_id).strip():
            raise ValueError(
                "context_id is required for an execution readiness"
            )
        environment_id = data.get("environment_id", "")
        if not environment_id or not str(environment_id).strip():
            raise ValueError(
                "environment_id is required for an execution readiness"
            )
        resource_id = data.get("resource_id", "")
        if not resource_id or not str(resource_id).strip():
            raise ValueError(
                "resource_id is required for an execution readiness"
            )
        constraint_id = data.get("constraint_id", "")
        if not constraint_id or not str(constraint_id).strip():
            raise ValueError(
                "constraint_id is required for an execution readiness"
            )
        capability_id = data.get("capability_id", "")
        if not capability_id or not str(capability_id).strip():
            raise ValueError(
                "capability_id is required for an execution readiness"
            )

        status_raw = data.get("readiness_status", "")
        if not status_raw or not str(status_raw).strip():
            raise ValueError(
                "readiness_status is required for an execution readiness"
            )
        status = str(status_raw).strip().upper()
        if status not in _VALID_READINESS_STATUSES:
            raise ValueError(
                f"Invalid readiness_status: {status_raw!r}. "
                f"Valid: {sorted(_VALID_READINESS_STATUSES)}"
            )

        checks = sorted(
            (cls._build_check(c) for c in data.get("checks", [])),
            key=cls._check_sort_key,
        )

        normalized = dict(data)
        normalized["context_id"] = str(context_id)
        normalized["environment_id"] = str(environment_id)
        normalized["resource_id"] = str(resource_id)
        normalized["constraint_id"] = str(constraint_id)
        normalized["capability_id"] = str(capability_id)
        normalized["readiness_status"] = status
        normalized.pop("checks", None)
        readiness = ExecutionReadiness.from_dict(normalized)
        readiness.checks = checks
        return readiness

    def _assemble(self, report: ExecutionReadinessReport) -> dict[str, Any]:
        # Duplicate readiness detection: same
        # (context_id, environment_id, resource_id, constraint_id,
        # capability_id). Keep first.
        seen: set[tuple[str, str, str, str, str]] = set()
        deduped: list[ExecutionReadiness] = []
        duplicates = 0
        for r in sorted(report.readinesses, key=self._readiness_sort_key):
            key = (
                r.context_id,
                r.environment_id,
                r.resource_id,
                r.constraint_id,
                r.capability_id,
            )
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            deduped.append(r)
        report.readinesses = deduped
        report.duplicate_readiness_count = duplicates

        readiness_status_counts: dict[str, int] = {}
        check_type_counts: dict[str, int] = {}
        check_count = 0
        for r in report.readinesses:
            readiness_status_counts[r.readiness_status] = (
                readiness_status_counts.get(r.readiness_status, 0) + 1
            )
            for c in r.checks:
                check_count += 1
                check_type_counts[c.check_type] = (
                    check_type_counts.get(c.check_type, 0) + 1
                )

        report.readiness_status_counts = {
            k: readiness_status_counts[k]
            for k in sorted(readiness_status_counts)
        }
        report.check_type_counts = {
            k: check_type_counts[k] for k in sorted(check_type_counts)
        }
        report.check_count = check_count
        report.ready_count = readiness_status_counts.get(
            ExecutionReadinessStatus.READY.value, 0
        )
        report.degraded_count = readiness_status_counts.get(
            ExecutionReadinessStatus.DEGRADED.value, 0
        )
        report.not_ready_count = readiness_status_counts.get(
            ExecutionReadinessStatus.NOT_READY.value, 0
        )
        report.readiness_count = len(report.readinesses)

        return report.to_dict()

    # ------------------------------------------------------------------
    # Create / Append (append-only)
    # ------------------------------------------------------------------

    def create(
        self,
        readinesses: list[dict[str, Any]] | None = None,
        raw_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new execution readiness report."""
        report = ExecutionReadinessReport(
            raw_metadata=dict(raw_metadata or {}),
        )
        report.readinesses = [
            self._build_readiness(r) for r in (readinesses or [])
        ]
        assembled = self._assemble(report)
        self._persist(assembled)
        self._write_evidence(assembled)
        return assembled

    def append(
        self,
        report_id: str,
        readinesses: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Append execution readiness records to a report (append-only)."""
        self._validate_id_segment(report_id, "report_id")
        existing = self._load_report(report_id)
        if existing is None:
            raise ValueError(f"Report not found: {report_id}")

        report = ExecutionReadinessReport(
            report_id=existing["report_id"],
            created_at=existing.get("created_at", ""),
            raw_metadata=dict(existing.get("raw_metadata", {})),
            schema_version=existing.get("schema_version", SCHEMA_VERSION),
        )
        report.readinesses = [
            ExecutionReadiness.from_dict(r)
            for r in existing.get("readinesses", [])
        ]
        report.readinesses.extend(
            self._build_readiness(r) for r in (readinesses or [])
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
            "readinesses": report.get("readinesses", []),
            "raw_metadata": report.get("raw_metadata", {}),
        }
        (evidence_dir / "execution_readiness_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_readiness_result.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_readiness_summary.md").write_text(
            self._generate_export_md(report), encoding="utf-8"
        )

        readiness_count = report.get("readiness_count", 0)
        ready_count = report.get("ready_count", 0)
        degraded_count = report.get("degraded_count", 0)
        not_ready_count = report.get("not_ready_count", 0)
        duplicate_readiness_count = report.get(
            "duplicate_readiness_count", 0
        )
        evidence = ExecutionReadinessEvidence(
            report_id=report["report_id"],
            summary=(
                f"{readiness_count} readiness record(s), "
                f"{ready_count} ready, "
                f"{degraded_count} degraded, "
                f"{not_ready_count} not-ready, "
                f"{duplicate_readiness_count} duplicate(s)"
            ),
        )

        # A report passes when it carries at least one readiness record and no
        # record is not-ready or degraded.
        passed = (
            readiness_count > 0
            and not_ready_count == 0
            and degraded_count == 0
        )
        pass_fail = {
            "passed": passed,
            "report_id": report["report_id"],
            "evidence_id": evidence.evidence_id,
            "readiness_count": readiness_count,
            "ready_count": ready_count,
            "degraded_count": degraded_count,
            "not_ready_count": not_ready_count,
            "duplicate_readiness_count": duplicate_readiness_count,
            "readiness_status_counts": dict(
                report.get("readiness_status_counts", {})
            ),
            "check_type_counts": dict(report.get("check_type_counts", {})),
            "check_count": report.get("check_count", 0),
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

        lines.append("# Execution Readiness Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append(f"- Schema Version: {data.get('schema_version', '')}")
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Readinesses: {data.get('readiness_count', 0)}")
        lines.append(f"- Ready: {data.get('ready_count', 0)}")
        lines.append(f"- Degraded: {data.get('degraded_count', 0)}")
        lines.append(f"- Not Ready: {data.get('not_ready_count', 0)}")
        lines.append(f"- Checks: {data.get('check_count', 0)}")
        lines.append(
            "- Duplicate Readinesses: "
            f"{data.get('duplicate_readiness_count', 0)}"
        )
        lines.append("")

        status_counts = data.get("readiness_status_counts", {})
        lines.append("## Readiness Status Counts")
        lines.append("")
        for status in sorted(status_counts):
            lines.append(f"- {status}: {status_counts[status]}")
        lines.append("")

        check_type_counts = data.get("check_type_counts", {})
        lines.append("## Check Type Counts")
        lines.append("")
        for ctype in sorted(check_type_counts):
            lines.append(f"- {ctype}: {check_type_counts[ctype]}")
        lines.append("")

        lines.append("## Readinesses")
        lines.append("")
        for r in data.get("readinesses", []):
            status = r.get("readiness_status", "")
            context_id = r.get("context_id", "")
            environment_id = r.get("environment_id", "")
            resource_id = r.get("resource_id", "")
            constraint_id = r.get("constraint_id", "")
            capability_id = r.get("capability_id", "")
            lines.append(
                f"- [{status}] context={context_id} "
                f"environment={environment_id} resource={resource_id} "
                f"constraint={constraint_id} capability={capability_id}"
            )
            for check in r.get("checks", []):
                ctype = check.get("check_type", "")
                cstatus = check.get("status", "")
                lines.append(f"  - [{ctype}] {cstatus}")
        lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _generate_export_csv(data: dict[str, Any]) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "record_kind",
                "readiness_id",
                "context_id",
                "environment_id",
                "resource_id",
                "constraint_id",
                "capability_id",
                "readiness_status",
                "check_id",
                "check_type",
                "check_status",
                "summary",
            ]
        )
        for r in data.get("readinesses", []):
            writer.writerow(
                [
                    "readiness",
                    r.get("readiness_id", ""),
                    r.get("context_id", ""),
                    r.get("environment_id", ""),
                    r.get("resource_id", ""),
                    r.get("constraint_id", ""),
                    r.get("capability_id", ""),
                    r.get("readiness_status", ""),
                    "",
                    "",
                    "",
                    r.get("summary", ""),
                ]
            )
            for check in r.get("checks", []):
                writer.writerow(
                    [
                        "check",
                        r.get("readiness_id", ""),
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        check.get("check_id", ""),
                        check.get("check_type", ""),
                        check.get("status", ""),
                        check.get("summary", ""),
                    ]
                )
        return buf.getvalue()
