"""Assertion Registry v1 — first-class assertion objects.

Creates durable assertion artifacts for engineering sessions. Assertions
become trackable objects that define expected behaviors and record
evaluation results. Shifts reasoning from Capability -> Tests to
Capability -> Assertions -> Tests.

Consumes: Session Questions, Session Plans, Work Items.

Non-goals: no execution, no mutation, no reports, no escalations.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AssertionType(str, Enum):
    """Type of assertion."""

    EXIT_CODE = "exit_code"
    STRATEGY = "strategy"
    READ_ONLY = "read_only"
    REASON = "reason"
    EVIDENCE = "evidence"
    DETERMINISTIC = "deterministic"
    CLASSIFICATION = "classification"
    PERSISTENCE = "persistence"


class AssertionStatus(str, Enum):
    """Status of an assertion."""

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AssertionSeverity(str, Enum):
    """Severity of an assertion."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Status ranking for deterministic sorting
_STATUS_RANK: dict[str, int] = {
    AssertionStatus.FAILED.value: 0,
    AssertionStatus.PENDING.value: 1,
    AssertionStatus.PASSED.value: 2,
    AssertionStatus.SKIPPED.value: 3,
}

# Severity ranking for deterministic sorting
_SEVERITY_RANK: dict[str, int] = {
    AssertionSeverity.CRITICAL.value: 0,
    AssertionSeverity.HIGH.value: 1,
    AssertionSeverity.MEDIUM.value: 2,
    AssertionSeverity.LOW.value: 3,
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class AssertionResult:
    """Result of evaluating an assertion."""

    result_id: str = ""
    assertion_id: str = ""
    status: str = "pending"
    actual_value: str = ""
    message: str = ""
    source: str = ""
    evaluated_at: str = ""

    def __post_init__(self) -> None:
        if not self.result_id:
            self.result_id = str(uuid4())
        if not self.evaluated_at:
            self.evaluated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "assertion_id": self.assertion_id,
            "status": self.status,
            "actual_value": self.actual_value,
            "message": self.message,
            "source": self.source,
            "evaluated_at": self.evaluated_at,
        }


