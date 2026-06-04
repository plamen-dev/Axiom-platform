"""Retry & Failure Classification Engine v1.

Deterministic classification of evidence-bundle outcomes into durable failure
categories, severity levels, and retry decisions. Consumes:

* Capability Execution Runner (PR #26) bundles under ``capability_runs/``
* Validation Evidence Runner (PR #25) bundles under ``validation_evidence/``
* Any evidence folder containing a ``pass_fail.json``

For each classified bundle the engine writes:

* ``failure_classification.json`` — machine-readable classification
* ``failure_classification.md`` — human-readable summary

Classification is read-only: it never overwrites ``pass_fail.json`` or any
other file in the bundle. The engine does not execute capabilities, retry
failures, promote candidates, or schedule anything.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Failure taxonomy
# ---------------------------------------------------------------------------


class FailureCategory(str, Enum):
    """Deterministic failure category for one evidence bundle."""

    PASSED = "passed"
    DENIED = "denied"
    REFUSED = "refused"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"
    EXECUTION_FAILED = "execution_failed"
    TRANSPORT_FAILED = "transport_failed"
    PREREQUISITE_MISSING = "prerequisite_missing"
    EVIDENCE_MISSING = "evidence_missing"
    VALIDATION_FAILED = "validation_failed"
    TIMEOUT = "timeout"
    PARSE_ERROR = "parse_error"
    POLICY_VIOLATION = "policy_violation"
    UNKNOWN_ERROR = "unknown_error"


class FailureSeverity(str, Enum):
    """Severity level for a classified failure."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class RetryEligibility(str, Enum):
    """High-level retry eligibility derived from the classification."""

    NOT_NEEDED = "not_needed"
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    CONDITIONAL = "conditional"


# ---------------------------------------------------------------------------
# Retry decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetryDecision:
    """Structured retry recommendation for one classified failure."""

    retry_allowed: bool
    retry_recommended: bool
    retry_reason: str
    max_retries: int = 0
    retry_delay_seconds: int = 0
    retry_requires_human: bool = False
    retry_requires_environment_change: bool = False

    def to_dict(self) -> dict:
        return {
            "retry_allowed": self.retry_allowed,
            "retry_recommended": self.retry_recommended,
            "retry_reason": self.retry_reason,
            "max_retries": self.max_retries,
            "retry_delay_seconds": self.retry_delay_seconds,
            "retry_requires_human": self.retry_requires_human,
            "retry_requires_environment_change": self.retry_requires_environment_change,
        }


# ---------------------------------------------------------------------------
# Evidence summary (the full classification record)
# ---------------------------------------------------------------------------


@dataclass
class FailureEvidenceSummary:
    """The consolidated classification output for one evidence bundle."""

    evidence_path: str
    bundle_type: str  # "capability_run" or "validation_run"
    capability_name: str
    outcome: str
    category: FailureCategory
    severity: FailureSeverity
    retry_eligibility: RetryEligibility
    retry_decision: RetryDecision
    checks: list[dict] = field(default_factory=list)
    error_detail: str = ""
    classified_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return {
            "evidence_path": self.evidence_path,
            "bundle_type": self.bundle_type,
            "capability_name": self.capability_name,
            "outcome": self.outcome,
            "category": self.category.value,
            "severity": self.severity.value,
            "retry_eligibility": self.retry_eligibility.value,
            "retry_decision": self.retry_decision.to_dict(),
            "checks": self.checks,
            "error_detail": self.error_detail,
            "classified_at": self.classified_at,
        }


# ---------------------------------------------------------------------------
# Severity mapping
# ---------------------------------------------------------------------------

_CATEGORY_SEVERITY: dict[FailureCategory, FailureSeverity] = {
    FailureCategory.PASSED: FailureSeverity.INFO,
    FailureCategory.DENIED: FailureSeverity.WARNING,
    FailureCategory.REFUSED: FailureSeverity.INFO,
    FailureCategory.BLOCKED: FailureSeverity.ERROR,
    FailureCategory.UNSUPPORTED: FailureSeverity.WARNING,
    FailureCategory.EXECUTION_FAILED: FailureSeverity.ERROR,
    FailureCategory.TRANSPORT_FAILED: FailureSeverity.ERROR,
    FailureCategory.PREREQUISITE_MISSING: FailureSeverity.ERROR,
    FailureCategory.EVIDENCE_MISSING: FailureSeverity.ERROR,
    FailureCategory.VALIDATION_FAILED: FailureSeverity.ERROR,
    FailureCategory.TIMEOUT: FailureSeverity.ERROR,
    FailureCategory.PARSE_ERROR: FailureSeverity.ERROR,
    FailureCategory.POLICY_VIOLATION: FailureSeverity.CRITICAL,
    FailureCategory.UNKNOWN_ERROR: FailureSeverity.ERROR,
}


