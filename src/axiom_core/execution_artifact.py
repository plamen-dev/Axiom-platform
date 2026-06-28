"""Execution Artifact Framework v1.

The execution-artifact layer continues the autonomous engineering roadmap on top
of the Execution Result Framework, the Execution Attempt Framework v2, and the
Capability Knowledge Graph. Where the Execution Result layer represents *what an
attempt produced*, this layer represents *the artifacts produced or referenced
by those results*: for a given result / attempt / capability, what type of
artifact it is (file, report, log, screenshot, recording, evidence_bundle,
test_output, pr_comment, other), what status it reached (created, referenced,
missing, invalid, unknown), where it lives (path / url), and which upstream
objects it references.

Per report it captures a deterministic, append-only set of execution artifacts,
ordered deterministically, aggregated with status counts, artifact-type counts,
missing-/invalid-/created-/referenced detection, and duplicate-artifact
detection, with preserved raw payloads and schema versioning.

It is deliberately *observational and declarative only*. Non-goals: no artifact
generation, no file scanning, no artifact uploading, no actual execution, no
orchestration, no scheduling, no optimization, no worker assignment, no
autonomous behavior, no network calls, no architecture changes. The upstream
result / attempt / graph layers are consumed read-only; nothing is mutated.
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

from axiom_core.artifact_paths import is_within_sandbox

SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ExecutionArtifactType(str, Enum):
    FILE = "FILE"
    REPORT = "REPORT"
    LOG = "LOG"
    SCREENSHOT = "SCREENSHOT"
    RECORDING = "RECORDING"
    EVIDENCE_BUNDLE = "EVIDENCE_BUNDLE"
    TEST_OUTPUT = "TEST_OUTPUT"
    PR_COMMENT = "PR_COMMENT"
    OTHER = "OTHER"


class ExecutionArtifactStatus(str, Enum):
    CREATED = "CREATED"
    REFERENCED = "REFERENCED"
    MISSING = "MISSING"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class ExecutionArtifactReferenceType(str, Enum):
    RESULT = "RESULT"
    ATTEMPT = "ATTEMPT"
    CAPABILITY = "CAPABILITY"
    FILE = "FILE"
    URL = "URL"
    VALIDATION = "VALIDATION"
    KNOWLEDGE_NODE = "KNOWLEDGE_NODE"
    OTHER = "OTHER"


_VALID_ARTIFACT_TYPES = {t.value for t in ExecutionArtifactType}
_VALID_STATUSES = {t.value for t in ExecutionArtifactStatus}
_VALID_REFERENCE_TYPES = {t.value for t in ExecutionArtifactReferenceType}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class ExecutionArtifactReference:
    """A single reference from an execution artifact to an upstream object."""

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
    def from_dict(cls, data: dict[str, Any]) -> ExecutionArtifactReference:
        return cls(
            reference_id=data.get("reference_id", ""),
            reference_type=data.get("reference_type", ""),
            reference_value=data.get("reference_value", ""),
            summary=data.get("summary", ""),
        )


@dataclass
class ExecutionArtifact:
    """A single artifact produced or referenced by an execution result."""

    artifact_id: str = ""
    result_id: str = ""
    attempt_id: str = ""
    capability_id: str = ""
    artifact_type: str = ""
    status: str = ""
    artifact_path: str = ""
    artifact_url: str = ""
    references: list[ExecutionArtifactReference] = field(default_factory=list)
    summary: str = ""
    created_at: str = ""
    schema_version: str = SCHEMA_VERSION
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.artifact_id:
            self.artifact_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "result_id": self.result_id,
            "attempt_id": self.attempt_id,
            "capability_id": self.capability_id,
            "artifact_type": self.artifact_type,
            "status": self.status,
            "artifact_path": self.artifact_path,
            "artifact_url": self.artifact_url,
            "references": [r.to_dict() for r in self.references],
            "summary": self.summary,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "raw_payload": dict(self.raw_payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionArtifact:
        return cls(
            artifact_id=data.get("artifact_id", ""),
            result_id=data.get("result_id", ""),
            attempt_id=data.get("attempt_id", ""),
            capability_id=data.get("capability_id", ""),
            artifact_type=data.get("artifact_type", ""),
            status=data.get("status", ""),
            artifact_path=data.get("artifact_path", ""),
            artifact_url=data.get("artifact_url", ""),
            references=[
                ExecutionArtifactReference.from_dict(r)
                for r in data.get("references", [])
            ],
            summary=data.get("summary", ""),
            created_at=data.get("created_at", ""),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            raw_payload=dict(data.get("raw_payload", {})),
        )


@dataclass
class ExecutionArtifactReport:
    """A deterministic, append-only execution artifact report."""

    report_id: str = ""
    artifacts: list[ExecutionArtifact] = field(default_factory=list)
    artifact_count: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    artifact_type_counts: dict[str, int] = field(default_factory=dict)
    missing_count: int = 0
    invalid_count: int = 0
    created_count: int = 0
    referenced_count: int = 0
    duplicate_artifact_count: int = 0
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
            "artifacts": [a.to_dict() for a in self.artifacts],
            "artifact_count": self.artifact_count,
            "status_counts": dict(self.status_counts),
            "artifact_type_counts": dict(self.artifact_type_counts),
            "missing_count": self.missing_count,
            "invalid_count": self.invalid_count,
            "created_count": self.created_count,
            "referenced_count": self.referenced_count,
            "duplicate_artifact_count": self.duplicate_artifact_count,
            "created_at": self.created_at,
            "raw_metadata": dict(self.raw_metadata),
            "schema_version": self.schema_version,
        }


@dataclass
class ExecutionArtifactEvidence:
    """Evidence record for an execution artifact report."""

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


class ExecutionArtifactEngine:
    """Manages execution artifact reports deterministically.

    Execution artifacts are validated, deduplicated, ordered deterministically,
    and aggregated with status counts, artifact-type counts, and
    missing/invalid/created/referenced detection. Reports are append-only. The
    upstream result / attempt / graph layers are *consumed* read-only; nothing
    is mutated. No artifact is generated, scanned, or uploaded.
    """

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "execution_artifact"
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
        if not is_within_sandbox(target, sandbox):
            raise ValueError(
                f"Resolved path escapes artifacts root: {report_id!r}"
            )
        return target

    # ------------------------------------------------------------------
    # Sort keys
    # ------------------------------------------------------------------

    @staticmethod
    def _artifact_sort_key(a: ExecutionArtifact) -> tuple:
        return (
            a.result_id,
            a.attempt_id,
            a.capability_id,
            a.artifact_type,
            a.status,
            a.artifact_id,
        )

    @staticmethod
    def _reference_sort_key(r: ExecutionArtifactReference) -> tuple:
        return (r.reference_type, r.reference_value, r.reference_id)

    # ------------------------------------------------------------------
    # Building / validation
    # ------------------------------------------------------------------

    @classmethod
    def _build_reference(
        cls, data: dict[str, Any]
    ) -> ExecutionArtifactReference:
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
        return ExecutionArtifactReference.from_dict(normalized)

    @classmethod
    def _build_artifact(cls, data: dict[str, Any]) -> ExecutionArtifact:
        result_id = data.get("result_id", "")
        if not result_id or not str(result_id).strip():
            raise ValueError("result_id is required for an execution artifact")
        attempt_id = data.get("attempt_id", "")
        if not attempt_id or not str(attempt_id).strip():
            raise ValueError(
                "attempt_id is required for an execution artifact"
            )
        capability_id = data.get("capability_id", "")
        if not capability_id or not str(capability_id).strip():
            raise ValueError(
                "capability_id is required for an execution artifact"
            )

        artifact_type_raw = data.get("artifact_type", "")
        if not artifact_type_raw or not str(artifact_type_raw).strip():
            raise ValueError(
                "artifact_type is required for an execution artifact"
            )
        artifact_type = str(artifact_type_raw).strip().upper()
        if artifact_type not in _VALID_ARTIFACT_TYPES:
            raise ValueError(
                f"Invalid artifact_type: {artifact_type_raw!r}. "
                f"Valid: {sorted(_VALID_ARTIFACT_TYPES)}"
            )

        status_raw = data.get("status", "")
        if not status_raw or not str(status_raw).strip():
            raise ValueError("status is required for an execution artifact")
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
        normalized["result_id"] = str(result_id)
        normalized["attempt_id"] = str(attempt_id)
        normalized["capability_id"] = str(capability_id)
        normalized["artifact_type"] = artifact_type
        normalized["status"] = status
        normalized["artifact_path"] = str(data.get("artifact_path", "") or "")
        normalized["artifact_url"] = str(data.get("artifact_url", "") or "")
        normalized.pop("references", None)
        artifact = ExecutionArtifact.from_dict(normalized)
        artifact.references = references
        return artifact

    def _assemble(self, report: ExecutionArtifactReport) -> dict[str, Any]:
        # Duplicate artifact detection: same
        # (result_id, attempt_id, capability_id, artifact_type,
        #  artifact_path, artifact_url). Keep first.
        seen: set[tuple[str, str, str, str, str, str]] = set()
        deduped: list[ExecutionArtifact] = []
        duplicates = 0
        for a in sorted(report.artifacts, key=self._artifact_sort_key):
            key = (
                a.result_id,
                a.attempt_id,
                a.capability_id,
                a.artifact_type,
                a.artifact_path,
                a.artifact_url,
            )
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            deduped.append(a)
        report.artifacts = deduped
        report.duplicate_artifact_count = duplicates

        status_counts: dict[str, int] = {}
        artifact_type_counts: dict[str, int] = {}
        for a in report.artifacts:
            status_counts[a.status] = status_counts.get(a.status, 0) + 1
            artifact_type_counts[a.artifact_type] = (
                artifact_type_counts.get(a.artifact_type, 0) + 1
            )

        report.status_counts = {
            k: status_counts[k] for k in sorted(status_counts)
        }
        report.artifact_type_counts = {
            k: artifact_type_counts[k] for k in sorted(artifact_type_counts)
        }
        report.missing_count = status_counts.get(
            ExecutionArtifactStatus.MISSING.value, 0
        )
        report.invalid_count = status_counts.get(
            ExecutionArtifactStatus.INVALID.value, 0
        )
        report.created_count = status_counts.get(
            ExecutionArtifactStatus.CREATED.value, 0
        )
        report.referenced_count = status_counts.get(
            ExecutionArtifactStatus.REFERENCED.value, 0
        )
        report.artifact_count = len(report.artifacts)

        return report.to_dict()

    # ------------------------------------------------------------------
    # Create / Append (append-only)
    # ------------------------------------------------------------------

    def create(
        self,
        artifacts: list[dict[str, Any]] | None = None,
        raw_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new execution artifact report."""
        report = ExecutionArtifactReport(
            raw_metadata=dict(raw_metadata or {}),
        )
        report.artifacts = [
            self._build_artifact(a) for a in (artifacts or [])
        ]
        assembled = self._assemble(report)
        self._persist(assembled)
        self._write_evidence(assembled)
        return assembled

    def append(
        self,
        report_id: str,
        artifacts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Append execution artifacts to an existing report (append-only)."""
        self._validate_id_segment(report_id, "report_id")
        existing = self._load_report(report_id)
        if existing is None:
            raise ValueError(f"Report not found: {report_id}")

        report = ExecutionArtifactReport(
            report_id=existing["report_id"],
            created_at=existing.get("created_at", ""),
            raw_metadata=dict(existing.get("raw_metadata", {})),
            schema_version=existing.get("schema_version", SCHEMA_VERSION),
        )
        report.artifacts = [
            ExecutionArtifact.from_dict(a)
            for a in existing.get("artifacts", [])
        ]
        report.artifacts.extend(
            self._build_artifact(a) for a in (artifacts or [])
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
            "artifacts": report.get("artifacts", []),
            "raw_metadata": report.get("raw_metadata", {}),
        }
        (evidence_dir / "execution_artifact_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_artifact_result.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_artifact_summary.md").write_text(
            self._generate_export_md(report), encoding="utf-8"
        )

        artifact_count = report.get("artifact_count", 0)
        missing_count = report.get("missing_count", 0)
        invalid_count = report.get("invalid_count", 0)
        created_count = report.get("created_count", 0)
        referenced_count = report.get("referenced_count", 0)
        duplicate_artifact_count = report.get("duplicate_artifact_count", 0)
        evidence = ExecutionArtifactEvidence(
            report_id=report["report_id"],
            summary=(
                f"{artifact_count} artifact(s), "
                f"{missing_count} missing, "
                f"{invalid_count} invalid, "
                f"{created_count} created, "
                f"{referenced_count} referenced, "
                f"{duplicate_artifact_count} duplicate(s)"
            ),
        )

        # A report passes when it carries at least one artifact and no artifact
        # is missing or invalid.
        passed = (
            artifact_count > 0
            and missing_count == 0
            and invalid_count == 0
        )
        pass_fail = {
            "passed": passed,
            "report_id": report["report_id"],
            "evidence_id": evidence.evidence_id,
            "artifact_count": artifact_count,
            "missing_count": missing_count,
            "invalid_count": invalid_count,
            "created_count": created_count,
            "referenced_count": referenced_count,
            "duplicate_artifact_count": duplicate_artifact_count,
            "status_counts": dict(report.get("status_counts", {})),
            "artifact_type_counts": dict(
                report.get("artifact_type_counts", {})
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

        lines.append("# Execution Artifact Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append(f"- Schema Version: {data.get('schema_version', '')}")
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Artifacts: {data.get('artifact_count', 0)}")
        lines.append(f"- Missing: {data.get('missing_count', 0)}")
        lines.append(f"- Invalid: {data.get('invalid_count', 0)}")
        lines.append(f"- Created: {data.get('created_count', 0)}")
        lines.append(f"- Referenced: {data.get('referenced_count', 0)}")
        lines.append(
            f"- Duplicate Artifacts: {data.get('duplicate_artifact_count', 0)}"
        )
        lines.append("")

        status_counts = data.get("status_counts", {})
        lines.append("## Status Counts")
        lines.append("")
        for status in sorted(status_counts):
            lines.append(f"- {status}: {status_counts[status]}")
        lines.append("")

        artifact_type_counts = data.get("artifact_type_counts", {})
        lines.append("## Artifact Type Counts")
        lines.append("")
        for artifact_type in sorted(artifact_type_counts):
            lines.append(
                f"- {artifact_type}: {artifact_type_counts[artifact_type]}"
            )
        lines.append("")

        lines.append("## Artifacts")
        lines.append("")
        for a in data.get("artifacts", []):
            artifact_type = a.get("artifact_type", "")
            status = a.get("status", "")
            result_id = a.get("result_id", "")
            attempt_id = a.get("attempt_id", "")
            capability_id = a.get("capability_id", "")
            artifact_path = a.get("artifact_path", "")
            artifact_url = a.get("artifact_url", "")
            location = artifact_path or artifact_url or "-"
            lines.append(
                f"- [{status}] [{artifact_type}] "
                f"result={result_id} attempt={attempt_id} "
                f"capability={capability_id} location={location}"
            )
            for ref in a.get("references", []):
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
                "artifact_id",
                "result_id",
                "attempt_id",
                "capability_id",
                "artifact_type",
                "status",
                "artifact_path",
                "artifact_url",
                "reference_id",
                "reference_type",
                "reference_value",
                "summary",
            ]
        )
        for a in data.get("artifacts", []):
            writer.writerow(
                [
                    "artifact",
                    a.get("artifact_id", ""),
                    a.get("result_id", ""),
                    a.get("attempt_id", ""),
                    a.get("capability_id", ""),
                    a.get("artifact_type", ""),
                    a.get("status", ""),
                    a.get("artifact_path", ""),
                    a.get("artifact_url", ""),
                    "",
                    "",
                    "",
                    a.get("summary", ""),
                ]
            )
            for ref in a.get("references", []):
                writer.writerow(
                    [
                        "reference",
                        a.get("artifact_id", ""),
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
