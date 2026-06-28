"""Work Prioritization Framework v1.

Provides deterministic prioritization on top of work queues and dependency
graphs. Moves from representing work relationships to determining execution
priority via weighted factors with stable tie-breaking.

Non-goals: no schedulers, no worker orchestration, no autonomous execution.
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


class WorkPriorityFactorType(str, Enum):
    USER_PRIORITY = "user_priority"
    DEPENDENCY_DEPTH = "dependency_depth"
    BLOCKER_COUNT = "blocker_count"
    AGE = "age"
    RETRY_COUNT = "retry_count"


_VALID_FACTOR_TYPES = {t.value for t in WorkPriorityFactorType}

_DEFAULT_WEIGHT = 1.0


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class WorkPriorityRule:
    """A weighting rule applied to a priority factor type."""

    rule_id: str = ""
    name: str = ""
    description: str = ""
    weight: float = 1.0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.rule_id:
            self.rule_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "description": self.description,
            "weight": self.weight,
            "created_at": self.created_at,
        }


@dataclass
class WorkPriorityFactor:
    """A single scored prioritization factor for a work item."""

    factor_id: str = ""
    work_id: str = ""
    factor_type: str = "user_priority"
    score: float = 0.0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.factor_id:
            self.factor_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "work_id": self.work_id,
            "factor_type": self.factor_type,
            "score": self.score,
            "created_at": self.created_at,
        }


@dataclass
class WorkPriorityResult:
    """The computed priority score and rank for a work item."""

    result_id: str = ""
    work_id: str = ""
    priority_score: float = 0.0
    execution_rank: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.result_id:
            self.result_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "work_id": self.work_id,
            "priority_score": self.priority_score,
            "execution_rank": self.execution_rank,
            "created_at": self.created_at,
        }


@dataclass
class WorkPrioritizationReport:
    """Report summarizing a prioritization run."""

    report_id: str = ""
    item_count: int = 0
    highest_priority_work_id: str = ""
    summary: str = ""
    created_at: str = ""
    rules: list[WorkPriorityRule] = field(default_factory=list)
    factors: list[WorkPriorityFactor] = field(default_factory=list)
    results: list[WorkPriorityResult] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "item_count": self.item_count,
            "highest_priority_work_id": self.highest_priority_work_id,
            "summary": self.summary,
            "created_at": self.created_at,
            "rules": [r.to_dict() for r in self.rules],
            "factors": [f.to_dict() for f in self.factors],
            "results": [r.to_dict() for r in self.results],
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class WorkPrioritizationEngine:
    """Computes deterministic work prioritization reports."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._report_dir = self._artifacts_root / "work_priorities"
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
        rules: list[dict[str, Any]] | None = None,
        factors: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a prioritization report from rules and factors."""
        rules = rules or []
        factors = factors or []

        rule_objects: list[WorkPriorityRule] = []
        for r_data in rules:
            rule_objects.append(
                WorkPriorityRule(
                    name=r_data.get("name", ""),
                    description=r_data.get("description", ""),
                    weight=float(r_data.get("weight", _DEFAULT_WEIGHT)),
                    created_at=r_data.get("created_at", ""),
                )
            )

        factor_objects: list[WorkPriorityFactor] = []
        for f_data in factors:
            factor_type = f_data.get("factor_type", "user_priority")
            if factor_type not in _VALID_FACTOR_TYPES:
                raise ValueError(
                    f"Invalid factor_type: {factor_type!r}. "
                    f"Valid: {sorted(_VALID_FACTOR_TYPES)}"
                )
            work_id = f_data.get("work_id", "")
            if not work_id:
                raise ValueError("work_id is required for a priority factor")
            factor_objects.append(
                WorkPriorityFactor(
                    work_id=work_id,
                    factor_type=factor_type,
                    score=float(f_data.get("score", 0.0)),
                    created_at=f_data.get("created_at", ""),
                )
            )

        # Deterministic ordering of rules and factors.
        rule_objects.sort(key=lambda r: (r.name, r.rule_id))
        factor_objects.sort(
            key=lambda f: (f.work_id, f.factor_type, f.factor_id)
        )

        # Weight lookup: a rule whose name matches a factor type applies its
        # weight to that factor type; otherwise the default weight is used.
        weight_by_type: dict[str, float] = {}
        for rule in rule_objects:
            if rule.name in _VALID_FACTOR_TYPES:
                weight_by_type[rule.name] = rule.weight

        # Aggregate weighted scores per work item.
        score_by_work: dict[str, float] = {}
        for factor in factor_objects:
            weight = weight_by_type.get(factor.factor_type, _DEFAULT_WEIGHT)
            score_by_work[factor.work_id] = (
                score_by_work.get(factor.work_id, 0.0) + factor.score * weight
            )

        # Deterministic ranking: highest score first; ties broken by work_id
        # ascending for stability.
        ranked = sorted(
            score_by_work.items(), key=lambda kv: (-kv[1], kv[0])
        )

        results: list[WorkPriorityResult] = []
        for rank, (work_id, score) in enumerate(ranked, start=1):
            results.append(
                WorkPriorityResult(
                    work_id=work_id,
                    priority_score=score,
                    execution_rank=rank,
                )
            )

        highest = ranked[0][0] if ranked else ""
        item_count = len(ranked)

        summary = ", ".join(
            [
                f"{item_count} items",
                f"{len(rule_objects)} rules",
                f"{len(factor_objects)} factors",
                f"highest={highest}" if highest else "highest=none",
            ]
        )

        report = WorkPrioritizationReport(
            item_count=item_count,
            highest_priority_work_id=highest,
            summary=summary,
            rules=rule_objects,
            factors=factor_objects,
            results=results,
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
            raise ValueError(f"Work prioritization report not found: {report_id}")
        return self._generate_export_md(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, report: WorkPrioritizationReport) -> None:
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

    def _write_evidence(self, report: WorkPrioritizationReport) -> None:
        evidence_dir = self._safe_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "rules": [r.to_dict() for r in report.rules],
            "factors": [f.to_dict() for f in report.factors],
        }
        (evidence_dir / "work_priority_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        (evidence_dir / "work_priority_result.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_export_md(report.to_dict())
        (evidence_dir / "work_priority_summary.md").write_text(md, encoding="utf-8")

        # A ranking passes when it is well-formed: ranks are unique and form a
        # contiguous 1..n sequence. Empty rankings pass.
        ranks = sorted(r.execution_rank for r in report.results)
        well_formed = ranks == list(range(1, len(ranks) + 1))
        passed = well_formed
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "item_count": report.item_count,
            "highest_priority_work_id": report.highest_priority_work_id,
            "well_formed_ranking": well_formed,
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

        lines.append("# Work Prioritization Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append(f"- Item Count: {data.get('item_count', 0)}")
        lines.append(
            f"- Highest Priority: {data.get('highest_priority_work_id', '') or 'none'}"
        )
        lines.append(f"- Summary: {data.get('summary', '')}")
        lines.append("")

        rules = data.get("rules", [])
        if rules:
            lines.append("## Rules")
            lines.append("")
            for r in rules:
                lines.append(
                    f"- {r.get('name', '')} (weight={r.get('weight', 0)})"
                )
            lines.append("")

        results = data.get("results", [])
        if results:
            lines.append("## Ranking")
            lines.append("")
            for r in results:
                lines.append(
                    f"{r.get('execution_rank', 0)}. {r.get('work_id', '')} "
                    f"(score={r.get('priority_score', 0)})"
                )
            lines.append("")

        return "\n".join(lines)