# ---------------------------------------------------------------------------
# Retry policy evaluator
# ---------------------------------------------------------------------------


class RetryPolicyEvaluator:
    """Deterministic retry-decision rules keyed on failure category.

    This is the governance layer that future retry/promotion engines will
    consume. No automatic retry is implemented: the evaluator only recommends.
    """

    @staticmethod
    def evaluate(
        category: FailureCategory,
        severity: FailureSeverity,  # noqa: ARG004
    ) -> RetryDecision:
        rules: dict[FailureCategory, RetryDecision] = {
            FailureCategory.PASSED: RetryDecision(
                retry_allowed=False, retry_recommended=False,
                retry_reason="Run passed — retry not needed.",
            ),
            FailureCategory.DENIED: RetryDecision(
                retry_allowed=False, retry_recommended=False,
                retry_reason="Capability not recognized — denied by default.",
            ),
            FailureCategory.REFUSED: RetryDecision(
                retry_allowed=False, retry_recommended=False,
                retry_reason="Capability refused by safety/governance policy.",
            ),
            FailureCategory.BLOCKED: RetryDecision(
                retry_allowed=True, retry_recommended=False,
                retry_reason="Run blocked — prerequisites unmet.",
                max_retries=3, retry_delay_seconds=30,
                retry_requires_environment_change=True,
            ),
            FailureCategory.PREREQUISITE_MISSING: RetryDecision(
                retry_allowed=True, retry_recommended=False,
                retry_reason="Prerequisite missing — retry after environment fix.",
                max_retries=3, retry_delay_seconds=30,
                retry_requires_environment_change=True,
            ),
            FailureCategory.UNSUPPORTED: RetryDecision(
                retry_allowed=False, retry_recommended=False,
                retry_reason="Capability unsupported — no safe executor available.",
            ),
            FailureCategory.EXECUTION_FAILED: RetryDecision(
                retry_allowed=True, retry_recommended=True,
                retry_reason="Execution failed — retry may succeed.",
                max_retries=3, retry_delay_seconds=10,
            ),
            FailureCategory.VALIDATION_FAILED: RetryDecision(
                retry_allowed=True, retry_recommended=True,
                retry_reason="Validation failed — retry may succeed.",
                max_retries=2, retry_delay_seconds=5,
            ),
            FailureCategory.TRANSPORT_FAILED: RetryDecision(
                retry_allowed=True, retry_recommended=True,
                retry_reason="Transport/bridge failure — retry after confirming "
                             "Revit is running and bridge is available.",
                max_retries=3, retry_delay_seconds=30,
                retry_requires_human=True,
            ),
            FailureCategory.TIMEOUT: RetryDecision(
                retry_allowed=True, retry_recommended=False,
                retry_reason="Timeout — retry with increased timeout or smaller scope.",
                max_retries=2, retry_delay_seconds=60,
            ),
            FailureCategory.PARSE_ERROR: RetryDecision(
                retry_allowed=False, retry_recommended=False,
                retry_reason="Malformed input or evidence — fix before retrying.",
                retry_requires_human=True,
            ),
            FailureCategory.EVIDENCE_MISSING: RetryDecision(
                retry_allowed=False, retry_recommended=False,
                retry_reason="Evidence missing — fix evidence pipeline before retrying.",
                retry_requires_human=True,
            ),
            FailureCategory.POLICY_VIOLATION: RetryDecision(
                retry_allowed=False, retry_recommended=False,
                retry_reason="Policy violation — retry not allowed.",
            ),
            FailureCategory.UNKNOWN_ERROR: RetryDecision(
                retry_allowed=False, retry_recommended=False,
                retry_reason="Unknown error — requires investigation.",
                retry_requires_human=True,
            ),
        }
        return rules[category]


# ---------------------------------------------------------------------------
# Sub-classification of "failed" outcomes
# ---------------------------------------------------------------------------

_TRANSPORT_KEYWORDS = frozenset({
    "bridge", "transport", "pipe", "connection", "connect",
    "unavailable", "unreachable", "namedpipe", "named_pipe",
})

