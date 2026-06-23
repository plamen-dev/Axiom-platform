"""Devin Session Metadata Import Framework v1.

Deterministically ingest structured Devin session metadata (session identity,
worker actions, artifacts, validation, skill proposals) into shapes consumable
by the Global Capability Registry, the Capability Event Timeline, and the
Capability Summary Framework, so Program 1 captures worker/session execution
context that GitHub metadata alone does not record.

This framework performs read-only metadata ingestion from a provided payload
(no Devin API, no scraping, no browser automation, no network calls). The
import adapter only observes and enriches: the Global Capability Registry
remains the sole owner of capability identity. It never creates, mutates, or
duplicates registry entries. Instead it records a non-owning ``registry
reference`` (consuming an existing ``capability_id``/``global_capability_number``
when provided, otherwise flagging ``missing_registry_reference`` without
touching the registry) and builds append-only timeline events
(TEST_STARTED/TEST_COMPLETED, VIDEO_RECORDED, SCREENSHOT_CAPTURED,
SKILL_PROPOSED/SKILL_APPROVED, REVIEW_FINDING, BUG_FIXED, PR_READY, WARNING,
NOTE) from the imported metadata. Raw payloads, schema version, and manual
overrides are preserved.

Non-goals: no Devin API integration, no automatic scraping, no browser
automation, no worker orchestration, no automatic PR sequencing, no Operator
Cockpit UI, no graph engine, no architecture changes, no new dependencies, no
network calls.
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

from axiom_core.capability_event_timeline import (
    CapabilityEvent,
    CapabilityEventArtifact,
    CapabilityEventReference,
    CapabilityEventType,
)

SCHEMA_VERSION = "1.0"

# Registry-reference status: whether the session names an existing global
# capability identity for the import to reference (never mint).
REGISTRY_REFERENCE_REFERENCED = "referenced"
REGISTRY_REFERENCE_MISSING = "missing_registry_reference"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DevinSessionImportStatus(str, Enum):
    IMPORTED = "imported"
    PARTIAL_IMPORT = "partial_import"
    FAILED = "failed"


class DevinSessionActionType(str, Enum):
    STARTED = "started"
    IMPLEMENTED = "implemented"
    TESTED = "tested"
    REVIEWED = "reviewed"
    FIXED_FINDING = "fixed_finding"
    RECORDED_WALKTHROUGH = "recorded_walkthrough"
    PROPOSED_SKILL = "proposed_skill"
    UPDATED_SKILL = "updated_skill"
    REPORTED_READY = "reported_ready"
    SLEPT = "slept"
    RESUMED = "resumed"
    NOTE = "note"


class DevinSessionArtifactType(str, Enum):
    RECORDING = "recording"
    SCREENSHOT = "screenshot"
    TEST_REPORT = "test_report"
    PR_COMMENT = "pr_comment"
    EVIDENCE_BUNDLE = "evidence_bundle"
    SKILL_FILE = "skill_file"
    LOG = "log"
    OTHER = "other"


class DevinSessionSkillProposalStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    MERGED = "merged"
    SUPERSEDED = "superseded"


_VALID_IMPORT_STATUSES = {s.value for s in DevinSessionImportStatus}
_VALID_ACTION_TYPES = {t.value for t in DevinSessionActionType}
_VALID_ARTIFACT_TYPES = {t.value for t in DevinSessionArtifactType}
_VALID_SKILL_STATUSES = {s.value for s in DevinSessionSkillProposalStatus}

# Map an action type onto a single timeline event type (conservative: only
# actions that clearly correspond to a recorded capability event emit one).
_ACTION_TO_EVENT = {
    DevinSessionActionType.TESTED.value: (
        CapabilityEventType.TEST_COMPLETED.value
    ),
    DevinSessionActionType.REVIEWED.value: (
        CapabilityEventType.REVIEW_FINDING.value
    ),
    DevinSessionActionType.FIXED_FINDING.value: (
        CapabilityEventType.BUG_FIXED.value
    ),
    DevinSessionActionType.RECORDED_WALKTHROUGH.value: (
        CapabilityEventType.VIDEO_RECORDED.value
    ),
    DevinSessionActionType.PROPOSED_SKILL.value: (
        CapabilityEventType.SKILL_PROPOSED.value
    ),
    DevinSessionActionType.UPDATED_SKILL.value: (
        CapabilityEventType.SKILL_PROPOSED.value
    ),
    DevinSessionActionType.REPORTED_READY.value: (
        CapabilityEventType.PR_READY.value
    ),
    DevinSessionActionType.SLEPT.value: CapabilityEventType.WARNING.value,
    DevinSessionActionType.STARTED.value: CapabilityEventType.NOTE.value,
    DevinSessionActionType.IMPLEMENTED.value: CapabilityEventType.NOTE.value,
    DevinSessionActionType.RESUMED.value: CapabilityEventType.NOTE.value,
    DevinSessionActionType.NOTE.value: CapabilityEventType.NOTE.value,
}

# Map an artifact type onto a timeline event type (only media artifacts emit).
_ARTIFACT_TO_EVENT = {
    DevinSessionArtifactType.RECORDING.value: (
        CapabilityEventType.VIDEO_RECORDED.value
    ),
    DevinSessionArtifactType.SCREENSHOT.value: (
        CapabilityEventType.SCREENSHOT_CAPTURED.value
    ),
}

# Map a skill proposal status onto a timeline event type.
_SKILL_STATUS_TO_EVENT = {
    DevinSessionSkillProposalStatus.PROPOSED.value: (
        CapabilityEventType.SKILL_PROPOSED.value
    ),
    DevinSessionSkillProposalStatus.APPROVED.value: (
        CapabilityEventType.SKILL_APPROVED.value
    ),
    DevinSessionSkillProposalStatus.MERGED.value: (
        CapabilityEventType.SKILL_APPROVED.value
    ),
}


# ---------------------------------------------------------------------------
# Metadata models
# ---------------------------------------------------------------------------


@dataclass
class DevinSessionActionMetadata:
    """A single worker action captured from a Devin session."""

    action_id: str = ""
    timestamp: str = ""
    action_type: str = DevinSessionActionType.NOTE.value
    summary: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "timestamp": self.timestamp,
            "action_type": self.action_type,
            "summary": self.summary,
            "raw_payload": dict(self.raw_payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DevinSessionActionMetadata:
        return cls(
            action_id=data.get("action_id", ""),
            timestamp=data.get("timestamp", ""),
            action_type=data.get("action_type", ""),
            summary=data.get("summary", ""),
            raw_payload=dict(data.get("raw_payload", {})),
        )


@dataclass
class DevinSessionArtifactMetadata:
    """A single artifact captured from a Devin session."""

    artifact_id: str = ""
    artifact_type: str = DevinSessionArtifactType.OTHER.value
    artifact_path: str = ""
    artifact_url: str = ""
    summary: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "artifact_path": self.artifact_path,
            "artifact_url": self.artifact_url,
            "summary": self.summary,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DevinSessionArtifactMetadata:
        return cls(
            artifact_id=data.get("artifact_id", ""),
            artifact_type=data.get("artifact_type", ""),
            artifact_path=data.get("artifact_path", ""),
            artifact_url=data.get("artifact_url", ""),
            summary=data.get("summary", ""),
            created_at=data.get("created_at", ""),
        )


@dataclass
class DevinSessionValidationMetadata:
    """Validation evidence captured from a Devin session."""

    pytest_passed: int = 0
    pytest_skipped: int = 0
    ruff_status: str = ""
    ci_status: str = ""
    cli_testing_summary: str = ""
    devin_review_status: str = ""
    devin_review_findings: int = 0
    repaired_findings: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pytest_passed": self.pytest_passed,
            "pytest_skipped": self.pytest_skipped,
            "ruff_status": self.ruff_status,
            "ci_status": self.ci_status,
            "cli_testing_summary": self.cli_testing_summary,
            "devin_review_status": self.devin_review_status,
            "devin_review_findings": self.devin_review_findings,
            "repaired_findings": self.repaired_findings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DevinSessionValidationMetadata:
        return cls(
            pytest_passed=int(data.get("pytest_passed", 0)),
            pytest_skipped=int(data.get("pytest_skipped", 0)),
            ruff_status=data.get("ruff_status", ""),
            ci_status=data.get("ci_status", ""),
            cli_testing_summary=data.get("cli_testing_summary", ""),
            devin_review_status=data.get("devin_review_status", ""),
            devin_review_findings=int(data.get("devin_review_findings", 0)),
            repaired_findings=int(data.get("repaired_findings", 0)),
        )


@dataclass
class DevinSessionSkillProposalMetadata:
    """A skill proposal captured from a Devin session."""

    skill_id: str = ""
    skill_name: str = ""
    proposal_summary: str = ""
    status: str = DevinSessionSkillProposalStatus.PROPOSED.value
    file_path: str = ""
    additions: int = 0
    deletions: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "proposal_summary": self.proposal_summary,
            "status": self.status,
            "file_path": self.file_path,
            "additions": self.additions,
            "deletions": self.deletions,
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any]
    ) -> DevinSessionSkillProposalMetadata:
        return cls(
            skill_id=data.get("skill_id", ""),
            skill_name=data.get("skill_name", ""),
            proposal_summary=data.get("proposal_summary", ""),
            status=data.get("status", ""),
            file_path=data.get("file_path", ""),
            additions=int(data.get("additions", 0)),
            deletions=int(data.get("deletions", 0)),
        )


@dataclass
class DevinSessionMetadata:
    """Identity and context of a single Devin session."""

    session_id: str = ""
    session_url: str = ""
    worker_id: str = ""
    worker_name: str = ""
    worker_type: str = ""
    repository_owner: str = ""
    repository_name: str = ""
    repository_pr_number: int = 0
    global_capability_number: int = 0
    capability_id: str = ""
    capability_name: str = ""
    started_at: str = ""
    completed_at: str = ""
    status: str = ""
    summary: str = ""
    schema_version: str = SCHEMA_VERSION
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "session_url": self.session_url,
            "worker_id": self.worker_id,
            "worker_name": self.worker_name,
            "worker_type": self.worker_type,
            "repository_owner": self.repository_owner,
            "repository_name": self.repository_name,
            "repository_pr_number": self.repository_pr_number,
            "global_capability_number": self.global_capability_number,
            "capability_id": self.capability_id,
            "capability_name": self.capability_name,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "summary": self.summary,
            "schema_version": self.schema_version,
            "raw_payload": dict(self.raw_payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DevinSessionMetadata:
        return cls(
            session_id=data.get("session_id", ""),
            session_url=data.get("session_url", ""),
            worker_id=data.get("worker_id", ""),
            worker_name=data.get("worker_name", ""),
            worker_type=data.get("worker_type", ""),
            repository_owner=data.get("repository_owner", ""),
            repository_name=data.get("repository_name", ""),
            repository_pr_number=int(data.get("repository_pr_number", 0)),
            global_capability_number=int(
                data.get("global_capability_number", 0)
            ),
            capability_id=data.get("capability_id", ""),
            capability_name=data.get("capability_name", ""),
            started_at=data.get("started_at", ""),
            completed_at=data.get("completed_at", ""),
            status=data.get("status", ""),
            summary=data.get("summary", ""),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            raw_payload=dict(data.get("raw_payload", {})),
        )


# ---------------------------------------------------------------------------
# Import / Report / Evidence
# ---------------------------------------------------------------------------


@dataclass
class DevinSessionMetadataImport:
    """A single deterministic Devin session metadata import."""

    import_id: str = ""
    global_capability_number: int = 0
    session: DevinSessionMetadata = field(
        default_factory=DevinSessionMetadata
    )
    actions: list[DevinSessionActionMetadata] = field(default_factory=list)
    artifacts: list[DevinSessionArtifactMetadata] = field(default_factory=list)
    validation: DevinSessionValidationMetadata = field(
        default_factory=DevinSessionValidationMetadata
    )
    skill_proposals: list[DevinSessionSkillProposalMetadata] = field(
        default_factory=list
    )
    status: str = DevinSessionImportStatus.IMPORTED.value
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
            "session": self.session.to_dict(),
            "actions": [a.to_dict() for a in self.actions],
            "artifacts": [a.to_dict() for a in self.artifacts],
            "validation": self.validation.to_dict(),
            "skill_proposals": [s.to_dict() for s in self.skill_proposals],
            "status": self.status,
            "skipped": list(self.skipped),
            "raw_metadata": dict(self.raw_metadata),
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }


@dataclass
class DevinSessionImportReport:
    """Report summarizing a Devin session metadata import."""

    report_id: str = ""
    session_id: str = ""
    repository: str = ""
    repository_pr_number: int = 0
    global_capability_number: int = 0
    status: str = DevinSessionImportStatus.IMPORTED.value
    action_count: int = 0
    artifact_count: int = 0
    skill_proposal_count: int = 0
    action_type_counts: dict[str, int] = field(default_factory=dict)
    artifact_type_counts: dict[str, int] = field(default_factory=dict)
    skill_proposal_status_counts: dict[str, int] = field(default_factory=dict)
    timeline_event_type_counts: dict[str, int] = field(default_factory=dict)
    metadata_import: DevinSessionMetadataImport = field(
        default_factory=DevinSessionMetadataImport
    )
    registry_reference_status: str = REGISTRY_REFERENCE_MISSING
    registry_reference: dict[str, Any] = field(default_factory=dict)
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
            "session_id": self.session_id,
            "repository": self.repository,
            "repository_pr_number": self.repository_pr_number,
            "global_capability_number": self.global_capability_number,
            "status": self.status,
            "action_count": self.action_count,
            "artifact_count": self.artifact_count,
            "skill_proposal_count": self.skill_proposal_count,
            "action_type_counts": dict(self.action_type_counts),
            "artifact_type_counts": dict(self.artifact_type_counts),
            "skill_proposal_status_counts": dict(
                self.skill_proposal_status_counts
            ),
            "timeline_event_type_counts": dict(
                self.timeline_event_type_counts
            ),
            "metadata_import": self.metadata_import.to_dict(),
            "registry_reference_status": self.registry_reference_status,
            "registry_reference": dict(self.registry_reference),
            "timeline_events": list(self.timeline_events),
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }


@dataclass
class DevinSessionImportEvidence:
    """Evidence record for a Devin session metadata import report."""

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


class DevinSessionMetadataImportEngine:
    """Imports Devin session metadata into registry/timeline shapes."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "devin_session_import"
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

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def import_session(
        self,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
        repo: str | None = None,
        pr_number: int | None = None,
        global_capability_number: int | None = None,
    ) -> dict[str, Any]:
        """Import Devin session metadata deterministically.

        ``session_id``, ``repo`` (``owner/name``), ``pr_number`` and
        ``global_capability_number`` are manual overrides that take precedence
        over the metadata payload, preserving manual override capability.
        """
        metadata = dict(metadata or {})
        session_data = dict(metadata.get("session", {}))

        # Manual overrides take precedence over payload values.
        if session_id is not None:
            session_data["session_id"] = session_id
        if repo is not None:
            owner, _, name = repo.partition("/")
            if not owner or not name:
                raise ValueError(
                    f"--repo must be in 'owner/name' form: {repo!r}"
                )
            session_data["repository_owner"] = owner
            session_data["repository_name"] = name
        if pr_number is not None:
            session_data["repository_pr_number"] = int(pr_number)

        resolved_number = session_data.get(
            "global_capability_number",
            metadata.get("global_capability_number", 0),
        )
        if global_capability_number is not None:
            resolved_number = int(global_capability_number)
        session_data["global_capability_number"] = int(resolved_number)

        session = DevinSessionMetadata.from_dict(session_data)

        # Session identity is mandatory; a missing session_id is a clear error.
        if not session.session_id or not session.session_id.strip():
            raise ValueError(
                "Malformed session metadata; missing required field: "
                "'session_id'"
            )

        # Duplicate imports (same session_id) are rejected.
        self._reject_duplicate(session.session_id)

        skipped: list[str] = []
        actions = self._parse_actions(metadata.get("actions", []), skipped)
        artifacts = self._parse_artifacts(
            metadata.get("artifacts", []), skipped
        )
        skill_proposals = self._parse_skill_proposals(
            metadata.get("skill_proposals", []), skipped
        )
        validation = DevinSessionValidationMetadata.from_dict(
            dict(metadata.get("validation", {}))
        )

        status = (
            DevinSessionImportStatus.PARTIAL_IMPORT.value
            if skipped
            else DevinSessionImportStatus.IMPORTED.value
        )

        metadata_import = DevinSessionMetadataImport(
            global_capability_number=int(resolved_number),
            session=session,
            actions=actions,
            artifacts=artifacts,
            validation=validation,
            skill_proposals=skill_proposals,
            status=status,
            skipped=skipped,
            raw_metadata=dict(metadata.get("raw_metadata", {})),
        )

        reference_status, registry_reference = self._build_registry_reference(
            metadata_import
        )
        timeline_events = self._build_timeline_events(metadata_import)

        report = DevinSessionImportReport(
            session_id=session.session_id,
            repository=self._repository_label(session),
            repository_pr_number=session.repository_pr_number,
            global_capability_number=metadata_import.global_capability_number,
            status=status,
            action_count=len(actions),
            artifact_count=len(artifacts),
            skill_proposal_count=len(skill_proposals),
            action_type_counts=self._count(a.action_type for a in actions),
            artifact_type_counts=self._count(
                a.artifact_type for a in artifacts
            ),
            skill_proposal_status_counts=self._count(
                s.status for s in skill_proposals
            ),
            timeline_event_type_counts=self._count(
                e.get("event_type", "") for e in timeline_events
            ),
            metadata_import=metadata_import,
            registry_reference_status=reference_status,
            registry_reference=registry_reference,
            timeline_events=timeline_events,
        )

        self._persist(report)
        self._write_evidence(report)
        return report.to_dict()

    @staticmethod
    def _repository_label(session: DevinSessionMetadata) -> str:
        if session.repository_owner and session.repository_name:
            return f"{session.repository_owner}/{session.repository_name}"
        return ""

    @staticmethod
    def _count(values: Any) -> dict[str, int]:
        counts: dict[str, int] = {}
        for value in values:
            counts[value] = counts.get(value, 0) + 1
        return {k: counts[k] for k in sorted(counts)}

    # ------------------------------------------------------------------
    # Parsing helpers (malformed sub-records skipped, not fatal)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_actions(
        data: list[dict[str, Any]], skipped: list[str]
    ) -> list[DevinSessionActionMetadata]:
        actions: list[DevinSessionActionMetadata] = []
        for idx, raw in enumerate(data):
            action = DevinSessionActionMetadata.from_dict(raw)
            if not action.timestamp or not action.timestamp.strip():
                skipped.append(f"action[{idx}]: missing timestamp")
                continue
            if action.action_type not in _VALID_ACTION_TYPES:
                skipped.append(
                    f"action[{idx}]: invalid action_type "
                    f"{action.action_type!r}"
                )
                continue
            actions.append(action)
        actions.sort(
            key=lambda a: (a.timestamp, a.action_type, a.action_id)
        )
        return actions

    @staticmethod
    def _parse_artifacts(
        data: list[dict[str, Any]], skipped: list[str]
    ) -> list[DevinSessionArtifactMetadata]:
        artifacts: list[DevinSessionArtifactMetadata] = []
        for idx, raw in enumerate(data):
            artifact = DevinSessionArtifactMetadata.from_dict(raw)
            if artifact.artifact_type not in _VALID_ARTIFACT_TYPES:
                skipped.append(
                    f"artifact[{idx}]: invalid artifact_type "
                    f"{artifact.artifact_type!r}"
                )
                continue
            artifacts.append(artifact)
        artifacts.sort(
            key=lambda a: (a.created_at, a.artifact_type, a.artifact_id)
        )
        return artifacts

    @staticmethod
    def _parse_skill_proposals(
        data: list[dict[str, Any]], skipped: list[str]
    ) -> list[DevinSessionSkillProposalMetadata]:
        proposals: list[DevinSessionSkillProposalMetadata] = []
        for idx, raw in enumerate(data):
            proposal = DevinSessionSkillProposalMetadata.from_dict(raw)
            if not proposal.skill_name or not proposal.skill_name.strip():
                skipped.append(f"skill_proposal[{idx}]: missing skill_name")
                continue
            if proposal.status not in _VALID_SKILL_STATUSES:
                skipped.append(
                    f"skill_proposal[{idx}]: invalid status "
                    f"{proposal.status!r}"
                )
                continue
            proposals.append(proposal)
        proposals.sort(key=lambda s: (s.skill_name, s.skill_id))
        return proposals

    # ------------------------------------------------------------------
    # Integration: reference (never own/mutate) registry + append events
    # ------------------------------------------------------------------

    @staticmethod
    def _build_registry_reference(
        metadata_import: DevinSessionMetadataImport,
    ) -> tuple[str, dict[str, Any]]:
        """Record a non-owning reference to an existing global capability.

        The Global Capability Registry owns capability identity; this adapter
        only observes it. When the session names an existing identity (a
        ``capability_id`` or ``global_capability_number``) the reference points
        at it; otherwise ``missing_registry_reference`` is reported and the
        registry is left untouched (no new canonical identity is minted).
        """
        session = metadata_import.session
        has_reference = bool(session.capability_id.strip()) or (
            metadata_import.global_capability_number > 0
        )
        reference_status = (
            REGISTRY_REFERENCE_REFERENCED
            if has_reference
            else REGISTRY_REFERENCE_MISSING
        )
        reference = {
            "reference_status": reference_status,
            "global_capability_number": (
                metadata_import.global_capability_number
            ),
            "capability_id": session.capability_id,
            "capability_name": session.capability_name,
            "repository_owner": session.repository_owner,
            "repository_name": session.repository_name,
            "repository_pr_number": session.repository_pr_number,
            "worker": {
                "worker_id": session.worker_id,
                "worker_type": session.worker_type,
            },
            "observed_session_status": session.status,
            "affected_files": [
                p.file_path
                for p in metadata_import.skill_proposals
                if p.file_path
            ],
        }
        return reference_status, reference

    def _build_timeline_events(
        self, metadata_import: DevinSessionMetadataImport
    ) -> list[dict[str, Any]]:
        session = metadata_import.session
        gc_id = (
            f"gc-{metadata_import.global_capability_number}"
            if metadata_import.global_capability_number
            else session.capability_id
        )
        session_ref = CapabilityEventReference(
            reference_type="session_url",
            target=session.session_url,
            label=session.session_id,
        )
        worker = session.worker_id or session.worker_name

        # (timestamp, event_type, summary, optional artifact) tuples, gathered
        # from actions, media artifacts, and skill proposals.
        raw_events: list[
            tuple[str, str, str, CapabilityEventArtifact | None]
        ] = []

        for action in metadata_import.actions:
            event_type = _ACTION_TO_EVENT.get(action.action_type)
            if event_type is None:
                continue
            raw_events.append(
                (action.timestamp, event_type, action.summary, None)
            )

        for artifact in metadata_import.artifacts:
            event_type = _ARTIFACT_TO_EVENT.get(artifact.artifact_type)
            if event_type is None:
                continue
            raw_events.append(
                (
                    artifact.created_at,
                    event_type,
                    artifact.summary,
                    CapabilityEventArtifact(
                        artifact_type=artifact.artifact_type,
                        path=artifact.artifact_path or artifact.artifact_url,
                        description=artifact.summary,
                    ),
                )
            )

        for proposal in metadata_import.skill_proposals:
            event_type = _SKILL_STATUS_TO_EVENT.get(proposal.status)
            if event_type is None:
                continue
            raw_events.append(
                (
                    session.completed_at or session.started_at,
                    event_type,
                    f"{proposal.skill_name}: {proposal.proposal_summary}",
                    None,
                )
            )

        # Deterministic ordering independent of input order and of the random
        # event ids assigned below.
        raw_events.sort(key=lambda e: (e[0], e[1], e[2]))

        events: list[CapabilityEvent] = []
        for sequence, (timestamp, event_type, summary, artifact) in enumerate(
            raw_events, start=1
        ):
            events.append(
                CapabilityEvent(
                    global_capability_id=gc_id,
                    timestamp=timestamp,
                    event_sequence=sequence,
                    worker=worker,
                    source="devin_session_import",
                    event_type=event_type,
                    summary=summary,
                    references=[session_ref],
                    artifacts=[artifact] if artifact is not None else [],
                )
            )
        return [e.to_dict() for e in events]

    # ------------------------------------------------------------------
    # Duplicate detection
    # ------------------------------------------------------------------

    def _reject_duplicate(self, session_id: str) -> None:
        for report in self.list_reports():
            existing = report.get("metadata_import", {}).get("session", {})
            if existing.get("session_id") == session_id:
                raise ValueError(
                    "Duplicate import: session "
                    f"{session_id!r} already imported "
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
            raise ValueError(
                f"Devin session import report not found: {report_id}"
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

    def _persist(self, report: DevinSessionImportReport) -> None:
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

    def _write_evidence(self, report: DevinSessionImportReport) -> None:
        evidence_dir = self._safe_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "global_capability_number": report.global_capability_number,
            "metadata_import": report.metadata_import.to_dict(),
        }
        (evidence_dir / "devin_session_import_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "devin_session_import_result.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "devin_session_import_summary.md").write_text(
            self._generate_export_md(report.to_dict()), encoding="utf-8"
        )

        evidence = DevinSessionImportEvidence(
            report_id=report.report_id,
            summary=(
                f"session {report.session_id}: {report.action_count} actions, "
                f"{report.artifact_count} artifacts, "
                f"{report.skill_proposal_count} skill proposals, "
                f"{len(report.timeline_events)} events"
            ),
        )

        # An import passes when it fully imported with no skipped sub-records.
        passed = report.status == DevinSessionImportStatus.IMPORTED.value
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "evidence_id": evidence.evidence_id,
            "session_id": report.session_id,
            "repository": report.repository,
            "repository_pr_number": report.repository_pr_number,
            "global_capability_number": report.global_capability_number,
            "import_status": report.status,
            "registry_reference_status": report.registry_reference_status,
            "action_count": report.action_count,
            "artifact_count": report.artifact_count,
            "skill_proposal_count": report.skill_proposal_count,
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

        lines.append("# Devin Session Metadata Import")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Session ID: {data.get('session_id', '')}")
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
        lines.append(f"- Actions: {data.get('action_count', 0)}")
        lines.append(f"- Artifacts: {data.get('artifact_count', 0)}")
        lines.append(
            f"- Skill Proposals: {data.get('skill_proposal_count', 0)}"
        )
        lines.append("")

        session = data.get("metadata_import", {}).get("session", {})
        lines.append("## Session")
        lines.append("")
        lines.append(f"- Worker: {session.get('worker_id', '')}")
        lines.append(f"- Worker Type: {session.get('worker_type', '')}")
        lines.append(f"- Capability: {session.get('capability_name', '')}")
        lines.append(f"- Status: {session.get('status', '')}")
        lines.append(f"- Summary: {session.get('summary', '')}")
        lines.append("")

        reference = data.get("registry_reference", {})
        lines.append("## Registry Reference")
        lines.append("")
        lines.append(
            f"- Reference Status: "
            f"{data.get('registry_reference_status', '')}"
        )
        lines.append(
            f"- Global Capability Number: "
            f"{reference.get('global_capability_number', 0)}"
        )
        lines.append(
            f"- Capability ID: {reference.get('capability_id', '')}"
        )
        lines.append("")

        action_counts = data.get("action_type_counts", {})
        lines.append("## Action Type Counts")
        lines.append("")
        for action_type in sorted(action_counts):
            lines.append(
                f"- {action_type.upper()}: {action_counts[action_type]}"
            )
        lines.append("")

        artifact_counts = data.get("artifact_type_counts", {})
        lines.append("## Artifact Type Counts")
        lines.append("")
        for artifact_type in sorted(artifact_counts):
            lines.append(
                f"- {artifact_type.upper()}: {artifact_counts[artifact_type]}"
            )
        lines.append("")

        skill_counts = data.get("skill_proposal_status_counts", {})
        lines.append("## Skill Proposal Status Counts")
        lines.append("")
        for skill_status in sorted(skill_counts):
            lines.append(
                f"- {skill_status.upper()}: {skill_counts[skill_status]}"
            )
        lines.append("")

        type_counts = data.get("timeline_event_type_counts", {})
        lines.append("## Timeline Event Counts")
        lines.append("")
        for event_type in sorted(type_counts):
            lines.append(
                f"- {event_type.upper()}: {type_counts[event_type]}"
            )
        lines.append("")

        actions = data.get("metadata_import", {}).get("actions", [])
        if actions:
            lines.append("## Actions")
            lines.append("")
            for a in actions:
                ts = a.get("timestamp", "")
                atype = a.get("action_type", "").upper()
                summary_text = a.get("summary", "")
                lines.append(f"- {ts} [{atype}] {summary_text}")
            lines.append("")

        artifacts = data.get("metadata_import", {}).get("artifacts", [])
        if artifacts:
            lines.append("## Artifacts")
            lines.append("")
            for a in artifacts:
                atype = a.get("artifact_type", "").upper()
                path = a.get("artifact_path", "") or a.get("artifact_url", "")
                summary_text = a.get("summary", "")
                lines.append(f"- [{atype}] {path}: {summary_text}")
            lines.append("")

        proposals = data.get("metadata_import", {}).get("skill_proposals", [])
        if proposals:
            lines.append("## Skill Proposals")
            lines.append("")
            for p in proposals:
                name = p.get("skill_name", "")
                pstatus = p.get("status", "").upper()
                lines.append(f"- {name} [{pstatus}]")
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
                "record_type",
                "identifier",
                "type_or_status",
                "summary",
                "timestamp",
                "session_id",
                "global_capability_number",
                "schema_version",
            ]
        )
        session_id = data.get("session_id", "")
        gc_number = data.get("global_capability_number", 0)
        schema_version = data.get("schema_version", "")
        metadata_import = data.get("metadata_import", {})

        for a in metadata_import.get("actions", []):
            writer.writerow(
                [
                    "action",
                    a.get("action_id", ""),
                    a.get("action_type", ""),
                    a.get("summary", ""),
                    a.get("timestamp", ""),
                    session_id,
                    gc_number,
                    schema_version,
                ]
            )
        for a in metadata_import.get("artifacts", []):
            writer.writerow(
                [
                    "artifact",
                    a.get("artifact_id", ""),
                    a.get("artifact_type", ""),
                    a.get("summary", ""),
                    a.get("created_at", ""),
                    session_id,
                    gc_number,
                    schema_version,
                ]
            )
        for p in metadata_import.get("skill_proposals", []):
            writer.writerow(
                [
                    "skill_proposal",
                    p.get("skill_id", ""),
                    p.get("status", ""),
                    f"{p.get('skill_name', '')}: {p.get('proposal_summary', '')}",
                    "",
                    session_id,
                    gc_number,
                    schema_version,
                ]
            )
        return buf.getvalue()
