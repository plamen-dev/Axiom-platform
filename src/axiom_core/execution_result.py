"""Execution Result Framework v1.

The execution-result layer continues the autonomous engineering roadmap on top
of the Execution Attempt Framework v2, the Execution Step Framework, and the
Capability Knowledge Graph. Where the Execution Attempt layer represents
*individual attempts to perform a planned step*, this layer represents *the
results those attempts produced*: for a given attempt / step / capability, what
type of result was produced (output, validation, error, artifact, report,
no_action, other), what status it reached (produced, failed, partial, empty,
unknown), and which upstream objects it references.

Per report it captures a deterministic, append-only set of execution results,
ordered deterministically, aggregated with status counts, result-type counts,
failed-/empty-/produced detection, and duplicate-result detection, with
preserved raw payloads and schema versioning.

It is deliberately *observational and declarative only*. Non-goals: no actual
execution, no orchestration, no scheduling, no optimization, no worker
assignment, no autonomous behavior, no network calls, no architecture changes.
The upstream attempt / step / graph layers are consumed read-only; nothing is
mutated.
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


class ExecutionResultType(str, Enum):
    OUTPUT = "OUTPUT"
    VALIDATION = "VALIDATION"
    ERROR = "ERROR"
    ARTIFACT = "ARTIFACT"
    REPORT = "REPORT"
    NO_ACTION = "NO_ACTION"
    OTHER = "OTHER"


class ExecutionResultStatus(str, Enum):
    PRODUCED = "PRODUCED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    EMPTY = "EMPTY"
    UNKNOWN = "UNKNOWN"


class ExecutionResultReferenceType(str, Enum):
    ATTEMPT = "ATTEMPT"
    STEP = "STEP"
    CAPABILITY = "CAPABILITY"
    FILE = "FILE"
    ARTIFACT = "ARTIFACT"
    VALIDATION = "VALIDATION"
    KNOWLEDGE_NODE = "KNOWLEDGE_NODE"
    OTHER = "OTHER"


_VALID_RESULT_TYPES = {t.value for t in ExecutionResultType}
_VALID_STATUSES = {t.value for t in ExecutionResultStatus}
_VALID_REFERENCE_TYPES = {t.value for t in ExecutionResultReferenceType}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class ExecutionResultReference:
    """A single reference from an execution result to an upstream object."""

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
    def from_dict(cls, data: dict[str, Any]) -> ExecutionResultReference:
        return cls(
            reference_id=data.get("reference_id", ""),
            reference_type=data.get("reference_type", ""),
            reference_value=data.get("reference_value", ""),
            summary=data.get("summary", ""),
        )


@dataclass
class ExecutionResult:
    """A single result produced by an execution attempt."""

    result_id: str = ""
    attempt_id: str = ""
    step_id: str = ""
    capability_id: str = ""
    result_type: str = ""
    status: str = ""
    references: list[ExecutionResultReference] = field(default_factory=list)
    summary: str = ""
    created_at: str = ""
    schema_version: str = SCHEMA_VERSION
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.result_id:
            self.result_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "attempt_id": self.attempt_id,
            "step_id": self.step_id,
            "capability_id": self.capability_id,
            "result_type": self.result_type,
            "status": self.status,
            "references": [r.to_dict() for r in self.references],
            "summary": self.summary,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "raw_payload": dict(self.raw_payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionResult:
        return cls(
            result_id=data.get("result_id", ""),
            attempt_id=data.get("attempt_id", ""),
            step_id=data.get("step_id", ""),
            capability_id=data.get("capability_id", ""),
            result_type=data.get("result_type", ""),
            status=data.get("status", ""),
            references=[
                ExecutionResultReference.from_dict(r)
                for r in data.get("references", [])
            ],
            summary=data.get("summary", ""),
            created_at=data.get("created_at", ""),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            raw_payload=dict(data.get("raw_payload", {})),
        )


@dataclass
class ExecutionResultReport:
    """A deterministic, append-only execution result report."""

    report_id: str = ""
    results: list[ExecutionResult] = field(default_factory=list)
    result_count: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    result_type_counts: dict[str, int] = field(default_factory=dict)
    failed_count: int = 0
    empty_count: int = 0
    produced_count: int = 0
    duplicate_result_count: int = 0
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
            "results": [r.to_dict() for r in self.results],
            "result_count": self.result_count,
            "status_counts": dict(self.status_counts),
            "result_type_counts": dict(self.result_type_counts),
            "failed_count": self.failed_count,
            "empty_count": self.empty_count,
            "produced_count": self.produced_count,
            "duplicate_result_count": self.duplicate_result_count,
            "created_at": self.created_at,
            "raw_metadata": dict(self.raw_metadata),
            "schema_version": self.schema_version,
        }


@dataclass
class ExecutionResultEvidence:
    """Evidence record for an execution result report."""

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


class ExecutionResultEngine:
    """Manages execution result reports deterministically.

    Execution results are validated, deduplicated, ordered deterministically,
    and aggregated with status counts, result-type counts, and
    failed/empty/produced detection. Reports are append-only. The upstream
    attempt / step / graph layers are *consumed* read-only; nothing is mutated.
    """

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "execution_result"
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
    def _result_sort_key(r: ExecutionResult) -> tuple:
        return (
            r.attempt_id,
            r.step_id,
            r.capability_id,
            r.result_type,
            r.status,
            r.result_id,
        )

    @staticmethod
    def _reference_sort_key(r: ExecutionResultReference) -> tuple:
        return (r.reference_type, r.reference_value, r.reference_id)

    # ------------------------------------------------------------------
    # Building / validation
    # ------------------------------------------------------------------

    @classmethod
    def _build_reference(
        cls, data: dict[str, Any]
    ) -> ExecutionResultReference:
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
        return ExecutionResultReference.from_dict(normalized)

    @classmethod
    def _build_result(cls, data: dict[str, Any]) -> ExecutionResult:
        attempt_id = data.get("attempt_id", "")
        if not attempt_id or not str(attempt_id).strip():
            raise ValueError("attempt_id is required for an execution result")
        step_id = data.get("step_id", "")
        if not step_id or not str(step_id).strip():
            raise ValueError("step_id is required for an execution result")
        capability_id = data.get("capability_id", "")
        if not capability_id or not str(capability_id).strip():
            raise ValueError(
                "capability_id is required for an execution result"
            )

        result_type_raw = data.get("result_type", "")
        if not result_type_raw or not str(result_type_raw).strip():
            raise ValueError(
                "result_type is required for an execution result"
            )
        result_type = str(result_type_raw).strip().upper()
        if result_type not in _VALID_RESULT_TYPES:
            raise ValueError(
                f"Invalid result_type: {result_type_raw!r}. "
                f"Valid: {sorted(_VALID_RESULT_TYPES)}"
            )

        status_raw = data.get("status", "")
        if not status_raw or not str(status_raw).strip():
            raise ValueError("status is required for an execution result")
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
        normalized["attempt_id"] = str(attempt_id)
        normalized["step_id"] = str(step_id)
        normalized["capability_id"] = str(capability_id)
        normalized["result_type"] = result_type
        normalized["status"] = status
        normalized.pop("references", None)
        result = ExecutionResult.from_dict(normalized)
        result.references = references
        return result

    def _assemble(self, report: ExecutionResultReport) -> dict[str, Any]:
        # Duplicate result detection: same
        # (attempt_id, step_id, capability_id, result_type). Keep first.
        seen: set[tuple[str, str, str, str]] = set()
        deduped: list[ExecutionResult] = []
        duplicates = 0
        for r in sorted(report.results, key=self._result_sort_key):
            key = (
                r.attempt_id,
                r.step_id,
                r.capability_id,
                r.result_type,
            )
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            deduped.append(r)
        report.results = deduped
        report.duplicate_result_count = duplicates

        status_counts: dict[str, int] = {}
        result_type_counts: dict[str, int] = {}
        for r in report.results:
            status_counts[r.status] = status_counts.get(r.status, 0) + 1
            result_type_counts[r.result_type] = (
                result_type_counts.get(r.result_type, 0) + 1
            )

        report.status_counts = {
            k: status_counts[k] for k in sorted(status_counts)
        }
        report.result_type_counts = {
            k: result_type_counts[k] for k in sorted(result_type_counts)
        }
        report.failed_count = status_counts.get(
            ExecutionResultStatus.FAILED.value, 0
        )
        report.empty_count = status_counts.get(
            ExecutionResultStatus.EMPTY.value, 0
        )
        report.produced_count = status_counts.get(
            ExecutionResultStatus.PRODUCED.value, 0
        )
        report.result_count = len(report.results)

        return report.to_dict()

    # ------------------------------------------------------------------
    # Create / Append (append-only)
    # ------------------------------------------------------------------

    def create(
        self,
        results: list[dict[str, Any]] | None = None,
        raw_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new execution result report."""
        report = ExecutionResultReport(
            raw_metadata=dict(raw_metadata or {}),
        )
        report.results = [self._build_result(r) for r in (results or [])]
        assembled = self._assemble(report)
        self._persist(assembled)
        self._write_evidence(assembled)
        return assembled

    def append(
        self,
        report_id: str,
        results: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Append execution results to an existing report (append-only)."""
        self._validate_id_segment(report_id, "report_id")
        existing = self._load_report(report_id)
        if existing is None:
            raise ValueError(f"Report not found: {report_id}")

        report = ExecutionResultReport(
            report_id=existing["report_id"],
            created_at=existing.get("created_at", ""),
            raw_metadata=dict(existing.get("raw_metadata", {})),
            schema_version=existing.get("schema_version", SCHEMA_VERSION),
        )
        report.results = [
            ExecutionResult.from_dict(r) for r in existing.get("results", [])
        ]
        report.results.extend(
            self._build_result(r) for r in (results or [])
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
            "results": report.get("results", []),
            "raw_metadata": report.get("raw_metadata", {}),
        }
        (evidence_dir / "execution_result_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_result_result.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_result_summary.md").write_text(
            self._generate_export_md(report), encoding="utf-8"
        )

        result_count = report.get("result_count", 0)
        failed_count = report.get("failed_count", 0)
        empty_count = report.get("empty_count", 0)
        produced_count = report.get("produced_count", 0)
        duplicate_result_count = report.get("duplicate_result_count", 0)
        evidence = ExecutionResultEvidence(
            report_id=report["report_id"],
            summary=(
                f"{result_count} result(s), "
                f"{failed_count} failed, "
                f"{empty_count} empty, "
                f"{produced_count} produced, "
                f"{duplicate_result_count} duplicate(s)"
            ),
        )

        # A report passes when it carries at least one result and no result is
        # failed or empty.
        passed = (
            result_count > 0
            and failed_count == 0
            and empty_count == 0
        )
        pass_fail = {
            "passed": passed,
            "report_id": report["report_id"],
            "evidence_id": evidence.evidence_id,
            "result_count": result_count,
            "failed_count": failed_count,
            "empty_count": empty_count,
            "produced_count": produced_count,
            "duplicate_result_count": duplicate_result_count,
            "status_counts": dict(report.get("status_counts", {})),
            "result_type_counts": dict(report.get("result_type_counts", {})),
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

        lines.append("# Execution Result Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append(f"- Schema Version: {data.get('schema_version', '')}")
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Results: {data.get('result_count', 0)}")
        lines.append(f"- Failed: {data.get('failed_count', 0)}")
        lines.append(f"- Empty: {data.get('empty_count', 0)}")
        lines.append(f"- Produced: {data.get('produced_count', 0)}")
        lines.append(
            f"- Duplicate Results: {data.get('duplicate_result_count', 0)}"
        )
        lines.append("")

        status_counts = data.get("status_counts", {})
        lines.append("## Status Counts")
        lines.append("")
        for status in sorted(status_counts):
            lines.append(f"- {status}: {status_counts[status]}")
        lines.append("")

        result_type_counts = data.get("result_type_counts", {})
        lines.append("## Result Type Counts")
        lines.append("")
        for result_type in sorted(result_type_counts):
            lines.append(f"- {result_type}: {result_type_counts[result_type]}")
        lines.append("")

        lines.append("## Results")
        lines.append("")
        for r in data.get("results", []):
            result_type = r.get("result_type", "")
            status = r.get("status", "")
            attempt_id = r.get("attempt_id", "")
            step_id = r.get("step_id", "")
            capability_id = r.get("capability_id", "")
            lines.append(
                f"- [{status}] [{result_type}] "
                f"attempt={attempt_id} step={step_id} "
                f"capability={capability_id}"
            )
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
                "result_id",
                "attempt_id",
                "step_id",
                "capability_id",
                "result_type",
                "status",
                "reference_id",
                "reference_type",
                "reference_value",
                "summary",
            ]
        )
        for r in data.get("results", []):
            writer.writerow(
                [
                    "result",
                    r.get("result_id", ""),
                    r.get("attempt_id", ""),
                    r.get("step_id", ""),
                    r.get("capability_id", ""),
                    r.get("result_type", ""),
                    r.get("status", ""),
                    "",
                    "",
                    "",
                    r.get("summary", ""),
                ]
            )
            for ref in r.get("references", []):
                writer.writerow(
                    [
                        "reference",
                        r.get("result_id", ""),
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
