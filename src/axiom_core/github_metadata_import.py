"""GitHub Metadata Import Framework v1.

Deterministically ingest structured GitHub metadata (PR, commits, changed
files, labels) into shapes consumable by the Global Capability Registry and the
Capability Event Timeline, so Program 1 captures information machines already
know and preserves a single engineering narrative across repositories and
workers.

This framework performs read-only metadata ingestion from a provided payload
(no network calls, no GitHub API, no GitHub mutation). It produces, but never
mutates, registry entries and timeline events: a derived registry entry and
PR_CREATED / PR_READY / PR_MERGED timeline events are built from the imported
metadata. Raw payloads, schema version, and manual overrides are preserved.

Non-goals: no worker orchestration, no automatic PR sequencing, no Devin
metadata import, no Operator Cockpit UI, no GitHub mutation, no architecture
changes.
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
from axiom_core.capability_event_timeline import (
    CapabilityEvent,
    CapabilityEventReference,
    CapabilityEventType,
)
from axiom_core.global_capability_registry import (
    GlobalCapabilityEntry,
    GlobalCapabilityRepositoryRef,
    GlobalCapabilityWorkerRef,
)

SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class GitHubMetadataImportStatus(str, Enum):
    IMPORTED = "imported"
    PARTIAL_IMPORT = "partial_import"
    FAILED = "failed"


_VALID_IMPORT_STATUSES = {s.value for s in GitHubMetadataImportStatus}

# Map a GitHub PR status onto a Global Capability Registry status.
_PR_STATUS_TO_REGISTRY_STATUS = {
    "open": "open",
    "draft": "proposed",
    "merged": "merged",
    "closed": "closed",
}


# ---------------------------------------------------------------------------
# Metadata models
# ---------------------------------------------------------------------------


@dataclass
class GitHubLabelMetadata:
    """A GitHub label attached to a pull request."""

    name: str = ""
    color: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "color": self.color,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GitHubLabelMetadata:
        return cls(
            name=data.get("name", ""),
            color=data.get("color", ""),
            description=data.get("description", ""),
        )


@dataclass
class GitHubCommitMetadata:
    """A single commit captured from GitHub PR metadata."""

    commit_sha: str = ""
    author: str = ""
    message: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "commit_sha": self.commit_sha,
            "author": self.author,
            "message": self.message,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GitHubCommitMetadata:
        return cls(
            commit_sha=data.get("commit_sha", ""),
            author=data.get("author", ""),
            message=data.get("message", ""),
            timestamp=data.get("timestamp", ""),
        )


@dataclass
class GitHubFileChangeMetadata:
    """A single changed file captured from GitHub PR metadata."""

    path: str = ""
    status: str = ""
    additions: int = 0
    deletions: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "status": self.status,
            "additions": self.additions,
            "deletions": self.deletions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GitHubFileChangeMetadata:
        return cls(
            path=data.get("path", ""),
            status=data.get("status", ""),
            additions=int(data.get("additions", 0)),
            deletions=int(data.get("deletions", 0)),
        )


@dataclass
class GitHubPRMetadata:
    """Pull request metadata captured from GitHub."""

    repository_owner: str = ""
    repository_name: str = ""
    repository_pr_number: int = 0
    repository_pr_url: str = ""
    title: str = ""
    description: str = ""
    author: str = ""
    branch_name: str = ""
    labels: list[GitHubLabelMetadata] = field(default_factory=list)
    status: str = ""
    merge_commit_sha: str = ""
    created_at: str = ""
    updated_at: str = ""
    merged_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository_owner": self.repository_owner,
            "repository_name": self.repository_name,
            "repository_pr_number": self.repository_pr_number,
            "repository_pr_url": self.repository_pr_url,
            "title": self.title,
            "description": self.description,
            "author": self.author,
            "branch_name": self.branch_name,
            "labels": [label.to_dict() for label in self.labels],
            "status": self.status,
            "merge_commit_sha": self.merge_commit_sha,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "merged_at": self.merged_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GitHubPRMetadata:
        return cls(
            repository_owner=data.get("repository_owner", ""),
            repository_name=data.get("repository_name", ""),
            repository_pr_number=int(data.get("repository_pr_number", 0)),
            repository_pr_url=data.get("repository_pr_url", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            author=data.get("author", ""),
            branch_name=data.get("branch_name", ""),
            labels=[
                GitHubLabelMetadata.from_dict(label)
                for label in data.get("labels", [])
            ],
            status=data.get("status", ""),
            merge_commit_sha=data.get("merge_commit_sha", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            merged_at=data.get("merged_at", ""),
        )


# ---------------------------------------------------------------------------
# Import / Report / Evidence
# ---------------------------------------------------------------------------


@dataclass
class GitHubMetadataImport:
    """A single deterministic GitHub metadata import."""

    import_id: str = ""
    global_capability_number: int = 0
    pr: GitHubPRMetadata = field(default_factory=GitHubPRMetadata)
    commits: list[GitHubCommitMetadata] = field(default_factory=list)
    files: list[GitHubFileChangeMetadata] = field(default_factory=list)
    labels: list[GitHubLabelMetadata] = field(default_factory=list)
    status: str = GitHubMetadataImportStatus.IMPORTED.value
    skipped: list[str] = field(default_factory=list)
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.import_id:
            self.import_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "import_id": self.import_id,
            "global_capability_number": self.global_capability_number,
            "pr": self.pr.to_dict(),
            "commits": [c.to_dict() for c in self.commits],
            "files": [f.to_dict() for f in self.files],
            "labels": [label.to_dict() for label in self.labels],
            "status": self.status,
            "skipped": list(self.skipped),
            "raw_metadata": dict(self.raw_metadata),
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }


@dataclass
class GitHubMetadataImportReport:
    """Report summarizing a GitHub metadata import."""

    report_id: str = ""
    repository: str = ""
    repository_pr_number: int = 0
    global_capability_number: int = 0
    status: str = GitHubMetadataImportStatus.IMPORTED.value
    commit_count: int = 0
    file_count: int = 0
    label_count: int = 0
    total_additions: int = 0
    total_deletions: int = 0
    timeline_event_type_counts: dict[str, int] = field(default_factory=dict)
    metadata_import: GitHubMetadataImport = field(
        default_factory=GitHubMetadataImport
    )
    registry_entry: dict[str, Any] = field(default_factory=dict)
    timeline_events: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "repository": self.repository,
            "repository_pr_number": self.repository_pr_number,
            "global_capability_number": self.global_capability_number,
            "status": self.status,
            "commit_count": self.commit_count,
            "file_count": self.file_count,
            "label_count": self.label_count,
            "total_additions": self.total_additions,
            "total_deletions": self.total_deletions,
            "timeline_event_type_counts": dict(
                self.timeline_event_type_counts
            ),
            "metadata_import": self.metadata_import.to_dict(),
            "registry_entry": dict(self.registry_entry),
            "timeline_events": list(self.timeline_events),
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }


@dataclass
class GitHubMetadataImportEvidence:
    """Evidence record for a GitHub metadata import report."""

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


class GitHubMetadataImportEngine:
    """Imports GitHub metadata deterministically into registry/timeline shapes."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "github_metadata_import"
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
        if not is_within_sandbox(target, sandbox):
            raise ValueError(
                f"Resolved path escapes artifacts root: {report_id!r}"
            )
        return target

    @staticmethod
    def _timeline_sort_key(event: CapabilityEvent) -> tuple:
        return (
            event.timestamp,
            event.event_sequence,
            event.event_type,
            event.event_id,
        )

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def import_metadata(
        self,
        metadata: dict[str, Any] | None = None,
        repo: str | None = None,
        pr_number: int | None = None,
        global_capability_number: int | None = None,
    ) -> dict[str, Any]:
        """Import GitHub PR metadata deterministically.

        ``repo`` (``owner/name``), ``pr_number`` and ``global_capability_number``
        are manual overrides that take precedence over the metadata payload,
        preserving manual override capability.
        """
        metadata = dict(metadata or {})
        pr_data = dict(metadata.get("pr", {}))

        # Manual overrides take precedence over payload values.
        if repo is not None:
            owner, _, name = repo.partition("/")
            if not owner or not name:
                raise ValueError(
                    f"--repo must be in 'owner/name' form: {repo!r}"
                )
            pr_data["repository_owner"] = owner
            pr_data["repository_name"] = name
        if pr_number is not None:
            pr_data["repository_pr_number"] = int(pr_number)

        resolved_number = metadata.get("global_capability_number", 0)
        if global_capability_number is not None:
            resolved_number = int(global_capability_number)

        pr = GitHubPRMetadata.from_dict(pr_data)

        # PR identity is mandatory; malformed identity is a clear error.
        missing = [
            field_name
            for field_name, value in (
                ("repository_owner", pr.repository_owner),
                ("repository_name", pr.repository_name),
            )
            if not value or not str(value).strip()
        ]
        if pr.repository_pr_number <= 0:
            missing.append("repository_pr_number")
        if missing:
            raise ValueError(
                "Malformed PR metadata; missing required fields: "
                f"{sorted(set(missing))}"
            )

        # Duplicate imports (same repository + PR number) are rejected.
        self._reject_duplicate(
            pr.repository_owner, pr.repository_name, pr.repository_pr_number
        )

        skipped: list[str] = []
        commits = self._parse_commits(metadata.get("commits", []), skipped)
        files = self._parse_files(metadata.get("files", []), skipped)
        labels = self._parse_labels(
            metadata.get("labels", pr_data.get("labels", [])), skipped
        )
        pr.labels = list(labels)

        status = (
            GitHubMetadataImportStatus.PARTIAL_IMPORT.value
            if skipped
            else GitHubMetadataImportStatus.IMPORTED.value
        )

        metadata_import = GitHubMetadataImport(
            global_capability_number=int(resolved_number),
            pr=pr,
            commits=commits,
            files=files,
            labels=labels,
            status=status,
            skipped=skipped,
            raw_metadata=dict(metadata.get("raw_metadata", {})),
        )

        registry_entry = self._build_registry_entry(metadata_import)
        timeline_events = self._build_timeline_events(metadata_import)

        type_counts: dict[str, int] = {}
        for event in timeline_events:
            etype = event.get("event_type", "")
            type_counts[etype] = type_counts.get(etype, 0) + 1
        type_counts = {k: type_counts[k] for k in sorted(type_counts)}

        report = GitHubMetadataImportReport(
            repository=f"{pr.repository_owner}/{pr.repository_name}",
            repository_pr_number=pr.repository_pr_number,
            global_capability_number=metadata_import.global_capability_number,
            status=status,
            commit_count=len(commits),
            file_count=len(files),
            label_count=len(labels),
            total_additions=sum(f.additions for f in files),
            total_deletions=sum(f.deletions for f in files),
            timeline_event_type_counts=type_counts,
            metadata_import=metadata_import,
            registry_entry=registry_entry,
            timeline_events=timeline_events,
        )

        self._persist(report)
        self._write_evidence(report)
        return report.to_dict()

    # ------------------------------------------------------------------
    # Parsing helpers (malformed sub-records skipped, not fatal)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_commits(
        data: list[dict[str, Any]], skipped: list[str]
    ) -> list[GitHubCommitMetadata]:
        commits: list[GitHubCommitMetadata] = []
        for idx, c in enumerate(data):
            commit = GitHubCommitMetadata.from_dict(c)
            if not commit.commit_sha or not commit.commit_sha.strip():
                skipped.append(f"commit[{idx}]: missing commit_sha")
                continue
            commits.append(commit)
        commits.sort(key=lambda c: (c.timestamp, c.commit_sha))
        return commits

    @staticmethod
    def _parse_files(
        data: list[dict[str, Any]], skipped: list[str]
    ) -> list[GitHubFileChangeMetadata]:
        files: list[GitHubFileChangeMetadata] = []
        for idx, f in enumerate(data):
            change = GitHubFileChangeMetadata.from_dict(f)
            if not change.path or not change.path.strip():
                skipped.append(f"file[{idx}]: missing path")
                continue
            files.append(change)
        files.sort(key=lambda f: f.path)
        return files

    @staticmethod
    def _parse_labels(
        data: list[dict[str, Any]], skipped: list[str]
    ) -> list[GitHubLabelMetadata]:
        labels: list[GitHubLabelMetadata] = []
        for idx, label_data in enumerate(data):
            label = GitHubLabelMetadata.from_dict(label_data)
            if not label.name or not label.name.strip():
                skipped.append(f"label[{idx}]: missing name")
                continue
            labels.append(label)
        labels.sort(key=lambda label: label.name)
        return labels

    # ------------------------------------------------------------------
    # Integration: build (never mutate) registry entry + timeline events
    # ------------------------------------------------------------------

    @staticmethod
    def _build_registry_entry(
        metadata_import: GitHubMetadataImport,
    ) -> dict[str, Any]:
        pr = metadata_import.pr
        registry_status = _PR_STATUS_TO_REGISTRY_STATUS.get(
            pr.status.lower(), "proposed"
        )
        entry = GlobalCapabilityEntry(
            global_capability_number=metadata_import.global_capability_number,
            capability_name=pr.title,
            worker=GlobalCapabilityWorkerRef(worker_id=pr.author),
            repository=GlobalCapabilityRepositoryRef(
                repository_owner=pr.repository_owner,
                repository_name=pr.repository_name,
                repository_pr_number=pr.repository_pr_number,
                repository_pr_url=pr.repository_pr_url,
                branch_name=pr.branch_name,
                merge_sha=pr.merge_commit_sha,
            ),
            affected_files=[f.path for f in metadata_import.files],
            status=registry_status,
            created_at=pr.created_at,
            updated_at=pr.updated_at,
            raw_metadata=dict(metadata_import.raw_metadata),
        )
        return entry.to_dict()

    def _build_timeline_events(
        self, metadata_import: GitHubMetadataImport
    ) -> list[dict[str, Any]]:
        pr = metadata_import.pr
        gc_id = (
            f"gc-{metadata_import.global_capability_number}"
            if metadata_import.global_capability_number
            else ""
        )
        pr_ref = CapabilityEventReference(
            reference_type="pr_url",
            target=pr.repository_pr_url,
            label=f"{pr.repository_owner}/{pr.repository_name}"
            f"#{pr.repository_pr_number}",
        )

        # (event_type, sequence, timestamp) for the lifecycle events that
        # actually occurred (only those with a timestamp are emitted).
        candidates = [
            (CapabilityEventType.PR_CREATED, 1, pr.created_at, "PR created"),
            (CapabilityEventType.PR_READY, 2, pr.updated_at, "PR ready"),
            (CapabilityEventType.PR_MERGED, 3, pr.merged_at, "PR merged"),
        ]

        events: list[CapabilityEvent] = []
        for event_type, sequence, timestamp, summary in candidates:
            if not timestamp or not str(timestamp).strip():
                continue
            events.append(
                CapabilityEvent(
                    global_capability_id=gc_id,
                    timestamp=timestamp,
                    event_sequence=sequence,
                    worker=pr.author,
                    source="github_metadata_import",
                    event_type=event_type.value,
                    summary=summary,
                    references=[pr_ref],
                )
            )

        events.sort(key=self._timeline_sort_key)
        return [e.to_dict() for e in events]

    # ------------------------------------------------------------------
    # Duplicate detection
    # ------------------------------------------------------------------

    def _reject_duplicate(
        self, owner: str, name: str, pr_number: int
    ) -> None:
        for report in self.list_reports():
            existing = report.get("metadata_import", {}).get("pr", {})
            if (
                existing.get("repository_owner") == owner
                and existing.get("repository_name") == name
                and existing.get("repository_pr_number") == pr_number
            ):
                raise ValueError(
                    "Duplicate import: "
                    f"{owner}/{name} PR #{pr_number} already imported "
                    f"(report {report.get('report_id')})"
                )

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
            raise ValueError(
                f"GitHub metadata import report not found: {report_id}"
            )
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

    def _persist(self, report: GitHubMetadataImportReport) -> None:
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

    def _write_evidence(self, report: GitHubMetadataImportReport) -> None:
        evidence_dir = self._safe_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "global_capability_number": report.global_capability_number,
            "metadata_import": report.metadata_import.to_dict(),
        }
        (evidence_dir / "github_import_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "github_import_result.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "github_import_summary.md").write_text(
            self._generate_export_md(report.to_dict()), encoding="utf-8"
        )

        (evidence_dir / "github_import_files.csv").write_text(
            self._generate_export_csv(report.to_dict()), encoding="utf-8"
        )

        evidence = GitHubMetadataImportEvidence(
            report_id=report.report_id,
            summary=(
                f"{report.repository} PR #{report.repository_pr_number}: "
                f"{report.commit_count} commits, {report.file_count} files, "
                f"{report.label_count} labels, {len(report.timeline_events)} "
                f"events"
            ),
        )

        # An import passes when it fully imported with no skipped sub-records.
        passed = report.status == GitHubMetadataImportStatus.IMPORTED.value
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "evidence_id": evidence.evidence_id,
            "repository": report.repository,
            "repository_pr_number": report.repository_pr_number,
            "global_capability_number": report.global_capability_number,
            "import_status": report.status,
            "commit_count": report.commit_count,
            "file_count": report.file_count,
            "label_count": report.label_count,
            "timeline_event_count": len(report.timeline_events),
            "skipped_count": len(report.metadata_import.skipped),
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

        lines.append("# GitHub Metadata Import")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Repository: {data.get('repository', '')}")
        lines.append(f"- PR Number: {data.get('repository_pr_number', 0)}")
        lines.append(
            f"- Global Capability Number: "
            f"{data.get('global_capability_number', 0)}"
        )
        lines.append(f"- Import Status: {data.get('status', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append(f"- Schema Version: {data.get('schema_version', '')}")
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Commits: {data.get('commit_count', 0)}")
        lines.append(f"- Files: {data.get('file_count', 0)}")
        lines.append(f"- Labels: {data.get('label_count', 0)}")
        lines.append(f"- Additions: {data.get('total_additions', 0)}")
        lines.append(f"- Deletions: {data.get('total_deletions', 0)}")
        lines.append("")

        type_counts = data.get("timeline_event_type_counts", {})
        lines.append("## Timeline Event Counts")
        lines.append("")
        for event_type in sorted(type_counts):
            lines.append(
                f"- {event_type.upper()}: {type_counts[event_type]}"
            )
        lines.append("")

        pr = data.get("metadata_import", {}).get("pr", {})
        lines.append("## Pull Request")
        lines.append("")
        lines.append(f"- Title: {pr.get('title', '')}")
        lines.append(f"- Author: {pr.get('author', '')}")
        lines.append(f"- Branch: {pr.get('branch_name', '')}")
        lines.append(f"- Status: {pr.get('status', '')}")
        labels = pr.get("labels", [])
        if labels:
            label_names = ", ".join(f"[{label.get('name', '')}]" for label in labels)
            lines.append(f"- Labels: {label_names}")
        lines.append("")

        commits = data.get("metadata_import", {}).get("commits", [])
        if commits:
            lines.append("## Commits")
            lines.append("")
            for c in commits:
                sha = c.get("commit_sha", "")
                msg = c.get("message", "")
                lines.append(f"- {sha}: {msg}")
            lines.append("")

        files = data.get("metadata_import", {}).get("files", [])
        if files:
            lines.append("## Changed Files")
            lines.append("")
            for f in files:
                path = f.get("path", "")
                fstatus = f.get("status", "")
                adds = f.get("additions", 0)
                dels = f.get("deletions", 0)
                lines.append(f"- {path} [{fstatus}] +{adds}/-{dels}")
            lines.append("")

        events = data.get("timeline_events", [])
        if events:
            lines.append("## Timeline Events")
            lines.append("")
            for e in events:
                seq = e.get("event_sequence", 0)
                etype = e.get("event_type", "").upper()
                ts = e.get("timestamp", "")
                summary_text = e.get("summary", "")
                lines.append(f"- [{seq}] {ts} [{etype}] {summary_text}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _generate_export_csv(data: dict[str, Any]) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "path",
                "status",
                "additions",
                "deletions",
                "repository",
                "repository_pr_number",
                "global_capability_number",
                "schema_version",
            ]
        )
        repository = data.get("repository", "")
        pr_number = data.get("repository_pr_number", 0)
        gc_number = data.get("global_capability_number", 0)
        schema_version = data.get("schema_version", "")
        for f in data.get("metadata_import", {}).get("files", []):
            writer.writerow(
                [
                    f.get("path", ""),
                    f.get("status", ""),
                    f.get("additions", 0),
                    f.get("deletions", 0),
                    repository,
                    pr_number,
                    gc_number,
                    schema_version,
                ]
            )
        return buf.getvalue()
