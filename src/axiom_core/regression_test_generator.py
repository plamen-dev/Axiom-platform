"""Regression Test Generator v1 — structured test recommendations from bugs.

Converts review findings, runtime failures, policy violations, and failure
classifications into regression-test candidates.  Advisory-only — does not
modify test files.

Chain: Review Findings -> Bug Patterns -> Regression Test Candidates

Non-goals: no test file modification, no code generation, no patch application,
no PR creation, no autonomous behavior, no GitHub API, no network dependency.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from axiom_core.database import (
    create_db_engine,
    get_session,
    init_db,
    make_session_factory,
)
from axiom_core.models import Base

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FailureOrigin(str, Enum):
    """Where the failure was detected."""

    REVIEW_FINDING = "review_finding"
    RUNTIME_FAILURE = "runtime_failure"
    POLICY_VIOLATION = "policy_violation"
    HUMAN_REVIEW = "human_review"
    EXTERNAL_REVIEW = "external_review"
    SECURITY = "security"


class BugClass(str, Enum):
    """Known bug classification for pattern matching."""

    TRUTHINESS_BUG = "truthiness_bug"
    ENUM_SERIALIZATION = "enum_serialization"
    PERSISTENCE_DEFECT = "persistence_defect"
    EVIDENCE_FAILURE = "evidence_failure"
    CLI_EXIT_CODE = "cli_exit_code"
    REFUSAL_PATH = "refusal_path"
    MALFORMED_INPUT = "malformed_input"
    PATH_TRAVERSAL = "path_traversal"
    COMMAND_INJECTION = "command_injection"
    SILENT_EXCEPTION = "silent_exception"
    STAGE_ORDERING = "stage_ordering"
    DUPLICATED_LOGIC = "duplicated_logic"
    OTHER = "other"


class TestIntentKind(str, Enum):
    """What the recommended test should assert."""

    __test__ = False

    ASSERT_FALSY_REJECTED = "assert_falsy_rejected"
    ASSERT_ENUM_ROUND_TRIP = "assert_enum_round_trip"
    ASSERT_PERSISTED_CORRECTLY = "assert_persisted_correctly"
    ASSERT_EVIDENCE_WRITTEN = "assert_evidence_written"
    ASSERT_EXIT_CODE = "assert_exit_code"
    ASSERT_REFUSAL = "assert_refusal"
    ASSERT_VALIDATION_ERROR = "assert_validation_error"
    ASSERT_PATH_REJECTED = "assert_path_rejected"
    ASSERT_INJECTION_REJECTED = "assert_injection_rejected"
    ASSERT_EXCEPTION_LOGGED = "assert_exception_logged"
    ASSERT_ORDERING_STABLE = "assert_ordering_stable"
    ASSERT_NO_DUPLICATION = "assert_no_duplication"
    ASSERT_GENERIC = "assert_generic"


class CandidateStatus(str, Enum):
    """Lifecycle status of a regression test candidate."""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    IMPLEMENTED = "implemented"
    DEFERRED = "deferred"


class CandidatePriority(str, Enum):
    """Priority ranking for regression test candidates."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNSET = "unset"


# ---------------------------------------------------------------------------
# ORM Rows
# ---------------------------------------------------------------------------


class RegressionTestCandidateRow(Base):
    """SQLAlchemy row for regression test candidates."""

    __tablename__ = "regression_test_candidates"

    candidate_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    bug_class: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
    )
    failure_origin: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
    )
    test_intent: Mapped[str] = mapped_column(String(50), nullable=False)
    priority: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True,
    )
    target_file: Mapped[str] = mapped_column(String(500), nullable=True)
    target_test_file: Mapped[str] = mapped_column(String(500), nullable=True)
    source_finding_id: Mapped[str] = mapped_column(
        String(200), nullable=True, index=True,
    )
    source_work_item_id: Mapped[str] = mapped_column(
        String(200), nullable=True, index=True,
    )
    assertion_hint: Mapped[str] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(50), nullable=False)


