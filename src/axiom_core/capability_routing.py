"""Capability Routing Framework v1.

Provides deterministic capability routing on top of skill compositions. Where
prior frameworks compose reusable skill sequences, capability routing represents
selecting which capability should handle a particular work item: routes (static
capability/work-type mappings), routing rules (weighted work-pattern matches),
and routing decisions (the capability selected for a given work item), with
evidence bundles.

Consumes ``CapabilityDefinition`` (via ``capability_id``), ``SkillComposition``
(routing context) and ``WorkItem`` (via ``work_id`` / ``work_type``) generically
through identifier references; source references are preserved through
persistence and export.

Non-goals: no dynamic scheduling, no autonomous worker assignment, no
multi-agent orchestration, no approvals, no workflow routing, no merge behavior.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from axiom_core.artifact_paths import is_within_sandbox

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CapabilityRoute:
    """A static mapping of a work type to a capability."""

    route_id: str = ""
    capability_id: str = ""
    work_type: str = ""
    priority: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.route_id:
            self.route_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "capability_id": self.capability_id,
            "work_type": self.work_type,
            "priority": self.priority,
            "created_at": self.created_at,
        }


@dataclass
class CapabilityRoutingRule:
    """A weighted rule matching a work pattern to a capability."""

    rule_id: str = ""
    work_pattern: str = ""
    capability_id: str = ""
    weight: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.rule_id:
            self.rule_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "work_pattern": self.work_pattern,
            "capability_id": self.capability_id,
            "weight": self.weight,
            "created_at": self.created_at,
        }


@dataclass
class CapabilityRoutingDecision:
    """The capability selected to handle a particular work item."""

    decision_id: str = ""
    work_id: str = ""
    selected_capability_id: str = ""
    candidate_count: int = 0
    routing_score: int = 0
    rationale: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.decision_id:
            self.decision_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "work_id": self.work_id,
            "selected_capability_id": self.selected_capability_id,
            "candidate_count": self.candidate_count,
            "routing_score": self.routing_score,
            "rationale": self.rationale,
            "created_at": self.created_at,
        }


@dataclass
class CapabilityRoutingReport:
    """Report summarizing capability routing decisions."""

    report_id: str = ""
    decision_count: int = 0
    capability_counts: dict[str, int] = field(default_factory=dict)
    created_at: str = ""
    routes: list[CapabilityRoute] = field(default_factory=list)
    rules: list[CapabilityRoutingRule] = field(default_factory=list)
    decisions: list[CapabilityRoutingDecision] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "decision_count": self.decision_count,
            "capability_counts": dict(self.capability_counts),
            "created_at": self.created_at,
            "routes": [r.to_dict() for r in self.routes],
            "rules": [r.to_dict() for r in self.rules],
            "decisions": [d.to_dict() for d in self.decisions],
        }


@dataclass
class CapabilityRoutingEvidence:
    """Evidence record for a capability routing report."""

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


class CapabilityRoutingEngine:
    """Manages capability routing reports deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "capability_routing"
        self._report_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"{name} must not be empty or whitespace")
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(f"{name} must not contain '..', '/', or '\\': {value!r}")

    def _safe_path(self, report_id: str) -> Path:
        target = (self._report_dir / report_id).resolve()
        sandbox = self._report_dir.resolve()
        if not is_within_sandbox(target, sandbox):
            raise ValueError(f"Resolved path escapes artifacts root: {report_id!r}")
        return target

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(
        self,
        routes: list[dict[str, Any]] | None = None,
        rules: list[dict[str, Any]] | None = None,
        decisions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a capability routing report from routes, rules and decisions."""
        routes = routes or []
        rules = rules or []
        decisions = decisions or []

        route_objects: list[CapabilityRoute] = []
        for r_data in routes:
            capability_id = r_data.get("capability_id", "")
            if not capability_id:
                raise ValueError("capability_id is required for a capability route")
            route_objects.append(
                CapabilityRoute(
                    capability_id=capability_id,
                    work_type=r_data.get("work_type", ""),
                    priority=int(r_data.get("priority", 0)),
                    created_at=r_data.get("created_at", ""),
                )
            )

        rule_objects: list[CapabilityRoutingRule] = []
        for rule_data in rules:
            capability_id = rule_data.get("capability_id", "")
            if not capability_id:
                raise ValueError(
                    "capability_id is required for a capability routing rule"
                )
            work_pattern = rule_data.get("work_pattern", "")
            if not work_pattern or not work_pattern.strip():
                raise ValueError(
                    "work_pattern is required for a capability routing rule"
                )
            rule_objects.append(
                CapabilityRoutingRule(
                    work_pattern=work_pattern,
                    capability_id=capability_id,
                    weight=int(rule_data.get("weight", 0)),
                    created_at=rule_data.get("created_at", ""),
                )
            )

        decision_objects: list[CapabilityRoutingDecision] = []
        for d_data in decisions:
            work_id = d_data.get("work_id", "")
            if not work_id:
                raise ValueError("work_id is required for a routing decision")
            decision_objects.append(
                CapabilityRoutingDecision(
                    work_id=work_id,
                    selected_capability_id=d_data.get("selected_capability_id", ""),
                    candidate_count=int(d_data.get("candidate_count", 0)),
                    routing_score=int(d_data.get("routing_score", 0)),
                    rationale=d_data.get("rationale", ""),
                    created_at=d_data.get("created_at", ""),
                )
            )

        # Deterministic ordering independent of input order.
        route_objects.sort(
            key=lambda r: (r.created_at, r.capability_id, r.route_id)
        )
        rule_objects.sort(
            key=lambda r: (r.created_at, r.work_pattern, r.rule_id)
        )
        decision_objects.sort(
            key=lambda d: (d.created_at, d.work_id, d.decision_id)
        )

        # Count routed decisions by selected capability (sorted keys for
        # reproducible output); unrouted decisions are excluded.
        capability_counts: dict[str, int] = {}
        for d in decision_objects:
            if not d.selected_capability_id:
                continue
            capability_counts[d.selected_capability_id] = (
                capability_counts.get(d.selected_capability_id, 0) + 1
            )
        capability_counts = {
            k: capability_counts[k] for k in sorted(capability_counts)
        }

        report = CapabilityRoutingReport(
            decision_count=len(decision_objects),
            capability_counts=capability_counts,
            routes=route_objects,
            rules=rule_objects,
            decisions=decision_objects,
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
            raise ValueError(f"Capability routing report not found: {report_id}")
        return self._generate_export_md(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, report: CapabilityRoutingReport) -> None:
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

    def _write_evidence(self, report: CapabilityRoutingReport) -> None:
        evidence_dir = self._safe_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "routes": [r.to_dict() for r in report.routes],
            "rules": [r.to_dict() for r in report.rules],
            "decisions": [d.to_dict() for d in report.decisions],
        }
        (evidence_dir / "capability_routing_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "capability_routing_result.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_export_md(report.to_dict())
        (evidence_dir / "capability_routing_summary.md").write_text(
            md, encoding="utf-8"
        )

        unrouted_count = sum(
            1 for d in report.decisions if not d.selected_capability_id
        )
        evidence = CapabilityRoutingEvidence(
            report_id=report.report_id,
            summary=(
                f"{report.decision_count} decisions, "
                f"{len(report.routes)} routes, "
                f"{len(report.rules)} rules, "
                f"{len(report.capability_counts)} capabilities, "
                f"{unrouted_count} unrouted decisions"
            ),
        )

        # A capability routing report passes when every decision selects a
        # capability (no unrouted decisions).
        passed = unrouted_count == 0
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "evidence_id": evidence.evidence_id,
            "decision_count": report.decision_count,
            "capability_counts": dict(report.capability_counts),
            "unrouted_count": unrouted_count,
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

        lines.append("# Capability Routing Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        lines.append("## Routing Summary")
        lines.append("")
        lines.append(f"- Decisions: {data.get('decision_count', 0)}")
        lines.append(f"- Routes: {len(data.get('routes', []))}")
        lines.append(f"- Rules: {len(data.get('rules', []))}")
        lines.append("")

        capability_counts = data.get("capability_counts", {})
        lines.append("## Capability Counts")
        lines.append("")
        for capability_id in sorted(capability_counts):
            lines.append(f"- {capability_id}: {capability_counts[capability_id]}")
        lines.append("")

        routes = data.get("routes", [])
        if routes:
            lines.append("## Routes")
            lines.append("")
            for r in routes:
                lines.append(
                    f"- [{r.get('work_type', '')}] -> {r.get('capability_id', '')} "
                    f"(priority {r.get('priority', 0)})"
                )
            lines.append("")

        rules = data.get("rules", [])
        if rules:
            lines.append("## Rules")
            lines.append("")
            for r in rules:
                lines.append(
                    f"- [{r.get('work_pattern', '')}] -> "
                    f"{r.get('capability_id', '')} (weight {r.get('weight', 0)})"
                )
            lines.append("")

        decisions = data.get("decisions", [])
        if decisions:
            lines.append("## Decisions")
            lines.append("")
            for d in decisions:
                work_id = d.get("work_id", "")
                selected = d.get("selected_capability_id", "") or "(unrouted)"
                lines.append(
                    f"- {work_id} -> {selected} "
                    f"(score {d.get('routing_score', 0)}, "
                    f"{d.get('candidate_count', 0)} candidates)"
                )
            lines.append("")

        return "\n".join(lines)
