"""Capability Definition Framework v1.

Provides explicit capability definitions as first-class objects on top of
configuration dependencies. Represents executable capabilities with types,
statuses, and dependency references.

Non-goals: no autonomous planning, no workflow engines, no schedulers,
no external capability services.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CapabilityType(str, Enum):
    VALIDATION = "validation"
    REPAIR = "repair"
    EXPLANATION = "explanation"
    EXECUTION = "execution"
    REPORTING = "reporting"
    ANALYSIS = "analysis"


class CapabilityStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    EXPERIMENTAL = "experimental"
    DEPRECATED = "deprecated"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CapabilityDefinition:
    """A first-class capability definition."""

    capability_id: str = ""
    name: str = ""
    description: str = ""
    capability_type: str = "validation"
    status: str = "active"
    dependency_ids: list[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.capability_id:
            self.capability_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "description": self.description,
            "capability_type": self.capability_type,
            "status": self.status,
            "dependency_ids": self.dependency_ids,
            "created_at": self.created_at,
        }


@dataclass
class CapabilityRegistry:
    """A registry of capability definitions."""

    registry_id: str = ""
    capabilities: list[CapabilityDefinition] = field(default_factory=list)
    capability_count: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.registry_id:
            self.registry_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "registry_id": self.registry_id,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "capability_count": self.capability_count,
            "created_at": self.created_at,
        }


@dataclass
class CapabilityDefinitionReport:
    """Report summarizing a capability registry."""

    report_id: str = ""
    registry_id: str = ""
    summary: str = ""
    active_count: int = 0
    disabled_count: int = 0
    experimental_count: int = 0
    deprecated_count: int = 0
    registry: CapabilityRegistry | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "registry_id": self.registry_id,
            "summary": self.summary,
            "active_count": self.active_count,
            "disabled_count": self.disabled_count,
            "experimental_count": self.experimental_count,
            "deprecated_count": self.deprecated_count,
            "registry": self.registry.to_dict() if self.registry else None,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Capability definition engine
# ---------------------------------------------------------------------------


class CapabilityDefinitionEngine:
    """Manages capability definitions deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._cap_dir = self._artifacts_root / "capabilities"
        self._cap_dir.mkdir(parents=True, exist_ok=True)

    def _safe_cap_path(self, report_id: str) -> Path:
        target = (self._cap_dir / report_id).resolve()
        sandbox = self._cap_dir.resolve()
        if not str(target).startswith(str(sandbox) + "/") and target != sandbox:
            raise ValueError(f"Resolved path escapes artifacts root: {report_id!r}")
        return target

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"{name} must not be empty or whitespace")
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(f"{name} must not contain '..', '/', or '\\': {value!r}")

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(
        self,
        capabilities: list[dict[str, Any]] | None = None,
        known_dependency_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a capability registry from a list of capability dicts."""
        capabilities = capabilities or []
        known_deps = set(known_dependency_ids) if known_dependency_ids is not None else None

        cap_objects: list[CapabilityDefinition] = []
        for cap_data in sorted(capabilities, key=lambda c: c.get("name", "")):
            cap = CapabilityDefinition(
                name=cap_data.get("name", ""),
                description=cap_data.get("description", ""),
                capability_type=cap_data.get("capability_type", "validation"),
                status=cap_data.get("status", "active"),
                dependency_ids=cap_data.get("dependency_ids") or [],
            )

            if known_deps is not None:
                for dep_id in cap.dependency_ids:
                    if dep_id not in known_deps:
                        cap.status = CapabilityStatus.DISABLED.value
                        break

            cap_objects.append(cap)

        registry = CapabilityRegistry(
            capabilities=cap_objects,
            capability_count=len(cap_objects),
        )

        active_count = sum(1 for c in cap_objects if c.status == CapabilityStatus.ACTIVE.value)
        disabled_count = sum(1 for c in cap_objects if c.status == CapabilityStatus.DISABLED.value)
        experimental_count = sum(
            1 for c in cap_objects if c.status == CapabilityStatus.EXPERIMENTAL.value
        )
        deprecated_count = sum(
            1 for c in cap_objects if c.status == CapabilityStatus.DEPRECATED.value
        )

        summary = (
            f"Registry '{registry.registry_id}': "
            f"{len(cap_objects)} capabilities — "
            f"{active_count} active, {disabled_count} disabled, "
            f"{experimental_count} experimental, {deprecated_count} deprecated."
        )

        report = CapabilityDefinitionReport(
            registry_id=registry.registry_id,
            summary=summary,
            active_count=active_count,
            disabled_count=disabled_count,
            experimental_count=experimental_count,
            deprecated_count=deprecated_count,
            registry=registry,
        )

        self._persist_report(report)
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
        if not self._cap_dir.exists():
            return reports

        sandbox = self._cap_dir.resolve()
        for entry in self._cap_dir.iterdir():
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

    def export_report(self, report_id: str) -> str:
        self._validate_id_segment(report_id, "report_id")
        data = self._load_report(report_id)
        if data is None:
            raise ValueError(f"Capability report not found: {report_id}")
        return self._generate_summary(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_report(self, report: CapabilityDefinitionReport) -> None:
        report_dir = self._safe_cap_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def _load_report(self, report_id: str) -> dict[str, Any] | None:
        report_dir = self._safe_cap_path(report_id)
        report_file = report_dir / "report.json"
        if not report_file.exists():
            return None
        return json.loads(report_file.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def _write_evidence(self, report: CapabilityDefinitionReport) -> None:
        evidence_dir = self._safe_cap_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "registry_id": report.registry_id,
            "capabilities": (
                [c.to_dict() for c in report.registry.capabilities] if report.registry else []
            ),
        }
        (evidence_dir / "capability_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        result_data = report.to_dict()
        (evidence_dir / "capability_result.json").write_text(
            json.dumps(result_data, indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_summary(report.to_dict())
        (evidence_dir / "capability_summary.md").write_text(
            md,
            encoding="utf-8",
        )

        passed = report.disabled_count == 0
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "registry_id": report.registry_id,
            "active_count": report.active_count,
            "disabled_count": report.disabled_count,
            "status": "passed" if passed else "failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _generate_summary(data: dict[str, Any]) -> str:
        lines: list[str] = []

        lines.append("# Capability Definition Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Registry ID: {data.get('registry_id', '')}")
        lines.append(f"- Summary: {data.get('summary', '')}")
        lines.append(f"- Active: {data.get('active_count', 0)}")
        lines.append(f"- Disabled: {data.get('disabled_count', 0)}")
        lines.append(f"- Experimental: {data.get('experimental_count', 0)}")
        lines.append(f"- Deprecated: {data.get('deprecated_count', 0)}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        registry = data.get("registry")
        if registry:
            caps = registry.get("capabilities", [])
            if caps:
                lines.append("## Capabilities")
                lines.append("")
                for cap in caps:
                    status = cap.get("status", "").upper()
                    ctype = cap.get("capability_type", "")
                    lines.append(f"- [{status}] {cap.get('name', '')} " f"(type: {ctype})")
                    if cap.get("description"):
                        lines.append(f"  {cap['description']}")
                    if cap.get("dependency_ids"):
                        lines.append(f"  Dependencies: {', '.join(cap['dependency_ids'])}")
                lines.append("")

        return "\n".join(lines)
