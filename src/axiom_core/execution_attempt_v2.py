"""Execution Attempt Framework v2.

The execution-attempt layer continues the autonomous engineering roadmap on top
of the Execution Step Framework, the Execution Plan Framework, and the Capability
Knowledge Graph. Where the Execution Step layer represents *the individual
executable units within a plan*, this layer represents *individual attempts to
perform those units*: for a given step / plan / capability, what status the
attempt reached (created, started, completed, failed, cancelled, timed_out),
what result it produced (success, failure, partial_success, no_action, unknown),
how long it took (duration_seconds derived from started_at / completed_at), and
which upstream objects it references.

Per report it captures a deterministic, append-only set of execution attempts,
ordered deterministically, aggregated with status counts, result counts,
failed-/timeout-/success detection, total-duration calculation, and
duplicate-attempt detection, with preserved raw payloads and schema versioning.

This is the v2 execution-roadmap attempt layer; it is distinct from the v1
``execution_attempt`` module (which tracks attempts over the Work Prioritization
Framework) and is kept separate to preserve that existing behavior. Evidence is
written under ``artifacts/execution_attempt_v2/``.

It is deliberately *observational and declarative only*. Non-goals: no actual
execution, no orchestration, no scheduling, no optimization, no worker
assignment, no autonomous behavior, no network calls, no architecture changes.
The upstream step / plan / graph layers are consumed read-only; nothing is
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

SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ExecutionAttemptStatus(str, Enum):
    CREATED = "CREATED"
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


class ExecutionAttemptResult(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    NO_ACTION = "NO_ACTION"
    UNKNOWN = "UNKNOWN"


class ExecutionAttemptReferenceType(str, Enum):
    STEP = "STEP"
    PLAN = "PLAN"
    CAPABILITY = "CAPABILITY"
    FILE = "FILE"
    ARTIFACT = "ARTIFACT"
    VALIDATION = "VALIDATION"
    KNOWLEDGE_NODE = "KNOWLEDGE_NODE"
    OTHER = "OTHER"


_VALID_STATUSES = {t.value for t in ExecutionAttemptStatus}
_VALID_RESULTS = {t.value for t in ExecutionAttemptResult}
_VALID_REFERENCE_TYPES = {t.value for t in ExecutionAttemptReferenceType}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class ExecutionAttemptReference:
    """A single reference from an execution attempt to an upstream object."""

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
    def from_dict(cls, data: dict[str, Any]) -> ExecutionAttemptReference:
        return cls(
            reference_id=data.get("reference_id", ""),
            reference_type=data.get("reference_type", ""),
            reference_value=data.get("reference_value", ""),
            summary=data.get("summary", ""),
        )


@dataclass
class ExecutionAttempt:
    """A single execution attempt against a step."""

    attempt_id: str = ""
    step_id: str = ""
    plan_id: str = ""
    capability_id: str = ""
    status: str = ""
    result: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0
    references: list[ExecutionAttemptReference] = field(default_factory=list)
    summary: str = ""
    created_at: str = ""
    schema_version: str = SCHEMA_VERSION
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.attempt_id:
            self.attempt_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "step_id": self.step_id,
            "plan_id": self.plan_id,
            "capability_id": self.capability_id,
            "status": self.status,
            "result": self.result,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "references": [r.to_dict() for r in self.references],
            "summary": self.summary,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "raw_payload": dict(self.raw_payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionAttempt:
        return cls(
            attempt_id=data.get("attempt_id", ""),
            step_id=data.get("step_id", ""),
            plan_id=data.get("plan_id", ""),
            capability_id=data.get("capability_id", ""),
            status=data.get("status", ""),
            result=data.get("result", ""),
            started_at=data.get("started_at", ""),
            completed_at=data.get("completed_at", ""),
            duration_seconds=data.get("duration_seconds", 0.0),
            references=[
                ExecutionAttemptReference.from_dict(r)
                for r in data.get("references", [])
            ],
            summary=data.get("summary", ""),
            created_at=data.get("created_at", ""),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            raw_payload=dict(data.get("raw_payload", {})),
        )


@dataclass
class ExecutionAttemptReport:
    """A deterministic, append-only execution attempt report."""

    report_id: str = ""
    attempts: list[ExecutionAttempt] = field(default_factory=list)
    attempt_count: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    result_counts: dict[str, int] = field(default_factory=dict)
    failed_count: int = 0
    timeout_count: int = 0
    success_count: int = 0
    total_duration_seconds: float = 0.0
    duplicate_attempt_count: int = 0
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
            "attempts": [a.to_dict() for a in self.attempts],
            "attempt_count": self.attempt_count,
            "status_counts": dict(self.status_counts),
            "result_counts": dict(self.result_counts),
            "failed_count": self.failed_count,
            "timeout_count": self.timeout_count,
            "success_count": self.success_count,
            "total_duration_seconds": self.total_duration_seconds,
            "duplicate_attempt_count": self.duplicate_attempt_count,
            "created_at": self.created_at,
            "raw_metadata": dict(self.raw_metadata),
            "schema_version": self.schema_version,
        }


@dataclass
class ExecutionAttemptEvidence:
    """Evidence record for an execution attempt report."""

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


class ExecutionAttemptEngine:
    """Manages execution attempt reports deterministically.

    Execution attempts are validated, deduplicated, ordered deterministically,
    and aggregated with status counts, result counts, total-duration
    calculation, and failed/timeout/success detection. Reports are append-only.
    The upstream step / plan / graph layers are *consumed* read-only; nothing is
    mutated.
    """

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "execution_attempt_v2"
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
    def _attempt_sort_key(a: ExecutionAttempt) -> tuple:
        return (
            a.plan_id,
            a.step_id,
            a.started_at,
            a.capability_id,
            a.status,
            a.result,
            a.attempt_id,
        )

    @staticmethod
    def _reference_sort_key(r: ExecutionAttemptReference) -> tuple:
        return (r.reference_type, r.reference_value, r.reference_id)

    # ------------------------------------------------------------------
    # Duration calculation
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_timestamp(value: str) -> datetime | None:
        if not value or not str(value).strip():
            return None
        try:
            return datetime.fromisoformat(str(value).strip())
        except ValueError:
            return None

    @classmethod
    def _compute_duration(
        cls,
        started_at: str,
        completed_at: str,
        explicit: Any,
    ) -> float:
        if explicit is not None:
            if isinstance(explicit, bool) or not isinstance(
                explicit, (int, float)
            ):
                raise ValueError(
                    f"duration_seconds must be a number: {explicit!r}"
                )
            if explicit < 0:
                raise ValueError(
                    f"duration_seconds must not be negative: {explicit!r}"
                )
            return float(explicit)

        start = cls._parse_timestamp(started_at)
        end = cls._parse_timestamp(completed_at)
        if start is not None and end is not None:
            delta = (end - start).total_seconds()
            if delta < 0:
                raise ValueError(
                    "completed_at must not precede started_at: "
                    f"{started_at!r} -> {completed_at!r}"
                )
            return float(delta)
        return 0.0

    # ------------------------------------------------------------------
    # Building / validation
    # ------------------------------------------------------------------

    @classmethod
    def _build_reference(
        cls, data: dict[str, Any]
    ) -> ExecutionAttemptReference:
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
        return ExecutionAttemptReference.from_dict(normalized)

    @classmethod
    def _build_attempt(cls, data: dict[str, Any]) -> ExecutionAttempt:
        step_id = data.get("step_id", "")
        if not step_id or not str(step_id).strip():
            raise ValueError("step_id is required for an execution attempt")
        plan_id = data.get("plan_id", "")
        if not plan_id or not str(plan_id).strip():
            raise ValueError("plan_id is required for an execution attempt")
        capability_id = data.get("capability_id", "")
        if not capability_id or not str(capability_id).strip():
            raise ValueError(
                "capability_id is required for an execution attempt"
            )

        status_raw = data.get("status", "")
        if not status_raw or not str(status_raw).strip():
            raise ValueError("status is required for an execution attempt")
        status = str(status_raw).strip().upper()
        if status not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid status: {status_raw!r}. "
                f"Valid: {sorted(_VALID_STATUSES)}"
            )

        result_raw = data.get("result", "")
        if not result_raw or not str(result_raw).strip():
            raise ValueError("result is required for an execution attempt")
        result = str(result_raw).strip().upper()
        if result not in _VALID_RESULTS:
            raise ValueError(
                f"Invalid result: {result_raw!r}. "
                f"Valid: {sorted(_VALID_RESULTS)}"
            )

        started_at = str(data.get("started_at", "") or "")
        completed_at = str(data.get("completed_at", "") or "")
        duration_seconds = cls._compute_duration(
            started_at, completed_at, data.get("duration_seconds")
        )

        references = sorted(
            (cls._build_reference(r) for r in data.get("references", [])),
            key=cls._reference_sort_key,
        )

        normalized = dict(data)
        normalized["step_id"] = str(step_id)
        normalized["plan_id"] = str(plan_id)
        normalized["capability_id"] = str(capability_id)
        normalized["status"] = status
        normalized["result"] = result
        normalized["started_at"] = started_at
        normalized["completed_at"] = completed_at
        normalized["duration_seconds"] = duration_seconds
        normalized.pop("references", None)
        attempt = ExecutionAttempt.from_dict(normalized)
        attempt.references = references
        return attempt

    def _assemble(self, report: ExecutionAttemptReport) -> dict[str, Any]:
        # Duplicate attempt detection: same
        # (step_id, plan_id, capability_id, started_at). Keep first.
        seen: set[tuple[str, str, str, str]] = set()
        deduped: list[ExecutionAttempt] = []
        duplicates = 0
        for a in sorted(report.attempts, key=self._attempt_sort_key):
            key = (
                a.step_id,
                a.plan_id,
                a.capability_id,
                a.started_at,
            )
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            deduped.append(a)
        report.attempts = deduped
        report.duplicate_attempt_count = duplicates

        status_counts: dict[str, int] = {}
        result_counts: dict[str, int] = {}
        total_duration = 0.0
        for a in report.attempts:
            status_counts[a.status] = status_counts.get(a.status, 0) + 1
            result_counts[a.result] = result_counts.get(a.result, 0) + 1
            total_duration += a.duration_seconds

        report.status_counts = {
            k: status_counts[k] for k in sorted(status_counts)
        }
        report.result_counts = {
            k: result_counts[k] for k in sorted(result_counts)
        }
        report.failed_count = status_counts.get(
            ExecutionAttemptStatus.FAILED.value, 0
        )
        report.timeout_count = status_counts.get(
            ExecutionAttemptStatus.TIMED_OUT.value, 0
        )
        report.success_count = result_counts.get(
            ExecutionAttemptResult.SUCCESS.value, 0
        )
        report.total_duration_seconds = total_duration
        report.attempt_count = len(report.attempts)

        return report.to_dict()

    # ------------------------------------------------------------------
    # Create / Append (append-only)
    # ------------------------------------------------------------------

    def create(
        self,
        attempts: list[dict[str, Any]] | None = None,
        raw_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new execution attempt report."""
        report = ExecutionAttemptReport(
            raw_metadata=dict(raw_metadata or {}),
        )
        report.attempts = [self._build_attempt(a) for a in (attempts or [])]
        assembled = self._assemble(report)
        self._persist(assembled)
        self._write_evidence(assembled)
        return assembled

    def append(
        self,
        report_id: str,
        attempts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Append execution attempts to an existing report (append-only)."""
        self._validate_id_segment(report_id, "report_id")
        existing = self._load_report(report_id)
        if existing is None:
            raise ValueError(f"Report not found: {report_id}")

        report = ExecutionAttemptReport(
            report_id=existing["report_id"],
            created_at=existing.get("created_at", ""),
            raw_metadata=dict(existing.get("raw_metadata", {})),
            schema_version=existing.get("schema_version", SCHEMA_VERSION),
        )
        report.attempts = [
            ExecutionAttempt.from_dict(a) for a in existing.get("attempts", [])
        ]
        report.attempts.extend(
            self._build_attempt(a) for a in (attempts or [])
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
            "attempts": report.get("attempts", []),
            "raw_metadata": report.get("raw_metadata", {}),
        }
        (evidence_dir / "execution_attempt_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_attempt_result.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_attempt_summary.md").write_text(
            self._generate_export_md(report), encoding="utf-8"
        )

        attempt_count = report.get("attempt_count", 0)
        failed_count = report.get("failed_count", 0)
        timeout_count = report.get("timeout_count", 0)
        success_count = report.get("success_count", 0)
        total_duration_seconds = report.get("total_duration_seconds", 0.0)
        duplicate_attempt_count = report.get("duplicate_attempt_count", 0)
        evidence = ExecutionAttemptEvidence(
            report_id=report["report_id"],
            summary=(
                f"{attempt_count} attempt(s), "
                f"{failed_count} failed, "
                f"{timeout_count} timed out, "
                f"{success_count} succeeded, "
                f"{total_duration_seconds}s total, "
                f"{duplicate_attempt_count} duplicate(s)"
            ),
        )

        # A report passes when it carries at least one attempt and no attempt
        # is failed or timed out.
        passed = (
            attempt_count > 0
            and failed_count == 0
            and timeout_count == 0
        )
        pass_fail = {
            "passed": passed,
            "report_id": report["report_id"],
            "evidence_id": evidence.evidence_id,
            "attempt_count": attempt_count,
            "failed_count": failed_count,
            "timeout_count": timeout_count,
            "success_count": success_count,
            "total_duration_seconds": total_duration_seconds,
            "duplicate_attempt_count": duplicate_attempt_count,
            "status_counts": dict(report.get("status_counts", {})),
            "result_counts": dict(report.get("result_counts", {})),
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

        lines.append("# Execution Attempt Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append(f"- Schema Version: {data.get('schema_version', '')}")
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Attempts: {data.get('attempt_count', 0)}")
        lines.append(f"- Failed: {data.get('failed_count', 0)}")
        lines.append(f"- Timed Out: {data.get('timeout_count', 0)}")
        lines.append(f"- Succeeded: {data.get('success_count', 0)}")
        lines.append(
            f"- Total Duration (s): "
            f"{data.get('total_duration_seconds', 0.0)}"
        )
        lines.append(
            f"- Duplicate Attempts: {data.get('duplicate_attempt_count', 0)}"
        )
        lines.append("")

        status_counts = data.get("status_counts", {})
        lines.append("## Status Counts")
        lines.append("")
        for status in sorted(status_counts):
            lines.append(f"- {status}: {status_counts[status]}")
        lines.append("")

        result_counts = data.get("result_counts", {})
        lines.append("## Result Counts")
        lines.append("")
        for result in sorted(result_counts):
            lines.append(f"- {result}: {result_counts[result]}")
        lines.append("")

        lines.append("## Attempts")
        lines.append("")
        for a in data.get("attempts", []):
            status = a.get("status", "")
            result = a.get("result", "")
            duration = a.get("duration_seconds", 0.0)
            step_id = a.get("step_id", "")
            plan_id = a.get("plan_id", "")
            capability_id = a.get("capability_id", "")
            lines.append(
                f"- [{status}] [{result}] [{duration}s] "
                f"step={step_id} plan={plan_id} capability={capability_id}"
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
                "attempt_id",
                "step_id",
                "plan_id",
                "capability_id",
                "status",
                "result",
                "started_at",
                "completed_at",
                "duration_seconds",
                "reference_id",
                "reference_type",
                "reference_value",
                "summary",
            ]
        )
        for a in data.get("attempts", []):
            writer.writerow(
                [
                    "attempt",
                    a.get("attempt_id", ""),
                    a.get("step_id", ""),
                    a.get("plan_id", ""),
                    a.get("capability_id", ""),
                    a.get("status", ""),
                    a.get("result", ""),
                    a.get("started_at", ""),
                    a.get("completed_at", ""),
                    a.get("duration_seconds", 0.0),
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
                        a.get("attempt_id", ""),
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
