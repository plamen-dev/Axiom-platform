"""Code Review Policy Engine v1 — deterministic policy evaluation for changed files.

Encodes recurring review bug patterns into explicit policies. Gives Axiom
an internal pre-review layer before external or human review.

Non-goals: no automatic fixes, no code modification, no PR creation,
no autonomous behavior, no external review integration, no GitHub API,
no network dependency.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
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


class PolicySeverity(str, Enum):
    """Severity of a policy violation."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class PolicyOrigin(str, Enum):
    """Where the policy was derived from."""

    DEVIN_REVIEW = "devin_review"
    RUNTIME_FAILURE = "runtime_failure"
    HUMAN_REVIEW = "human_review"
    SECURITY = "security"
    ARCHITECTURE = "architecture"


class PolicyCategory(str, Enum):
    """Category of review policy."""

    TRUTHINESS = "truthiness"
    ENUM_SERIALIZATION = "enum_serialization"
    SILENT_EXCEPTION = "silent_exception"
    EVIDENCE_BUNDLE = "evidence_bundle"
    CLI_EXIT_CODE = "cli_exit_code"
    CLASSIFICATION_DISTINCTNESS = "classification_distinctness"
    PATH_TRAVERSAL = "path_traversal"
    API_MISMATCH = "api_mismatch"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ReviewPolicy:
    """A deterministic review policy derived from recurring bug patterns."""

    policy_id: str = ""
    name: str = ""
    category: str = ""
    severity: str = "medium"
    origin: str = "devin_review"
    description: str = ""
    check_function: str = ""
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.policy_id:
            self.policy_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "name": self.name,
            "category": self.category,
            "severity": self.severity,
            "origin": self.origin,
            "description": self.description,
            "check_function": self.check_function,
            "enabled": self.enabled,
        }


@dataclass
class PolicyViolation:
    """A violation detected by a review policy."""

    violation_id: str = ""
    policy_id: str = ""
    policy_name: str = ""
    category: str = ""
    severity: str = "medium"
    file_path: str = ""
    line_number: int = 0
    description: str = ""
    suggestion: str = ""

    def __post_init__(self) -> None:
        if not self.violation_id:
            self.violation_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "violation_id": self.violation_id,
            "policy_id": self.policy_id,
            "policy_name": self.policy_name,
            "category": self.category,
            "severity": self.severity,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "description": self.description,
            "suggestion": self.suggestion,
        }


@dataclass
class PolicyEvaluationResult:
    """Result of evaluating all policies against changed files."""

    run_id: str = ""
    evaluated_at: str = ""
    files_evaluated: list[str] = field(default_factory=list)
    total_violations: int = 0
    violations: list[PolicyViolation] = field(default_factory=list)
    policies_checked: int = 0
    passed: bool = True

    def __post_init__(self) -> None:
        if not self.run_id:
            self.run_id = str(uuid4())
        if not self.evaluated_at:
            self.evaluated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "evaluated_at": self.evaluated_at,
            "files_evaluated": sorted(self.files_evaluated),
            "total_violations": self.total_violations,
            "violations": [v.to_dict() for v in self.violations],
            "policies_checked": self.policies_checked,
            "passed": self.passed,
            "violations_by_severity": self._count_by_severity(),
        }

    def _count_by_severity(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for v in self.violations:
            counts[v.severity] = counts.get(v.severity, 0) + 1
        return counts


# Semantic severity ordering
_SEVERITY_RANK: dict[str, int] = {
    PolicySeverity.CRITICAL.value: 0,
    PolicySeverity.HIGH.value: 1,
    PolicySeverity.MEDIUM.value: 2,
    PolicySeverity.LOW.value: 3,
    PolicySeverity.INFO.value: 4,
}


# ---------------------------------------------------------------------------
# Built-in policies
# ---------------------------------------------------------------------------

_TRUTHINESS_PATTERN = re.compile(
    r"\bif\s+([\w.]+)\s*:", re.MULTILINE,
)

_BARE_EXCEPT_PATTERN = re.compile(
    r"^\s*except\s*:", re.MULTILINE,
)

_BROAD_EXCEPT_PATTERN = re.compile(
    r"^\s*except\s+Exception\s*:", re.MULTILINE,
)

_PASS_AFTER_EXCEPT = re.compile(
    r"except[^:]*:\s*\n\s+pass\b", re.MULTILINE,
)


def _check_truthiness(source: str, file_path: str) -> list[PolicyViolation]:
    """Detect ambiguous truthiness checks on variables that may be empty strings/0."""
    violations: list[PolicyViolation] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return violations

    for node in ast.walk(tree):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name):
            violations.append(PolicyViolation(
                policy_name="truthiness_ambiguity",
                category=PolicyCategory.TRUTHINESS.value,
                severity=PolicySeverity.MEDIUM.value,
                file_path=file_path,
                line_number=node.lineno,
                description=(
                    f"Ambiguous truthiness check on '{node.test.id}' — "
                    f"consider explicit comparison (is None, == '', etc.)"
                ),
                suggestion=f"Replace 'if {node.test.id}:' with explicit check",
            ))
    return violations


