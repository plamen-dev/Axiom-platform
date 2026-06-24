"""Execution Environment Framework v1.

The execution-environment layer continues the autonomous engineering roadmap on
top of the Execution Context Framework and the Capability Knowledge Graph. Where
the Execution Context layer represents the *state in which execution occurs*,
this layer represents the *environment where execution is expected to happen*:
for a given context / capability, what kind of environment it is (local, devin,
github actions, windows revit, local runner, axiom worker, ...), what status it
is in (available, unavailable, degraded, unknown), and which upstream objects it
references.

Per report it captures a deterministic, append-only set of execution
environments, aggregated with environment-type counts and status counts,
unavailable- and degraded-environment detection, and duplicate-environment
detection, with preserved raw payloads and schema versioning.

It is deliberately *structure only*. Non-goals: no execution engine, no
environment provisioning, no worker orchestration, no scheduling, no Docker/VM
management, no network calls, no graph query language, no dashboard, no
architecture changes. The upstream context / graph layers are consumed
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


class ExecutionEnvironmentType(str, Enum):
    LOCAL = "LOCAL"
    DEVIN = "DEVIN"
    GITHUB_ACTIONS = "GITHUB_ACTIONS"
    WINDOWS_REVIT = "WINDOWS_REVIT"
    LOCAL_RUNNER = "LOCAL_RUNNER"
    AXIOM_WORKER = "AXIOM_WORKER"
    OTHER = "OTHER"


class ExecutionEnvironmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


class ExecutionEnvironmentReferenceType(str, Enum):
    CONTEXT = "CONTEXT"
    CAPABILITY = "CAPABILITY"
    WORKER = "WORKER"
    REPOSITORY = "REPOSITORY"
    BRANCH = "BRANCH"
    COMMIT = "COMMIT"
    ARTIFACT = "ARTIFACT"
    CONFIGURATION = "CONFIGURATION"
    OTHER = "OTHER"


_VALID_ENVIRONMENT_TYPES = {t.value for t in ExecutionEnvironmentType}
_VALID_STATUSES = {t.value for t in ExecutionEnvironmentStatus}
_VALID_REFERENCE_TYPES = {t.value for t in ExecutionEnvironmentReferenceType}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class ExecutionEnvironmentReference:
    """A single reference from an execution environment to an upstream object."""

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
    def from_dict(cls, data: dict[str, Any]) -> ExecutionEnvironmentReference:
        return cls(
            reference_id=data.get("reference_id", ""),
            reference_type=data.get("reference_type", ""),
            reference_value=data.get("reference_value", ""),
            summary=data.get("summary", ""),
        )


@dataclass
class ExecutionEnvironment:
    """A single execution environment."""

    environment_id: str = ""
    context_id: str = ""
    capability_id: str = ""
    environment_type: str = ""
    status: str = ""
    references: list[ExecutionEnvironmentReference] = field(default_factory=list)
    summary: str = ""
    created_at: str = ""
    schema_version: str = SCHEMA_VERSION
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.environment_id:
            self.environment_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "environment_id": self.environment_id,
            "context_id": self.context_id,
            "capability_id": self.capability_id,
            "environment_type": self.environment_type,
            "status": self.status,
            "references": [r.to_dict() for r in self.references],
            "summary": self.summary,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "raw_payload": dict(self.raw_payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionEnvironment:
        return cls(
            environment_id=data.get("environment_id", ""),
            context_id=data.get("context_id", ""),
            capability_id=data.get("capability_id", ""),
            environment_type=data.get("environment_type", ""),
            status=data.get("status", ""),
            references=[
                ExecutionEnvironmentReference.from_dict(r)
                for r in data.get("references", [])
            ],
            summary=data.get("summary", ""),
            created_at=data.get("created_at", ""),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            raw_payload=dict(data.get("raw_payload", {})),
        )


@dataclass
class ExecutionEnvironmentReport:
    """A deterministic, append-only execution environment report."""

    report_id: str = ""
    environments: list[ExecutionEnvironment] = field(default_factory=list)
    environment_count: int = 0
    environment_type_counts: dict[str, int] = field(default_factory=dict)
    status_counts: dict[str, int] = field(default_factory=dict)
    unavailable_count: int = 0
    degraded_count: int = 0
    duplicate_environment_count: int = 0
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
            "environments": [e.to_dict() for e in self.environments],
            "environment_count": self.environment_count,
            "environment_type_counts": dict(self.environment_type_counts),
            "status_counts": dict(self.status_counts),
            "unavailable_count": self.unavailable_count,
            "degraded_count": self.degraded_count,
            "duplicate_environment_count": self.duplicate_environment_count,
            "created_at": self.created_at,
            "raw_metadata": dict(self.raw_metadata),
            "schema_version": self.schema_version,
        }


@dataclass
class ExecutionEnvironmentEvidence:
    """Evidence record for an execution environment report."""

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


class ExecutionEnvironmentEngine:
    """Manages execution environment reports deterministically.

    Execution environments are validated, deduplicated, ordered
    deterministically, and aggregated with environment-type counts, status
    counts, and unavailable/degraded detection. Reports are append-only. The
    upstream context / graph layers are *consumed* read-only; nothing is
    mutated.
    """

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "execution_environment"
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
    def _environment_sort_key(e: ExecutionEnvironment) -> tuple:
        return (
            e.context_id,
            e.capability_id,
            e.environment_type,
            e.status,
            e.environment_id,
        )

    @staticmethod
    def _reference_sort_key(r: ExecutionEnvironmentReference) -> tuple:
        return (r.reference_type, r.reference_value, r.reference_id)

    # ------------------------------------------------------------------
    # Building / validation
    # ------------------------------------------------------------------

    @classmethod
    def _build_reference(
        cls, data: dict[str, Any]
    ) -> ExecutionEnvironmentReference:
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
        return ExecutionEnvironmentReference.from_dict(normalized)

    @classmethod
    def _build_environment(cls, data: dict[str, Any]) -> ExecutionEnvironment:
        context_id = data.get("context_id", "")
        if not context_id or not str(context_id).strip():
            raise ValueError(
                "context_id is required for an execution environment"
            )
        capability_id = data.get("capability_id", "")
        if not capability_id or not str(capability_id).strip():
            raise ValueError(
                "capability_id is required for an execution environment"
            )

        etype_raw = data.get("environment_type", "")
        if not etype_raw or not str(etype_raw).strip():
            raise ValueError(
                "environment_type is required for an execution environment"
            )
        etype = str(etype_raw).strip().upper()
        if etype not in _VALID_ENVIRONMENT_TYPES:
            raise ValueError(
                f"Invalid environment_type: {etype_raw!r}. "
                f"Valid: {sorted(_VALID_ENVIRONMENT_TYPES)}"
            )

        status_raw = data.get("status", "")
        if not status_raw or not str(status_raw).strip():
            raise ValueError(
                "status is required for an execution environment"
            )
        status = str(status_raw).strip().upper()
        if status not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid status: {status_raw!r}. "
                f"Valid: {sorted(_VALID_STATUSES)}"
            )

        references = sorted(
            (cls._build_reference(r) for r in data.get("references", [])),
            key=cls._reference_sort_key,
        )

        normalized = dict(data)
        normalized["context_id"] = str(context_id)
        normalized["capability_id"] = str(capability_id)
        normalized["environment_type"] = etype
        normalized["status"] = status
        normalized.pop("references", None)
        environment = ExecutionEnvironment.from_dict(normalized)
        environment.references = references
        return environment

    def _assemble(self, report: ExecutionEnvironmentReport) -> dict[str, Any]:
        # Duplicate environment detection: same
        # (context_id, capability_id, environment_type). Keep first.
        seen: set[tuple[str, str, str]] = set()
        deduped: list[ExecutionEnvironment] = []
        duplicates = 0
        for e in sorted(report.environments, key=self._environment_sort_key):
            key = (e.context_id, e.capability_id, e.environment_type)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            deduped.append(e)
        report.environments = deduped
        report.duplicate_environment_count = duplicates

        environment_type_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        for e in report.environments:
            environment_type_counts[e.environment_type] = (
                environment_type_counts.get(e.environment_type, 0) + 1
            )
            status_counts[e.status] = status_counts.get(e.status, 0) + 1

        report.environment_type_counts = {
            k: environment_type_counts[k]
            for k in sorted(environment_type_counts)
        }
        report.status_counts = {
            k: status_counts[k] for k in sorted(status_counts)
        }
        report.unavailable_count = status_counts.get(
            ExecutionEnvironmentStatus.UNAVAILABLE.value, 0
        )
        report.degraded_count = status_counts.get(
            ExecutionEnvironmentStatus.DEGRADED.value, 0
        )
        report.environment_count = len(report.environments)

        return report.to_dict()

    # ------------------------------------------------------------------
    # Create / Append (append-only)
    # ------------------------------------------------------------------

    def create(
        self,
        environments: list[dict[str, Any]] | None = None,
        raw_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new execution environment report."""
        report = ExecutionEnvironmentReport(
            raw_metadata=dict(raw_metadata or {}),
        )
        report.environments = [
            self._build_environment(e) for e in (environments or [])
        ]
        assembled = self._assemble(report)
        self._persist(assembled)
        self._write_evidence(assembled)
        return assembled

    def append(
        self,
        report_id: str,
        environments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Append execution environments to an existing report (append-only)."""
        self._validate_id_segment(report_id, "report_id")
        existing = self._load_report(report_id)
        if existing is None:
            raise ValueError(f"Report not found: {report_id}")

        report = ExecutionEnvironmentReport(
            report_id=existing["report_id"],
            created_at=existing.get("created_at", ""),
            raw_metadata=dict(existing.get("raw_metadata", {})),
            schema_version=existing.get("schema_version", SCHEMA_VERSION),
        )
        report.environments = [
            ExecutionEnvironment.from_dict(e)
            for e in existing.get("environments", [])
        ]
        report.environments.extend(
            self._build_environment(e) for e in (environments or [])
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
            "environments": report.get("environments", []),
            "raw_metadata": report.get("raw_metadata", {}),
        }
        (evidence_dir / "execution_environment_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_environment_result.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_environment_summary.md").write_text(
            self._generate_export_md(report), encoding="utf-8"
        )

        environment_count = report.get("environment_count", 0)
        unavailable_count = report.get("unavailable_count", 0)
        degraded_count = report.get("degraded_count", 0)
        duplicate_environment_count = report.get(
            "duplicate_environment_count", 0
        )
        evidence = ExecutionEnvironmentEvidence(
            report_id=report["report_id"],
            summary=(
                f"{environment_count} environment(s), "
                f"{unavailable_count} unavailable, "
                f"{degraded_count} degraded, "
                f"{duplicate_environment_count} duplicate(s)"
            ),
        )

        # A report passes when it carries at least one environment and no
        # environment is unavailable or degraded.
        passed = (
            environment_count > 0
            and unavailable_count == 0
            and degraded_count == 0
        )
        pass_fail = {
            "passed": passed,
            "report_id": report["report_id"],
            "evidence_id": evidence.evidence_id,
            "environment_count": environment_count,
            "unavailable_count": unavailable_count,
            "degraded_count": degraded_count,
            "duplicate_environment_count": duplicate_environment_count,
            "status_counts": dict(report.get("status_counts", {})),
            "environment_type_counts": dict(
                report.get("environment_type_counts", {})
            ),
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

        lines.append("# Execution Environment Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append(f"- Schema Version: {data.get('schema_version', '')}")
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Environments: {data.get('environment_count', 0)}")
        lines.append(f"- Unavailable: {data.get('unavailable_count', 0)}")
        lines.append(f"- Degraded: {data.get('degraded_count', 0)}")
        lines.append(
            "- Duplicate Environments: "
            f"{data.get('duplicate_environment_count', 0)}"
        )
        lines.append("")

        status_counts = data.get("status_counts", {})
        lines.append("## Status Counts")
        lines.append("")
        for status in sorted(status_counts):
            lines.append(f"- {status}: {status_counts[status]}")
        lines.append("")

        environment_type_counts = data.get("environment_type_counts", {})
        lines.append("## Environment Type Counts")
        lines.append("")
        for etype in sorted(environment_type_counts):
            lines.append(f"- {etype}: {environment_type_counts[etype]}")
        lines.append("")

        lines.append("## Environments")
        lines.append("")
        for e in data.get("environments", []):
            status = e.get("status", "")
            etype = e.get("environment_type", "")
            context_id = e.get("context_id", "")
            capability_id = e.get("capability_id", "")
            lines.append(
                f"- [{status}] [{etype}] context={context_id} "
                f"capability={capability_id}"
            )
            for r in e.get("references", []):
                rtype = r.get("reference_type", "")
                rvalue = r.get("reference_value", "")
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
                "environment_id",
                "context_id",
                "capability_id",
                "environment_type",
                "status",
                "reference_id",
                "reference_type",
                "reference_value",
                "summary",
            ]
        )
        for e in data.get("environments", []):
            writer.writerow(
                [
                    "environment",
                    e.get("environment_id", ""),
                    e.get("context_id", ""),
                    e.get("capability_id", ""),
                    e.get("environment_type", ""),
                    e.get("status", ""),
                    "",
                    "",
                    "",
                    e.get("summary", ""),
                ]
            )
            for r in e.get("references", []):
                writer.writerow(
                    [
                        "reference",
                        e.get("environment_id", ""),
                        "",
                        "",
                        "",
                        "",
                        r.get("reference_id", ""),
                        r.get("reference_type", ""),
                        r.get("reference_value", ""),
                        r.get("summary", ""),
                    ]
                )
        return buf.getvalue()
