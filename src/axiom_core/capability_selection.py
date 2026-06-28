"""Capability Selection Framework v1.

Provides deterministic capability selection on top of capability routing. Where
capability routing routes work to candidate capabilities, capability selection
chooses the best capability from ranked candidates: candidates (scored options
for a work item), decisions (the capability selected for a work item, with the
reasons it was chosen) and reasons (why a particular candidate won), with
evidence bundles.

Consumes ``CapabilityRoute`` / ``CapabilityRoutingDecision`` (routing context),
``CapabilityDefinition`` (via ``capability_id``) and ``WorkItem`` (via
``work_id``) generically through identifier references; source references are
preserved through persistence and export.

Selection is deterministic with stable tie-breaking: within a work item the
candidate with the highest ``final_score`` wins, breaking ties by
``confidence_score``, ``priority_score``, ``routing_score`` and finally the
``capability_id`` (lexicographic). A work item with no candidates yields a
``NO_CANDIDATE`` decision.

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

# Supported reason types, in canonical display order.
REASON_TYPES = (
    "ROUTING_MATCH",
    "HIGHEST_SCORE",
    "HIGHEST_CONFIDENCE",
    "HIGHEST_PRIORITY",
    "TIE_BREAKER",
    "NO_CANDIDATE",
)

_REASON_ORDER = {name: index for index, name in enumerate(REASON_TYPES)}

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CapabilitySelectionCandidate:
    """A scored capability option for a particular work item."""

    candidate_id: str = ""
    capability_id: str = ""
    work_id: str = ""
    routing_score: int = 0
    confidence_score: int = 0
    priority_score: int = 0
    final_score: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.candidate_id:
            self.candidate_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "capability_id": self.capability_id,
            "work_id": self.work_id,
            "routing_score": self.routing_score,
            "confidence_score": self.confidence_score,
            "priority_score": self.priority_score,
            "final_score": self.final_score,
            "created_at": self.created_at,
        }


@dataclass
class CapabilitySelectionReason:
    """An explanation for why a candidate was selected."""

    reason_id: str = ""
    reason_type: str = ""
    summary: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.reason_id:
            self.reason_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason_id": self.reason_id,
            "reason_type": self.reason_type,
            "summary": self.summary,
            "created_at": self.created_at,
        }


@dataclass
class CapabilitySelectionDecision:
    """The capability selected to handle a particular work item."""

    decision_id: str = ""
    work_id: str = ""
    selected_capability_id: str = ""
    selected_candidate_id: str = ""
    candidate_count: int = 0
    final_score: int = 0
    reasons: list[CapabilitySelectionReason] = field(default_factory=list)
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
            "selected_candidate_id": self.selected_candidate_id,
            "candidate_count": self.candidate_count,
            "final_score": self.final_score,
            "reasons": [r.to_dict() for r in self.reasons],
            "created_at": self.created_at,
        }


@dataclass
class CapabilitySelectionReport:
    """Report summarizing capability selection decisions."""

    report_id: str = ""
    decision_count: int = 0
    selected_count: int = 0
    no_candidate_count: int = 0
    capability_counts: dict[str, int] = field(default_factory=dict)
    created_at: str = ""
    candidates: list[CapabilitySelectionCandidate] = field(default_factory=list)
    decisions: list[CapabilitySelectionDecision] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "decision_count": self.decision_count,
            "selected_count": self.selected_count,
            "no_candidate_count": self.no_candidate_count,
            "capability_counts": dict(self.capability_counts),
            "created_at": self.created_at,
            "candidates": [c.to_dict() for c in self.candidates],
            "decisions": [d.to_dict() for d in self.decisions],
        }


@dataclass
class CapabilitySelectionEvidence:
    """Evidence record for a capability selection report."""

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


class CapabilitySelectionEngine:
    """Selects the best capability per work item deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "capability_selection"
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
        candidates: list[dict[str, Any]] | None = None,
        decisions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a capability selection report.

        ``candidates`` are the scored options the engine selects between.
        ``decisions`` is an optional list declaring additional work items to
        evaluate (each entry needs a ``work_id``); this lets work items with no
        candidates be represented as ``NO_CANDIDATE`` decisions. The engine
        always performs the selection itself — any ``selected_capability_id``
        supplied on a decision entry is ignored in favour of deterministic
        derivation from the candidates.
        """
        candidates = candidates or []
        decisions = decisions or []

        candidate_objects: list[CapabilitySelectionCandidate] = []
        for c_data in candidates:
            capability_id = c_data.get("capability_id", "")
            if not capability_id:
                raise ValueError("capability_id is required for a selection candidate")
            work_id = c_data.get("work_id", "")
            if not work_id:
                raise ValueError("work_id is required for a selection candidate")
            routing_score = int(c_data.get("routing_score", 0))
            confidence_score = int(c_data.get("confidence_score", 0))
            priority_score = int(c_data.get("priority_score", 0))
            if "final_score" in c_data and c_data.get("final_score") is not None:
                final_score = int(c_data["final_score"])
            else:
                final_score = routing_score + confidence_score + priority_score
            candidate_objects.append(
                CapabilitySelectionCandidate(
                    capability_id=capability_id,
                    work_id=work_id,
                    routing_score=routing_score,
                    confidence_score=confidence_score,
                    priority_score=priority_score,
                    final_score=final_score,
                    created_at=c_data.get("created_at", ""),
                )
            )

        # Work items to decide on: every work id seen in candidates plus any
        # explicitly declared in the decisions input (which may have none).
        declared_work_ids: list[str] = []
        for d_data in decisions:
            work_id = d_data.get("work_id", "")
            if not work_id:
                raise ValueError("work_id is required for a selection decision")
            declared_work_ids.append(work_id)

        work_ids = sorted(
            {c.work_id for c in candidate_objects} | set(declared_work_ids)
        )

        by_work: dict[str, list[CapabilitySelectionCandidate]] = {}
        for c in candidate_objects:
            by_work.setdefault(c.work_id, []).append(c)

        decision_objects: list[CapabilitySelectionDecision] = []
        for work_id in work_ids:
            group = by_work.get(work_id, [])
            decision_objects.append(self._select(work_id, group))

        # Deterministic ordering independent of input order.
        candidate_objects.sort(
            key=lambda c: (c.created_at, c.work_id, c.capability_id, c.candidate_id)
        )
        decision_objects.sort(key=lambda d: (d.work_id, d.decision_id))

        selected_count = sum(
            1 for d in decision_objects if d.selected_capability_id
        )
        no_candidate_count = len(decision_objects) - selected_count

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

        report = CapabilitySelectionReport(
            decision_count=len(decision_objects),
            selected_count=selected_count,
            no_candidate_count=no_candidate_count,
            capability_counts=capability_counts,
            candidates=candidate_objects,
            decisions=decision_objects,
        )

        self._persist(report)
        self._write_evidence(report)

        return report.to_dict()

    @staticmethod
    def _select(
        work_id: str, group: list[CapabilitySelectionCandidate]
    ) -> CapabilitySelectionDecision:
        """Select the best candidate for a work item with stable tie-breaking."""
        if not group:
            reason = CapabilitySelectionReason(
                reason_type="NO_CANDIDATE",
                summary=f"No candidates available for work {work_id}",
            )
            return CapabilitySelectionDecision(
                work_id=work_id,
                selected_capability_id="",
                selected_candidate_id="",
                candidate_count=0,
                final_score=0,
                reasons=[reason],
            )

        # Stable tie-break: highest final, then confidence, priority, routing,
        # then capability_id (lexicographic) for a deterministic winner.
        ranked = sorted(
            group,
            key=lambda c: (
                -c.final_score,
                -c.confidence_score,
                -c.priority_score,
                -c.routing_score,
                c.capability_id,
                c.candidate_id,
            ),
        )
        winner = ranked[0]

        max_final = max(c.final_score for c in group)
        max_confidence = max(c.confidence_score for c in group)
        max_priority = max(c.priority_score for c in group)
        tied = sum(1 for c in group if c.final_score == max_final)

        reason_specs: list[tuple[str, str]] = []
        if winner.routing_score > 0:
            reason_specs.append(
                (
                    "ROUTING_MATCH",
                    f"{winner.capability_id} matched routing "
                    f"(routing score {winner.routing_score})",
                )
            )
        reason_specs.append(
            (
                "HIGHEST_SCORE",
                f"{winner.capability_id} has the highest final score "
                f"({winner.final_score})",
            )
        )
        if winner.confidence_score == max_confidence:
            reason_specs.append(
                (
                    "HIGHEST_CONFIDENCE",
                    f"{winner.capability_id} has the highest confidence "
                    f"({winner.confidence_score})",
                )
            )
        if winner.priority_score == max_priority:
            reason_specs.append(
                (
                    "HIGHEST_PRIORITY",
                    f"{winner.capability_id} has the highest priority "
                    f"({winner.priority_score})",
                )
            )
        if tied > 1:
            reason_specs.append(
                (
                    "TIE_BREAKER",
                    f"{tied} candidates tied on final score {max_final}; "
                    f"broke tie deterministically",
                )
            )

        reason_specs.sort(key=lambda spec: _REASON_ORDER[spec[0]])
        reasons = [
            CapabilitySelectionReason(reason_type=rt, summary=summary)
            for rt, summary in reason_specs
        ]

        return CapabilitySelectionDecision(
            work_id=work_id,
            selected_capability_id=winner.capability_id,
            selected_candidate_id=winner.candidate_id,
            candidate_count=len(group),
            final_score=winner.final_score,
            reasons=reasons,
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

    def export_report(self, report_id: str) -> str:
        self._validate_id_segment(report_id, "report_id")
        data = self._load_report(report_id)
        if data is None:
            raise ValueError(f"Capability selection report not found: {report_id}")
        return self._generate_export_md(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, report: CapabilitySelectionReport) -> None:
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

    def _write_evidence(self, report: CapabilitySelectionReport) -> None:
        evidence_dir = self._safe_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "candidates": [c.to_dict() for c in report.candidates],
            "decisions": [
                {"work_id": d.work_id} for d in report.decisions
            ],
        }
        (evidence_dir / "capability_selection_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "capability_selection_result.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_export_md(report.to_dict())
        (evidence_dir / "capability_selection_summary.md").write_text(
            md, encoding="utf-8"
        )

        evidence = CapabilitySelectionEvidence(
            report_id=report.report_id,
            summary=(
                f"{report.decision_count} decisions, "
                f"{len(report.candidates)} candidates, "
                f"{report.selected_count} selected, "
                f"{report.no_candidate_count} no-candidate, "
                f"{len(report.capability_counts)} capabilities"
            ),
        )

        # A capability selection report passes when every work item resolves to
        # a selected capability (no no-candidate decisions).
        passed = report.no_candidate_count == 0
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "evidence_id": evidence.evidence_id,
            "decision_count": report.decision_count,
            "selected_count": report.selected_count,
            "no_candidate_count": report.no_candidate_count,
            "capability_counts": dict(report.capability_counts),
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

        lines.append("# Capability Selection Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        lines.append("## Selection Summary")
        lines.append("")
        lines.append(f"- Decisions: {data.get('decision_count', 0)}")
        lines.append(f"- Candidates: {len(data.get('candidates', []))}")
        lines.append(f"- Selected: {data.get('selected_count', 0)}")
        lines.append(f"- No candidate: {data.get('no_candidate_count', 0)}")
        lines.append("")

        capability_counts = data.get("capability_counts", {})
        lines.append("## Capability Counts")
        lines.append("")
        for capability_id in sorted(capability_counts):
            lines.append(f"- {capability_id}: {capability_counts[capability_id]}")
        lines.append("")

        candidates = data.get("candidates", [])
        if candidates:
            lines.append("## Candidates")
            lines.append("")
            for c in candidates:
                lines.append(
                    f"- [{c.get('work_id', '')}] {c.get('capability_id', '')} "
                    f"(final {c.get('final_score', 0)}, "
                    f"routing {c.get('routing_score', 0)}, "
                    f"confidence {c.get('confidence_score', 0)}, "
                    f"priority {c.get('priority_score', 0)})"
                )
            lines.append("")

        decisions = data.get("decisions", [])
        if decisions:
            lines.append("## Decisions")
            lines.append("")
            for d in decisions:
                work_id = d.get("work_id", "")
                selected = d.get("selected_capability_id", "") or "(no candidate)"
                lines.append(
                    f"- {work_id} -> {selected} "
                    f"(final {d.get('final_score', 0)}, "
                    f"{d.get('candidate_count', 0)} candidates)"
                )
                for reason in d.get("reasons", []):
                    lines.append(
                        f"  - {reason.get('reason_type', '')}: "
                        f"{reason.get('summary', '')}"
                    )
            lines.append("")

        return "\n".join(lines)
