"""Capability File Knowledge Framework v1.

The first formal capability-to-file knowledge layer. Where the Global Capability
Registry establishes identity, the Capability Summary establishes understanding,
the Capability Relationship Framework establishes relationships, and the
Capability Impact Framework establishes meaning, this layer establishes
*location*: which concrete code assets a capability created, modified, validated,
tested, depends on, or references.

Per capability it captures a deterministic, append-only set of typed
file relationships plus derived file references and directory aggregation, with
preserved raw payloads and schema versioning. Capabilities become traceable to
concrete files and directories.

It is deliberately *structure only*. Non-goals: no graph engine, no graph
queries, no repository scanning, no automatic file discovery, no visualization,
no worker orchestration, no network calls. The registry/relationship/import
layers are consumed read-only; nothing is mutated.
"""

from __future__ import annotations

import csv
import io
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from axiom_core.artifact_paths import is_within_sandbox

SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CapabilityFileRelationshipType(str, Enum):
    CREATED = "CREATED"
    MODIFIED = "MODIFIED"
    VALIDATED = "VALIDATED"
    TESTED = "TESTED"
    DEPENDS_ON = "DEPENDS_ON"
    REFERENCES = "REFERENCES"


_VALID_RELATIONSHIP_TYPES = {t.value for t in CapabilityFileRelationshipType}


# ---------------------------------------------------------------------------
# Path normalization (for file_path *data*, not filesystem access)
# ---------------------------------------------------------------------------


def _normalize_file_path(raw: str) -> str:
    """Normalize a file path string deterministically.

    Operates on file paths as *data* (not for filesystem access): converts
    backslashes to forward slashes, strips whitespace, drops leading ``./``
    and redundant separators. Does not resolve ``..`` — it is preserved as
    a literal path segment.
    """
    s = str(raw).strip().replace("\\", "/")
    segments = [seg for seg in s.split("/") if seg not in ("", ".")]
    leading_slash = s.startswith("/")
    normalized = "/".join(segments)
    if leading_slash:
        normalized = "/" + normalized
    return normalized


def _file_name(path: str) -> str:
    return PurePosixPath(path).name


def _file_extension(path: str) -> str:
    return PurePosixPath(path).suffix


def _directory(path: str) -> str:
    parent = str(PurePosixPath(path).parent)
    return parent


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class CapabilityFileReference:
    """A reference linking a capability to a concrete file."""

    file_reference_id: str = ""
    capability_id: str = ""
    file_path: str = ""
    file_name: str = ""
    file_extension: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.file_reference_id:
            self.file_reference_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_reference_id": self.file_reference_id,
            "capability_id": self.capability_id,
            "file_path": self.file_path,
            "file_name": self.file_name,
            "file_extension": self.file_extension,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityFileReference:
        return cls(
            file_reference_id=data.get("file_reference_id", ""),
            capability_id=data.get("capability_id", ""),
            file_path=data.get("file_path", ""),
            file_name=data.get("file_name", ""),
            file_extension=data.get("file_extension", ""),
            created_at=data.get("created_at", ""),
        )


@dataclass
class CapabilityFileRelationship:
    """A typed relationship between a capability and a file."""

    relationship_id: str = ""
    capability_id: str = ""
    file_path: str = ""
    relationship_type: str = ""
    summary: str = ""

    def __post_init__(self) -> None:
        if not self.relationship_id:
            self.relationship_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "relationship_id": self.relationship_id,
            "capability_id": self.capability_id,
            "file_path": self.file_path,
            "relationship_type": self.relationship_type,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityFileRelationship:
        return cls(
            relationship_id=data.get("relationship_id", ""),
            capability_id=data.get("capability_id", ""),
            file_path=data.get("file_path", ""),
            relationship_type=data.get("relationship_type", ""),
            summary=data.get("summary", ""),
        )


@dataclass
class CapabilityFileKnowledge:
    """Per-capability aggregate of file references and relationships."""

    knowledge_id: str = ""
    capability_id: str = ""
    file_count: int = 0
    relationship_count: int = 0
    affected_directories: list[str] = field(default_factory=list)
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
            "file_count": self.file_count,
            "relationship_count": self.relationship_count,
            "affected_directories": list(self.affected_directories),
            "created_at": self.created_at,
            "raw_payload": dict(self.raw_payload),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityFileKnowledge:
        return cls(
            knowledge_id=data.get("knowledge_id", ""),
            capability_id=data.get("capability_id", ""),
            file_count=data.get("file_count", 0),
            relationship_count=data.get("relationship_count", 0),
            affected_directories=list(data.get("affected_directories", [])),
            created_at=data.get("created_at", ""),
            raw_payload=dict(data.get("raw_payload", {})),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )


@dataclass
class CapabilityFileKnowledgeReport:
    """A deterministic, append-only capability file knowledge report."""

    report_id: str = ""
    references: list[CapabilityFileReference] = field(default_factory=list)
    relationships: list[CapabilityFileRelationship] = field(
        default_factory=list
    )
    knowledge: list[CapabilityFileKnowledge] = field(default_factory=list)
    capability_count: int = 0
    file_count: int = 0
    relationship_count: int = 0
    directory_count: int = 0
    duplicate_relationship_count: int = 0
    relationship_type_counts: dict[str, int] = field(default_factory=dict)
    affected_directories: list[str] = field(default_factory=list)
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
            "references": [r.to_dict() for r in self.references],
            "relationships": [r.to_dict() for r in self.relationships],
            "knowledge": [k.to_dict() for k in self.knowledge],
            "capability_count": self.capability_count,
            "file_count": self.file_count,
            "relationship_count": self.relationship_count,
            "directory_count": self.directory_count,
            "duplicate_relationship_count": self.duplicate_relationship_count,
            "relationship_type_counts": dict(self.relationship_type_counts),
            "affected_directories": list(self.affected_directories),
            "created_at": self.created_at,
            "raw_metadata": dict(self.raw_metadata),
            "schema_version": self.schema_version,
        }


@dataclass
class CapabilityFileKnowledgeEvidence:
    """Evidence record for a capability file knowledge report."""

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


