"""Capability Chain Framework v1.

Provides deterministic capability chain pipelines on top of capability
selection. Where selection picks the best capability for a single work item,
chains represent complete ordered pipelines of capabilities for a work item
with evidence bundles.

Non-goals: no execution engine, no scheduling, no retries, no autonomy, no
orchestration, no approvals, no workflow routing, no merge behavior.
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

from axiom_core.artifact_paths import is_within_sandbox

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CapabilityChainType(str, Enum):
    LINEAR = "linear"
    VALIDATION_CHAIN = "validation_chain"
    REPAIR_CHAIN = "repair_chain"
    REVIEW_CHAIN = "review_chain"
    CUSTOM_CHAIN = "custom_chain"


_VALID_TYPES = {t.value for t in CapabilityChainType}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CapabilityChainStep:
    """A single ordered step within a capability chain."""

    step_id: str = ""
    order_index: int = 0
    capability_id: str = ""
    selection_id: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        if not self.step_id:
            self.step_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "order_index": self.order_index,
            "capability_id": self.capability_id,
            "selection_id": self.selection_id,
            "description": self.description,
        }


@dataclass
class CapabilityChain:
    """A complete deterministic capability pipeline for a work item."""

    chain_id: str = ""
    work_id: str = ""
    chain_type: str = "linear"
    steps: list[CapabilityChainStep] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.chain_id:
            self.chain_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "work_id": self.work_id,
            "chain_type": self.chain_type,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
        }


@dataclass
class CapabilityChainReport:
    """Report summarizing a set of capability chains."""

    report_id: str = ""
    chain_count: int = 0
    step_count: int = 0
    chain_type_counts: dict[str, int] = field(default_factory=dict)
    empty_step_count: int = 0
    created_at: str = ""
    chains: list[CapabilityChain] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "chain_count": self.chain_count,
            "step_count": self.step_count,
            "chain_type_counts": dict(self.chain_type_counts),
            "empty_step_count": self.empty_step_count,
            "created_at": self.created_at,
            "chains": [c.to_dict() for c in self.chains],
        }


@dataclass
class CapabilityChainEvidence:
    """Evidence record for a capability chain report."""

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


class CapabilityChainEngine:
    """Manages capability chain reports deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "capability_chains"
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

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(
        self, chains: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Create a capability chain report from a list of chains."""
        chains = chains or []

        chain_objects: list[CapabilityChain] = []
        for c_data in chains:
            chain_type = c_data.get("chain_type", "linear")
            if chain_type not in _VALID_TYPES:
                raise ValueError(
                    f"Invalid chain_type: {chain_type!r}. "
                    f"Valid: {sorted(_VALID_TYPES)}"
                )
            work_id = c_data.get("work_id", "")
            if not work_id or not work_id.strip():
                raise ValueError("work_id is required for a capability chain")

            step_objects: list[CapabilityChainStep] = []
            for s_data in c_data.get("steps", []):
                capability_id = s_data.get("capability_id", "")
                if not capability_id:
                    raise ValueError(
                        "capability_id is required for a capability chain step"
                    )
                step_objects.append(
                    CapabilityChainStep(
                        order_index=int(s_data.get("order_index", 0)),
                        capability_id=capability_id,
                        selection_id=s_data.get("selection_id", ""),
                        description=s_data.get("description", ""),
                    )
                )

            # Deterministic step ordering: by order_index, then capability_id,
            # then step_id for stability.
            step_objects.sort(
                key=lambda s: (s.order_index, s.capability_id, s.step_id)
            )

            chain_objects.append(
                CapabilityChain(
                    work_id=work_id,
                    chain_type=chain_type,
                    steps=step_objects,
                    created_at=c_data.get("created_at", ""),
                )
            )

        # Deterministic chain ordering: by created_at, then work_id, then
        # chain_id for stability.
        chain_objects.sort(
            key=lambda c: (c.created_at, c.work_id, c.chain_id)
        )

        chain_type_counts: dict[str, int] = {}
        for c in chain_objects:
            chain_type_counts[c.chain_type] = (
                chain_type_counts.get(c.chain_type, 0) + 1
            )
        chain_type_counts = {
            k: chain_type_counts[k] for k in sorted(chain_type_counts)
        }

        total_steps = sum(len(c.steps) for c in chain_objects)
        empty_step_count = sum(1 for c in chain_objects if not c.steps)

        report = CapabilityChainReport(
            chain_count=len(chain_objects),
            step_count=total_steps,
            chain_type_counts=chain_type_counts,
            empty_step_count=empty_step_count,
            chains=chain_objects,
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

    def export_report(self, report_id: str) -> str:
        self._validate_id_segment(report_id, "report_id")
        data = self._load_report(report_id)
        if data is None:
            raise ValueError(f"Capability chain report not found: {report_id}")
        return self._generate_export_md(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, report: CapabilityChainReport) -> None:
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

    def _write_evidence(self, report: CapabilityChainReport) -> None:
        evidence_dir = self._safe_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {"chains": [c.to_dict() for c in report.chains]}
        (evidence_dir / "capability_chain_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "capability_chain_result.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_export_md(report.to_dict())
        (evidence_dir / "capability_chain_summary.md").write_text(
            md, encoding="utf-8"
        )

        evidence = CapabilityChainEvidence(
            report_id=report.report_id,
            summary=(
                f"{report.chain_count} chains, "
                f"{report.step_count} steps, "
                f"{report.empty_step_count} empty chains"
            ),
        )

        passed = report.empty_step_count == 0
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "evidence_id": evidence.evidence_id,
            "chain_count": report.chain_count,
            "step_count": report.step_count,
            "chain_type_counts": dict(report.chain_type_counts),
            "empty_step_count": report.empty_step_count,
            "status": "passed" if passed else "failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _generate_export_md(data: dict[str, Any]) -> str:
        lines: list[str] = []

        lines.append("# Capability Chain Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        lines.append("## Chain Summary")
        lines.append("")
        lines.append(f"- Chains: {data.get('chain_count', 0)}")
        lines.append(f"- Steps: {data.get('step_count', 0)}")
        lines.append(f"- Empty chains: {data.get('empty_step_count', 0)}")
        lines.append("")

        chain_type_counts = data.get("chain_type_counts", {})
        lines.append("## Type Counts")
        lines.append("")
        for chain_type in sorted(chain_type_counts):
            lines.append(
                f"- {chain_type.upper()}: {chain_type_counts[chain_type]}"
            )
        lines.append("")

        chains_data = data.get("chains", [])
        if chains_data:
            lines.append("## Chains")
            lines.append("")
            for c in chains_data:
                chain_type = c.get("chain_type", "").upper()
                work_id = c.get("work_id", "")
                steps = c.get("steps", [])
                step_label = f"{len(steps)} steps" if steps else "(empty)"
                lines.append(
                    f"- [{work_id}] {chain_type} ({step_label})"
                )
                for s in steps:
                    order_index = s.get("order_index", 0)
                    capability_id = s.get("capability_id", "")
                    description = s.get("description", "")
                    desc_suffix = f" - {description}" if description else ""
                    lines.append(
                        f"  - {order_index}. {capability_id}{desc_suffix}"
                    )
            lines.append("")

        return "\n".join(lines)
