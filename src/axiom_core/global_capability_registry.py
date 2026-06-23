"""Global Capability Registry Framework v1.

Canonical identity layer for Program 1. GitHub PR numbers are repository-local;
the Global Capability ID / number becomes the primary identity so capability
history remains continuous across repositories, workers, and future systems.
Repository PR numbers become references.

Non-goals: no GitHub API, no automation, no orchestration, no event timeline.
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


class GlobalCapabilityStatus(str, Enum):
    PROPOSED = "proposed"
    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"
    SUPERSEDED = "superseded"


_VALID_STATUSES = {s.value for s in GlobalCapabilityStatus}


# ---------------------------------------------------------------------------
# Reference / summary models
# ---------------------------------------------------------------------------


@dataclass
class GlobalCapabilityRepositoryRef:
    """Reference to the repository-local artifacts for a capability."""

    repository_owner: str = ""
    repository_name: str = ""
    repository_pr_number: int = 0
    repository_pr_url: str = ""
    branch_name: str = ""
    commit_sha: str = ""
    merge_sha: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository_owner": self.repository_owner,
            "repository_name": self.repository_name,
            "repository_pr_number": self.repository_pr_number,
            "repository_pr_url": self.repository_pr_url,
            "branch_name": self.branch_name,
            "commit_sha": self.commit_sha,
            "merge_sha": self.merge_sha,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GlobalCapabilityRepositoryRef:
        return cls(
            repository_owner=data.get("repository_owner", ""),
            repository_name=data.get("repository_name", ""),
            repository_pr_number=int(data.get("repository_pr_number", 0)),
            repository_pr_url=data.get("repository_pr_url", ""),
            branch_name=data.get("branch_name", ""),
            commit_sha=data.get("commit_sha", ""),
            merge_sha=data.get("merge_sha", ""),
        )


@dataclass
class GlobalCapabilityWorkerRef:
    """Reference to the worker that produced a capability."""

    worker_id: str = ""
    worker_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"worker_id": self.worker_id, "worker_type": self.worker_type}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GlobalCapabilityWorkerRef:
        return cls(
            worker_id=data.get("worker_id", ""),
            worker_type=data.get("worker_type", ""),
        )


@dataclass
class GlobalCapabilityValidationSummary:
    """Validation evidence captured for a capability."""

    new_tests: int = 0
    total_tests: int = 0
    skipped_tests: int = 0
    ruff_clean: bool = False
    ci_status: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "new_tests": self.new_tests,
            "total_tests": self.total_tests,
            "skipped_tests": self.skipped_tests,
            "ruff_clean": self.ruff_clean,
            "ci_status": self.ci_status,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any]
    ) -> GlobalCapabilityValidationSummary:
        return cls(
            new_tests=int(data.get("new_tests", 0)),
            total_tests=int(data.get("total_tests", 0)),
            skipped_tests=int(data.get("skipped_tests", 0)),
            ruff_clean=bool(data.get("ruff_clean", False)),
            ci_status=data.get("ci_status", ""),
            notes=data.get("notes", ""),
        )


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


@dataclass
class GlobalCapabilityEntry:
    """A single canonical capability identity record."""

    global_capability_id: str = ""
    global_capability_number: int = 0
    capability_name: str = ""
    worker: GlobalCapabilityWorkerRef = field(
        default_factory=GlobalCapabilityWorkerRef
    )
    repository: GlobalCapabilityRepositoryRef = field(
        default_factory=GlobalCapabilityRepositoryRef
    )
    validation: GlobalCapabilityValidationSummary = field(
        default_factory=GlobalCapabilityValidationSummary
    )
    primary_program: str = ""
    secondary_programs: list[str] = field(default_factory=list)
    parent_capability_ids: list[str] = field(default_factory=list)
    related_capability_ids: list[str] = field(default_factory=list)
    affected_files: list[str] = field(default_factory=list)
    status: str = "proposed"
    created_at: str = ""
    updated_at: str = ""
    schema_version: str = SCHEMA_VERSION
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.global_capability_id:
            self.global_capability_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "global_capability_id": self.global_capability_id,
            "global_capability_number": self.global_capability_number,
            "capability_name": self.capability_name,
            "worker": self.worker.to_dict(),
            "repository": self.repository.to_dict(),
            "validation": self.validation.to_dict(),
            "primary_program": self.primary_program,
            "secondary_programs": list(self.secondary_programs),
            "parent_capability_ids": list(self.parent_capability_ids),
            "related_capability_ids": list(self.related_capability_ids),
            "affected_files": list(self.affected_files),
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "schema_version": self.schema_version,
            "raw_metadata": dict(self.raw_metadata),
        }


# ---------------------------------------------------------------------------
# Registry (in-memory collection)
# ---------------------------------------------------------------------------


@dataclass
class GlobalCapabilityRegistry:
    """An ordered, de-duplicated collection of global capability entries."""

    entries: list[GlobalCapabilityEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"entries": [e.to_dict() for e in self.entries]}


# ---------------------------------------------------------------------------
# Report / Evidence
# ---------------------------------------------------------------------------


@dataclass
class GlobalCapabilityReport:
    """Report summarizing the global capability registry."""

    report_id: str = ""
    entry_count: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    program_counts: dict[str, int] = field(default_factory=dict)
    created_at: str = ""
    schema_version: str = SCHEMA_VERSION
    entries: list[GlobalCapabilityEntry] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "entry_count": self.entry_count,
            "status_counts": dict(self.status_counts),
            "program_counts": dict(self.program_counts),
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "entries": [e.to_dict() for e in self.entries],
        }


@dataclass
class GlobalCapabilityEvidence:
    """Evidence record for a global capability registry report."""

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


class GlobalCapabilityRegistryEngine:
    """Manages global capability registry reports deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "global_capability_registry"
        self._report_dir.mkdir(parents=True, exist_ok=True)

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

    @staticmethod
    def _sort_key(entry: GlobalCapabilityEntry) -> tuple:
        # Authoritative global ordering.
        return (
            entry.global_capability_number,
            entry.created_at,
            entry.repository.repository_owner,
            entry.repository.repository_name,
            entry.repository.repository_pr_number,
            entry.global_capability_id,
        )

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(
        self, entries: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Create a global capability registry report from entries."""
        entries = entries or []

        entry_objects: list[GlobalCapabilityEntry] = []
        seen_numbers: dict[int, str] = {}
        for e_data in entries:
            number = e_data.get("global_capability_number")
            if number is None:
                raise ValueError(
                    "global_capability_number is required for an entry"
                )
            number = int(number)
            capability_name = e_data.get("capability_name", "")
            if not capability_name or not capability_name.strip():
                raise ValueError("capability_name is required for an entry")

            if number in seen_numbers:
                raise ValueError(
                    f"Duplicate global_capability_number: {number} "
                    f"(already used by {seen_numbers[number]!r})"
                )

            status = e_data.get("status", "proposed")
            if status not in _VALID_STATUSES:
                raise ValueError(
                    f"Invalid status: {status!r}. "
                    f"Valid: {sorted(_VALID_STATUSES)}"
                )

            entry = GlobalCapabilityEntry(
                global_capability_id=e_data.get("global_capability_id", ""),
                global_capability_number=number,
                capability_name=capability_name,
                worker=GlobalCapabilityWorkerRef.from_dict(
                    e_data.get("worker", {})
                ),
                repository=GlobalCapabilityRepositoryRef.from_dict(
                    e_data.get("repository", {})
                ),
                validation=GlobalCapabilityValidationSummary.from_dict(
                    e_data.get("validation", {})
                ),
                primary_program=e_data.get("primary_program", ""),
                secondary_programs=list(e_data.get("secondary_programs", [])),
                parent_capability_ids=list(
                    e_data.get("parent_capability_ids", [])
                ),
                related_capability_ids=list(
                    e_data.get("related_capability_ids", [])
                ),
                affected_files=list(e_data.get("affected_files", [])),
                status=status,
                created_at=e_data.get("created_at", ""),
                updated_at=e_data.get("updated_at", ""),
                schema_version=e_data.get("schema_version", SCHEMA_VERSION),
                raw_metadata=dict(e_data.get("raw_metadata", {})),
            )
            seen_numbers[number] = capability_name
            entry_objects.append(entry)

        entry_objects.sort(key=self._sort_key)

        status_counts: dict[str, int] = {}
        program_counts: dict[str, int] = {}
        for e in entry_objects:
            status_counts[e.status] = status_counts.get(e.status, 0) + 1
            if e.primary_program:
                program_counts[e.primary_program] = (
                    program_counts.get(e.primary_program, 0) + 1
                )
        status_counts = {k: status_counts[k] for k in sorted(status_counts)}
        program_counts = {k: program_counts[k] for k in sorted(program_counts)}

        report = GlobalCapabilityReport(
            entry_count=len(entry_objects),
            status_counts=status_counts,
            program_counts=program_counts,
            entries=entry_objects,
        )

        self._persist(report)
        self._write_evidence(report)

        return report.to_dict()

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
            if not str(resolved).startswith(str(sandbox) + "/") and resolved != sandbox:
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
            raise ValueError(
                f"Global capability registry report not found: {report_id}"
            )
        fmt = (fmt or "markdown").lower()
        if fmt == "json":
            return json.dumps(data, indent=2, default=str)
        if fmt == "csv":
            return self._generate_export_csv(data)
        if fmt == "markdown":
            return self._generate_export_md(data)
        raise ValueError(
            f"Invalid export format: {fmt!r}. Valid: ['csv', 'json', 'markdown']"
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, report: GlobalCapabilityReport) -> None:
        report_dir = self._safe_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
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

    def _write_evidence(self, report: GlobalCapabilityReport) -> None:
        evidence_dir = self._safe_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {"entries": [e.to_dict() for e in report.entries]}
        (evidence_dir / "global_capability_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "global_capability_result.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_export_md(report.to_dict())
        (evidence_dir / "global_capability_summary.md").write_text(
            md, encoding="utf-8"
        )

        (evidence_dir / "global_capability_timeline.csv").write_text(
            self._generate_export_csv(report.to_dict()),
            encoding="utf-8",
        )

        evidence = GlobalCapabilityEvidence(
            report_id=report.report_id,
            summary=(
                f"{report.entry_count} global capabilities, "
                f"{len(report.status_counts)} statuses, "
                f"{len(report.program_counts)} programs"
            ),
        )

        # A registry report passes when every entry has a unique global number
        # (enforced at create time) and at least one entry is present.
        passed = report.entry_count > 0
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "evidence_id": evidence.evidence_id,
            "entry_count": report.entry_count,
            "status_counts": dict(report.status_counts),
            "program_counts": dict(report.program_counts),
            "schema_version": report.schema_version,
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

    @staticmethod
    def _generate_export_md(data: dict[str, Any]) -> str:
        lines: list[str] = []

        lines.append("# Global Capability Registry")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append(f"- Schema Version: {data.get('schema_version', '')}")
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Entries: {data.get('entry_count', 0)}")
        lines.append("")

        status_counts = data.get("status_counts", {})
        lines.append("## Status Counts")
        lines.append("")
        for status in sorted(status_counts):
            lines.append(f"- {status.upper()}: {status_counts[status]}")
        lines.append("")

        program_counts = data.get("program_counts", {})
        lines.append("## Program Counts")
        lines.append("")
        for program in sorted(program_counts):
            lines.append(f"- {program}: {program_counts[program]}")
        lines.append("")

        entries = data.get("entries", [])
        if entries:
            lines.append("## Timeline")
            lines.append("")
            for e in entries:
                number = e.get("global_capability_number", 0)
                name = e.get("capability_name", "")
                status = e.get("status", "").upper()
                repo = e.get("repository", {})
                owner = repo.get("repository_owner", "")
                repo_name = repo.get("repository_name", "")
                pr_number = repo.get("repository_pr_number", 0)
                lines.append(
                    f"- #{number} {name} [{status}] "
                    f"({owner}/{repo_name} PR #{pr_number})"
                )
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _generate_export_csv(data: dict[str, Any]) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "global_capability_number",
                "global_capability_id",
                "capability_name",
                "status",
                "primary_program",
                "worker_id",
                "worker_type",
                "repository_owner",
                "repository_name",
                "repository_pr_number",
                "repository_pr_url",
                "branch_name",
                "commit_sha",
                "merge_sha",
                "created_at",
                "schema_version",
            ]
        )
        for e in data.get("entries", []):
            repo = e.get("repository", {})
            worker = e.get("worker", {})
            writer.writerow(
                [
                    e.get("global_capability_number", 0),
                    e.get("global_capability_id", ""),
                    e.get("capability_name", ""),
                    e.get("status", ""),
                    e.get("primary_program", ""),
                    worker.get("worker_id", ""),
                    worker.get("worker_type", ""),
                    repo.get("repository_owner", ""),
                    repo.get("repository_name", ""),
                    repo.get("repository_pr_number", 0),
                    repo.get("repository_pr_url", ""),
                    repo.get("branch_name", ""),
                    repo.get("commit_sha", ""),
                    repo.get("merge_sha", ""),
                    e.get("created_at", ""),
                    e.get("schema_version", ""),
                ]
            )
        return buf.getvalue()
