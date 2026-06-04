"""Promotion Eligibility Engine v1 (PR #30).

Axiom can already discover, execute, validate, classify, and remember capability
lifecycle state. What it lacked was a deterministic way to decide whether a
capability is *eligible* to be promoted from candidate/experimental toward
trusted status. This module provides that decision layer by **summarizing
existing governed sources** into one per-capability promotion decision:

* the **Capability State Registry** (PR #27) — durable lifecycle state, evidence
  counts, latest run ids, and the current status,
* the **Capability Validation Registry** (PR #24) — whether a validation
  definition exists and the capability type (read-only vs. mutation),
* the **Runner Command Registry** (PR #22) — the governed command a capability
  drives and its safety classification (mutation / high-risk),
* the **Failure Classification Engine** (PR #29) outputs
  (``failure_classification.json``) written next to the latest evidence bundle,
  consumed when present and handled conservatively when absent.

This is eligibility/governance infrastructure ONLY. It decides and recommends;
it promotes nothing, mutates no registry or state, executes nothing, retries
nothing, and schedules nothing. The CLI may write an optional evidence record
under ``artifacts/promotion_checks/<run_id>/`` — that is a report, not a state
change.

Decisions are deterministic: the same state + artifacts always yield the same
:class:`PromotionDecision`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from axiom_core.runner import capability_runner as caprun
from axiom_core.runner import command_registry as cmdreg
from axiom_core.runner.capability_state import (
    CapabilityState,
    CapabilityStateRegistry,
    CapabilityStatus,
)
from axiom_core.validation import validation_registry as valreg


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Promotion taxonomy
# ---------------------------------------------------------------------------


class PromotionStatus(str, Enum):
    """Deterministic promotion-eligibility verdict for one capability."""

    ELIGIBLE = "eligible"                    # meets every criterion in v1
    NOT_ELIGIBLE = "not_eligible"            # known, but does not yet qualify
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"  # no / insufficient passing evidence
    FAILED_RECENTLY = "failed_recently"      # latest run failed — must recover first
    BLOCKED = "blocked"                      # unresolved blocked/unsupported/critical
    POLICY_REFUSED = "policy_refused"        # mutation/high-risk or refused by policy
    UNKNOWN = "unknown"                      # not known to any registry/artifact


# Statuses that are not eligible but also not a hard policy/blocked refusal.
_SOFT_INELIGIBLE = {
    PromotionStatus.NOT_ELIGIBLE,
    PromotionStatus.NEEDS_MORE_EVIDENCE,
    PromotionStatus.FAILED_RECENTLY,
}


# ---------------------------------------------------------------------------
# Criteria
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PromotionCriteria:
    """The explicit v1 promotion criteria. Simple and deterministic by design.

    Defaults encode the PR #30 contract for a read-only/safe capability:
    at least one passing validation or execution, a valid evidence bundle, no
    unresolved blocked/refused/unsupported status, no recent failure, and no
    critical/policy failure classification. Mutation/high-risk capabilities are
    not eligible in v1.
    """

    minimum_successful_runs: int = 1
    require_evidence_bundle: bool = True
    allow_mutation: bool = False
    allow_high_risk: bool = False
    disallow_recent_failure: bool = True
    disallow_unresolved_block: bool = True

    def to_dict(self) -> dict:
        return {
            "minimum_successful_runs": self.minimum_successful_runs,
            "require_evidence_bundle": self.require_evidence_bundle,
            "allow_mutation": self.allow_mutation,
            "allow_high_risk": self.allow_high_risk,
            "disallow_recent_failure": self.disallow_recent_failure,
            "disallow_unresolved_block": self.disallow_unresolved_block,
        }


# ---------------------------------------------------------------------------
# Blocker + evidence summary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PromotionBlocker:
    """A single reason a capability is not eligible for promotion."""

    code: str
    detail: str

    def to_dict(self) -> dict:
        return {"code": self.code, "detail": self.detail}


@dataclass
class PromotionEvidenceSummary:
    """The consolidated inputs the decision was derived from (read-only)."""

    capability_name: str
    known: bool
    current_status: str
    adapter: str
    capability_type: str
    safety_level: str
    is_mutation: bool
    is_high_risk: bool
    known_command: bool
    command_allowed: bool
    validation_defined: bool
    pass_count: int = 0
    fail_count: int = 0
    refused_count: int = 0
    blocked_count: int = 0
    unsupported_count: int = 0
    validation_pass_count: int = 0
    validation_fail_count: int = 0
    successful_runs: int = 0
    last_evidence_path: Optional[str] = None
    last_execution_run_id: Optional[str] = None
    last_validation_run_id: Optional[str] = None
    last_error_summary: str = ""
    failure_classification_present: bool = False
    latest_failure_category: Optional[str] = None
    latest_failure_severity: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "capability_name": self.capability_name,
            "known": self.known,
            "current_status": self.current_status,
            "adapter": self.adapter,
            "capability_type": self.capability_type,
            "safety_level": self.safety_level,
            "is_mutation": self.is_mutation,
            "is_high_risk": self.is_high_risk,
            "known_command": self.known_command,
            "command_allowed": self.command_allowed,
            "validation_defined": self.validation_defined,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "refused_count": self.refused_count,
            "blocked_count": self.blocked_count,
            "unsupported_count": self.unsupported_count,
            "validation_pass_count": self.validation_pass_count,
            "validation_fail_count": self.validation_fail_count,
            "successful_runs": self.successful_runs,
            "last_evidence_path": self.last_evidence_path,
            "last_execution_run_id": self.last_execution_run_id,
            "last_validation_run_id": self.last_validation_run_id,
            "last_error_summary": self.last_error_summary,
            "failure_classification_present": self.failure_classification_present,
            "latest_failure_category": self.latest_failure_category,
            "latest_failure_severity": self.latest_failure_severity,
        }


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


@dataclass
class PromotionDecision:
    """The promotion-eligibility decision for one capability."""

    capability_name: str
    status: PromotionStatus
    eligible: bool
    reason: str
    blockers: list[PromotionBlocker]
    criteria: PromotionCriteria
    evidence: PromotionEvidenceSummary
    evaluated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return {
            "capability_name": self.capability_name,
            "status": self.status.value,
            "eligible": self.eligible,
            "reason": self.reason,
            "blockers": [b.to_dict() for b in self.blockers],
            "criteria": self.criteria.to_dict(),
            "evidence": self.evidence.to_dict(),
            "evaluated_at": self.evaluated_at,
        }


# Current statuses that represent an unresolved block (cannot promote until
# resolved). REFUSED is handled separately as a policy refusal.
_BLOCKED_STATUSES = {
    CapabilityStatus.BLOCKED,
    CapabilityStatus.UNSUPPORTED,
}
_RECENT_FAILURE_STATUSES = {
    CapabilityStatus.EXECUTION_FAILED,
    CapabilityStatus.VALIDATION_FAILED,
}


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class PromotionEligibilityEngine:
    """Deterministically decides promotion eligibility from governed sources.

    Pure read: consumes the Capability State Registry snapshot, the validation
    and command registries, and failure-classification artifacts. It never
    refreshes/persists state, executes, retries, promotes, or schedules.
    """

    def __init__(
        self,
        *,
        state_registry: CapabilityStateRegistry | None = None,
        criteria: PromotionCriteria | None = None,
    ) -> None:
        self.state_registry = state_registry or CapabilityStateRegistry()
        self.criteria = criteria or PromotionCriteria()

    # -- public API --------------------------------------------------------

    def evaluate(self, capability_name: str) -> PromotionDecision:
        """Decide eligibility for one capability (read-only)."""
        snapshot = self.state_registry.snapshot()
        state = snapshot.get(capability_name)
        return self._evaluate_state(capability_name, state)

    def evaluate_all(self) -> list[PromotionDecision]:
        """Decide eligibility for every known capability, sorted by name."""
        snapshot = self.state_registry.snapshot()
        return [self._evaluate_state(s.capability_name, s)
                for s in snapshot.states]

    # -- core decision -----------------------------------------------------

    def _evaluate_state(
        self, capability_name: str, state: CapabilityState | None,
    ) -> PromotionDecision:
        if state is None:
            return self._unknown_decision(capability_name)

        evidence = self._summarize(state)
        blockers: list[PromotionBlocker] = []

        # 1. Policy: mutation / high-risk capabilities are not eligible in v1.
        if evidence.is_mutation and not self.criteria.allow_mutation:
            blockers.append(PromotionBlocker(
                "mutation_not_eligible",
                "Mutation capabilities are not promotion-eligible in v1 "
                "(higher promotion bar; preview/apply on a disposable model "
                "required first).",
            ))
            return self._decision(PromotionStatus.POLICY_REFUSED, evidence,
                                  blockers,
                                  "Mutation capability — refused by policy in v1.")
        if evidence.is_high_risk and not self.criteria.allow_high_risk:
            blockers.append(PromotionBlocker(
                "high_risk_not_eligible",
                "High-risk command is not promotion-eligible in v1.",
            ))
            return self._decision(PromotionStatus.POLICY_REFUSED, evidence,
                                  blockers,
                                  "High-risk capability — refused by policy in v1.")

        # 2. Policy: latest run refused by governance.
        if state.current_status is CapabilityStatus.REFUSED:
            blockers.append(PromotionBlocker(
                "refused", "Latest run was refused by policy."))
            return self._decision(PromotionStatus.POLICY_REFUSED, evidence,
                                  blockers, "Latest run refused by policy.")

        # 3. Critical / policy-violation failure classification (when present).
        if evidence.latest_failure_category == "policy_violation":
            blockers.append(PromotionBlocker(
                "policy_violation",
                "Latest failure classification is a policy violation."))
            return self._decision(PromotionStatus.BLOCKED, evidence, blockers,
                                  "Failure classification indicates a policy "
                                  "violation.")
        if evidence.latest_failure_severity == "critical":
            blockers.append(PromotionBlocker(
                "critical_failure",
                "Latest failure classification severity is critical."))
            return self._decision(PromotionStatus.BLOCKED, evidence, blockers,
                                  "Latest failure classification is critical.")

        # 4. Unresolved blocked / unsupported status.
        if (self.criteria.disallow_unresolved_block
                and state.current_status in _BLOCKED_STATUSES):
            blockers.append(PromotionBlocker(
                state.current_status.value,
                f"Current status is '{state.current_status.value}' — must be "
                "resolved before promotion."))
            return self._decision(PromotionStatus.BLOCKED, evidence, blockers,
                                  f"Unresolved {state.current_status.value} "
                                  "status.")

        # 5. Recent failure — must recover (a later pass clears this).
        if (self.criteria.disallow_recent_failure
                and state.current_status in _RECENT_FAILURE_STATUSES):
            blockers.append(PromotionBlocker(
                "recent_failure",
                f"Latest run failed (status '{state.current_status.value}')."))
            return self._decision(PromotionStatus.FAILED_RECENTLY, evidence,
                                  blockers, "Most recent run failed.")

        # 6. Evidence bundle required.
        if self.criteria.require_evidence_bundle and not state.last_evidence_path:
            blockers.append(PromotionBlocker(
                "no_evidence_bundle",
                "No evidence bundle found for this capability."))
            return self._decision(PromotionStatus.NEEDS_MORE_EVIDENCE, evidence,
                                  blockers, "No evidence bundle yet.")

        # 7. Minimum passing runs (validation or execution).
        if evidence.successful_runs < self.criteria.minimum_successful_runs:
            blockers.append(PromotionBlocker(
                "insufficient_successes",
                f"{evidence.successful_runs} passing run(s); "
                f"need {self.criteria.minimum_successful_runs}."))
            return self._decision(PromotionStatus.NEEDS_MORE_EVIDENCE, evidence,
                                  blockers,
                                  "Insufficient passing evidence.")

        # 8. Eligible — every criterion met.
        return self._decision(
            PromotionStatus.ELIGIBLE, evidence, blockers,
            f"Meets v1 promotion criteria: {evidence.successful_runs} passing "
            f"run(s), valid evidence, no unresolved failure.")

    # -- helpers -----------------------------------------------------------

    def _unknown_decision(self, capability_name: str) -> PromotionDecision:
        evidence = PromotionEvidenceSummary(
            capability_name=capability_name,
            known=False,
            current_status="unknown",
            adapter="",
            capability_type="",
            safety_level="",
            is_mutation=False,
            is_high_risk=False,
            known_command=False,
            command_allowed=False,
            validation_defined=False,
        )
        blocker = PromotionBlocker(
            "unknown_capability",
            "Capability is unknown to the state/validation/command registries.")
        return PromotionDecision(
            capability_name=capability_name,
            status=PromotionStatus.UNKNOWN,
            eligible=False,
            reason="Unknown capability — no promotion decision possible.",
            blockers=[blocker],
            criteria=self.criteria,
            evidence=evidence,
        )

    def _summarize(self, state: CapabilityState) -> PromotionEvidenceSummary:
        is_mutation, is_high_risk, safety_level, known_command, command_allowed = (
            self._safety_profile(state))
        validation_defined = bool(
            state.metadata.get("validation_defined")) or self._has_validation(
            state.capability_name)
        validation_pass = int(state.metadata.get("validation_pass_count", 0) or 0)
        validation_fail = int(state.metadata.get("validation_fail_count", 0) or 0)
        successful_runs = state.pass_count + validation_pass

        evidence = PromotionEvidenceSummary(
            capability_name=state.capability_name,
            known=True,
            current_status=state.current_status.value,
            adapter=state.adapter,
            capability_type=state.capability_type,
            safety_level=safety_level,
            is_mutation=is_mutation,
            is_high_risk=is_high_risk,
            known_command=known_command,
            command_allowed=command_allowed,
            validation_defined=validation_defined,
            pass_count=state.pass_count,
            fail_count=state.fail_count,
            refused_count=state.refused_count,
            blocked_count=state.blocked_count,
            unsupported_count=state.unsupported_count,
            validation_pass_count=validation_pass,
            validation_fail_count=validation_fail,
            successful_runs=successful_runs,
            last_evidence_path=state.last_evidence_path,
            last_execution_run_id=state.last_execution_run_id,
            last_validation_run_id=state.last_validation_run_id,
            last_error_summary=state.last_error_summary,
        )
        self._attach_failure_classification(evidence, state.last_evidence_path)
        return evidence

    @staticmethod
    def _has_validation(capability_name: str) -> bool:
        return any(p.capability_name == capability_name
                   for p in valreg.list_procedures())

    @staticmethod
    def _safety_profile(
        state: CapabilityState,
    ) -> tuple[bool, bool, str, bool, bool]:
        """Return (is_mutation, is_high_risk, safety_level, known_command,
        command_allowed) by consulting the validation + command registries."""
        is_mutation = False
        is_high_risk = False
        safety_level = ""
        known_command = False
        command_allowed = False

        # Validation registry: capability type (mutation is the strongest signal).
        for proc in valreg.list_procedures():
            if proc.capability_name == state.capability_name:
                is_mutation = is_mutation or proc.is_mutation
                break

        # Command registry: the governed command this capability drives.
        command_name = state.metadata.get("command_name")
        if not command_name:
            spec = caprun.SUPPORTED_CAPABILITIES.get(state.capability_name)
            command_name = spec.command_name if spec else None
        if command_name:
            cmd = cmdreg.get_command(command_name)
            if cmd is not None:
                known_command = True
                command_allowed = cmdreg.is_allowed(command_name)
                safety_level = cmd.safety_level.value
                if cmd.safety_level is cmdreg.SafetyLevel.HIGH_RISK:
                    is_high_risk = True
                if cmd.classification is cmdreg.CommandClass.MUTATION:
                    is_mutation = True
        return is_mutation, is_high_risk, safety_level, known_command, command_allowed

    @staticmethod
    def _attach_failure_classification(
        evidence: PromotionEvidenceSummary, last_evidence_path: str | None,
    ) -> None:
        """Consume a failure_classification.json next to the latest evidence
        bundle when present. Absent/unreadable classifications are handled
        conservatively (left unset — they never make a capability eligible)."""
        if not last_evidence_path:
            return
        path = Path(last_evidence_path) / "failure_classification.json"
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        evidence.failure_classification_present = True
        category = data.get("category")
        severity = data.get("severity")
        evidence.latest_failure_category = (
            category if isinstance(category, str) else None)
        evidence.latest_failure_severity = (
            severity if isinstance(severity, str) else None)

    def _decision(
        self,
        status: PromotionStatus,
        evidence: PromotionEvidenceSummary,
        blockers: list[PromotionBlocker],
        reason: str,
    ) -> PromotionDecision:
        return PromotionDecision(
            capability_name=evidence.capability_name,
            status=status,
            eligible=status is PromotionStatus.ELIGIBLE,
            reason=reason,
            blockers=blockers,
            criteria=self.criteria,
            evidence=evidence,
        )


# ---------------------------------------------------------------------------
# Output writing (optional evidence record — never mutates state)
# ---------------------------------------------------------------------------


DEFAULT_PROMOTION_CHECKS_BASE = "artifacts/promotion_checks"


def _slug(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in value) or "all"


def promotion_run_id(scope: str, *, at: str | None = None) -> str:
    """Deterministic-ish run id for a promotion check evidence folder."""
    stamp = (at or _now_iso()).replace(":", "").replace("-", "").replace(".", "")
    return f"pcheck_{_slug(scope)}_{stamp}"


def write_promotion_decisions(
    decisions: list[PromotionDecision],
    *,
    out_dir: str | Path,
) -> tuple[Path, Path]:
    """Write promotion_decision.json + .md into ``out_dir``.

    Returns (json_path, md_path). This writes a *report* only — it never mutates
    capability state or any registry.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # One report → one timestamp shared by both files.
    generated_at = _now_iso()
    payload = {
        "generated_at": generated_at,
        "count": len(decisions),
        "eligible": sorted(d.capability_name for d in decisions if d.eligible),
        "status_counts": _status_counts(decisions),
        "decisions": [d.to_dict() for d in decisions],
    }
    json_path = out / "promotion_decision.json"
    json_path.write_text(json.dumps(payload, indent=2, default=str) + "\n",
                         encoding="utf-8")

    md_path = out / "promotion_decision.md"
    md_path.write_text(_render_md(decisions, generated_at), encoding="utf-8")
    return json_path, md_path


