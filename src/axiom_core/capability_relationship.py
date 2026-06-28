"""Capability Relationship Framework v1.

The first formal relationship layer for capabilities. Where the Global
Capability Registry establishes identity and the Capability Summary establishes
understanding, this layer establishes *relationships* between capabilities:
graph-ready, typed, directed edges (``source -> target``) with a relationship
type, confidence, and a preserved raw payload.

This framework moves beyond linear previous/next capability chains and models
capability evolution as a graph. It is deliberately *structure only*: it builds
a deterministic, append-only edge list plus a lightweight reference projection.

Non-goals: no graph engine, no graph queries, no visualization, no dashboard,
no Organizational Twin, no worker orchestration, no automatic relationship
discovery, no network calls.
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


class CapabilityRelationshipType(str, Enum):
    BUILDS_ON = "BUILDS_ON"
    ENABLES = "ENABLES"
    RELATED_TO = "RELATED_TO"
    DEPENDS_ON = "DEPENDS_ON"
    SUPERSEDES = "SUPERSEDES"
    DERIVED_FROM = "DERIVED_FROM"
    AFFECTS = "AFFECTS"
    VALIDATES = "VALIDATES"
    REPAIRS = "REPAIRS"


_VALID_RELATIONSHIP_TYPES = {t.value for t in CapabilityRelationshipType}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class CapabilityRelationship:
    """A typed, directed relationship between two capabilities."""

    relationship_id: str = ""
    source_capability_id: str = ""
    target_capability_id: str = ""
    relationship_type: str = ""
    confidence: float = 1.0
    summary: str = ""
    created_at: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.relationship_id:
            self.relationship_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "relationship_id": self.relationship_id,
            "source_capability_id": self.source_capability_id,
            "target_capability_id": self.target_capability_id,
            "relationship_type": self.relationship_type,
            "confidence": self.confidence,
            "summary": self.summary,
            "created_at": self.created_at,
            "raw_payload": dict(self.raw_payload),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityRelationship:
        return cls(
            relationship_id=data.get("relationship_id", ""),
            source_capability_id=data.get("source_capability_id", ""),
            target_capability_id=data.get("target_capability_id", ""),
            relationship_type=data.get("relationship_type", ""),
            confidence=data.get("confidence", 1.0),
            summary=data.get("summary", ""),
            created_at=data.get("created_at", ""),
            raw_payload=dict(data.get("raw_payload", {})),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )


@dataclass
class CapabilityRelationshipReference:
    """A lightweight, graph-ready projection of a relationship edge."""

    reference_id: str = ""
    source_capability_id: str = ""
    target_capability_id: str = ""
    relationship_type: str = ""

    def __post_init__(self) -> None:
        if not self.reference_id:
            self.reference_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_id": self.reference_id,
            "source_capability_id": self.source_capability_id,
            "target_capability_id": self.target_capability_id,
            "relationship_type": self.relationship_type,
        }


@dataclass
class CapabilityRelationshipReport:
    """A deterministic, append-only relationship report (edge list)."""

    report_id: str = ""
    relationships: list[CapabilityRelationship] = field(default_factory=list)
    references: list[CapabilityRelationshipReference] = field(
        default_factory=list
    )
    relationship_count: int = 0
    relationship_type_counts: dict[str, int] = field(default_factory=dict)
    duplicate_relationship_count: int = 0
    known_capability_ids: list[str] = field(default_factory=list)
    orphan_capability_ids: list[str] = field(default_factory=list)
    orphan_capability_count: int = 0
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
            "relationships": [r.to_dict() for r in self.relationships],
            "references": [r.to_dict() for r in self.references],
            "relationship_count": self.relationship_count,
            "relationship_type_counts": dict(self.relationship_type_counts),
            "duplicate_relationship_count": self.duplicate_relationship_count,
            "known_capability_ids": list(self.known_capability_ids),
            "orphan_capability_ids": list(self.orphan_capability_ids),
            "orphan_capability_count": self.orphan_capability_count,
            "created_at": self.created_at,
            "raw_metadata": dict(self.raw_metadata),
            "schema_version": self.schema_version,
        }


@dataclass
class CapabilityRelationshipEvidence:
    """Evidence record for a capability relationship report."""

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


class CapabilityRelationshipEngine:
    """Manages capability relationship reports deterministically.

    Relationships are deduplicated on ``(source, target, type)`` so the edge
    list is graph-ready, ordered deterministically, and append-only. The
    registry/summary are *consumed* read-only via an optional set of known
    capability ids used only to detect orphan capabilities (those with no
    relationships); nothing is mutated.
    """

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "capability_relationships"
        self._report_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Path safety
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
    # Building / validation
    # ------------------------------------------------------------------

    @staticmethod
    def _relationship_sort_key(r: CapabilityRelationship) -> tuple:
        return (
            r.source_capability_id,
            r.target_capability_id,
            r.relationship_type,
            r.relationship_id,
        )

    @staticmethod
    def _build_relationship(data: dict[str, Any]) -> CapabilityRelationship:
        source = data.get("source_capability_id", "")
        if not source or not str(source).strip():
            raise ValueError(
                "source_capability_id is required for a relationship"
            )
        target = data.get("target_capability_id", "")
        if not target or not str(target).strip():
            raise ValueError(
                "target_capability_id is required for a relationship"
            )
        rel_type_raw = data.get("relationship_type", "")
        if not rel_type_raw or not str(rel_type_raw).strip():
            raise ValueError(
                "relationship_type is required for a relationship"
            )
        rel_type = str(rel_type_raw).strip().upper()
        if rel_type not in _VALID_RELATIONSHIP_TYPES:
            raise ValueError(
                f"Invalid relationship_type: {rel_type_raw!r}. "
                f"Valid: {sorted(_VALID_RELATIONSHIP_TYPES)}"
            )

        confidence_raw = data.get("confidence", 1.0)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"confidence must be a number: {confidence_raw!r}"
            ) from exc
        confidence = max(0.0, min(1.0, confidence))

        normalized = dict(data)
        normalized["source_capability_id"] = str(source)
        normalized["target_capability_id"] = str(target)
        normalized["relationship_type"] = rel_type
        normalized["confidence"] = confidence
        return CapabilityRelationship.from_dict(normalized)

    def _assemble(
        self, report: CapabilityRelationshipReport
    ) -> dict[str, Any]:
        report.relationships.sort(key=self._relationship_sort_key)

        # Deduplicate graph edges on (source, target, type); keep the first
        # occurrence in deterministic order and count the rest.
        seen: set[tuple[str, str, str]] = set()
        deduped: list[CapabilityRelationship] = []
        duplicate_count = 0
        for r in report.relationships:
            edge = (
                r.source_capability_id,
                r.target_capability_id,
                r.relationship_type,
            )
            if edge in seen:
                duplicate_count += 1
                continue
            seen.add(edge)
            deduped.append(r)
        report.relationships = deduped
        report.duplicate_relationship_count = duplicate_count
        report.relationship_count = len(deduped)

        type_counts: dict[str, int] = {}
        for r in deduped:
            type_counts[r.relationship_type] = (
                type_counts.get(r.relationship_type, 0) + 1
            )
        report.relationship_type_counts = {
            k: type_counts[k] for k in sorted(type_counts)
        }

        report.references = [
            CapabilityRelationshipReference(
                source_capability_id=r.source_capability_id,
                target_capability_id=r.target_capability_id,
                relationship_type=r.relationship_type,
            )
            for r in deduped
        ]

        # Orphan detection: known capabilities not participating in any edge.
        connected: set[str] = set()
        for r in deduped:
            connected.add(r.source_capability_id)
            connected.add(r.target_capability_id)
        known = sorted({str(c) for c in report.known_capability_ids if c})
        report.known_capability_ids = known
        orphans = [c for c in known if c not in connected]
        report.orphan_capability_ids = orphans
        report.orphan_capability_count = len(orphans)

        return report.to_dict()

    # ------------------------------------------------------------------
    # Create / Append (append-only)
    # ------------------------------------------------------------------

    def create(
        self,
        relationships: list[dict[str, Any]] | None = None,
        known_capability_ids: list[str] | None = None,
        raw_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new capability relationship report."""
        report = CapabilityRelationshipReport(
            raw_metadata=dict(raw_metadata or {}),
            known_capability_ids=list(known_capability_ids or []),
        )
        report.relationships = [
            self._build_relationship(r) for r in (relationships or [])
        ]
        assembled = self._assemble(report)
        self._persist(assembled)
        self._write_evidence(assembled)
        return assembled

    def append(
        self,
        report_id: str,
        relationships: list[dict[str, Any]] | None = None,
        known_capability_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Append relationships to a report (append-only; no removal)."""
        self._validate_id_segment(report_id, "report_id")
        existing = self._load_report(report_id)
        if existing is None:
            raise ValueError(f"Report not found: {report_id}")

        merged_known = list(existing.get("known_capability_ids", []))
        merged_known.extend(known_capability_ids or [])
        report = CapabilityRelationshipReport(
            report_id=existing["report_id"],
            created_at=existing.get("created_at", ""),
            raw_metadata=dict(existing.get("raw_metadata", {})),
            known_capability_ids=merged_known,
            schema_version=existing.get("schema_version", SCHEMA_VERSION),
        )
        # Preserve existing relationships verbatim (append-only).
        report.relationships = [
            CapabilityRelationship.from_dict(r)
            for r in existing.get("relationships", [])
        ]
        report.relationships.extend(
            self._build_relationship(r) for r in (relationships or [])
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
            "relationships": report.get("relationships", []),
            "known_capability_ids": report.get("known_capability_ids", []),
            "raw_metadata": report.get("raw_metadata", {}),
        }
        (evidence_dir / "capability_relationship_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "capability_relationship_result.json").write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "capability_relationship_summary.md").write_text(
            self._generate_export_md(report), encoding="utf-8"
        )

        relationship_count = report.get("relationship_count", 0)
        duplicate_count = report.get("duplicate_relationship_count", 0)
        evidence = CapabilityRelationshipEvidence(
            report_id=report["report_id"],
            summary=(
                f"{relationship_count} relationship(s), "
                f"{report.get('orphan_capability_count', 0)} orphan(s), "
                f"{duplicate_count} duplicate(s)"
            ),
        )

        # A report passes when it carries at least one relationship and no
        # duplicate edges were detected (graph-edge uniqueness integrity).
        passed = relationship_count > 0 and duplicate_count == 0
        pass_fail = {
            "passed": passed,
            "report_id": report["report_id"],
            "evidence_id": evidence.evidence_id,
            "relationship_count": relationship_count,
            "duplicate_relationship_count": duplicate_count,
            "orphan_capability_count": report.get(
                "orphan_capability_count", 0
            ),
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

        lines.append("# Capability Relationship Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append(f"- Schema Version: {data.get('schema_version', '')}")
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        lines.append(
            f"- Relationships: {data.get('relationship_count', 0)}"
        )
        lines.append(
            f"- Duplicates: {data.get('duplicate_relationship_count', 0)}"
        )
        lines.append(
            f"- Orphan Capabilities: "
            f"{data.get('orphan_capability_count', 0)}"
        )
        lines.append("")

        type_counts = data.get("relationship_type_counts", {})
        lines.append("## Relationship Type Counts")
        lines.append("")
        for rel_type in sorted(type_counts):
            lines.append(f"- {rel_type}: {type_counts[rel_type]}")
        lines.append("")

        lines.append("## Relationships")
        lines.append("")
        for r in data.get("relationships", []):
            source = r.get("source_capability_id", "")
            target = r.get("target_capability_id", "")
            rel_type = r.get("relationship_type", "")
            confidence = r.get("confidence", "")
            lines.append(
                f"- [{source}] --[{rel_type}]--> [{target}] "
                f"(confidence: {confidence})"
            )
        lines.append("")

        orphans = data.get("orphan_capability_ids", [])
        lines.append("## Orphan Capabilities")
        lines.append("")
        for cap_id in orphans:
            lines.append(f"- [{cap_id}]")
        lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _generate_export_csv(data: dict[str, Any]) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "source_capability_id",
                "target_capability_id",
                "relationship_type",
                "confidence",
                "created_at",
                "schema_version",
            ]
        )
        for r in data.get("relationships", []):
            writer.writerow(
                [
                    r.get("source_capability_id", ""),
                    r.get("target_capability_id", ""),
                    r.get("relationship_type", ""),
                    r.get("confidence", ""),
                    r.get("created_at", ""),
                    r.get("schema_version", ""),
                ]
            )
        return buf.getvalue()
