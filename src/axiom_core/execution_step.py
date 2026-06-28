"""Execution Step Framework v1.

The execution-step layer continues the autonomous engineering roadmap on top of
the Execution Plan Framework, the Capability Chain, and the Capability Knowledge
Graph. Where the Execution Plan layer represents *what execution would do* (the
plan that execution would follow), this layer represents *the individual
executable units within a plan*: for a given plan / capability, what kind of
step it is (implementation, validation, repair, review, reporting,
investigation, approval, ...), where it sits in the plan (order_index), what its
status is (created, ready, blocked, completed, failed, skipped), and which
upstream objects it references.

Per report it captures a deterministic, append-only set of execution steps,
ordered by their position within a plan, aggregated with step-type counts,
status counts, blocked-/failed-/skipped-step detection, and duplicate-step
detection, with preserved raw payloads and schema versioning.

It is deliberately *observational and declarative only*. Non-goals: no actual
execution, no orchestration, no scheduling, no optimization, no worker
assignment, no autonomous behavior, no network calls, no architecture changes.
The upstream plan / chain / graph layers are consumed read-only; nothing is
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


class ExecutionStepType(str, Enum):
    IMPLEMENTATION = "IMPLEMENTATION"
    VALIDATION = "VALIDATION"
    REPAIR = "REPAIR"
    REVIEW = "REVIEW"
    REPORTING = "REPORTING"
    INVESTIGATION = "INVESTIGATION"
    APPROVAL = "APPROVAL"
    OTHER = "OTHER"


class ExecutionStepStatus(str, Enum):
    CREATED = "CREATED"
    READY = "READY"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ExecutionStepReferenceType(str, Enum):
    CAPABILITY = "CAPABILITY"
    PLAN = "PLAN"
    FILE = "FILE"
    ARTIFACT = "ARTIFACT"
    VALIDATION = "VALIDATION"
    KNOWLEDGE_NODE = "KNOWLEDGE_NODE"
    OTHER = "OTHER"


_VALID_STEP_TYPES = {t.value for t in ExecutionStepType}
_VALID_STATUSES = {t.value for t in ExecutionStepStatus}
_VALID_REFERENCE_TYPES = {t.value for t in ExecutionStepReferenceType}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class ExecutionStepReference:
    """A single reference from an execution step to an upstream object."""

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
    def from_dict(cls, data: dict[str, Any]) -> ExecutionStepReference:
        return cls(
            reference_id=data.get("reference_id", ""),
            reference_type=data.get("reference_type", ""),
            reference_value=data.get("reference_value", ""),
            summary=data.get("summary", ""),
        )


@dataclass
class ExecutionStep:
    """A single execution step."""

    step_id: str = ""
    plan_id: str = ""
    capability_id: str = ""
    order_index: int = 0
    step_type: str = ""
    status: str = ""
    references: list[ExecutionStepReference] = field(default_factory=list)
    summary: str = ""
    created_at: str = ""
    schema_version: str = SCHEMA_VERSION
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.step_id:
            self.step_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "plan_id": self.plan_id,
            "capability_id": self.capability_id,
            "order_index": self.order_index,
            "step_type": self.step_type,
            "status": self.status,
            "references": [r.to_dict() for r in self.references],
            "summary": self.summary,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "raw_payload": dict(self.raw_payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionStep:
        return cls(
            step_id=data.get("step_id", ""),
            plan_id=data.get("plan_id", ""),
            capability_id=data.get("capability_id", ""),
            order_index=data.get("order_index", 0),
            step_type=data.get("step_type", ""),
            status=data.get("status", ""),
            references=[
                ExecutionStepReference.from_dict(r)
                for r in data.get("references", [])
            ],
            summary=data.get("summary", ""),
            created_at=data.get("created_at", ""),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            raw_payload=dict(data.get("raw_payload", {})),
        )


@dataclass
class ExecutionStepReport:
    """A deterministic, append-only execution step report."""

    report_id: str = ""
    steps: list[ExecutionStep] = field(default_factory=list)
    step_count: int = 0
    step_type_counts: dict[str, int] = field(default_factory=dict)
    status_counts: dict[str, int] = field(default_factory=dict)
    blocked_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    duplicate_step_count: int = 0
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
            "steps": [s.to_dict() for s in self.steps],
            "step_count": self.step_count,
            "step_type_counts": dict(self.step_type_counts),
            "status_counts": dict(self.status_counts),
            "blocked_count": self.blocked_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "duplicate_step_count": self.duplicate_step_count,
            "created_at": self.created_at,
            "raw_metadata": dict(self.raw_metadata),
            "schema_version": self.schema_version,
        }


@dataclass
class ExecutionStepEvidence:
    """Evidence record for an execution step report."""

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


class ExecutionStepEngine:
    """Manages execution step reports deterministically.

    Execution steps are validated, deduplicated, ordered deterministically by
    their position within a plan, and aggregated with step-type counts, status
    counts, and blocked/failed/skipped detection. Reports are append-only. The
    upstream plan / chain / graph layers are *consumed* read-only; nothing is
    mutated.
    """

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "execution_step"
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
    def _step_sort_key(s: ExecutionStep) -> tuple:
        return (
            s.plan_id,
            s.order_index,
            s.capability_id,
            s.step_type,
            s.status,
            s.step_id,
        )

    @staticmethod
    def _reference_sort_key(r: ExecutionStepReference) -> tuple:
        return (r.reference_type, r.reference_value, r.reference_id)

    # ------------------------------------------------------------------
    # Building / validation
    # ------------------------------------------------------------------

    @classmethod
    def _build_reference(cls, data: dict[str, Any]) -> ExecutionStepReference:
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
        return ExecutionStepReference.from_dict(normalized)

    @classmethod
    def _build_step(cls, data: dict[str, Any]) -> ExecutionStep:
        plan_id = data.get("plan_id", "")
        if not plan_id or not str(plan_id).strip():
            raise ValueError("plan_id is required for an execution step")
        capability_id = data.get("capability_id", "")
        if not capability_id or not str(capability_id).strip():
            raise ValueError("capability_id is required for an execution step")

        order_index_raw = data.get("order_index", 0)
        if isinstance(order_index_raw, bool) or not isinstance(
            order_index_raw, int
        ):
            raise ValueError(
                f"order_index must be an integer: {order_index_raw!r}"
            )

        stype_raw = data.get("step_type", "")
        if not stype_raw or not str(stype_raw).strip():
            raise ValueError("step_type is required for an execution step")
        stype = str(stype_raw).strip().upper()
        if stype not in _VALID_STEP_TYPES:
            raise ValueError(
                f"Invalid step_type: {stype_raw!r}. "
                f"Valid: {sorted(_VALID_STEP_TYPES)}"
            )

        status_raw = data.get("status", "")
        if not status_raw or not str(status_raw).strip():
            raise ValueError("status is required for an execution step")
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
        normalized["plan_id"] = str(plan_id)
        normalized["capability_id"] = str(capability_id)
        normalized["order_index"] = order_index_raw
        normalized["step_type"] = stype
        normalized["status"] = status
        normalized.pop("references", None)
        step = ExecutionStep.from_dict(normalized)
        step.references = references
        return step

    def _assemble(self, report: ExecutionStepReport) -> dict[str, Any]:
        # Duplicate step detection: same
        # (plan_id, capability_id, order_index, step_type). Keep first.
        seen: set[tuple[str, str, int, str]] = set()
        deduped: list[ExecutionStep] = []
        duplicates = 0
        for s in sorted(report.steps, key=self._step_sort_key):
            key = (
                s.plan_id,
                s.capability_id,
                s.order_index,
                s.step_type,
            )
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            deduped.append(s)
        report.steps = deduped
        report.duplicate_step_count = duplicates

        step_type_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        for s in report.steps:
            step_type_counts[s.step_type] = (
                step_type_counts.get(s.step_type, 0) + 1
            )
            status_counts[s.status] = status_counts.get(s.status, 0) + 1

        report.step_type_counts = {
            k: step_type_counts[k] for k in sorted(step_type_counts)
        }
        report.status_counts = {
            k: status_counts[k] for k in sorted(status_counts)
        }
        report.blocked_count = status_counts.get(
            ExecutionStepStatus.BLOCKED.value, 0
        )
        report.failed_count = status_counts.get(
            ExecutionStepStatus.FAILED.value, 0
        )
        report.skipped_count = status_counts.get(
            ExecutionStepStatus.SKIPPED.value, 0
        )
        report.step_count = len(report.steps)

        return report.to_dict()

    # ------------------------------------------------------------------
    # Create / Append (append-only)
    # ------------------------------------------------------------------

    def create(
        self,
        steps: list[dict[str, Any]] | None = None,
        raw_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new execution step report."""
        report = ExecutionStepReport(
            raw_metadata=dict(raw_metadata or {}),
        )
        report.steps = [self._build_step(s) for s in (steps or [])]
        assembled = self._assemble(report)
        self._persist(assembled)
        self._write_evidence(assembled)
        return assembled

    def append(
        self,
        report_id: str,
        steps: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Append execution steps to an existing report (append-only)."""
        self._validate_id_segment(report_id, "report_id")
        existing = self._load_report(report_id)
        if existing is None:
            raise ValueError(f"Report not found: {report_id}")

        report = ExecutionStepReport(
            report_id=existing["report_id"],
            created_at=existing.get("created_at", ""),
            raw_metadata=dict(existing.get("raw_metadata", {})),
            schema_version=existing.get("schema_version", SCHEMA_VERSION),
        )
        report.steps = [
            ExecutionStep.from_dict(s) for s in existing.get("steps", [])
        ]
        report.steps.extend(self._build_step(s) for s in (steps or []))

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
            "steps": report.get("steps", []),
            "raw_metadata": report.get("raw_metadata", {}),
        }
        (evidence_dir / "execution_step_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_step_result.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_step_summary.md").write_text(
            self._generate_export_md(report), encoding="utf-8"
        )

        step_count = report.get("step_count", 0)
        blocked_count = report.get("blocked_count", 0)
        failed_count = report.get("failed_count", 0)
        skipped_count = report.get("skipped_count", 0)
        duplicate_step_count = report.get("duplicate_step_count", 0)
        evidence = ExecutionStepEvidence(
            report_id=report["report_id"],
            summary=(
                f"{step_count} step(s), "
                f"{blocked_count} blocked, "
                f"{failed_count} failed, "
                f"{skipped_count} skipped, "
                f"{duplicate_step_count} duplicate(s)"
            ),
        )

        # A report passes when it carries at least one step and no step is
        # blocked or failed.
        passed = (
            step_count > 0 and blocked_count == 0 and failed_count == 0
        )
        pass_fail = {
            "passed": passed,
            "report_id": report["report_id"],
            "evidence_id": evidence.evidence_id,
            "step_count": step_count,
            "blocked_count": blocked_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "duplicate_step_count": duplicate_step_count,
            "status_counts": dict(report.get("status_counts", {})),
            "step_type_counts": dict(report.get("step_type_counts", {})),
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

        lines.append("# Execution Step Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append(f"- Schema Version: {data.get('schema_version', '')}")
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Steps: {data.get('step_count', 0)}")
        lines.append(f"- Blocked: {data.get('blocked_count', 0)}")
        lines.append(f"- Failed: {data.get('failed_count', 0)}")
        lines.append(f"- Skipped: {data.get('skipped_count', 0)}")
        lines.append(
            f"- Duplicate Steps: {data.get('duplicate_step_count', 0)}"
        )
        lines.append("")

        status_counts = data.get("status_counts", {})
        lines.append("## Status Counts")
        lines.append("")
        for status in sorted(status_counts):
            lines.append(f"- {status}: {status_counts[status]}")
        lines.append("")

        step_type_counts = data.get("step_type_counts", {})
        lines.append("## Step Type Counts")
        lines.append("")
        for stype in sorted(step_type_counts):
            lines.append(f"- {stype}: {step_type_counts[stype]}")
        lines.append("")

        lines.append("## Steps")
        lines.append("")
        for s in data.get("steps", []):
            status = s.get("status", "")
            stype = s.get("step_type", "")
            order_index = s.get("order_index", 0)
            plan_id = s.get("plan_id", "")
            capability_id = s.get("capability_id", "")
            lines.append(
                f"- [{status}] [{stype}] [{order_index}] "
                f"plan={plan_id} capability={capability_id}"
            )
            for ref in s.get("references", []):
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
                "step_id",
                "plan_id",
                "capability_id",
                "order_index",
                "step_type",
                "status",
                "reference_id",
                "reference_type",
                "reference_value",
                "summary",
            ]
        )
        for s in data.get("steps", []):
            writer.writerow(
                [
                    "step",
                    s.get("step_id", ""),
                    s.get("plan_id", ""),
                    s.get("capability_id", ""),
                    s.get("order_index", 0),
                    s.get("step_type", ""),
                    s.get("status", ""),
                    "",
                    "",
                    "",
                    s.get("summary", ""),
                ]
            )
            for ref in s.get("references", []):
                writer.writerow(
                    [
                        "reference",
                        s.get("step_id", ""),
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