def _status_counts(decisions: list[PromotionDecision]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for d in decisions:
        counts[d.status.value] = counts.get(d.status.value, 0) + 1
    return dict(sorted(counts.items()))


def _render_md(decisions: list[PromotionDecision], generated_at: str) -> str:
    lines = [
        "# Promotion Eligibility Decision",
        "",
        f"- **Generated at:** {generated_at}",
        f"- **Capabilities evaluated:** {len(decisions)}",
        "",
        "| Capability | Status | Eligible | Successful runs | Reason |",
        "|------------|--------|----------|-----------------|--------|",
    ]
    for d in sorted(decisions, key=lambda x: x.capability_name):
        lines.append(
            f"| {d.capability_name} | {d.status.value} | "
            f"{'yes' if d.eligible else 'no'} | "
            f"{d.evidence.successful_runs} | {d.reason} |")
    lines.append("")

    for d in sorted(decisions, key=lambda x: x.capability_name):
        if not d.blockers:
            continue
        lines.append(f"## Blockers — {d.capability_name}")
        lines.append("")
        for b in d.blockers:
            lines.append(f"- **{b.code}:** {b.detail}")
        lines.append("")

    lines.append(
        "_Promotion eligibility (PR #30). Decide and recommend only; no "
        "automatic promotion, registry mutation, retry, scheduling, or "
        "learning._")
    return "\n".join(lines) + "\n"