class BugPatternRow(Base):
    """Persistent record of detected bug patterns."""

    __tablename__ = "bug_patterns"

    pattern_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    bug_class: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
    )
    occurrence_count: Mapped[str] = mapped_column(String(10), nullable=False)
    source_findings_json: Mapped[str] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(50), nullable=False)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class TestIntent:
    """Describes what a recommended regression test should assert."""

    __test__ = False

    def __init__(
        self,
        intent_kind: str = "",
        description: str = "",
        assertion_hint: str = "",
        target_file: str = "",
        target_test_file: str = "",
    ) -> None:
        self.intent_kind = intent_kind
        self.description = description
        self.assertion_hint = assertion_hint
        self.target_file = target_file
        self.target_test_file = target_test_file

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_kind": self.intent_kind,
            "description": self.description,
            "assertion_hint": self.assertion_hint,
            "target_file": self.target_file,
            "target_test_file": self.target_test_file,
        }


class BugPattern:
    """A detected recurring bug class across findings."""

    def __init__(
        self,
        pattern_id: str = "",
        bug_class: str = "",
        occurrence_count: int = 0,
        source_findings: list[str] | None = None,
        description: str = "",
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.pattern_id = pattern_id or str(uuid4())
        self.bug_class = bug_class
        self.occurrence_count = occurrence_count
        self.source_findings = source_findings or []
        self.description = description
        self.created_at = created_at or now
        self.updated_at = updated_at or now

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "bug_class": self.bug_class,
            "occurrence_count": self.occurrence_count,
            "source_findings": self.source_findings,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class RegressionTestCandidate:
    """A proposed regression test derived from bug history."""

    __test__ = False

    def __init__(
        self,
        candidate_id: str = "",
        title: str = "",
        description: str = "",
        bug_class: str = "other",
        failure_origin: str = "review_finding",
        test_intent: str = "assert_generic",
        priority: str = "unset",
        status: str = "proposed",
        target_file: str = "",
        target_test_file: str = "",
        source_finding_id: str = "",
        source_work_item_id: str = "",
        assertion_hint: str = "",
        evidence: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.candidate_id = candidate_id or str(uuid4())
        self.title = title
        self.description = description
        self.bug_class = bug_class
        self.failure_origin = failure_origin
        self.test_intent = test_intent
        self.priority = priority
        self.status = status
        self.target_file = target_file
        self.target_test_file = target_test_file
        self.source_finding_id = source_finding_id
        self.source_work_item_id = source_work_item_id
        self.assertion_hint = assertion_hint
        self.evidence = evidence or []
        self.metadata = metadata or {}
        self.created_at = created_at or now
        self.updated_at = updated_at or now

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "title": self.title,
            "description": self.description,
            "bug_class": self.bug_class,
            "failure_origin": self.failure_origin,
            "test_intent": self.test_intent,
            "priority": self.priority,
            "status": self.status,
            "target_file": self.target_file,
            "target_test_file": self.target_test_file,
            "source_finding_id": self.source_finding_id,
            "source_work_item_id": self.source_work_item_id,
            "assertion_hint": self.assertion_hint,
            "evidence": self.evidence,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ---------------------------------------------------------------------------
# Bug class -> test intent mapping
# ---------------------------------------------------------------------------

_BUG_CLASS_TO_INTENT: dict[str, tuple[str, str, str]] = {
    BugClass.TRUTHINESS_BUG.value: (
        TestIntentKind.ASSERT_FALSY_REJECTED.value,
        "Assert falsy values are rejected",
        'assert func("") raises or returns error; assert func(None) ...',
    ),
    BugClass.ENUM_SERIALIZATION.value: (
        TestIntentKind.ASSERT_ENUM_ROUND_TRIP.value,
        "Assert enum serializes and deserializes correctly",
        "assert Enum(serialized.value) == original for all members",
    ),
    BugClass.PERSISTENCE_DEFECT.value: (
        TestIntentKind.ASSERT_PERSISTED_CORRECTLY.value,
        "Assert data persists and round-trips through DB",
        "create -> persist -> reload -> assert fields match",
    ),
    BugClass.EVIDENCE_FAILURE.value: (
        TestIntentKind.ASSERT_EVIDENCE_WRITTEN.value,
        "Assert evidence bundle is written completely",
        "run operation -> assert all 4 evidence files exist and are valid JSON",
    ),
    BugClass.CLI_EXIT_CODE.value: (
        TestIntentKind.ASSERT_EXIT_CODE.value,
        "Assert CLI returns correct exit code",
        "invoke CLI with bad input -> assert exit code != 0; good input -> 0",
    ),
    BugClass.REFUSAL_PATH.value: (
        TestIntentKind.ASSERT_REFUSAL.value,
        "Assert operation is refused for invalid state",
        "attempt operation with rejected/unknown/expired input -> assert refusal",
    ),
    BugClass.MALFORMED_INPUT.value: (
        TestIntentKind.ASSERT_VALIDATION_ERROR.value,
        "Assert malformed input is caught at validation",
        "pass empty/null/oversized/special-char input -> assert ValueError",
    ),
    BugClass.PATH_TRAVERSAL.value: (
        TestIntentKind.ASSERT_PATH_REJECTED.value,
        "Assert path traversal sequences are rejected",
        'assert "../../etc/passwd" raises ValueError with "must not contain"',
    ),
    BugClass.COMMAND_INJECTION.value: (
        TestIntentKind.ASSERT_INJECTION_REJECTED.value,
        "Assert command injection is prevented",
        "assert shell metacharacters in input are escaped or rejected",
    ),
    BugClass.SILENT_EXCEPTION.value: (
        TestIntentKind.ASSERT_EXCEPTION_LOGGED.value,
        "Assert exceptions are logged, not swallowed",
        "trigger error path -> assert logger.warning/error was called",
    ),
    BugClass.STAGE_ORDERING.value: (
        TestIntentKind.ASSERT_ORDERING_STABLE.value,
        "Assert stage/step ordering is deterministic",
        "run twice -> assert output order identical",
    ),
    BugClass.DUPLICATED_LOGIC.value: (
        TestIntentKind.ASSERT_NO_DUPLICATION.value,
        "Assert no duplicated logic exists",
        "verify shared helper is called instead of inline reimplementation",
    ),
    BugClass.OTHER.value: (
        TestIntentKind.ASSERT_GENERIC.value,
        "Assert correct behavior for the identified pattern",
        "write targeted test for the specific bug pattern",
    ),
}

# Bug class keyword detection from finding descriptions
_BUG_CLASS_KEYWORDS: dict[str, list[str]] = {
    BugClass.TRUTHINESS_BUG.value: [
        "truthiness", "falsy", "empty string", "is not none",
        "truthy check", "boolean coercion",
    ],
    BugClass.ENUM_SERIALIZATION.value: [
        "enum serialization", "enum round-trip", "enum.value",
        "enum deserialization", "enum member",
    ],
    BugClass.PERSISTENCE_DEFECT.value: [
        "persistence defect", "not persisted", "missing column",
        "database write", "db round-trip", "updated_at missing",
        "double commit", "transaction boundary",
    ],
    BugClass.EVIDENCE_FAILURE.value: [
        "evidence missing", "evidence not written", "pass_fail.json",
        "evidence bundle incomplete", "artifact not created",
    ],
    BugClass.CLI_EXIT_CODE.value: [
        "exit code", "exit status", "non-zero exit",
        "cli exit", "systemexit",
    ],
    BugClass.REFUSAL_PATH.value: [
        "refusal path", "should refuse", "rejected proposal",
        "unapproved", "deprecated proposal", "superseded proposal",
    ],
    BugClass.MALFORMED_INPUT.value: [
        "malformed input", "invalid input", "empty input",
        "null input", "validation error", "missing required",
    ],
    BugClass.PATH_TRAVERSAL.value: [
        "path traversal", "directory traversal", "cwe-22",
        "../", "must not contain",
    ],
    BugClass.COMMAND_INJECTION.value: [
        "command injection", "shell injection", "cwe-78",
        "cwe-88", "argument injection", "shlex",
    ],
    BugClass.SILENT_EXCEPTION.value: [
        "silent exception", "swallowed exception", "bare except",
        "exception ignored", "silently swallowed",
    ],
    BugClass.STAGE_ORDERING.value: [
        "stage ordering", "non-deterministic", "ordering issue",
        "sort order", "deterministic ordering",
    ],
    BugClass.DUPLICATED_LOGIC.value: [
        "duplicated logic", "code duplication", "redundant code",
        "copy-paste", "inline reimplementation",
    ],
}


# Semantic priority ordering for deterministic sorting
_PRIORITY_RANK: dict[str, int] = {
    CandidatePriority.CRITICAL.value: 0,
    CandidatePriority.HIGH.value: 1,
    CandidatePriority.MEDIUM.value: 2,
    CandidatePriority.LOW.value: 3,
    CandidatePriority.UNSET.value: 4,
}


# ---------------------------------------------------------------------------
# Core generator
# ---------------------------------------------------------------------------


class RegressionTestGenerator:
    """Generates regression test candidates from review findings and bugs."""

    __test__ = False

    def __init__(
        self,
        db_path: str = "",
        artifacts_root: str = "",
    ) -> None:
        self._db_path = db_path or os.environ.get(
            "AXIOM_DB_PATH", "axiom_governance.db",
        )
        self._artifacts_root = artifacts_root or os.environ.get(
            "AXIOM_ARTIFACTS_ROOT", "artifacts",
        )
        engine = create_db_engine(self._db_path)
        init_db(engine)
        self._session_factory = make_session_factory(engine)

    # -- ID validation ------------------------------------------------------

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if ".." in value or "/" in value or "\\" in value:
            msg = f"{name} must not contain '..', '/', or '\\': {value!r}"
            raise ValueError(msg)

    # -- Bug class detection ------------------------------------------------

    @staticmethod
    def _detect_bug_class(text: str) -> str:
        lower = text.lower()
        for bug_class, keywords in _BUG_CLASS_KEYWORDS.items():
            for kw in keywords:
                if kw in lower:
                    return bug_class
        return BugClass.OTHER.value

    # -- Test intent from bug class -----------------------------------------

    @staticmethod
    def _intent_for_bug_class(bug_class: str) -> TestIntent:
        intent_kind, description, hint = _BUG_CLASS_TO_INTENT.get(
            bug_class,
            (
                TestIntentKind.ASSERT_GENERIC.value,
                "Assert correct behavior",
                "write targeted test",
            ),
        )
        return TestIntent(
            intent_kind=intent_kind,
            description=description,
            assertion_hint=hint,
        )

    # -- Priority from bug class --------------------------------------------

    @staticmethod
    def _priority_for_bug_class(bug_class: str) -> str:
        high_priority = {
            BugClass.PATH_TRAVERSAL.value,
            BugClass.COMMAND_INJECTION.value,
            BugClass.PERSISTENCE_DEFECT.value,
        }
        medium_priority = {
            BugClass.TRUTHINESS_BUG.value,
            BugClass.ENUM_SERIALIZATION.value,
            BugClass.EVIDENCE_FAILURE.value,
            BugClass.REFUSAL_PATH.value,
            BugClass.CLI_EXIT_CODE.value,
            BugClass.SILENT_EXCEPTION.value,
            BugClass.MALFORMED_INPUT.value,
        }
        if bug_class in high_priority:
            return CandidatePriority.HIGH.value
        if bug_class in medium_priority:
            return CandidatePriority.MEDIUM.value
        return CandidatePriority.LOW.value

    # -- Generate from findings ---------------------------------------------

    def generate_from_findings(self) -> dict[str, Any]:
        """Generate regression test candidates from review findings.

        Returns a dict with candidates, patterns, and run metadata.
        """
        run_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        findings = self._gather_findings()
        candidates: list[RegressionTestCandidate] = []
        bug_class_counts: dict[str, list[str]] = {}

        for finding in findings:
            finding_id = finding.get("finding_id", "")
            title = finding.get("title", "")
            description = finding.get("description", "")
            category = finding.get("category", "")
            text = f"{title} {description} {category}"

            bug_class = self._detect_bug_class(text)

            if bug_class not in bug_class_counts:
                bug_class_counts[bug_class] = []
            bug_class_counts[bug_class].append(finding_id)

            intent = self._intent_for_bug_class(bug_class)
            priority = self._priority_for_bug_class(bug_class)

            target_file = finding.get("source_file", "")
            target_test = ""
            if target_file:
                stem = Path(target_file).stem
                target_test = f"tests/test_{stem}.py"

            candidate = RegressionTestCandidate(
                title=f"Regression: {title}",
                description=(
                    f"Bug class: {bug_class}. "
                    f"Origin: review_finding. "
                    f"{intent.description}."
                ),
                bug_class=bug_class,
                failure_origin=FailureOrigin.REVIEW_FINDING.value,
                test_intent=intent.intent_kind,
                priority=priority,
                target_file=target_file,
                target_test_file=target_test,
                source_finding_id=finding_id,
                assertion_hint=intent.assertion_hint,
                evidence=[{
                    "type": "review_finding",
                    "finding_id": finding_id,
                    "title": title,
                }],
            )
            candidates.append(candidate)

        # Detect patterns (2+ occurrences of same bug class)
        patterns: list[BugPattern] = []
        for bug_class, finding_ids in sorted(bug_class_counts.items()):
            if bug_class == BugClass.OTHER.value:
                continue
            if len(finding_ids) >= 2:
                patterns.append(BugPattern(
                    bug_class=bug_class,
                    occurrence_count=len(finding_ids),
                    source_findings=finding_ids,
                    description=(
                        f"Bug class '{bug_class}' detected "
                        f"{len(finding_ids)} times across review findings"
                    ),
                ))

        # Persist
        self._persist_all(candidates, patterns)

        # Sort deterministically
        candidates.sort(
            key=lambda c: (
                _PRIORITY_RANK.get(c.priority, 99),
                c.bug_class,
                c.title,
            ),
        )
        patterns.sort(key=lambda p: (-p.occurrence_count, p.bug_class))

        result = {
            "run_id": run_id,
            "generated_at": now,
            "total_findings_analyzed": len(findings),
            "total_candidates": len(candidates),
            "total_patterns": len(patterns),
            "candidates": [c.to_dict() for c in candidates],
            "patterns": [p.to_dict() for p in patterns],
        }
        return result

    # -- Generate from explicit input ---------------------------------------

    def generate_from_input(
        self,
        title: str,
        description: str,
        failure_origin: str,
        bug_class: str = "",
        target_file: str = "",
        source_finding_id: str = "",
        source_work_item_id: str = "",
    ) -> RegressionTestCandidate:
        """Create a single candidate from explicit input."""
        if not title:
            msg = "title is required"
            raise ValueError(msg)

        if not bug_class:
            bug_class = self._detect_bug_class(f"{title} {description}")

        intent = self._intent_for_bug_class(bug_class)
        priority = self._priority_for_bug_class(bug_class)

        target_test = ""
        if target_file:
            stem = Path(target_file).stem
            target_test = f"tests/test_{stem}.py"

        candidate = RegressionTestCandidate(
            title=f"Regression: {title}",
            description=(
                f"Bug class: {bug_class}. "
                f"Origin: {failure_origin}. "
                f"{intent.description}."
            ),
            bug_class=bug_class,
            failure_origin=failure_origin,
            test_intent=intent.intent_kind,
            priority=priority,
            target_file=target_file,
            target_test_file=target_test,
            source_finding_id=source_finding_id,
            source_work_item_id=source_work_item_id,
            assertion_hint=intent.assertion_hint,
            evidence=[{
                "type": failure_origin,
                "title": title,
            }],
        )

        self._persist_candidates([candidate])
        return candidate

    # -- List/get -----------------------------------------------------------

    def list_candidates(
        self,
        bug_class: str = "",
        status: str = "",
        priority: str = "",
    ) -> list[dict[str, Any]]:
        """List regression test candidates with optional filters."""
        with get_session(self._session_factory) as session:
            query = session.query(RegressionTestCandidateRow)
            if bug_class:
                query = query.filter(
                    RegressionTestCandidateRow.bug_class == bug_class,
                )
            if status:
                query = query.filter(
                    RegressionTestCandidateRow.status == status,
                )
            if priority:
                query = query.filter(
                    RegressionTestCandidateRow.priority == priority,
                )
            rows = query.all()
            results = [self._row_to_dict(r) for r in rows]
            results.sort(
                key=lambda c: (
                    _PRIORITY_RANK.get(c.get("priority", "unset"), 99),
                    c.get("bug_class", ""),
                    c.get("title", ""),
                ),
            )
            return results

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        """Get a single candidate by ID."""
        self._validate_id_segment(candidate_id, "candidate_id")
        with get_session(self._session_factory) as session:
            row = session.get(RegressionTestCandidateRow, candidate_id)
            if row is None:
                return None
            return self._row_to_dict(row)

    def update_candidate_status(
        self,
        candidate_id: str,
        status: str,
    ) -> dict[str, Any] | None:
        """Update candidate status."""
        self._validate_id_segment(candidate_id, "candidate_id")
        with get_session(self._session_factory) as session:
            row = session.get(RegressionTestCandidateRow, candidate_id)
            if row is None:
                return None
            row.status = status
            row.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
            return self._row_to_dict(row)

    def list_patterns(self) -> list[dict[str, Any]]:
        """List detected bug patterns."""
        with get_session(self._session_factory) as session:
            rows = session.query(BugPatternRow).order_by(
                BugPatternRow.bug_class,
            ).all()
            return [self._pattern_row_to_dict(r) for r in rows]

    # -- Evidence -----------------------------------------------------------

    def write_evidence(
        self,
        result: dict[str, Any],
    ) -> str:
        """Write evidence bundle for a generation run."""
        run_id = result.get("run_id", str(uuid4()))
        self._validate_id_segment(run_id, "run_id")

        evidence_dir = (
            Path(self._artifacts_root) / "regression_tests" / run_id
        )
        evidence_dir.mkdir(parents=True, exist_ok=True)

        # Request
        request_path = evidence_dir / "regression_request.json"
        request_data = {
            "run_id": run_id,
            "generated_at": result.get("generated_at", ""),
            "total_findings_analyzed": result.get(
                "total_findings_analyzed", 0,
            ),
        }
        request_path.write_text(
            json.dumps(request_data, indent=2, default=str),
        )

        # Result
        result_path = evidence_dir / "regression_result.json"
        result_path.write_text(
            json.dumps(result, indent=2, default=str),
        )

        # Summary
        summary_path = evidence_dir / "regression_summary.md"
        summary_lines = [
            "# Regression Test Generator Summary\n",
            f"- Run ID: {run_id}",
            f"- Generated at: {result.get('generated_at', '')}",
            f"- Findings analyzed: {result.get('total_findings_analyzed', 0)}",
            f"- Candidates generated: {result.get('total_candidates', 0)}",
            f"- Patterns detected: {result.get('total_patterns', 0)}",
            "",
        ]
        if result.get("candidates"):
            summary_lines.append("## Candidates\n")
            for c in result["candidates"]:
                summary_lines.append(
                    f"- [{c.get('priority', 'unset')}] "
                    f"{c.get('title', 'untitled')} "
                    f"({c.get('bug_class', 'other')})"
                )
            summary_lines.append("")
        if result.get("patterns"):
            summary_lines.append("## Patterns\n")
            for p in result["patterns"]:
                summary_lines.append(
                    f"- {p.get('bug_class', 'other')}: "
                    f"{p.get('occurrence_count', 0)} occurrences"
                )
            summary_lines.append("")
        summary_path.write_text("\n".join(summary_lines))

        # Pass/fail
        pass_fail_path = evidence_dir / "pass_fail.json"
        pass_fail_data = {
            "passed": True,
            "run_id": run_id,
            "total_candidates": result.get("total_candidates", 0),
            "total_patterns": result.get("total_patterns", 0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        pass_fail_path.write_text(
            json.dumps(pass_fail_data, indent=2, default=str),
        )

        return str(evidence_dir)

    # -- Internal -----------------------------------------------------------

    def _gather_findings(self) -> list[dict[str, Any]]:
        """Load review findings from the database."""
        try:
            from axiom_core.review_finding_registry import (
                ReviewFindingRegistry,
            )
            registry = ReviewFindingRegistry(db_path=self._db_path)
            findings = registry.list_findings()
            return [f.to_dict() for f in findings]
        except Exception:
            _logger.warning(
                "Failed to load review findings", exc_info=True,
            )
            return []

    def _persist_all(
        self,
        candidates: list[RegressionTestCandidate],
        patterns: list[BugPattern],
    ) -> None:
        """Persist candidates and patterns in a single transaction."""
        with get_session(self._session_factory) as session:
            for c in candidates:
                row = RegressionTestCandidateRow(
                    candidate_id=c.candidate_id,
                    title=c.title,
                    description=c.description,
                    bug_class=c.bug_class,
                    failure_origin=c.failure_origin,
                    test_intent=c.test_intent,
                    priority=c.priority,
                    status=c.status,
                    target_file=c.target_file,
                    target_test_file=c.target_test_file,
                    source_finding_id=c.source_finding_id,
                    source_work_item_id=c.source_work_item_id,
                    assertion_hint=c.assertion_hint,
                    evidence_json=json.dumps(c.evidence, default=str),
                    metadata_json=json.dumps(c.metadata, default=str),
                    created_at=c.created_at,
                    updated_at=c.updated_at,
                )
                session.merge(row)
            for p in patterns:
                row = BugPatternRow(
                    pattern_id=p.pattern_id,
                    bug_class=p.bug_class,
                    occurrence_count=str(p.occurrence_count),
                    source_findings_json=json.dumps(
                        p.source_findings, default=str,
                    ),
                    description=p.description,
                    created_at=p.created_at,
                    updated_at=p.updated_at,
                )
                session.merge(row)
            session.commit()

    def _persist_candidates(
        self,
        candidates: list[RegressionTestCandidate],
    ) -> None:
        """Persist candidates only."""
        with get_session(self._session_factory) as session:
            for c in candidates:
                row = RegressionTestCandidateRow(
                    candidate_id=c.candidate_id,
                    title=c.title,
                    description=c.description,
                    bug_class=c.bug_class,
                    failure_origin=c.failure_origin,
                    test_intent=c.test_intent,
                    priority=c.priority,
                    status=c.status,
                    target_file=c.target_file,
                    target_test_file=c.target_test_file,
                    source_finding_id=c.source_finding_id,
                    source_work_item_id=c.source_work_item_id,
                    assertion_hint=c.assertion_hint,
                    evidence_json=json.dumps(c.evidence, default=str),
                    metadata_json=json.dumps(c.metadata, default=str),
                    created_at=c.created_at,
                    updated_at=c.updated_at,
                )
                session.merge(row)
            session.commit()

    @staticmethod
    def _row_to_dict(row: RegressionTestCandidateRow) -> dict[str, Any]:
        evidence = []
        if row.evidence_json:
            try:
                evidence = json.loads(row.evidence_json)
            except (json.JSONDecodeError, TypeError):
                pass
        metadata = {}
        if row.metadata_json:
            try:
                metadata = json.loads(row.metadata_json)
            except (json.JSONDecodeError, TypeError):
                pass
        return {
            "candidate_id": row.candidate_id,
            "title": row.title,
            "description": row.description,
            "bug_class": row.bug_class,
            "failure_origin": row.failure_origin,
            "test_intent": row.test_intent,
            "priority": row.priority,
            "status": row.status,
            "target_file": row.target_file,
            "target_test_file": row.target_test_file,
            "source_finding_id": row.source_finding_id,
            "source_work_item_id": row.source_work_item_id,
            "assertion_hint": row.assertion_hint,
            "evidence": evidence,
            "metadata": metadata,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def _pattern_row_to_dict(row: BugPatternRow) -> dict[str, Any]:
        source_findings: list[str] = []
        if row.source_findings_json:
            try:
                source_findings = json.loads(row.source_findings_json)
            except (json.JSONDecodeError, TypeError):
                pass
        return {
            "pattern_id": row.pattern_id,
            "bug_class": row.bug_class,
            "occurrence_count": int(row.occurrence_count),
            "source_findings": source_findings,
            "description": row.description,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
