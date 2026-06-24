"""Execution Context Framework v1.

The execution-context layer resumes the autonomous engineering roadmap on top
of the Capability Chain Framework and the Capability Knowledge Graph. Where the
Global Capability Registry establishes identity, the Timeline establishes
memory, and the Knowledge Graph establishes structure, this layer represents the
*state in which execution occurs*: for a given work item / capability / chain,
what kind of execution context it is (implementation, validation, repair, ...),
what state it is in (ready, blocked, running, completed, failed, ...), and which
upstream objects it references.

Per report it captures a deterministic, append-only set of execution contexts,
aggregated with state counts and context-type counts, blocked- and
failed-context detection, and duplicate-context detection, with preserved raw
payloads and schema versioning.

It is deliberately *structure only*. Non-goals: no execution engine, no
scheduling, no worker orchestration, no autonomous execution, no graph query
language, no dashboard, no network calls, no architecture changes. The upstream
chain / work-item / graph layers are consumed read-only; nothing is mutated.
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


class ExecutionContextType(str, Enum):
    IMPLEMENTATION = "IMPLEMENTATION"
    VALIDATION = "VALIDATION"
    REPAIR = "REPAIR"
    REVIEW = "REVIEW"
    REPORTING = "REPORTING"
    INVESTIGATION = "INVESTIGATION"
    OTHER = "OTHER"


class ExecutionContextState(str, Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class ExecutionContextReferenceType(str, Enum):
    CAPABILITY = "CAPABILITY"
    WORK_ITEM = "WORK_ITEM"
    CHAIN = "CHAIN"
    FILE = "FILE"
    VALIDATION = "VALIDATION"
    GRAPH_NODE = "GRAPH_NODE"
    GRAPH_EDGE = "GRAPH_EDGE"
    ARTIFACT = "ARTIFACT"
    OTHER = "OTHER"


_VALID_CONTEXT_TYPES = {t.value for t in ExecutionContextType}
_VALID_STATES = {t.value for t in ExecutionContextState}
_VALID_REFERENCE_TYPES = {t.value for t in ExecutionContextReferenceType}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class ExecutionContextReference:
    """A single reference from an execution context to an upstream object."""

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
    def from_dict(cls, data: dict[str, Any]) -> ExecutionContextReference:
        return cls(
            reference_id=data.get("reference_id", ""),
            reference_type=data.get("reference_type", ""),
            reference_value=data.get("reference_value", ""),
            summary=data.get("summary", ""),
        )


@dataclass
class ExecutionContext:
    """A single execution context."""

    context_id: str = ""
    work_id: str = ""
    capability_id: str = ""
    chain_id: str = ""
    context_type: str = ""
    state: str = ""
    references: list[ExecutionContextReference] = field(default_factory=list)
    summary: str = ""
    created_at: str = ""
    schema_version: str = SCHEMA_VERSION
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.context_id:
            self.context_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_id": self.context_id,
            "work_id": self.work_id,
            "capability_id": self.capability_id,
            "chain_id": self.chain_id,
            "context_type": self.context_type,
            "state": self.state,
            "references": [r.to_dict() for r in self.references],
            "summary": self.summary,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "raw_payload": dict(self.raw_payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionContext:
        return cls(
            context_id=data.get("context_id", ""),
            work_id=data.get("work_id", ""),
            capability_id=data.get("capability_id", ""),
            chain_id=data.get("chain_id", ""),
            context_type=data.get("context_type", ""),
            state=data.get("state", ""),
            references=[
                ExecutionContextReference.from_dict(r)
                for r in data.get("references", [])
            ],
            summary=data.get("summary", ""),
            created_at=data.get("created_at", ""),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            raw_payload=dict(data.get("raw_payload", {})),
        )


@dataclass
class ExecutionContextReport:
    """A deterministic, append-only execution context report."""

    report_id: str = ""
    contexts: list[ExecutionContext] = field(default_factory=list)
    context_count: int = 0
    state_counts: dict[str, int] = field(default_factory=dict)
    context_type_counts: dict[str, int] = field(default_factory=dict)
    blocked_count: int = 0
    failed_count: int = 0
    duplicate_context_count: int = 0
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
            "contexts": [c.to_dict() for c in self.contexts],
            "context_count": self.context_count,
            "state_counts": dict(self.state_counts),
            "context_type_counts": dict(self.context_type_counts),
            "blocked_count": self.blocked_count,
            "failed_count": self.failed_count,
            "duplicate_context_count": self.duplicate_context_count,
            "created_at": self.created_at,
            "raw_metadata": dict(self.raw_metadata),
            "schema_version": self.schema_version,
        }


@dataclass
class ExecutionContextEvidence:
    """Evidence record for an execution context report."""

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


class ExecutionContextEngine:
    """Manages execution context reports deterministically.

    Execution contexts are validated, deduplicated, ordered deterministically,
    and aggregated with state counts, context-type counts, and blocked/failed
    detection. Reports are append-only. The upstream chain / work-item / graph
    layers are *consumed* read-only; nothing is mutated.
    """

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "execution_context"
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
    def _context_sort_key(c: ExecutionContext) -> tuple:
        return (
            c.work_id,
            c.capability_id,
            c.chain_id,
            c.context_type,
            c.state,
            c.context_id,
        )

    @staticmethod
    def _reference_sort_key(r: ExecutionContextReference) -> tuple:
        return (r.reference_type, r.reference_value, r.reference_id)

    # ------------------------------------------------------------------
    # Building / validation
    # ------------------------------------------------------------------

    @classmethod
    def _build_reference(
        cls, data: dict[str, Any]
    ) -> ExecutionContextReference:
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
        return ExecutionContextReference.from_dict(normalized)

    @classmethod
    def _build_context(cls, data: dict[str, Any]) -> ExecutionContext:
        work_id = data.get("work_id", "")
        if not work_id or not str(work_id).strip():
            raise ValueError("work_id is required for an execution context")
        capability_id = data.get("capability_id", "")
        if not capability_id or not str(capability_id).strip():
            raise ValueError(
                "capability_id is required for an execution context"
            )

        ctype_raw = data.get("context_type", "")
        if not ctype_raw or not str(ctype_raw).strip():
            raise ValueError(
                "context_type is required for an execution context"
            )
        ctype = str(ctype_raw).strip().upper()
        if ctype not in _VALID_CONTEXT_TYPES:
            raise ValueError(
                f"Invalid context_type: {ctype_raw!r}. "
                f"Valid: {sorted(_VALID_CONTEXT_TYPES)}"
            )

        state_raw = data.get("state", "")
        if not state_raw or not str(state_raw).strip():
            raise ValueError("state is required for an execution context")
        state = str(state_raw).strip().upper()
        if state not in _VALID_STATES:
            raise ValueError(
                f"Invalid state: {state_raw!r}. Valid: {sorted(_VALID_STATES)}"
            )

        references = sorted(
            (cls._build_reference(r) for r in data.get("references", [])),
            key=cls._reference_sort_key,
        )

        normalized = dict(data)
        normalized["work_id"] = str(work_id)
        normalized["capability_id"] = str(capability_id)
        normalized["chain_id"] = str(data.get("chain_id", ""))
        normalized["context_type"] = ctype
        normalized["state"] = state
        normalized.pop("references", None)
        context = ExecutionContext.from_dict(normalized)
        context.references = references
        return context

    def _assemble(self, report: ExecutionContextReport) -> dict[str, Any]:
        # Duplicate context detection: same
        # (work_id, capability_id, chain_id, context_type). Keep first.
        seen: set[tuple[str, str, str, str]] = set()
        deduped: list[ExecutionContext] = []
        duplicates = 0
        for c in sorted(report.contexts, key=self._context_sort_key):
            key = (c.work_id, c.capability_id, c.chain_id, c.context_type)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            deduped.append(c)
        report.contexts = deduped
        report.duplicate_context_count = duplicates

        state_counts: dict[str, int] = {}
        context_type_counts: dict[str, int] = {}
        for c in report.contexts:
            state_counts[c.state] = state_counts.get(c.state, 0) + 1
            context_type_counts[c.context_type] = (
                context_type_counts.get(c.context_type, 0) + 1
            )

        report.state_counts = {
            k: state_counts[k] for k in sorted(state_counts)
        }
        report.context_type_counts = {
            k: context_type_counts[k] for k in sorted(context_type_counts)
        }
        report.blocked_count = state_counts.get(
            ExecutionContextState.BLOCKED.value, 0
        )
        report.failed_count = state_counts.get(
            ExecutionContextState.FAILED.value, 0
        )
        report.context_count = len(report.contexts)

        return report.to_dict()

    # ------------------------------------------------------------------
    # Create / Append (append-only)
    # ------------------------------------------------------------------

    def create(
        self,
        contexts: list[dict[str, Any]] | None = None,
        raw_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new execution context report."""
        report = ExecutionContextReport(
            raw_metadata=dict(raw_metadata or {}),
        )
        report.contexts = [
            self._build_context(c) for c in (contexts or [])
        ]
        assembled = self._assemble(report)
        self._persist(assembled)
        self._write_evidence(assembled)
        return assembled

    def append(
        self,
        report_id: str,
        contexts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Append execution contexts to an existing report (append-only)."""
        self._validate_id_segment(report_id, "report_id")
        existing = self._load_report(report_id)
        if existing is None:
            raise ValueError(f"Report not found: {report_id}")

        report = ExecutionContextReport(
            report_id=existing["report_id"],
            created_at=existing.get("created_at", ""),
            raw_metadata=dict(existing.get("raw_metadata", {})),
            schema_version=existing.get("schema_version", SCHEMA_VERSION),
        )
        report.contexts = [
            ExecutionContext.from_dict(c)
            for c in existing.get("contexts", [])
        ]
        report.contexts.extend(
            self._build_context(c) for c in (contexts or [])
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
            "contexts": report.get("contexts", []),
            "raw_metadata": report.get("raw_metadata", {}),
        }
        (evidence_dir / "execution_context_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_context_result.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "execution_context_summary.md").write_text(
            self._generate_export_md(report), encoding="utf-8"
        )

        context_count = report.get("context_count", 0)
        blocked_count = report.get("blocked_count", 0)
        failed_count = report.get("failed_count", 0)
        duplicate_context_count = report.get("duplicate_context_count", 0)
        evidence = ExecutionContextEvidence(
            report_id=report["report_id"],
            summary=(
                f"{context_count} context(s), "
                f"{blocked_count} blocked, "
                f"{failed_count} failed, "
                f"{duplicate_context_count} duplicate(s)"
            ),
        )

        # A report passes when it carries at least one context and no context
        # is blocked or failed.
        passed = (
            context_count > 0
            and blocked_count == 0
            and failed_count == 0
        )
        pass_fail = {
            "passed": passed,
            "report_id": report["report_id"],
            "evidence_id": evidence.evidence_id,
            "context_count": context_count,
            "blocked_count": blocked_count,
            "failed_count": failed_count,
            "duplicate_context_count": duplicate_context_count,
            "state_counts": dict(report.get("state_counts", {})),
            "context_type_counts": dict(
                report.get("context_type_counts", {})
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

        lines.append("# Execution Context Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append(f"- Schema Version: {data.get('schema_version', '')}")
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Contexts: {data.get('context_count', 0)}")
        lines.append(f"- Blocked: {data.get('blocked_count', 0)}")
        lines.append(f"- Failed: {data.get('failed_count', 0)}")
        lines.append(
            f"- Duplicate Contexts: {data.get('duplicate_context_count', 0)}"
        )
        lines.append("")

        state_counts = data.get("state_counts", {})
        lines.append("## State Counts")
        lines.append("")
        for state in sorted(state_counts):
            lines.append(f"- {state}: {state_counts[state]}")
        lines.append("")

        context_type_counts = data.get("context_type_counts", {})
        lines.append("## Context Type Counts")
        lines.append("")
        for ctype in sorted(context_type_counts):
            lines.append(f"- {ctype}: {context_type_counts[ctype]}")
        lines.append("")

        lines.append("## Contexts")
        lines.append("")
        for c in data.get("contexts", []):
            state = c.get("state", "")
            ctype = c.get("context_type", "")
            work_id = c.get("work_id", "")
            capability_id = c.get("capability_id", "")
            chain_id = c.get("chain_id", "")
            lines.append(
                f"- [{state}] [{ctype}] work={work_id} "
                f"capability={capability_id} chain={chain_id}"
            )
            for r in c.get("references", []):
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
                "context_id",
                "work_id",
                "capability_id",
                "chain_id",
                "context_type",
                "state",
                "reference_id",
                "reference_type",
                "reference_value",
                "summary",
            ]
        )
        for c in data.get("contexts", []):
            writer.writerow(
                [
                    "context",
                    c.get("context_id", ""),
                    c.get("work_id", ""),
                    c.get("capability_id", ""),
                    c.get("chain_id", ""),
                    c.get("context_type", ""),
                    c.get("state", ""),
                    "",
                    "",
                    "",
                    c.get("summary", ""),
                ]
            )
            for r in c.get("references", []):
                writer.writerow(
                    [
                        "reference",
                        c.get("context_id", ""),
                        "",
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