def _check_silent_exception(
    source: str, file_path: str,
) -> list[PolicyViolation]:
    """Detect bare except or except-pass patterns."""
    violations: list[PolicyViolation] = []
    lines = source.split("\n")
    for i, line in enumerate(lines, 1):
        if _BARE_EXCEPT_PATTERN.match(line):
            violations.append(PolicyViolation(
                policy_name="silent_exception_swallowing",
                category=PolicyCategory.SILENT_EXCEPTION.value,
                severity=PolicySeverity.HIGH.value,
                file_path=file_path,
                line_number=i,
                description="Bare except: clause swallows all exceptions",
                suggestion="Catch specific exceptions or add logging",
            ))

    for match in _PASS_AFTER_EXCEPT.finditer(source):
        lineno = source[:match.start()].count("\n") + 1
        violations.append(PolicyViolation(
            policy_name="silent_exception_swallowing",
            category=PolicyCategory.SILENT_EXCEPTION.value,
            severity=PolicySeverity.MEDIUM.value,
            file_path=file_path,
            line_number=lineno,
            description="except-pass pattern silently swallows exception",
            suggestion="Add logging or handle the exception",
        ))
    return violations


def _check_evidence_bundle(
    source: str, file_path: str,
) -> list[PolicyViolation]:
    """Check evidence bundle contracts: pass_fail.json must always be written."""
    violations: list[PolicyViolation] = []
    if "write_evidence" in source or "evidence" in file_path.lower():
        if "pass_fail" not in source and file_path.endswith(".py"):
            violations.append(PolicyViolation(
                policy_name="evidence_bundle_guarantee",
                category=PolicyCategory.EVIDENCE_BUNDLE.value,
                severity=PolicySeverity.HIGH.value,
                file_path=file_path,
                line_number=0,
                description="Evidence writer does not reference pass_fail.json",
                suggestion="Ensure pass_fail.json is always written",
            ))
    return violations


def _check_cli_exit_code(
    source: str, file_path: str,
) -> list[PolicyViolation]:
    """Check CLI commands use consistent exit codes."""
    violations: list[PolicyViolation] = []
    if not file_path.endswith("main.py"):
        return violations

    lines = source.split("\n")
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if "sys.exit(" in stripped:
            violations.append(PolicyViolation(
                policy_name="cli_exit_code_consistency",
                category=PolicyCategory.CLI_EXIT_CODE.value,
                severity=PolicySeverity.LOW.value,
                file_path=file_path,
                line_number=i,
                description="Uses sys.exit() instead of raise SystemExit()",
                suggestion="Use raise SystemExit(code) for consistency",
            ))
    return violations


def _check_enum_serialization(
    source: str, file_path: str,
) -> list[PolicyViolation]:
    """Detect enum values compared without .value."""
    violations: list[PolicyViolation] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return violations

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for comparator in node.comparators:
                if (
                    isinstance(comparator, ast.Attribute)
                    and isinstance(comparator.value, ast.Attribute)
                    and comparator.attr != "value"
                    and isinstance(comparator.value.value, ast.Name)
                ):
                    parent_name = comparator.value.value.id
                    if parent_name.endswith(("Status", "Level", "Kind", "Type", "Class", "Origin")):
                        violations.append(PolicyViolation(
                            policy_name="enum_serialization_fragility",
                            category=PolicyCategory.ENUM_SERIALIZATION.value,
                            severity=PolicySeverity.MEDIUM.value,
                            file_path=file_path,
                            line_number=node.lineno,
                            description=(
                                "Enum member compared without .value — "
                                "may fail after serialization round-trip"
                            ),
                            suggestion="Use .value for serialized comparisons",
                        ))
    return violations


def _check_path_traversal(
    source: str, file_path: str,
) -> list[PolicyViolation]:
    """Detect path construction from user input without validation."""
    violations: list[PolicyViolation] = []
    lines = source.split("\n")
    offset = 0
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if ("os.path.join" in stripped or "Path(" in stripped) and (
            "request" in stripped.lower()
            or "user" in stripped.lower()
            or "input" in stripped.lower()
        ):
            if "_validate" not in source[:offset]:
                violations.append(PolicyViolation(
                    policy_name="path_traversal_risk",
                    category=PolicyCategory.PATH_TRAVERSAL.value,
                    severity=PolicySeverity.HIGH.value,
                    file_path=file_path,
                    line_number=i,
                    description="Path constructed from potential user input without validation",
                    suggestion="Add _validate_id_segment() or path boundary check",
                ))
        offset += len(line) + 1
    return violations