_TIMEOUT_KEYWORDS = frozenset({
    "timeout", "timed out", "timed_out", "deadline", "exceeded",
})

_PREREQUISITE_KEYWORDS = frozenset({
    "prerequisite", "prerequisites", "missing_prerequisite",
})


def _sub_classify_failed(
    checks: list[dict],
    reason: str,
    bundle_type: str,
) -> FailureCategory:
    """Sub-classify a "failed" outcome into a more specific category
    based on check details and the reason string."""
    combined = reason.lower()
    for chk in checks:
        if not chk.get("passed", True):
            combined += " " + (chk.get("detail") or "").lower()
            combined += " " + (chk.get("name") or "").lower()

    if any(kw in combined for kw in _PREREQUISITE_KEYWORDS):
        return FailureCategory.PREREQUISITE_MISSING

    if any(kw in combined for kw in _TRANSPORT_KEYWORDS):
        return FailureCategory.TRANSPORT_FAILED

    if any(kw in combined for kw in _TIMEOUT_KEYWORDS):
        return FailureCategory.TIMEOUT

    if bundle_type == "validation_run":
        return FailureCategory.VALIDATION_FAILED

    return FailureCategory.EXECUTION_FAILED


# ---------------------------------------------------------------------------
# Bundle detection helpers
# ---------------------------------------------------------------------------


def _detect_bundle_type(evidence_path: Path) -> str:
    """Heuristic: capability_result.json → capability_run, else validation_run."""
    if (evidence_path / "capability_result.json").exists():
        return "capability_run"
    if (evidence_path / "validation_result.json").exists():
        return "validation_run"
    # Fall back based on directory path naming convention
    path_lower = str(evidence_path).lower()
    if "validation" in path_lower:
        return "validation_run"
    return "capability_run"


