"""Capability Validation Knowledge Framework v1.

The validation knowledge layer. Where the Global Capability Registry establishes
identity, the Capability File Knowledge Framework establishes location, and the
Capability Impact Framework establishes meaning, this layer establishes
*validation history*: how a capability has been validated, tested, reviewed, and
verified.

Per capability it captures a deterministic, append-only set of validation
records plus their findings and artifacts, aggregated with finding counts and
unresolved-finding detection, with preserved raw payloads and schema
versioning. Validation history becomes a first-class capability object.

It is deliberately *structure only*. Non-goals: no automatic test execution, no
CI integration, no orchestration, no graph engine, no dashboards, no network
calls. The registry/relationship/file-knowledge/session-import layers are
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


class CapabilityValidationType(str, Enum):
    PYTEST = "PYTEST"
    RUFF = "RUFF"
    CI = "CI"
    DEVIN_REVIEW = "DEVIN_REVIEW"
    CLI_TEST = "CLI_TEST"
    MANUAL_TEST = "MANUAL_TEST"
    INTEGRATION_TEST = "INTEGRATION_TEST"
    REGRESSION_TEST = "REGRESSION_TEST"


class CapabilityValidationStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    WARNING = "WARNING"


class CapabilityValidationFindingSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


_VALID_VALIDATION_TYPES = {t.value for t in CapabilityValidationType}
_VALID_VALIDATION_STATUSES = {s.value for s in CapabilityValidationStatus}
_VALID_SEVERITIES = {s.value for s in CapabilityValidationFindingSeverity}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class CapabilityValidationRecord:
    """A single validation of a capability."""

    validation_id: str = ""
    capability_id: str = ""
    validation_type: str = ""
    validation_status: str = ""
    validator: str = ""
    summary: str = ""
    created_at: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.validation_id:
            self.validation_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "validation_id": self.validation_id,
            "capability_id": self.capability_id,
            "validation_type": self.validation_type,
            "validation_status": self.validation_status,
            "validator": self.validator,
            "summary": self.summary,
            "created_at": self.created_at,
            "raw_payload": dict(self.raw_payload),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityValidationRecord:
        return cls(
            validation_id=data.get("validation_id", ""),
            capability_id=data.get("capability_id", ""),
            validation_type=data.get("validation_type", ""),
            validation_status=data.get("validation_status", ""),
            validator=data.get("validator", ""),
            summary=data.get("summary", ""),
            created_at=data.get("created_at", ""),
            raw_payload=dict(data.get("raw_payload", {})),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )


@dataclass
class CapabilityValidationFinding:
    """A finding raised by a validation."""

    finding_id: str = ""
    validation_id: str = ""
    severity: str = ""
    summary: str = ""
    resolved: bool = False
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.finding_id:
            self.finding_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "validation_id": self.validation_id,
            "severity": self.severity,
            "summary": self.summary,
            "resolved": self.resolved,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityValidationFinding:
        return cls(
            finding_id=data.get("finding_id", ""),
            validation_id=data.get("validation_id", ""),
            severity=data.get("severity", ""),
            summary=data.get("summary", ""),
            resolved=bool(data.get("resolved", False)),
            created_at=data.get("created_at", ""),
        )


@dataclass
class CapabilityValidationArtifact:
    """An artifact produced by a validation."""

    artifact_id: str = ""
    validation_id: str = ""
    artifact_path: str = ""
    summary: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.artifact_id:
            self.artifact_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "validation_id": self.validation_id,
            "artifact_path": self.artifact_path,
            "summary": self.summary,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityValidationArtifact:
        return cls(
            artifact_id=data.get("artifact_id", ""),
            validation_id=data.get("validation_id", ""),
            artifact_path=data.get("artifact_path", ""),
            summary=data.get("summary", ""),
            created_at=data.get("created_at", ""),
        )


@dataclass
class CapabilityValidationKnowledge:
    """Per-capability aggregate of validation records and findings."""

    knowledge_id: str = ""
    capability_id: str = ""
    validation_count: int = 0
    finding_count: int = 0
    unresolved_count: int = 0
    validation_type_counts: dict[str, int] = field(default_factory=dict)
    created_at: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.knowledge_id:
            self.knowledge_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "knowledge_id": self.knowledge_id,
            "capability_id": self.capability_id,
            "validation_count": self.validation_count,
            "finding_count": self.finding_count,
            "unresolved_count": self.unresolved_count,
            "validation_type_counts": dict(self.validation_type_counts),
            "created_at": self.created_at,
            "raw_payload": dict(self.raw_payload),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityValidationKnowledge:
        return cls(
            knowledge_id=data.get("knowledge_id", ""),
            capability_id=data.get("capability_id", ""),
            validation_count=data.get("validation_count", 0),
            finding_count=data.get("finding_count", 0),
            unresolved_count=data.get("unresolved_count", 0),
            validation_type_counts=dict(
                data.get("validation_type_counts", {})
            ),
            created_at=data.get("created_at", ""),
            raw_payload=dict(data.get("raw_payload", {})),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )


@dataclass
class CapabilityValidationKnowledgeReport:
    """A deterministic, append-only capability validation knowledge report."""

    report_id: str = ""
    records: list[CapabilityValidationRecord] = field(default_factory=list)
    findings: list[CapabilityValidationFinding] = field(default_factory=list)
    artifacts: list[CapabilityValidationArtifact] = field(default_factory=list)
    knowledge: list[CapabilityValidationKnowledge] = field(
        default_factory=list
    )
    capability_count: int = 0
    validation_count: int = 0
    finding_count: int = 0
    unresolved_count: int = 0
    duplicate_validation_count: int = 0
    validation_type_counts: dict[str, int] = field(default_factory=dict)
    validation_status_counts: dict[str, int] = field(default_factory=dict)
    finding_severity_counts: dict[str, int] = field(default_factory=dict)
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
            "records": [r.to_dict() for r in self.records],
            "findings": [f.to_dict() for f in self.findings],
            "artifacts": [a.to_dict() for a in self.artifacts],
            "knowledge": [k.to_dict() for k in self.knowledge],
            "capability_count": self.capability_count,
            "validation_count": self.validation_count,
            "finding_count": self.finding_count,
            "unresolved_count": self.unresolved_count,
            "duplicate_validation_count": self.duplicate_validation_count,
            "validation_type_counts": dict(self.validation_type_counts),
            "validation_status_counts": dict(self.validation_status_counts),
            "finding_severity_counts": dict(self.finding_severity_counts),
            "created_at": self.created_at,
            "raw_metadata": dict(self.raw_metadata),
            "schema_version": self.schema_version,
        }


@dataclass
class CapabilityValidationKnowledgeEvidence:
    """Evidence record for a capability validation knowledge report."""

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


class CapabilityValidationKnowledgeEngine:
    """Manages capability validation knowledge reports deterministically.

    Validation records are validated, deduplicated, ordered deterministically,
    and aggregated per capability with finding and unresolved-finding
    aggregation. Reports are append-only. The registry/relationship/
    file-knowledge/import layers are *consumed* read-only; nothing is mutated.
    """

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = (
            self._artifacts_root / "capability_validation_knowledge"
        )
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
    def _record_sort_key(r: CapabilityValidationRecord) -> tuple:
        return (
            r.capability_id,
            r.validation_type,
            r.validation_status,
            r.validator,
            r.validation_id,
        )

    @staticmethod
    def _finding_sort_key(f: CapabilityValidationFinding) -> tuple:
        return (f.validation_id, f.severity, f.finding_id)

    @staticmethod
    def _artifact_sort_key(a: CapabilityValidationArtifact) -> tuple:
        return (a.validation_id, a.artifact_path, a.artifact_id)

    @staticmethod
    def _knowledge_sort_key(k: CapabilityValidationKnowledge) -> tuple:
        return (k.capability_id, k.knowledge_id)

    # ------------------------------------------------------------------
    # Building / validation
    # ------------------------------------------------------------------

    @staticmethod
    def _build_record(data: dict[str, Any]) -> CapabilityValidationRecord:
        capability_id = data.get("capability_id", "")
        if not capability_id or not str(capability_id).strip():
            raise ValueError("capability_id is required for a validation")

        vtype_raw = data.get("validation_type", "")
        if not vtype_raw or not str(vtype_raw).strip():
            raise ValueError("validation_type is required for a validation")
        vtype = str(vtype_raw).strip().upper()
        if vtype not in _VALID_VALIDATION_TYPES:
            raise ValueError(
                f"Invalid validation_type: {vtype_raw!r}. "
                f"Valid: {sorted(_VALID_VALIDATION_TYPES)}"
            )

        vstatus_raw = data.get("validation_status", "")
        if not vstatus_raw or not str(vstatus_raw).strip():
            raise ValueError("validation_status is required for a validation")
        vstatus = str(vstatus_raw).strip().upper()
        if vstatus not in _VALID_VALIDATION_STATUSES:
            raise ValueError(
                f"Invalid validation_status: {vstatus_raw!r}. "
                f"Valid: {sorted(_VALID_VALIDATION_STATUSES)}"
            )

        normalized = dict(data)
        normalized["capability_id"] = str(capability_id)
        normalized["validation_type"] = vtype
        normalized["validation_status"] = vstatus
        return CapabilityValidationRecord.from_dict(normalized)

    @staticmethod
    def _build_finding(data: dict[str, Any]) -> CapabilityValidationFinding:
        validation_id = data.get("validation_id", "")
        if not validation_id or not str(validation_id).strip():
            raise ValueError("validation_id is required for a finding")

        severity_raw = data.get("severity", "")
        if not severity_raw or not str(severity_raw).strip():
            raise ValueError("severity is required for a finding")
        severity = str(severity_raw).strip().upper()
        if severity not in _VALID_SEVERITIES:
            raise ValueError(
                f"Invalid severity: {severity_raw!r}. "
                f"Valid: {sorted(_VALID_SEVERITIES)}"
            )

        normalized = dict(data)
        normalized["validation_id"] = str(validation_id)
        normalized["severity"] = severity
        return CapabilityValidationFinding.from_dict(normalized)

    @staticmethod
    def _build_artifact(data: dict[str, Any]) -> CapabilityValidationArtifact:
        validation_id = data.get("validation_id", "")
        if not validation_id or not str(validation_id).strip():
            raise ValueError("validation_id is required for an artifact")
        artifact_path = data.get("artifact_path", "")
        if not artifact_path or not str(artifact_path).strip():
            raise ValueError("artifact_path is required for an artifact")
        normalized = dict(data)
        normalized["validation_id"] = str(validation_id)
        normalized["artifact_path"] = str(artifact_path)
        return CapabilityValidationArtifact.from_dict(normalized)

    def _assemble(
        self,
        report: CapabilityValidationKnowledgeReport,
        knowledge_payloads: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        knowledge_payloads = knowledge_payloads or {}

        # Duplicate validation detection: same
        # (capability_id, validation_type, validation_status, validator).
        # Keep first; count duplicates; drop the rest.
        seen: set[tuple[str, str, str, str]] = set()
        deduped: list[CapabilityValidationRecord] = []
        duplicate_count = 0
        for r in sorted(report.records, key=self._record_sort_key):
            key = (
                r.capability_id,
                r.validation_type,
                r.validation_status,
                r.validator,
            )
            if key in seen:
                duplicate_count += 1
                continue
            seen.add(key)
            deduped.append(r)
        report.records = deduped
        report.duplicate_validation_count = duplicate_count

        report.findings = sorted(
            report.findings, key=self._finding_sort_key
        )
        report.artifacts = sorted(
            report.artifacts, key=self._artifact_sort_key
        )

        # Map each surviving validation_id to its capability.
        validation_to_cap: dict[str, str] = {
            r.validation_id: r.capability_id for r in report.records
        }

        # Per-capability aggregation.
        capabilities = sorted({r.capability_id for r in report.records})
        knowledge: list[CapabilityValidationKnowledge] = []
        for cap in capabilities:
            cap_records = [
                r for r in report.records if r.capability_id == cap
            ]
            cap_findings = [
                f
                for f in report.findings
                if validation_to_cap.get(f.validation_id) == cap
            ]
            cap_unresolved = [f for f in cap_findings if not f.resolved]
            cap_type_counts: dict[str, int] = {}
            for r in cap_records:
                cap_type_counts[r.validation_type] = (
                    cap_type_counts.get(r.validation_type, 0) + 1
                )
            knowledge.append(
                CapabilityValidationKnowledge(
                    capability_id=cap,
                    validation_count=len(cap_records),
                    finding_count=len(cap_findings),
                    unresolved_count=len(cap_unresolved),
                    validation_type_counts={
                        k: cap_type_counts[k] for k in sorted(cap_type_counts)
                    },
                    raw_payload=dict(knowledge_payloads.get(cap, {})),
                )
            )
        report.knowledge = sorted(knowledge, key=self._knowledge_sort_key)

        type_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        for r in report.records:
            type_counts[r.validation_type] = (
                type_counts.get(r.validation_type, 0) + 1
            )
            status_counts[r.validation_status] = (
                status_counts.get(r.validation_status, 0) + 1
            )
        severity_counts: dict[str, int] = {}
        for f in report.findings:
            severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1

        report.validation_type_counts = {
            k: type_counts[k] for k in sorted(type_counts)
        }
        report.validation_status_counts = {
            k: status_counts[k] for k in sorted(status_counts)
        }
        report.finding_severity_counts = {
            k: severity_counts[k] for k in sorted(severity_counts)
        }

        report.capability_count = len(capabilities)
        report.validation_count = len(report.records)
        report.finding_count = len(report.findings)
        report.unresolved_count = sum(
            1 for f in report.findings if not f.resolved
        )

        return report.to_dict()

    # ------------------------------------------------------------------
    # Create / Append (append-only)
    # ------------------------------------------------------------------

    def create(
        self,
        validation_records: list[dict[str, Any]] | None = None,
        validation_findings: list[dict[str, Any]] | None = None,
        validation_artifacts: list[dict[str, Any]] | None = None,
        knowledge_payloads: dict[str, dict[str, Any]] | None = None,
        raw_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new capability validation knowledge report."""
        report = CapabilityValidationKnowledgeReport(
            raw_metadata=dict(raw_metadata or {}),
        )
        report.records = [
            self._build_record(r) for r in (validation_records or [])
        ]
        report.findings = [
            self._build_finding(f) for f in (validation_findings or [])
        ]
        report.artifacts = [
            self._build_artifact(a) for a in (validation_artifacts or [])
        ]
        assembled = self._assemble(report, knowledge_payloads)
        self._persist(assembled)
        self._write_evidence(assembled)
        return assembled

    def append(
        self,
        report_id: str,
        validation_records: list[dict[str, Any]] | None = None,
        validation_findings: list[dict[str, Any]] | None = None,
        validation_artifacts: list[dict[str, Any]] | None = None,
        knowledge_payloads: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Append records/findings/artifacts to a report (append-only)."""
        self._validate_id_segment(report_id, "report_id")
        existing = self._load_report(report_id)
        if existing is None:
            raise ValueError(f"Report not found: {report_id}")

        report = CapabilityValidationKnowledgeReport(
            report_id=existing["report_id"],
            created_at=existing.get("created_at", ""),
            raw_metadata=dict(existing.get("raw_metadata", {})),
            schema_version=existing.get("schema_version", SCHEMA_VERSION),
        )
        report.records = [
            CapabilityValidationRecord.from_dict(r)
            for r in existing.get("records", [])
        ]
        report.records.extend(
            self._build_record(r) for r in (validation_records or [])
        )
        report.findings = [
            CapabilityValidationFinding.from_dict(f)
            for f in existing.get("findings", [])
        ]
        report.findings.extend(
            self._build_finding(f) for f in (validation_findings or [])
        )
        report.artifacts = [
            CapabilityValidationArtifact.from_dict(a)
            for a in existing.get("artifacts", [])
        ]
        report.artifacts.extend(
            self._build_artifact(a) for a in (validation_artifacts or [])
        )

        merged_payloads: dict[str, dict[str, Any]] = {
            k.get("capability_id", ""): dict(k.get("raw_payload", {}))
            for k in existing.get("knowledge", [])
            if k.get("raw_payload")
        }
        merged_payloads.update(knowledge_payloads or {})

        assembled = self._assemble(report, merged_payloads)
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
            "records": report.get("records", []),
            "findings": report.get("findings", []),
            "artifacts": report.get("artifacts", []),
            "raw_metadata": report.get("raw_metadata", {}),
        }
        (evidence_dir / "capability_validation_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "capability_validation_result.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "capability_validation_summary.md").write_text(
            self._generate_export_md(report), encoding="utf-8"
        )

        validation_count = report.get("validation_count", 0)
        finding_count = report.get("finding_count", 0)
        unresolved_count = report.get("unresolved_count", 0)
        duplicate_count = report.get("duplicate_validation_count", 0)
        evidence = CapabilityValidationKnowledgeEvidence(
            report_id=report["report_id"],
            summary=(
                f"{validation_count} validation(s), "
                f"{finding_count} finding(s), "
                f"{unresolved_count} unresolved, "
                f"{duplicate_count} duplicate(s)"
            ),
        )

        # A report passes when it carries at least one validation, no duplicate
        # validations were detected, and no findings remain unresolved.
        passed = (
            validation_count > 0
            and duplicate_count == 0
            and unresolved_count == 0
        )
        pass_fail = {
            "passed": passed,
            "report_id": report["report_id"],
            "evidence_id": evidence.evidence_id,
            "capability_count": report.get("capability_count", 0),
            "validation_count": validation_count,
            "finding_count": finding_count,
            "unresolved_count": unresolved_count,
            "duplicate_validation_count": duplicate_count,
            "validation_type_counts": dict(
                report.get("validation_type_counts", {})
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

        lines.append("# Capability Validation Knowledge Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append(f"- Schema Version: {data.get('schema_version', '')}")
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Capabilities: {data.get('capability_count', 0)}")
        lines.append(f"- Validations: {data.get('validation_count', 0)}")
        lines.append(f"- Findings: {data.get('finding_count', 0)}")
        lines.append(f"- Unresolved: {data.get('unresolved_count', 0)}")
        lines.append(
            f"- Duplicate Validations: "
            f"{data.get('duplicate_validation_count', 0)}"
        )
        lines.append("")

        type_counts = data.get("validation_type_counts", {})
        lines.append("## Validation Type Counts")
        lines.append("")
        for vtype in sorted(type_counts):
            lines.append(f"- {vtype}: {type_counts[vtype]}")
        lines.append("")

        status_counts = data.get("validation_status_counts", {})
        lines.append("## Validation Status Counts")
        lines.append("")
        for status in sorted(status_counts):
            lines.append(f"- {status}: {status_counts[status]}")
        lines.append("")

        severity_counts = data.get("finding_severity_counts", {})
        lines.append("## Finding Severity Counts")
        lines.append("")
        for severity in sorted(severity_counts):
            lines.append(f"- {severity}: {severity_counts[severity]}")
        lines.append("")

        lines.append("## Validations")
        lines.append("")
        for r in data.get("records", []):
            cap = r.get("capability_id", "")
            vtype = r.get("validation_type", "")
            vstatus = r.get("validation_status", "")
            validator = r.get("validator", "")
            summary = r.get("summary", "")
            lines.append(
                f"- [{cap}] [{vtype}] [{vstatus}] {validator} {summary}"
            )
        lines.append("")

        lines.append("## Findings")
        lines.append("")
        for f in data.get("findings", []):
            severity = f.get("severity", "")
            resolved = "resolved" if f.get("resolved") else "unresolved"
            summary = f.get("summary", "")
            lines.append(f"- [{severity}] [{resolved}] {summary}")
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
                "validation_id",
                "validation_type",
                "validation_status",
                "validator",
                "severity",
                "resolved",
                "summary",
            ]
        )
        for r in data.get("records", []):
            writer.writerow(
                [
                    "validation",
                    r.get("capability_id", ""),
                    r.get("validation_id", ""),
                    r.get("validation_type", ""),
                    r.get("validation_status", ""),
                    r.get("validator", ""),
                    "",
                    "",
                    r.get("summary", ""),
                ]
            )
        for f in data.get("findings", []):
            writer.writerow(
                [
                    "finding",
                    "",
                    f.get("validation_id", ""),
                    "",
                    "",
                    "",
                    f.get("severity", ""),
                    f.get("resolved", False),
                    f.get("summary", ""),
                ]
            )
        for a in data.get("artifacts", []):
            writer.writerow(
                [
                    "artifact",
                    "",
                    a.get("validation_id", ""),
                    "",
                    "",
                    "",
                    "",
                    "",
                    a.get("summary", ""),
                ]
            )
        return buf.getvalue()