def _check_classification_distinctness(
    source: str, file_path: str,
) -> list[PolicyViolation]:
    """Detect overlapping string-based classification sets."""
    violations: list[PolicyViolation] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return violations

    set_literals: list[tuple[int, set[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Set):
            values = set()
            for elt in node.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    values.add(elt.value)
            if len(values) >= 2:
                set_literals.append((node.lineno, values))

    for i, (line_a, set_a) in enumerate(set_literals):
        for line_b, set_b in set_literals[i + 1:]:
            overlap = set_a & set_b
            if overlap:
                violations.append(PolicyViolation(
                    policy_name="classification_distinctness",
                    category=PolicyCategory.CLASSIFICATION_DISTINCTNESS.value,
                    severity=PolicySeverity.MEDIUM.value,
                    file_path=file_path,
                    line_number=line_a,
                    description=(
                        f"Overlapping classification sets at lines "
                        f"{line_a} and {line_b}: {overlap}"
                    ),
                    suggestion="Ensure classification sets are disjoint",
                ))
    return violations


# Registry of all built-in checks
_BUILTIN_CHECKS: list[
    tuple[str, str, str, str, Any]
] = [
    (
        "truthiness_ambiguity",
        PolicyCategory.TRUTHINESS.value,
        PolicySeverity.MEDIUM.value,
        PolicyOrigin.DEVIN_REVIEW.value,
        _check_truthiness,
    ),
    (
        "silent_exception_swallowing",
        PolicyCategory.SILENT_EXCEPTION.value,
        PolicySeverity.HIGH.value,
        PolicyOrigin.DEVIN_REVIEW.value,
        _check_silent_exception,
    ),
    (
        "evidence_bundle_guarantee",
        PolicyCategory.EVIDENCE_BUNDLE.value,
        PolicySeverity.HIGH.value,
        PolicyOrigin.DEVIN_REVIEW.value,
        _check_evidence_bundle,
    ),
    (
        "cli_exit_code_consistency",
        PolicyCategory.CLI_EXIT_CODE.value,
        PolicySeverity.LOW.value,
        PolicyOrigin.DEVIN_REVIEW.value,
        _check_cli_exit_code,
    ),
    (
        "enum_serialization_fragility",
        PolicyCategory.ENUM_SERIALIZATION.value,
        PolicySeverity.MEDIUM.value,
        PolicyOrigin.DEVIN_REVIEW.value,
        _check_enum_serialization,
    ),
    (
        "path_traversal_risk",
        PolicyCategory.PATH_TRAVERSAL.value,
        PolicySeverity.HIGH.value,
        PolicyOrigin.SECURITY.value,
        _check_path_traversal,
    ),
    (
        "classification_distinctness",
        PolicyCategory.CLASSIFICATION_DISTINCTNESS.value,
        PolicySeverity.MEDIUM.value,
        PolicyOrigin.ARCHITECTURE.value,
        _check_classification_distinctness,
    ),
]


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------


class CodeReviewPolicyEngine:
    """Evaluates changed files against deterministic review policies."""

    def __init__(
        self,
        repo_root: str = "",
        artifacts_root: str = "",
    ) -> None:
        self._repo_root = repo_root or os.environ.get(
            "AXIOM_REPO_ROOT", ".",
        )
        self._artifacts_root = artifacts_root or os.environ.get(
            "AXIOM_ARTIFACTS_ROOT", "artifacts",
        )
        self._policies = self._build_policies()

    # -- ID validation ------------------------------------------------------

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if ".." in value or "/" in value or "\\" in value:
            msg = f"{name} must not contain '..', '/', or '\\': {value!r}"
            raise ValueError(msg)

    # -- Policy building ----------------------------------------------------

    @staticmethod
    def _build_policies() -> list[ReviewPolicy]:
        policies: list[ReviewPolicy] = []
        for name, category, severity, origin, _fn in _BUILTIN_CHECKS:
            policies.append(ReviewPolicy(
                name=name,
                category=category,
                severity=severity,
                origin=origin,
                description=f"Built-in policy: {name}",
                check_function=name,
            ))
        return policies

    # -- Evaluate files -----------------------------------------------------

    def evaluate_files(
        self,
        changed_files: list[str],
    ) -> dict[str, Any]:
        """Evaluate all policies against a list of changed files."""
        result = PolicyEvaluationResult(
            files_evaluated=list(changed_files),
            policies_checked=len(self._policies),
        )

        for fpath in changed_files:
            if not fpath.endswith(".py"):
                continue
            source = self._read_file(fpath)
            if source is None:
                continue
            for _name, _category, _severity, _origin, check_fn in _BUILTIN_CHECKS:
                try:
                    violations = check_fn(source, fpath)
                    result.violations.extend(violations)
                except Exception:
                    _logger.warning(
                        "Policy check %s failed on %s",
                        _name, fpath, exc_info=True,
                    )

        result.total_violations = len(result.violations)
        result.passed = not any(
            v.severity in (
                PolicySeverity.CRITICAL.value,
                PolicySeverity.HIGH.value,
            )
            for v in result.violations
        )

        # Deterministic ordering
        result.violations.sort(
            key=lambda v: (
                _SEVERITY_RANK.get(v.severity, 99),
                v.category,
                v.file_path,
                v.line_number,
            ),
        )

        return result.to_dict()

    # -- Evaluate from source string ----------------------------------------

    def evaluate_source(
        self,
        source: str,
        file_path: str = "<stdin>",
    ) -> dict[str, Any]:
        """Evaluate all policies against a source string."""
        result = PolicyEvaluationResult(
            files_evaluated=[file_path],
            policies_checked=len(self._policies),
        )

        for _name, _category, _severity, _origin, check_fn in _BUILTIN_CHECKS:
            try:
                violations = check_fn(source, file_path)
                result.violations.extend(violations)
            except Exception:
                _logger.warning(
                    "Policy check %s failed",
                    _name, exc_info=True,
                )

        result.total_violations = len(result.violations)
        result.passed = not any(
            v.severity in (
                PolicySeverity.CRITICAL.value,
                PolicySeverity.HIGH.value,
            )
            for v in result.violations
        )

        result.violations.sort(
            key=lambda v: (
                _SEVERITY_RANK.get(v.severity, 99),
                v.category,
                v.file_path,
                v.line_number,
            ),
        )

        return result.to_dict()

    # -- List policies ------------------------------------------------------

    def list_policies(self) -> list[dict[str, Any]]:
        """List all registered policies."""
        return [p.to_dict() for p in self._policies]

    # -- Read file ----------------------------------------------------------

    def _read_file(self, fpath: str) -> str | None:
        """Read file contents, resolving against repo root."""
        root = Path(self._repo_root).resolve()
        full_path = (root / fpath).resolve()
        if not full_path.is_relative_to(root):
            _logger.warning("Path escapes repo root: %s", fpath)
            return None
        try:
            return full_path.read_text(encoding="utf-8")
        except (FileNotFoundError, PermissionError, UnicodeDecodeError):
            _logger.warning("Could not read file %s", fpath)
            return None

    # -- Evidence writing ---------------------------------------------------

    def write_evidence(self, result: dict[str, Any]) -> str:
        """Write evidence bundle for the policy evaluation run."""
        run_id = result.get("run_id", str(uuid4()))
        self._validate_id_segment(run_id, "run_id")

        evidence_dir = Path(self._artifacts_root) / "policy_evaluations" / run_id
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "run_id": run_id,
            "evaluated_at": result.get("evaluated_at", ""),
            "files_evaluated": result.get("files_evaluated", []),
            "policies_checked": result.get("policies_checked", 0),
        }
        (evidence_dir / "policy_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
        )

        summary_lines = [
            "# Code Review Policy Evaluation Summary\n",
            f"- Run ID: {run_id}",
            f"- Evaluated at: {result.get('evaluated_at', '')}",
            f"- Files evaluated: {len(result.get('files_evaluated', []))}",
            f"- Policies checked: {result.get('policies_checked', 0)}",
            f"- Total violations: {result.get('total_violations', 0)}",
            f"- Passed: {result.get('passed', True)}",
        ]
        by_severity = result.get("violations_by_severity", {})
        if by_severity:
            summary_lines.append("\n## Violations by Severity")
            for sev, count in sorted(by_severity.items()):
                summary_lines.append(f"- {sev}: {count}")
        (evidence_dir / "policy_summary.md").write_text(
            "\n".join(summary_lines) + "\n",
        )

        pass_fail = {
            "passed": result.get("passed", True),
            "run_id": run_id,
            "total_violations": result.get("total_violations", 0),
            "violations_by_severity": by_severity,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
        )

        (evidence_dir / "policy_result.json").write_text(
            json.dumps(result, indent=2, default=str),
        )

        return str(evidence_dir)
