"""Execution Resource Framework v1.

The execution-resource layer continues the autonomous engineering roadmap on top
of the Execution Context Framework, the Execution Environment Framework, and the
Capability Knowledge Graph. Where the Execution Context layer represents the
*state in which execution occurs* and the Execution Environment layer represents
the *location where execution is expected to happen*, this layer represents the
*resources execution requires*: for a given context / environment / capability,
what kind of resource it is (cpu, memory, storage, network, gpu, repository,
tool, software, credential, ...), what status it is in (available, unavailable,
degraded, unknown), and which requirements it declares.

Per report it captures a deterministic, append-only set of execution resources,
aggregated with resource-type counts, status counts, requirement counts,
unavailable- and degraded-resource detection, and duplicate-resource detection,
with preserved raw payloads and schema versioning.

It is deliberately *observational and declarative only*. Non-goals: no resource
allocation, no provisioning, no scheduling, no orchestration, no optimization, no
worker assignment, no network calls, no architecture changes. The upstream
context / environment / graph layers are consumed read-only; nothing is mutated.
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


class ExecutionResourceType(str, Enum):
    CPU = "CPU"
    MEMORY = "MEMORY"
    STORAGE = "STORAGE"
    NETWORK = "NETWORK"
    GPU = "GPU"
    REPOSITORY = "REPOSITORY"
    TOOL = "TOOL"
    SOFTWARE = "SOFTWARE"
    CREDENTIAL = "CREDENTIAL"
    OTHER = "OTHER"


class ExecutionResourceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


_VALID_RESOURCE_TYPES = {t.value for t in ExecutionResourceType}
_VALID_STATUSES = {t.value for t in ExecutionResourceStatus}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class ExecutionResourceRequirement:
    """A single requirement declared by an execution resource."""

    requirement_id: str = ""
    requirement_type: str = ""
    requirement_value: str = ""
    summary: str = ""

    def __post_init__(self) -> None:
        if not self.requirement_id:
            self.requirement_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "requirement_type": self.requirement_type,
            "requirement_value": self.requirement_value,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionResourceRequirement:
        return cls(
            requirement_id=data.get("requirement_id", ""),
            requirement_type=data.get("requirement_type", ""),
            requirement_value=data.get("requirement_value", ""),
            summary=data.get("summary", ""),
        )


@dataclass
class ExecutionResource:
    """A single execution resource."""

    resource_id: str = ""
    context_id: str = ""
    environment_id: str = ""
    capability_id: str = ""
    resource_type: str = ""
    status: str = ""
    requirements: list[ExecutionResourceRequirement] = field(
        default_factory=list
    )
    summary: str = ""
    created_at: str = ""
    schema_version: str = SCHEMA_VERSION
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.resource_id:
            self.resource_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "context_id": self.context_id,
            "environment_id": self.environment_id,
            "capability_id": self.capability_id,
            "resource_type": self.resource_type,
            "status": self.status,
            "requirements": [r.to_dict() for r in self.requirements],
            "summary": self.summary,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "raw_payload": dict(self.raw_payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionResource:
        return cls(
            resource_id=data.get("resource_id", ""),
            context_id=data.get("context_id", ""),
            environment_id=data.get("environment_id", ""),
            capability_id=data.get("capability_id", ""),
            resource_type=data.get("resource_type", ""),
            status=data.get("status", ""),
            requirements=[
                ExecutionResourceRequirement.from_dict(r)
                for r in data.get("requirements", [])
            ],
            summary=data.get("summary", ""),
            created_at=data.get("created_at", ""),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            raw_payload=dict(data.get("raw_payload", {})),
        )


@dataclass
class ExecutionResourceReport:
    """A deterministic, append-only execution resource report."""

    report_id: str = ""
    resources: list[ExecutionResource] = field(default_factory=list)
    resource_count: int = 0
    resource_type_counts: dict[str, int] = field(default_factory=dict)
    status_counts: dict[str, int] = field(default_factory=dict)
    unavailable_count: int = 0
    degraded_count: int = 0
    requirement_count: int = 0
    duplicate_resource_count: int = 0
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
            "resources": [r.to_dict() for r in self.resources],
            "resource_count": self.resource_count,
            "resource_type_counts": dict(self.resource_type_counts),
            "status_counts": dict(self.status_counts),
            "unavailable_count": self.unavailable_count,
            "degraded_count": self.degraded_count,
            "requirement_count": self.requirement_count,
            "duplicate_resource_count": self.duplicate_resource_count,
            "created_at": self.created_at,
            "raw_metadata": dict(self.raw_metadata),
            "schema_version": self.schema_version,
        }


@dataclass
class ExecutionResourceEvidence:
    """Evidence record for an execution resource report."""

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


class ExecutionResourceEngine:
    """Manages execution resource reports deterministically.

    Execution resources are validated, deduplicated, ordered deterministically,
    and aggregated with resource-type counts, status counts, requirement counts,
    and unavailable/degraded detection. Reports are append-only. The upstream
    context / environment / graph layers are *consumed* read-only; nothing is
    mutated.
    """

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "execution_resource"
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
    def _resource_sort_key(r: ExecutionResource) -> tuple:
        return (
            r.context_id,
            r.environment_id,
            r.capability_id,
            r.resource_type,
            r.status,
            r.resource_id,
        )

    @staticmethod
    def _requirement_sort_key(r: ExecutionResourceRequirement) -> tuple:
        return (r.requirement_type, r.requirement_value, r.requirement_id)

    # ------------------------------------------------------------------
    # Building / validation
    # ------------------------------------------------------------------

    @classmethod
    def _build_requirement(
        cls, data: dict[str, Any]
    ) -> ExecutionResourceRequirement:
        rtype_raw = data.get("requirement_type", "")
        if not rtype_raw or not str(rtype_raw).strip():
            raise ValueError("requirement_type is required for a requirement")
        rvalue = data.get("requirement_value", "")
        if not rvalue or not str(rvalue).strip():
            raise ValueError("requirement_value is required for a requirement")

        normalized = dict(data)
        normalized["requirement_type"] = str(rtype_raw).strip()
        normalized["requirement_value"] = str(rvalue)
        return ExecutionResourceRequirement.from_dict(normalized)

    @classmethod
    def _build_resource(cls, data: dict[str, Any]) -> ExecutionResource:
        context_id = data.get("context_id", "")
        if not context_id or not str(context_id).strip():
            raise ValueError(
                "context_id is required for an execution resource"
            )
        environment_id = data.get("environment_id", "")
        if not environment_id or not str(environment_id).strip():
            raise ValueError(
                "environment_id is required for an execution resource"
            )
        capability_id = data.get("capability_id", "")
        if not capability_id or not str(capability_id).strip():
            raise ValueError(
                "capability_id is required for an execution resource"
            )

        rtype_raw = data.get("resource_type", "")
        if not rtype_raw or not str(rtype_raw).strip():
            raise ValueError(
                "resource_type is required for an execution resource"
            )
        rtype = str(rtype_raw).strip().upper()
        if rtype not in _VALID_RESOURCE_TYPES:
            raise ValueError(
                f"Invalid resource_type: {rtype_raw!r}. "
                f"Valid: {sorted(_VALID_RESOURCE_TYPES)}"
            )

        status_raw = data.get("status", "")
        if not status_raw or not str(status_raw).strip():
            raise ValueError(
                "status is required for an execution resource"
            )
        status = str(status_raw).strip().upper()
        if status not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid status: {status_raw!r}. "
                f"Valid: {sorted(_VALID_STATUSES)}"
            )

        requirements = sorted(
            (cls._build_requirement(r) for r in data.get("requirements", [])),
            key=cls._requirement_sort_key,
        )

        normalized = dict(data)
        normalized["context_id"] = str(context_id)
        normalized["environment_id"] = str(environment_id)
        normalized["capability_id"] = str(capability_id)
        normalized["resource_type"] = rtype
        normalized["status"] = status
        normalized.pop("requirements", None)
        resource = ExecutionResource.from_dict(normalized)
        resource.requirements = requirements
        return resource

    def _assemble(self, report: ExecutionResourceReport) -> dict[str, Any]:
        # Duplicate resource detection: same
        # (context_id, environment_id, capability_id, resource_type).
        # Keep first.
        seen: set[tuple[str, str, str, str]] = set()
        deduped: list[ExecutionResource] = []
        duplicates = 0
        for r in sorted(report.resources, key=self._resource_sort_key):
            key = (
                r.context_id,
                r.environment_id,
                r.capability_id,
                r.resource_type,
            )
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            deduped.append(r)
        report.resources = deduped
        report.duplicate_resource_count = duplicates

        resource_type_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        requirement_count = 0
        for r in report.resources:
            resource_type_counts[r.resource_type] = (
                resource_type_counts.get(r.resource_type, 0) + 1
            )
            status_counts[r.status] = status_counts.get(r.status, 0) + 1
            requirement_count += len(r.requirements)

        report.resource_type_counts = {
            k: resource_type_counts[k] for k in sorted(resource_type_counts)
        }
        report.status_counts = {
            k: status_counts[k] for k in sorted(status_counts)
        }
        report.unavailable_count = status_counts.get(
            ExecutionResourceStatus.UNAVAILABLE.value, 0
        )
        report.degraded_count = status_counts.get(
            ExecutionResourceStatus.DEGRADED.value, 0
        )
        report.requirement_count = requirement_count
        report.resource_count = len(report.resources)

        return report.to_dict()

    # ------------------------------------------------------------------
    # Create / Append (append-only)
    # ------------------------------------------------------------------

    def create(
        self,
        resources: list[dict[str, Any]] | None = None,
        raw_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new execution resource report."""
        report = ExecutionResourceReport(
            raw_metadata=dict(raw_metadata or {}),
        )
        report.resources = [
            self._build_resource(r) for r in (resources or [])
        ]
        assembled = self._assemble(report)
        self._persist(assembled)
        self._write_evidence(assembled)
        return assembled

    def append(
        self,
        report_id: str,
        resources: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Append execution resources to an existing report (append-only)."""
        self._validate_id_segment(report_id, "report_id")
        existing = self._load_report(report_id)
        if existing is None:
            raise ValueError(f"Report not found: {report_id}")

        report = ExecutionResourceReport(
            report_id=existing["report_id"],
            created_at=existing.get("created_at", ""),
            raw_metadata=dict(existing.get("raw_metadata", {})),
            schema_version=existing.get("schema_version", SCHEMA_VERSION),
        )
        report.resources = [
            ExecutionResource.from_dict(r)
            for r in existing.get("resources", [])
        ]
        report.resources.extend(
            self._build_resource(r) for r in (resources or [])
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
            "resources": report.get("resources", []),
            "raw_metadata": report.get("raw_metadata", {}),
        }
        (evidence_dir / "execution_resource_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_resource_result.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_resource_summary.md").write_text(
            self._generate_export_md(report), encoding="utf-8"
        )

        resource_count = report.get("resource_count", 0)
        unavailable_count = report.get("unavailable_count", 0)
        degraded_count = report.get("degraded_count", 0)
        requirement_count = report.get("requirement_count", 0)
        duplicate_resource_count = report.get("duplicate_resource_count", 0)
        evidence = ExecutionResourceEvidence(
            report_id=report["report_id"],
            summary=(
                f"{resource_count} resource(s), "
                f"{unavailable_count} unavailable, "
                f"{degraded_count} degraded, "
                f"{requirement_count} requirement(s), "
                f"{duplicate_resource_count} duplicate(s)"
            ),
        )

        # A report passes when it carries at least one resource and no resource
        # is unavailable or degraded.
        passed = (
            resource_count > 0
            and unavailable_count == 0
            and degraded_count == 0
        )
        pass_fail = {
            "passed": passed,
            "report_id": report["report_id"],
            "evidence_id": evidence.evidence_id,
            "resource_count": resource_count,
            "unavailable_count": unavailable_count,
            "degraded_count": degraded_count,
            "requirement_count": requirement_count,
            "duplicate_resource_count": duplicate_resource_count,
            "status_counts": dict(report.get("status_counts", {})),
            "resource_type_counts": dict(
                report.get("resource_type_counts", {})
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

        lines.append("# Execution Resource Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append(f"- Schema Version: {data.get('schema_version', '')}")
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Resources: {data.get('resource_count', 0)}")
        lines.append(f"- Unavailable: {data.get('unavailable_count', 0)}")
        lines.append(f"- Degraded: {data.get('degraded_count', 0)}")
        lines.append(f"- Requirements: {data.get('requirement_count', 0)}")
        lines.append(
            "- Duplicate Resources: "
            f"{data.get('duplicate_resource_count', 0)}"
        )
        lines.append("")

        status_counts = data.get("status_counts", {})
        lines.append("## Status Counts")
        lines.append("")
        for status in sorted(status_counts):
            lines.append(f"- {status}: {status_counts[status]}")
        lines.append("")

        resource_type_counts = data.get("resource_type_counts", {})
        lines.append("## Resource Type Counts")
        lines.append("")
        for rtype in sorted(resource_type_counts):
            lines.append(f"- {rtype}: {resource_type_counts[rtype]}")
        lines.append("")

        lines.append("## Resources")
        lines.append("")
        for r in data.get("resources", []):
            status = r.get("status", "")
            rtype = r.get("resource_type", "")
            context_id = r.get("context_id", "")
            environment_id = r.get("environment_id", "")
            capability_id = r.get("capability_id", "")
            lines.append(
                f"- [{status}] [{rtype}] context={context_id} "
                f"environment={environment_id} capability={capability_id}"
            )
            for req in r.get("requirements", []):
                rqtype = req.get("requirement_type", "")
                rqvalue = req.get("requirement_value", "")
                lines.append(f"  - [{rqtype}] {rqvalue}")
        lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _generate_export_csv(data: dict[str, Any]) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "record_kind",
                "resource_id",
                "context_id",
                "environment_id",
                "capability_id",
                "resource_type",
                "status",
                "requirement_id",
                "requirement_type",
                "requirement_value",
                "summary",
            ]
        )
        for r in data.get("resources", []):
            writer.writerow(
                [
                    "resource",
                    r.get("resource_id", ""),
                    r.get("context_id", ""),
                    r.get("environment_id", ""),
                    r.get("capability_id", ""),
                    r.get("resource_type", ""),
                    r.get("status", ""),
                    "",
                    "",
                    "",
                    r.get("summary", ""),
                ]
            )
            for req in r.get("requirements", []):
                writer.writerow(
                    [
                        "requirement",
                        r.get("resource_id", ""),
                        "",
                        "",
                        "",
                        "",
                        "",
                        req.get("requirement_id", ""),
                        req.get("requirement_type", ""),
                        req.get("requirement_value", ""),
                        req.get("summary", ""),
                    ]
                )
        return buf.getvalue()
