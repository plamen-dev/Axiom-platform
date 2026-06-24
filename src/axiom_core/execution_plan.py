"""Execution Plan Framework v1.

The execution-plan layer continues the autonomous engineering roadmap on top of
the Execution Context, Execution Environment, Execution Resource, Execution
Constraint, and Execution Readiness frameworks. Where the Execution Readiness
layer determines *whether execution is ready to proceed*, this layer represents
*the plan that execution would follow*: for a given capability / readiness /
chain, what kind of plan it is (implementation, validation, repair, review,
reporting, investigation, custom), what its status is (created, ready, blocked,
completed, failed), and which ordered steps the plan is composed of.

Per report it captures a deterministic, append-only set of execution plan
records, aggregated with status counts, plan-type counts, step counts,
blocked- and failed-plan detection, and duplicate-plan detection, with preserved
raw payloads and schema versioning.

It is deliberately *declarative and observational only*. Non-goals: no
execution, no orchestration, no scheduling, no optimization, no worker
assignment, no autonomous behavior, no network calls, no architecture changes.
The upstream readiness / chain / knowledge-graph layers are consumed read-only;
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


class ExecutionPlanType(str, Enum):
    IMPLEMENTATION = "IMPLEMENTATION"
    VALIDATION = "VALIDATION"
    REPAIR = "REPAIR"
    REVIEW = "REVIEW"
    REPORTING = "REPORTING"
    INVESTIGATION = "INVESTIGATION"
    CUSTOM = "CUSTOM"


class ExecutionPlanStatus(str, Enum):
    CREATED = "CREATED"
    READY = "READY"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


_VALID_PLAN_TYPES = {t.value for t in ExecutionPlanType}
_VALID_PLAN_STATUSES = {t.value for t in ExecutionPlanStatus}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class ExecutionPlanStep:
    """A single ordered step within an execution plan."""

    step_id: str = ""
    plan_id: str = ""
    order_index: int = 0
    step_name: str = ""
    summary: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.step_id:
            self.step_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "plan_id": self.plan_id,
            "order_index": self.order_index,
            "step_name": self.step_name,
            "summary": self.summary,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionPlanStep:
        return cls(
            step_id=data.get("step_id", ""),
            plan_id=data.get("plan_id", ""),
            order_index=int(data.get("order_index", 0)),
            step_name=data.get("step_name", ""),
            summary=data.get("summary", ""),
            created_at=data.get("created_at", ""),
        )


@dataclass
class ExecutionPlan:
    """A single execution plan record."""

    plan_id: str = ""
    capability_id: str = ""
    readiness_id: str = ""
    chain_id: str = ""
    plan_type: str = ""
    status: str = ""
    steps: list[ExecutionPlanStep] = field(default_factory=list)
    summary: str = ""
    created_at: str = ""
    schema_version: str = SCHEMA_VERSION
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.plan_id:
            self.plan_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "capability_id": self.capability_id,
            "readiness_id": self.readiness_id,
            "chain_id": self.chain_id,
            "plan_type": self.plan_type,
            "status": self.status,
            "steps": [s.to_dict() for s in self.steps],
            "summary": self.summary,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "raw_payload": dict(self.raw_payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionPlan:
        return cls(
            plan_id=data.get("plan_id", ""),
            capability_id=data.get("capability_id", ""),
            readiness_id=data.get("readiness_id", ""),
            chain_id=data.get("chain_id", ""),
            plan_type=data.get("plan_type", ""),
            status=data.get("status", ""),
            steps=[
                ExecutionPlanStep.from_dict(s) for s in data.get("steps", [])
            ],
            summary=data.get("summary", ""),
            created_at=data.get("created_at", ""),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            raw_payload=dict(data.get("raw_payload", {})),
        )


@dataclass
class ExecutionPlanReport:
    """A deterministic, append-only execution plan report."""

    report_id: str = ""
    plans: list[ExecutionPlan] = field(default_factory=list)
    plan_count: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    plan_type_counts: dict[str, int] = field(default_factory=dict)
    step_count: int = 0
    blocked_count: int = 0
    failed_count: int = 0
    duplicate_plan_count: int = 0
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
            "plans": [p.to_dict() for p in self.plans],
            "plan_count": self.plan_count,
            "status_counts": dict(self.status_counts),
            "plan_type_counts": dict(self.plan_type_counts),
            "step_count": self.step_count,
            "blocked_count": self.blocked_count,
            "failed_count": self.failed_count,
            "duplicate_plan_count": self.duplicate_plan_count,
            "created_at": self.created_at,
            "raw_metadata": dict(self.raw_metadata),
            "schema_version": self.schema_version,
        }


@dataclass
class ExecutionPlanEvidence:
    """Evidence record for an execution plan report."""

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


class ExecutionPlanEngine:
    """Manages execution plan reports deterministically.

    Execution plan records are validated, deduplicated, ordered
    deterministically, and aggregated with status counts, plan-type counts,
    step counts, and blocked/failed detection. Reports are append-only. The
    upstream readiness / chain / knowledge-graph layers are *consumed*
    read-only; nothing is mutated.
    """

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "execution_plan"
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
    def _plan_sort_key(p: ExecutionPlan) -> tuple:
        return (
            p.capability_id,
            p.readiness_id,
            p.chain_id,
            p.plan_type,
            p.status,
            p.plan_id,
        )

    @staticmethod
    def _step_sort_key(s: ExecutionPlanStep) -> tuple:
        return (s.order_index, s.step_name, s.step_id)

    # ------------------------------------------------------------------
    # Building / validation
    # ------------------------------------------------------------------

    @classmethod
    def _build_step(
        cls, data: dict[str, Any], plan_id: str
    ) -> ExecutionPlanStep:
        name_raw = data.get("step_name", "")
        if not name_raw or not str(name_raw).strip():
            raise ValueError("step_name is required for an execution plan step")
        order_raw = data.get("order_index", 0)
        try:
            order_index = int(order_raw)
        except (TypeError, ValueError):
            raise ValueError(
                f"order_index must be an integer: {order_raw!r}"
            ) from None

        normalized = dict(data)
        normalized["step_name"] = str(name_raw)
        normalized["order_index"] = order_index
        normalized["plan_id"] = plan_id
        return ExecutionPlanStep.from_dict(normalized)

    @classmethod
    def _build_plan(cls, data: dict[str, Any]) -> ExecutionPlan:
        capability_id = data.get("capability_id", "")
        if not capability_id or not str(capability_id).strip():
            raise ValueError("capability_id is required for an execution plan")
        readiness_id = data.get("readiness_id", "")
        if not readiness_id or not str(readiness_id).strip():
            raise ValueError("readiness_id is required for an execution plan")
        chain_id = data.get("chain_id", "")
        if not chain_id or not str(chain_id).strip():
            raise ValueError("chain_id is required for an execution plan")

        type_raw = data.get("plan_type", "")
        if not type_raw or not str(type_raw).strip():
            raise ValueError("plan_type is required for an execution plan")
        plan_type = str(type_raw).strip().upper()
        if plan_type not in _VALID_PLAN_TYPES:
            raise ValueError(
                f"Invalid plan_type: {type_raw!r}. "
                f"Valid: {sorted(_VALID_PLAN_TYPES)}"
            )

        status_raw = data.get("status", "")
        if not status_raw or not str(status_raw).strip():
            raise ValueError("status is required for an execution plan")
        status = str(status_raw).strip().upper()
        if status not in _VALID_PLAN_STATUSES:
            raise ValueError(
                f"Invalid status: {status_raw!r}. "
                f"Valid: {sorted(_VALID_PLAN_STATUSES)}"
            )

        normalized = dict(data)
        normalized["capability_id"] = str(capability_id)
        normalized["readiness_id"] = str(readiness_id)
        normalized["chain_id"] = str(chain_id)
        normalized["plan_type"] = plan_type
        normalized["status"] = status
        normalized.pop("steps", None)
        plan = ExecutionPlan.from_dict(normalized)
        plan.steps = sorted(
            (cls._build_step(s, plan.plan_id) for s in data.get("steps", [])),
            key=cls._step_sort_key,
        )
        return plan

    def _assemble(self, report: ExecutionPlanReport) -> dict[str, Any]:
        # Duplicate plan detection: same
        # (capability_id, readiness_id, chain_id, plan_type). Keep first.
        seen: set[tuple[str, str, str, str]] = set()
        deduped: list[ExecutionPlan] = []
        duplicates = 0
        for p in sorted(report.plans, key=self._plan_sort_key):
            key = (p.capability_id, p.readiness_id, p.chain_id, p.plan_type)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            deduped.append(p)
        report.plans = deduped
        report.duplicate_plan_count = duplicates

        status_counts: dict[str, int] = {}
        plan_type_counts: dict[str, int] = {}
        step_count = 0
        for p in report.plans:
            status_counts[p.status] = status_counts.get(p.status, 0) + 1
            plan_type_counts[p.plan_type] = (
                plan_type_counts.get(p.plan_type, 0) + 1
            )
            step_count += len(p.steps)

        report.status_counts = {
            k: status_counts[k] for k in sorted(status_counts)
        }
        report.plan_type_counts = {
            k: plan_type_counts[k] for k in sorted(plan_type_counts)
        }
        report.step_count = step_count
        report.blocked_count = status_counts.get(
            ExecutionPlanStatus.BLOCKED.value, 0
        )
        report.failed_count = status_counts.get(
            ExecutionPlanStatus.FAILED.value, 0
        )
        report.plan_count = len(report.plans)

        return report.to_dict()

    # ------------------------------------------------------------------
    # Create / Append (append-only)
    # ------------------------------------------------------------------

    def create(
        self,
        plans: list[dict[str, Any]] | None = None,
        raw_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new execution plan report."""
        report = ExecutionPlanReport(
            raw_metadata=dict(raw_metadata or {}),
        )
        report.plans = [self._build_plan(p) for p in (plans or [])]
        assembled = self._assemble(report)
        self._persist(assembled)
        self._write_evidence(assembled)
        return assembled

    def append(
        self,
        report_id: str,
        plans: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Append execution plan records to a report (append-only)."""
        self._validate_id_segment(report_id, "report_id")
        existing = self._load_report(report_id)
        if existing is None:
            raise ValueError(f"Report not found: {report_id}")

        report = ExecutionPlanReport(
            report_id=existing["report_id"],
            created_at=existing.get("created_at", ""),
            raw_metadata=dict(existing.get("raw_metadata", {})),
            schema_version=existing.get("schema_version", SCHEMA_VERSION),
        )
        report.plans = [
            ExecutionPlan.from_dict(p) for p in existing.get("plans", [])
        ]
        report.plans.extend(self._build_plan(p) for p in (plans or []))

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
            "plans": report.get("plans", []),
            "raw_metadata": report.get("raw_metadata", {}),
        }
        (evidence_dir / "execution_plan_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_plan_result.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_plan_summary.md").write_text(
            self._generate_export_md(report), encoding="utf-8"
        )

        plan_count = report.get("plan_count", 0)
        step_count = report.get("step_count", 0)
        blocked_count = report.get("blocked_count", 0)
        failed_count = report.get("failed_count", 0)
        duplicate_plan_count = report.get("duplicate_plan_count", 0)
        evidence = ExecutionPlanEvidence(
            report_id=report["report_id"],
            summary=(
                f"{plan_count} plan(s), "
                f"{step_count} step(s), "
                f"{blocked_count} blocked, "
                f"{failed_count} failed, "
                f"{duplicate_plan_count} duplicate(s)"
            ),
        )

        # A report passes when it carries at least one plan and no plan is
        # blocked or failed.
        passed = (
            plan_count > 0 and blocked_count == 0 and failed_count == 0
        )
        pass_fail = {
            "passed": passed,
            "report_id": report["report_id"],
            "evidence_id": evidence.evidence_id,
            "plan_count": plan_count,
            "step_count": step_count,
            "blocked_count": blocked_count,
            "failed_count": failed_count,
            "duplicate_plan_count": duplicate_plan_count,
            "status_counts": dict(report.get("status_counts", {})),
            "plan_type_counts": dict(report.get("plan_type_counts", {})),
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

        lines.append("# Execution Plan Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append(f"- Schema Version: {data.get('schema_version', '')}")
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Plans: {data.get('plan_count', 0)}")
        lines.append(f"- Blocked: {data.get('blocked_count', 0)}")
        lines.append(f"- Failed: {data.get('failed_count', 0)}")
        lines.append(f"- Steps: {data.get('step_count', 0)}")
        lines.append(
            f"- Duplicate Plans: {data.get('duplicate_plan_count', 0)}"
        )
        lines.append("")

        status_counts = data.get("status_counts", {})
        lines.append("## Status Counts")
        lines.append("")
        for status in sorted(status_counts):
            lines.append(f"- {status}: {status_counts[status]}")
        lines.append("")

        plan_type_counts = data.get("plan_type_counts", {})
        lines.append("## Plan Type Counts")
        lines.append("")
        for ptype in sorted(plan_type_counts):
            lines.append(f"- {ptype}: {plan_type_counts[ptype]}")
        lines.append("")

        lines.append("## Plans")
        lines.append("")
        for p in data.get("plans", []):
            status = p.get("status", "")
            plan_type = p.get("plan_type", "")
            capability_id = p.get("capability_id", "")
            readiness_id = p.get("readiness_id", "")
            chain_id = p.get("chain_id", "")
            lines.append(
                f"- [{status}] [{plan_type}] capability={capability_id} "
                f"readiness={readiness_id} chain={chain_id}"
            )
            for step in p.get("steps", []):
                order_index = step.get("order_index", 0)
                step_name = step.get("step_name", "")
                lines.append(f"  - [{order_index}] {step_name}")
        lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _generate_export_csv(data: dict[str, Any]) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "record_kind",
                "plan_id",
                "capability_id",
                "readiness_id",
                "chain_id",
                "plan_type",
                "status",
                "step_id",
                "order_index",
                "step_name",
                "summary",
            ]
        )
        for p in data.get("plans", []):
            writer.writerow(
                [
                    "plan",
                    p.get("plan_id", ""),
                    p.get("capability_id", ""),
                    p.get("readiness_id", ""),
                    p.get("chain_id", ""),
                    p.get("plan_type", ""),
                    p.get("status", ""),
                    "",
                    "",
                    "",
                    p.get("summary", ""),
                ]
            )
            for step in p.get("steps", []):
                writer.writerow(
                    [
                        "step",
                        p.get("plan_id", ""),
                        "",
                        "",
                        "",
                        "",
                        "",
                        step.get("step_id", ""),
                        step.get("order_index", 0),
                        step.get("step_name", ""),
                        step.get("summary", ""),
                    ]
                )
        return buf.getvalue()