@dataclass
class Assertion:
    """A durable assertion artifact."""

    assertion_id: str = ""
    assertion_type: str = "exit_code"
    description: str = ""
    expected_value: str = ""
    severity: str = "medium"
    status: str = "pending"
    plan_id: str = ""
    question_id: str = ""
    work_item_id: str = ""
    capability: str = ""
    rationale: str = ""
    results: list[AssertionResult] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.assertion_id:
            self.assertion_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "assertion_id": self.assertion_id,
            "assertion_type": self.assertion_type,
            "description": self.description,
            "expected_value": self.expected_value,
            "severity": self.severity,
            "status": self.status,
            "plan_id": self.plan_id,
            "question_id": self.question_id,
            "work_item_id": self.work_item_id,
            "capability": self.capability,
            "rationale": self.rationale,
            "results": [r.to_dict() for r in self.results],
            "assertion_summary": self._assertion_summary(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def _assertion_summary(self) -> dict[str, Any]:
        total = len(self.results)
        passed = sum(1 for r in self.results if r.status == "passed")
        failed = sum(1 for r in self.results if r.status == "failed")
        return {
            "total_results": total,
            "passed": passed,
            "failed": failed,
            "latest_status": self.status,
        }


# ---------------------------------------------------------------------------
# Core registry
# ---------------------------------------------------------------------------


class AssertionRegistry:
    """Durable registry for assertion artifacts."""

    def __init__(
        self,
        artifacts_root: str = "",
    ) -> None:
        self._artifacts_root = artifacts_root or os.environ.get(
            "AXIOM_ARTIFACTS_ROOT", "artifacts",
        )
        self._assertions_dir = Path(self._artifacts_root) / "assertions"
        self._assertions_dir.mkdir(parents=True, exist_ok=True)

    # -- ID validation ------------------------------------------------------

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            msg = f"{name} must not be empty"
            raise ValueError(msg)
        if ".." in value or "/" in value or "\\" in value:
            msg = f"{name} must not contain '..', '/', or '\\': {value!r}"
            raise ValueError(msg)

    # -- Create assertion ---------------------------------------------------

    def create_assertion(
        self,
        assertion_type: str,
        description: str,
        expected_value: str = "",
        severity: str = "medium",
        plan_id: str = "",
        question_id: str = "",
        work_item_id: str = "",
        capability: str = "",
        rationale: str = "",
    ) -> dict[str, Any]:
        """Create a new assertion."""
        assertion = Assertion(
            assertion_type=assertion_type,
            description=description,
            expected_value=expected_value,
            severity=severity,
            plan_id=plan_id,
            question_id=question_id,
            work_item_id=work_item_id,
            capability=capability,
            rationale=rationale,
        )
        self._persist_assertion(assertion)
        return assertion.to_dict()

    # -- Get assertion ------------------------------------------------------

    def get_assertion(self, assertion_id: str) -> dict[str, Any] | None:
        """Get an assertion by ID."""
        self._validate_id_segment(assertion_id, "assertion_id")
        return self._load_assertion(assertion_id)

    # -- List assertions ----------------------------------------------------

    def list_assertions(
        self,
        status: str = "",
        assertion_type: str = "",
        capability: str = "",
    ) -> list[dict[str, Any]]:
        """List all assertions, optionally filtered."""
        assertions: list[dict[str, Any]] = []
        if not self._assertions_dir.exists():
            return assertions

        for entry in sorted(self._assertions_dir.iterdir()):
            if not entry.is_dir():
                continue
            a_file = entry / "assertion.json"
            if not a_file.exists():
                continue
            try:
                data = json.loads(a_file.read_text(encoding="utf-8"))
                if status and data.get("status") != status:
                    continue
                if assertion_type and data.get("assertion_type") != assertion_type:
                    continue
                if capability and data.get("capability") != capability:
                    continue
                assertions.append(data)
            except (json.JSONDecodeError, OSError):
                _logger.warning("Could not read assertion %s", entry.name)

        assertions.sort(
            key=lambda a: (
                _STATUS_RANK.get(a.get("status", ""), 99),
                _SEVERITY_RANK.get(a.get("severity", ""), 99),
                a.get("created_at", ""),
            ),
        )
        return assertions

    # -- Record result ------------------------------------------------------

    _VALID_STATUSES = frozenset(s.value for s in AssertionStatus)

    def record_result(
        self,
        assertion_id: str,
        status: str,
        actual_value: str = "",
        message: str = "",
        source: str = "",
    ) -> dict[str, Any] | None:
        """Record an evaluation result for an assertion."""
        self._validate_id_segment(assertion_id, "assertion_id")
        if status not in self._VALID_STATUSES:
            msg = f"Invalid status {status!r}, expected one of {sorted(self._VALID_STATUSES)}"
            raise ValueError(msg)

        assertion = self._load_assertion(assertion_id)
        if assertion is None:
            return None

        result = AssertionResult(
            assertion_id=assertion_id,
            status=status,
            actual_value=actual_value,
            message=message,
            source=source,
        )
        assertion.setdefault("results", []).append(result.to_dict())
        assertion["status"] = status
        assertion["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_assertion(assertion_id, assertion)
        return assertion

    # -- List results -------------------------------------------------------

    def list_results(
        self, assertion_id: str,
    ) -> list[dict[str, Any]]:
        """List all results for an assertion."""
        self._validate_id_segment(assertion_id, "assertion_id")
        assertion = self._load_assertion(assertion_id)
        if assertion is None:
            return []
        return assertion.get("results", [])

    # -- Export assertion ----------------------------------------------------

    def export_assertion(self, assertion_id: str) -> str:
        """Export assertion as markdown."""
        self._validate_id_segment(assertion_id, "assertion_id")
        assertion = self._load_assertion(assertion_id)
        if assertion is None:
            msg = f"Assertion not found: {assertion_id}"
            raise ValueError(msg)

        lines = [
            f"# Assertion: {assertion.get('description', '')}\n",
            f"- Assertion ID: {assertion_id}",
            f"- Type: {assertion.get('assertion_type', '')}",
            f"- Status: {assertion.get('status', '')}",
            f"- Severity: {assertion.get('severity', '')}",
            f"- Expected: {assertion.get('expected_value', '')}",
        ]

        if assertion.get("capability"):
            lines.append(f"- Capability: {assertion['capability']}")
        if assertion.get("plan_id"):
            lines.append(f"- Plan ID: {assertion['plan_id']}")
        if assertion.get("question_id"):
            lines.append(f"- Question ID: {assertion['question_id']}")
        if assertion.get("work_item_id"):
            lines.append(f"- Work Item ID: {assertion['work_item_id']}")
        lines.append(f"- Created: {assertion.get('created_at', '')}")

        if assertion.get("rationale"):
            lines.append(f"\n## Rationale\n\n{assertion['rationale']}")

        results = assertion.get("results", [])
        if results:
            lines.append(f"\n## Results ({len(results)})\n")
            for r in results:
                src = f" (source: {r['source']})" if r.get("source") else ""
                lines.append(
                    f"- [{r.get('status', '')}] "
                    f"actual={r.get('actual_value', '')}"
                    f"{src}",
                )
                if r.get("message"):
                    lines.append(f"  {r['message']}")

        summary = assertion.get("assertion_summary", {})
        lines.append(
            f"\n## Summary\n\n"
            f"- Total results: {summary.get('total_results', 0)}\n"
            f"- Passed: {summary.get('passed', 0)}\n"
            f"- Failed: {summary.get('failed', 0)}",
        )

        return "\n".join(lines) + "\n"

    # -- Evidence writing ---------------------------------------------------

    def write_evidence(self, assertion_id: str) -> str:
        """Write evidence bundle for an assertion."""
        self._validate_id_segment(assertion_id, "assertion_id")
        assertion = self._load_assertion(assertion_id)
        if assertion is None:
            msg = f"Assertion not found: {assertion_id}"
            raise ValueError(msg)

        evidence_dir = self._assertions_dir / assertion_id
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "assertion_id": assertion_id,
            "assertion_type": assertion.get("assertion_type", ""),
            "description": assertion.get("description", ""),
            "expected_value": assertion.get("expected_value", ""),
            "severity": assertion.get("severity", ""),
            "status": assertion.get("status", ""),
            "capability": assertion.get("capability", ""),
            "created_at": assertion.get("created_at", ""),
        }
        (evidence_dir / "assertion_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
        )

        (evidence_dir / "assertion_result.json").write_text(
            json.dumps(assertion, indent=2, default=str),
        )

        (evidence_dir / "assertion_summary.md").write_text(
            self.export_assertion(assertion_id),
        )

        summary = assertion.get("assertion_summary", {})
        pass_fail = {
            "passed": assertion.get("status") in (
                AssertionStatus.PENDING.value,
                AssertionStatus.PASSED.value,
            ),
            "assertion_id": assertion_id,
            "status": assertion.get("status", ""),
            "total_results": summary.get("total_results", 0),
            "passed_count": summary.get("passed", 0),
            "failed_count": summary.get("failed", 0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
        )

        return str(evidence_dir)

    # -- Internal helpers ---------------------------------------------------

    def _persist_assertion(self, assertion: Assertion) -> None:
        a_dir = self._assertions_dir / assertion.assertion_id
        a_dir.mkdir(parents=True, exist_ok=True)
        (a_dir / "assertion.json").write_text(
            json.dumps(assertion.to_dict(), indent=2, default=str),
        )

    def _load_assertion(self, assertion_id: str) -> dict[str, Any] | None:
        a_path = self._assertions_dir / assertion_id / "assertion.json"
        if not a_path.exists():
            return None
        return json.loads(a_path.read_text(encoding="utf-8"))

    @staticmethod
    def _recompute_assertion_summary(data: dict[str, Any]) -> None:
        """Recalculate assertion_summary from current state."""
        results = data.get("results", [])
        passed = sum(1 for r in results if r.get("status") == "passed")
        failed = sum(1 for r in results if r.get("status") == "failed")
        data["assertion_summary"] = {
            "total_results": len(results),
            "passed": passed,
            "failed": failed,
            "latest_status": data.get("status", "pending"),
        }

    def _write_assertion(
        self, assertion_id: str, data: dict[str, Any],
    ) -> None:
        self._recompute_assertion_summary(data)
        a_dir = self._assertions_dir / assertion_id
        a_dir.mkdir(parents=True, exist_ok=True)
        (a_dir / "assertion.json").write_text(
            json.dumps(data, indent=2, default=str),
        )
