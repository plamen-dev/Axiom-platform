"""Execution Constraint Framework v1.

The execution-constraint layer continues the autonomous engineering roadmap on
top of the Execution Context Framework, the Execution Environment Framework, the
Execution Resource Framework, and the Capability Knowledge Graph. Where the
Execution Context layer represents the *state in which execution occurs*, the
Execution Environment layer represents the *location where execution is expected
to happen*, and the Execution Resource layer represents the *resources execution
requires*, this layer represents the *limitations, restrictions, and boundaries
execution must obey*: for a given context / environment / resource / capability,
what kind of constraint it is (time, memory, storage, security, network,
tooling, version, policy, dependency, ...), how severe it is (info, warning,
error, critical), and which upstream objects it references.

Per report it captures a deterministic, append-only set of execution
constraints, aggregated with constraint-type counts, severity counts,
critical- and error-constraint detection, and duplicate-constraint detection,
with preserved raw payloads and schema versioning.

It is deliberately *observational and declarative only*. Non-goals: no
constraint enforcement, no orchestration, no scheduling, no optimization, no
worker assignment, no autonomous execution, no network calls, no architecture
changes. The upstream context / environment / resource / graph layers are
consumed read-only; nothing is mutated.
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


class ExecutionConstraintType(str, Enum):
    TIME = "TIME"
    MEMORY = "MEMORY"
    STORAGE = "STORAGE"
    SECURITY = "SECURITY"
    NETWORK = "NETWORK"
    TOOLING = "TOOLING"
    VERSION = "VERSION"
    POLICY = "POLICY"
    DEPENDENCY = "DEPENDENCY"
    OTHER = "OTHER"


class ExecutionConstraintSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ExecutionConstraintReferenceType(str, Enum):
    CAPABILITY = "CAPABILITY"
    CONTEXT = "CONTEXT"
    ENVIRONMENT = "ENVIRONMENT"
    RESOURCE = "RESOURCE"
    FILE = "FILE"
    VALIDATION = "VALIDATION"
    ARTIFACT = "ARTIFACT"
    POLICY = "POLICY"
    OTHER = "OTHER"


_VALID_CONSTRAINT_TYPES = {t.value for t in ExecutionConstraintType}
_VALID_SEVERITIES = {t.value for t in ExecutionConstraintSeverity}
_VALID_REFERENCE_TYPES = {t.value for t in ExecutionConstraintReferenceType}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class ExecutionConstraintReference:
    """A single reference from an execution constraint to an upstream object."""

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
    def from_dict(cls, data: dict[str, Any]) -> ExecutionConstraintReference:
        return cls(
            reference_id=data.get("reference_id", ""),
            reference_type=data.get("reference_type", ""),
            reference_value=data.get("reference_value", ""),
            summary=data.get("summary", ""),
        )


@dataclass
class ExecutionConstraint:
    """A single execution constraint."""

    constraint_id: str = ""
    context_id: str = ""
    environment_id: str = ""
    resource_id: str = ""
    capability_id: str = ""
    constraint_type: str = ""
    severity: str = ""
    references: list[ExecutionConstraintReference] = field(
        default_factory=list
    )
    summary: str = ""
    created_at: str = ""
    schema_version: str = SCHEMA_VERSION
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.constraint_id:
            self.constraint_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "context_id": self.context_id,
            "environment_id": self.environment_id,
            "resource_id": self.resource_id,
            "capability_id": self.capability_id,
            "constraint_type": self.constraint_type,
            "severity": self.severity,
            "references": [r.to_dict() for r in self.references],
            "summary": self.summary,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "raw_payload": dict(self.raw_payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionConstraint:
        return cls(
            constraint_id=data.get("constraint_id", ""),
            context_id=data.get("context_id", ""),
            environment_id=data.get("environment_id", ""),
            resource_id=data.get("resource_id", ""),
            capability_id=data.get("capability_id", ""),
            constraint_type=data.get("constraint_type", ""),
            severity=data.get("severity", ""),
            references=[
                ExecutionConstraintReference.from_dict(r)
                for r in data.get("references", [])
            ],
            summary=data.get("summary", ""),
            created_at=data.get("created_at", ""),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            raw_payload=dict(data.get("raw_payload", {})),
        )


@dataclass
class ExecutionConstraintReport:
    """A deterministic, append-only execution constraint report."""

    report_id: str = ""
    constraints: list[ExecutionConstraint] = field(default_factory=list)
    constraint_count: int = 0
    constraint_type_counts: dict[str, int] = field(default_factory=dict)
    severity_counts: dict[str, int] = field(default_factory=dict)
    critical_count: int = 0
    error_count: int = 0
    duplicate_constraint_count: int = 0
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
            "constraints": [c.to_dict() for c in self.constraints],
            "constraint_count": self.constraint_count,
            "constraint_type_counts": dict(self.constraint_type_counts),
            "severity_counts": dict(self.severity_counts),
            "critical_count": self.critical_count,
            "error_count": self.error_count,
            "duplicate_constraint_count": self.duplicate_constraint_count,
            "created_at": self.created_at,
            "raw_metadata": dict(self.raw_metadata),
            "schema_version": self.schema_version,
        }


@dataclass
class ExecutionConstraintEvidence:
    """Evidence record for an execution constraint report."""

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


class ExecutionConstraintEngine:
    """Manages execution constraint reports deterministically.

    Execution constraints are validated, deduplicated, ordered deterministically,
    and aggregated with constraint-type counts, severity counts, and
    critical/error detection. Reports are append-only. The upstream context /
    environment / resource / graph layers are *consumed* read-only; nothing is
    mutated.
    """

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "execution_constraint"
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
    def _constraint_sort_key(c: ExecutionConstraint) -> tuple:
        return (
            c.context_id,
            c.environment_id,
            c.resource_id,
            c.capability_id,
            c.constraint_type,
            c.severity,
            c.constraint_id,
        )

    @staticmethod
    def _reference_sort_key(r: ExecutionConstraintReference) -> tuple:
        return (r.reference_type, r.reference_value, r.reference_id)

    # ------------------------------------------------------------------
    # Building / validation
    # ------------------------------------------------------------------

    @classmethod
    def _build_reference(
        cls, data: dict[str, Any]
    ) -> ExecutionConstraintReference:
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
        return ExecutionConstraintReference.from_dict(normalized)

    @classmethod
    def _build_constraint(cls, data: dict[str, Any]) -> ExecutionConstraint:
        context_id = data.get("context_id", "")
        if not context_id or not str(context_id).strip():
            raise ValueError(
                "context_id is required for an execution constraint"
            )
        environment_id = data.get("environment_id", "")
        if not environment_id or not str(environment_id).strip():
            raise ValueError(
                "environment_id is required for an execution constraint"
            )
        resource_id = data.get("resource_id", "")
        if not resource_id or not str(resource_id).strip():
            raise ValueError(
                "resource_id is required for an execution constraint"
            )
        capability_id = data.get("capability_id", "")
        if not capability_id or not str(capability_id).strip():
            raise ValueError(
                "capability_id is required for an execution constraint"
            )

        ctype_raw = data.get("constraint_type", "")
        if not ctype_raw or not str(ctype_raw).strip():
            raise ValueError(
                "constraint_type is required for an execution constraint"
            )
        ctype = str(ctype_raw).strip().upper()
        if ctype not in _VALID_CONSTRAINT_TYPES:
            raise ValueError(
                f"Invalid constraint_type: {ctype_raw!r}. "
                f"Valid: {sorted(_VALID_CONSTRAINT_TYPES)}"
            )

        severity_raw = data.get("severity", "")
        if not severity_raw or not str(severity_raw).strip():
            raise ValueError(
                "severity is required for an execution constraint"
            )
        severity = str(severity_raw).strip().upper()
        if severity not in _VALID_SEVERITIES:
            raise ValueError(
                f"Invalid severity: {severity_raw!r}. "
                f"Valid: {sorted(_VALID_SEVERITIES)}"
            )

        references = sorted(
            (cls._build_reference(r) for r in data.get("references", [])),
            key=cls._reference_sort_key,
        )

        normalized = dict(data)
        normalized["context_id"] = str(context_id)
        normalized["environment_id"] = str(environment_id)
        normalized["resource_id"] = str(resource_id)
        normalized["capability_id"] = str(capability_id)
        normalized["constraint_type"] = ctype
        normalized["severity"] = severity
        normalized.pop("references", None)
        constraint = ExecutionConstraint.from_dict(normalized)
        constraint.references = references
        return constraint

    def _assemble(self, report: ExecutionConstraintReport) -> dict[str, Any]:
        # Duplicate constraint detection: same
        # (context_id, environment_id, resource_id, capability_id,
        # constraint_type). Keep first.
        seen: set[tuple[str, str, str, str, str]] = set()
        deduped: list[ExecutionConstraint] = []
        duplicates = 0
        for c in sorted(report.constraints, key=self._constraint_sort_key):
            key = (
                c.context_id,
                c.environment_id,
                c.resource_id,
                c.capability_id,
                c.constraint_type,
            )
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            deduped.append(c)
        report.constraints = deduped
        report.duplicate_constraint_count = duplicates

        constraint_type_counts: dict[str, int] = {}
        severity_counts: dict[str, int] = {}
        for c in report.constraints:
            constraint_type_counts[c.constraint_type] = (
                constraint_type_counts.get(c.constraint_type, 0) + 1
            )
            severity_counts[c.severity] = (
                severity_counts.get(c.severity, 0) + 1
            )

        report.constraint_type_counts = {
            k: constraint_type_counts[k]
            for k in sorted(constraint_type_counts)
        }
        report.severity_counts = {
            k: severity_counts[k] for k in sorted(severity_counts)
        }
        report.critical_count = severity_counts.get(
            ExecutionConstraintSeverity.CRITICAL.value, 0
        )
        report.error_count = severity_counts.get(
            ExecutionConstraintSeverity.ERROR.value, 0
        )
        report.constraint_count = len(report.constraints)

        return report.to_dict()

    # ------------------------------------------------------------------
    # Create / Append (append-only)
    # ------------------------------------------------------------------

    def create(
        self,
        constraints: list[dict[str, Any]] | None = None,
        raw_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new execution constraint report."""
        report = ExecutionConstraintReport(
            raw_metadata=dict(raw_metadata or {}),
        )
        report.constraints = [
            self._build_constraint(c) for c in (constraints or [])
        ]
        assembled = self._assemble(report)
        self._persist(assembled)
        self._write_evidence(assembled)
        return assembled

    def append(
        self,
        report_id: str,
        constraints: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Append execution constraints to an existing report (append-only)."""
        self._validate_id_segment(report_id, "report_id")
        existing = self._load_report(report_id)
        if existing is None:
            raise ValueError(f"Report not found: {report_id}")

        report = ExecutionConstraintReport(
            report_id=existing["report_id"],
            created_at=existing.get("created_at", ""),
            raw_metadata=dict(existing.get("raw_metadata", {})),
            schema_version=existing.get("schema_version", SCHEMA_VERSION),
        )
        report.constraints = [
            ExecutionConstraint.from_dict(c)
            for c in existing.get("constraints", [])
        ]
        report.constraints.extend(
            self._build_constraint(c) for c in (constraints or [])
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
            "constraints": report.get("constraints", []),
            "raw_metadata": report.get("raw_metadata", {}),
        }
        (evidence_dir / "execution_constraint_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_constraint_result.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_constraint_summary.md").write_text(
            self._generate_export_md(report), encoding="utf-8"
        )

        constraint_count = report.get("constraint_count", 0)
        critical_count = report.get("critical_count", 0)
        error_count = report.get("error_count", 0)
        duplicate_constraint_count = report.get(
            "duplicate_constraint_count", 0
        )
        evidence = ExecutionConstraintEvidence(
            report_id=report["report_id"],
            summary=(
                f"{constraint_count} constraint(s), "
                f"{critical_count} critical, "
                f"{error_count} error, "
                f"{duplicate_constraint_count} duplicate(s)"
            ),
        )

        # A report passes when it carries at least one constraint and no
        # constraint is critical or error severity.
        passed = (
            constraint_count > 0
            and critical_count == 0
            and error_count == 0
        )
        pass_fail = {
            "passed": passed,
            "report_id": report["report_id"],
            "evidence_id": evidence.evidence_id,
            "constraint_count": constraint_count,
            "critical_count": critical_count,
            "error_count": error_count,
            "duplicate_constraint_count": duplicate_constraint_count,
            "severity_counts": dict(report.get("severity_counts", {})),
            "constraint_type_counts": dict(
                report.get("constraint_type_counts", {})
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

        lines.append("# Execution Constraint Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append(f"- Schema Version: {data.get('schema_version', '')}")
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Constraints: {data.get('constraint_count', 0)}")
        lines.append(f"- Critical: {data.get('critical_count', 0)}")
        lines.append(f"- Error: {data.get('error_count', 0)}")
        lines.append(
            "- Duplicate Constraints: "
            f"{data.get('duplicate_constraint_count', 0)}"
        )
        lines.append("")

        severity_counts = data.get("severity_counts", {})
        lines.append("## Severity Counts")
        lines.append("")
        for severity in sorted(severity_counts):
            lines.append(f"- {severity}: {severity_counts[severity]}")
        lines.append("")

        constraint_type_counts = data.get("constraint_type_counts", {})
        lines.append("## Constraint Type Counts")
        lines.append("")
        for ctype in sorted(constraint_type_counts):
            lines.append(f"- {ctype}: {constraint_type_counts[ctype]}")
        lines.append("")

        lines.append("## Constraints")
        lines.append("")
        for c in data.get("constraints", []):
            severity = c.get("severity", "")
            ctype = c.get("constraint_type", "")
            context_id = c.get("context_id", "")
            environment_id = c.get("environment_id", "")
            resource_id = c.get("resource_id", "")
            capability_id = c.get("capability_id", "")
            lines.append(
                f"- [{severity}] [{ctype}] context={context_id} "
                f"environment={environment_id} resource={resource_id} "
                f"capability={capability_id}"
            )
            for ref in c.get("references", []):
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
                "constraint_id",
                "context_id",
                "environment_id",
                "resource_id",
                "capability_id",
                "constraint_type",
                "severity",
                "reference_id",
                "reference_type",
                "reference_value",
                "summary",
            ]
        )
        for c in data.get("constraints", []):
            writer.writerow(
                [
                    "constraint",
                    c.get("constraint_id", ""),
                    c.get("context_id", ""),
                    c.get("environment_id", ""),
                    c.get("resource_id", ""),
                    c.get("capability_id", ""),
                    c.get("constraint_type", ""),
                    c.get("severity", ""),
                    "",
                    "",
                    "",
                    c.get("summary", ""),
                ]
            )
            for ref in c.get("references", []):
                writer.writerow(
                    [
                        "reference",
                        c.get("constraint_id", ""),
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