def _read_json(path: Path) -> dict[str, Any] | None:
    """Read JSON object or return None on failure.

    Returns ``None`` for non-object JSON (list/int/bool/str) so the caller
    treats it as unparseable rather than crashing on a missing ``.get``.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _extract_capability_name(pass_fail: dict, result: dict | None) -> str:
    """Pull capability name from whichever source has it."""
    name = pass_fail.get("capability_name") or pass_fail.get("validation_name") or ""
    if not name and result:
        name = (result.get("capability_name")
                or result.get("validation_name") or "")
    return name


def _extract_reason(result: dict | None) -> str:
    """Pull the human-readable reason from the result JSON if present."""
    if result:
        return result.get("reason") or ""
    return ""


# ---------------------------------------------------------------------------
# Classification engine
# ---------------------------------------------------------------------------


class FailureClassificationEngine:
    """Deterministic classifier that reads an evidence bundle and produces a
    :class:`FailureEvidenceSummary` with category, severity, and retry decision.
    """

    _OUTCOME_CATEGORY: dict[str, FailureCategory] = {
        "passed": FailureCategory.PASSED,
        "denied": FailureCategory.DENIED,
        "refused": FailureCategory.REFUSED,
        "blocked": FailureCategory.BLOCKED,
        "unsupported": FailureCategory.UNSUPPORTED,
    }

    def __init__(self) -> None:
        self._retry_policy = RetryPolicyEvaluator()

    def classify(self, evidence_path: Path) -> FailureEvidenceSummary:
        """Classify one evidence bundle and return a structured summary."""
        evidence_path = Path(evidence_path)
        pf_path = evidence_path / "pass_fail.json"

        # Missing evidence
        if not pf_path.exists():
            return self._make_summary(
                evidence_path=evidence_path,
                bundle_type=_detect_bundle_type(evidence_path),
                capability_name="",
                outcome="(missing)",
                category=FailureCategory.EVIDENCE_MISSING,
                error_detail=f"pass_fail.json not found in {evidence_path}",
            )

        # Malformed evidence
        pass_fail = _read_json(pf_path)
        if pass_fail is None:
            return self._make_summary(
                evidence_path=evidence_path,
                bundle_type=_detect_bundle_type(evidence_path),
                capability_name="",
                outcome="(unparseable)",
                category=FailureCategory.PARSE_ERROR,
                error_detail=f"pass_fail.json could not be parsed in {evidence_path}",
            )

        bundle_type = _detect_bundle_type(evidence_path)
        result_file = ("capability_result.json" if bundle_type == "capability_run"
                       else "validation_result.json")
        result = _read_json(evidence_path / result_file)

        outcome = pass_fail.get("outcome", "")
        checks = pass_fail.get("checks") or []
        capability_name = _extract_capability_name(pass_fail, result)
        reason = _extract_reason(result)

        # Direct outcome mapping
        if outcome in self._OUTCOME_CATEGORY:
            category = self._OUTCOME_CATEGORY[outcome]
        elif outcome == "failed":
            category = _sub_classify_failed(checks, reason, bundle_type)
        else:
            category = FailureCategory.UNKNOWN_ERROR

        return self._make_summary(
            evidence_path=evidence_path,
            bundle_type=bundle_type,
            capability_name=capability_name,
            outcome=outcome,
            category=category,
            checks=checks,
            error_detail=reason,
        )

    def _make_summary(
        self,
        *,
        evidence_path: Path,
        bundle_type: str,
        capability_name: str,
        outcome: str,
        category: FailureCategory,
        checks: list[dict] | None = None,
        error_detail: str = "",
    ) -> FailureEvidenceSummary:
        severity = _CATEGORY_SEVERITY[category]
        retry = self._retry_policy.evaluate(category, severity)

        if category is FailureCategory.PASSED:
            eligibility = RetryEligibility.NOT_NEEDED
        elif retry.retry_allowed:
            eligibility = (RetryEligibility.CONDITIONAL
                           if retry.retry_requires_human
                           or retry.retry_requires_environment_change
                           else RetryEligibility.ELIGIBLE)
        else:
            eligibility = RetryEligibility.INELIGIBLE

        return FailureEvidenceSummary(
            evidence_path=str(evidence_path),
            bundle_type=bundle_type,
            capability_name=capability_name,
            outcome=outcome,
            category=category,
            severity=severity,
            retry_eligibility=eligibility,
            retry_decision=retry,
            checks=checks or [],
            error_detail=error_detail,
        )


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------


def write_classification(summary: FailureEvidenceSummary) -> tuple[Path, Path]:
    """Write failure_classification.json + .md into the evidence folder.

    Never overwrites pass_fail.json. Returns (json_path, md_path).
    """
    evidence_dir = Path(summary.evidence_path)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    json_path = evidence_dir / "failure_classification.json"
    json_path.write_text(
        json.dumps(summary.to_dict(), indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    md_path = evidence_dir / "failure_classification.md"
    md_path.write_text(_render_md(summary), encoding="utf-8")

    return json_path, md_path


def _render_md(summary: FailureEvidenceSummary) -> str:
    rd = summary.retry_decision
    lines = [
        f"# Failure Classification — {summary.capability_name or '(unknown)'}",
        "",
        f"- **Evidence path:** `{summary.evidence_path}`",
        f"- **Bundle type:** {summary.bundle_type}",
        f"- **Outcome:** {summary.outcome}",
        f"- **Category:** {summary.category.value}",
        f"- **Severity:** {summary.severity.value}",
        f"- **Retry eligibility:** {summary.retry_eligibility.value}",
        f"- **Classified at:** {summary.classified_at}",
        "",
        "## Retry Decision",
        "",
        f"- **Retry allowed:** {rd.retry_allowed}",
        f"- **Retry recommended:** {rd.retry_recommended}",
        f"- **Reason:** {rd.retry_reason}",
        f"- **Max retries:** {rd.max_retries}",
        f"- **Retry delay (seconds):** {rd.retry_delay_seconds}",
        f"- **Requires human:** {rd.retry_requires_human}",
        f"- **Requires environment change:** {rd.retry_requires_environment_change}",
        "",
    ]
    if summary.error_detail:
        lines.append("## Error Detail")
        lines.append("")
        lines.append(summary.error_detail)
        lines.append("")

    if summary.checks:
        passed = sum(1 for c in summary.checks if c.get("passed"))
        lines.append(f"## Checks ({passed}/{len(summary.checks)} passed)")
        lines.append("")
        lines.append("| Check | Result | Detail |")
        lines.append("|-------|--------|--------|")
        for c in summary.checks:
            result_str = "PASS" if c.get("passed") else "FAIL"
            lines.append(f"| {c.get('name') or ''} | {result_str} | "
                         f"{c.get('detail') or ''} |")
        lines.append("")

    lines.append(
        "_Failure classification (PR #29). Classify and recommend only; "
        "no automatic retry, promotion, scheduling, or learning._"
    )
    return "\n".join(lines) + "\n"