class CapabilityFileKnowledgeEngine:
    """Manages capability file knowledge reports deterministically.

    File relationships are normalized, deduplicated, ordered deterministically,
    and aggregated per capability with directory aggregation. Reports are
    append-only. The registry/relationship/import layers are *consumed*
    read-only; nothing is mutated. File paths are treated as data and are not
    used for filesystem access (``..`` is preserved as a literal segment).
    """

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "capability_file_knowledge"
        self._report_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Path safety (for report_id only — file_path is data)
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
    def _reference_sort_key(r: CapabilityFileReference) -> tuple:
        return (r.capability_id, r.file_path, r.file_reference_id)

    @staticmethod
    def _relationship_sort_key(r: CapabilityFileRelationship) -> tuple:
        return (
            r.capability_id,
            r.file_path,
            r.relationship_type,
            r.relationship_id,
        )

    @staticmethod
    def _knowledge_sort_key(k: CapabilityFileKnowledge) -> tuple:
        return (k.capability_id, k.knowledge_id)

    # ------------------------------------------------------------------
    # Building / validation
    # ------------------------------------------------------------------

    @staticmethod
    def _build_relationship(
        data: dict[str, Any],
    ) -> CapabilityFileRelationship:
        capability_id = data.get("capability_id", "")
        if not capability_id or not str(capability_id).strip():
            raise ValueError("capability_id is required for a relationship")

        file_path_raw = data.get("file_path", "")
        if not file_path_raw or not str(file_path_raw).strip():
            raise ValueError("file_path is required for a relationship")

        rel_type_raw = data.get("relationship_type", "")
        if not rel_type_raw or not str(rel_type_raw).strip():
            raise ValueError("relationship_type is required for a relationship")
        rel_type = str(rel_type_raw).strip().upper()
        if rel_type not in _VALID_RELATIONSHIP_TYPES:
            raise ValueError(
                f"Invalid relationship_type: {rel_type_raw!r}. "
                f"Valid: {sorted(_VALID_RELATIONSHIP_TYPES)}"
            )

        normalized = dict(data)
        normalized["capability_id"] = str(capability_id)
        normalized["file_path"] = _normalize_file_path(file_path_raw)
        normalized["relationship_type"] = rel_type
        return CapabilityFileRelationship.from_dict(normalized)

    @staticmethod
    def _build_reference(data: dict[str, Any]) -> CapabilityFileReference:
        capability_id = data.get("capability_id", "")
        if not capability_id or not str(capability_id).strip():
            raise ValueError("capability_id is required for a file reference")

        file_path_raw = data.get("file_path", "")
        if not file_path_raw or not str(file_path_raw).strip():
            raise ValueError("file_path is required for a file reference")

        file_path = _normalize_file_path(file_path_raw)
        normalized = dict(data)
        normalized["capability_id"] = str(capability_id)
        normalized["file_path"] = file_path
        normalized["file_name"] = _file_name(file_path)
        normalized["file_extension"] = _file_extension(file_path)
        return CapabilityFileReference.from_dict(normalized)

    def _assemble(
        self,
        report: CapabilityFileKnowledgeReport,
        knowledge_payloads: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        knowledge_payloads = knowledge_payloads or {}

        # Duplicate relationship detection: same
        # (capability_id, file_path, relationship_type). Keep first; count
        # duplicates; drop the rest.
        seen_rels: set[tuple[str, str, str]] = set()
        deduped_rels: list[CapabilityFileRelationship] = []
        duplicate_count = 0
        for r in sorted(report.relationships, key=self._relationship_sort_key):
            key = (r.capability_id, r.file_path, r.relationship_type)
            if key in seen_rels:
                duplicate_count += 1
                continue
            seen_rels.add(key)
            deduped_rels.append(r)
        report.relationships = deduped_rels
        report.duplicate_relationship_count = duplicate_count

        # Derive file references: union of explicit references plus every
        # (capability_id, file_path) seen in relationships. Deduped per pair.
        ref_by_pair: dict[tuple[str, str], CapabilityFileReference] = {}
        for ref in report.references:
            ref_by_pair.setdefault((ref.capability_id, ref.file_path), ref)
        for r in report.relationships:
            pair = (r.capability_id, r.file_path)
            if pair not in ref_by_pair:
                ref_by_pair[pair] = CapabilityFileReference(
                    capability_id=r.capability_id,
                    file_path=r.file_path,
                    file_name=_file_name(r.file_path),
                    file_extension=_file_extension(r.file_path),
                )
        report.references = sorted(
            ref_by_pair.values(), key=self._reference_sort_key
        )

        # Per-capability knowledge aggregation with directory aggregation.
        capabilities = sorted(
            {r.capability_id for r in report.references}
            | {r.capability_id for r in report.relationships}
        )
        knowledge: list[CapabilityFileKnowledge] = []
        all_directories: set[str] = set()
        for cap in capabilities:
            cap_files = sorted(
                {
                    ref.file_path
                    for ref in report.references
                    if ref.capability_id == cap
                }
            )
            cap_rels = [
                r for r in report.relationships if r.capability_id == cap
            ]
            cap_dirs = sorted({_directory(f) for f in cap_files})
            all_directories.update(cap_dirs)
            knowledge.append(
                CapabilityFileKnowledge(
                    capability_id=cap,
                    file_count=len(cap_files),
                    relationship_count=len(cap_rels),
                    affected_directories=cap_dirs,
                    raw_payload=dict(knowledge_payloads.get(cap, {})),
                )
            )
        report.knowledge = sorted(knowledge, key=self._knowledge_sort_key)

        type_counts: dict[str, int] = {}
        for r in report.relationships:
            type_counts[r.relationship_type] = (
                type_counts.get(r.relationship_type, 0) + 1
            )
        report.relationship_type_counts = {
            k: type_counts[k] for k in sorted(type_counts)
        }

        report.affected_directories = sorted(all_directories)
        report.capability_count = len(capabilities)
        report.file_count = len(report.references)
        report.relationship_count = len(report.relationships)
        report.directory_count = len(report.affected_directories)

        return report.to_dict()

    # ------------------------------------------------------------------
    # Create / Append (append-only)
    # ------------------------------------------------------------------

    def create(
        self,
        file_relationships: list[dict[str, Any]] | None = None,
        file_references: list[dict[str, Any]] | None = None,
        knowledge_payloads: dict[str, dict[str, Any]] | None = None,
        raw_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new capability file knowledge report."""
        report = CapabilityFileKnowledgeReport(
            raw_metadata=dict(raw_metadata or {}),
        )
        report.relationships = [
            self._build_relationship(r) for r in (file_relationships or [])
        ]
        report.references = [
            self._build_reference(r) for r in (file_references or [])
        ]
        assembled = self._assemble(report, knowledge_payloads)
        self._persist(assembled)
        self._write_evidence(assembled)
        return assembled

    def append(
        self,
        report_id: str,
        file_relationships: list[dict[str, Any]] | None = None,
        file_references: list[dict[str, Any]] | None = None,
        knowledge_payloads: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Append relationships/references to a report (append-only)."""
        self._validate_id_segment(report_id, "report_id")
        existing = self._load_report(report_id)
        if existing is None:
            raise ValueError(f"Report not found: {report_id}")

        report = CapabilityFileKnowledgeReport(
            report_id=existing["report_id"],
            created_at=existing.get("created_at", ""),
            raw_metadata=dict(existing.get("raw_metadata", {})),
            schema_version=existing.get("schema_version", SCHEMA_VERSION),
        )
        report.relationships = [
            CapabilityFileRelationship.from_dict(r)
            for r in existing.get("relationships", [])
        ]
        report.relationships.extend(
            self._build_relationship(r) for r in (file_relationships or [])
        )
        report.references = [
            CapabilityFileReference.from_dict(r)
            for r in existing.get("references", [])
        ]
        report.references.extend(
            self._build_reference(r) for r in (file_references or [])
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
            "relationships": report.get("relationships", []),
            "references": report.get("references", []),
            "raw_metadata": report.get("raw_metadata", {}),
        }
        (evidence_dir / "capability_file_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "capability_file_result.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "capability_file_summary.md").write_text(
            self._generate_export_md(report), encoding="utf-8"
        )

        relationship_count = report.get("relationship_count", 0)
        file_count = report.get("file_count", 0)
        directory_count = report.get("directory_count", 0)
        duplicate_count = report.get("duplicate_relationship_count", 0)
        evidence = CapabilityFileKnowledgeEvidence(
            report_id=report["report_id"],
            summary=(
                f"{file_count} file(s), "
                f"{relationship_count} relationship(s), "
                f"{directory_count} director(ies), "
                f"{duplicate_count} duplicate(s)"
            ),
        )

        # A report passes when it carries at least one relationship and no
        # duplicate relationships were detected.
        passed = relationship_count > 0 and duplicate_count == 0
        pass_fail = {
            "passed": passed,
            "report_id": report["report_id"],
            "evidence_id": evidence.evidence_id,
            "capability_count": report.get("capability_count", 0),
            "file_count": file_count,
            "relationship_count": relationship_count,
            "directory_count": directory_count,
            "duplicate_relationship_count": duplicate_count,
            "relationship_type_counts": dict(
                report.get("relationship_type_counts", {})
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

        lines.append("# Capability File Knowledge Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append(f"- Schema Version: {data.get('schema_version', '')}")
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        lines.append(f"- Capabilities: {data.get('capability_count', 0)}")
        lines.append(f"- Files: {data.get('file_count', 0)}")
        lines.append(f"- Relationships: {data.get('relationship_count', 0)}")
        lines.append(f"- Directories: {data.get('directory_count', 0)}")
        lines.append(
            f"- Duplicate Relationships: "
            f"{data.get('duplicate_relationship_count', 0)}"
        )
        lines.append("")

        type_counts = data.get("relationship_type_counts", {})
        lines.append("## Relationship Type Counts")
        lines.append("")
        for rel_type in sorted(type_counts):
            lines.append(f"- {rel_type}: {type_counts[rel_type]}")
        lines.append("")

        lines.append("## Affected Directories")
        lines.append("")
        for directory in data.get("affected_directories", []):
            lines.append(f"- {directory}")
        lines.append("")

        lines.append("## File Relationships")
        lines.append("")
        for r in data.get("relationships", []):
            cap = r.get("capability_id", "")
            rel_type = r.get("relationship_type", "")
            file_path = r.get("file_path", "")
            summary = r.get("summary", "")
            lines.append(f"- [{cap}] [{rel_type}] {file_path} {summary}")
        lines.append("")

        lines.append("## File References")
        lines.append("")
        for ref in data.get("references", []):
            cap = ref.get("capability_id", "")
            file_path = ref.get("file_path", "")
            ext = ref.get("file_extension", "")
            lines.append(f"- [{cap}] {file_path} ({ext})")
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
                "file_path",
                "file_name",
                "file_extension",
                "relationship_type",
                "summary",
            ]
        )
        for r in data.get("relationships", []):
            writer.writerow(
                [
                    "relationship",
                    r.get("capability_id", ""),
                    r.get("file_path", ""),
                    "",
                    "",
                    r.get("relationship_type", ""),
                    r.get("summary", ""),
                ]
            )
        for ref in data.get("references", []):
            writer.writerow(
                [
                    "reference",
                    ref.get("capability_id", ""),
                    ref.get("file_path", ""),
                    ref.get("file_name", ""),
                    ref.get("file_extension", ""),
                    "",
                    "",
                ]
            )
        return buf.getvalue()
