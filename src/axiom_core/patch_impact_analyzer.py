"""Patch Impact Analyzer v1 — deterministic impact analysis for proposed changes.

Identifies affected modules, commands, registries, tests, docs, evidence
contracts, and future behavior boundaries before patch application.

Consumes: Patch Proposal Registry, Codebase Inventory, Symbol Registry,
Test Selection Engine.

Non-goals: no patch application, no code modification, no test execution,
no PR creation, no autonomous behavior, no GitHub API, no network dependency.
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


class RiskArea(str, Enum):
    """High-risk area classification."""

    EVIDENCE = "evidence"
    PERSISTENCE = "persistence"
    RUNNER = "runner"
    MUTATION = "mutation"
    REVIT_BRIDGE = "revit_bridge"
    GOVERNANCE = "governance"
    SECURITY = "security"
    CLI = "cli"
    NONE = "none"


class ImpactLevel(str, Enum):
    """Severity of impact on a component."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class ChangeScope(str, Enum):
    """Scope of the proposed change."""

    MODULE = "module"
    FUNCTION = "function"
    CLASS = "class"
    FILE = "file"
    REGISTRY = "registry"
    CLI_COMMAND = "cli_command"
    TEST = "test"
    DOC = "doc"
    CONFIG = "config"
    ARTIFACT = "artifact"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class AffectedSymbol:
    """A symbol (function, class, etc.) affected by the proposed change."""

    name: str = ""
    kind: str = ""
    file_path: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "file_path": self.file_path,
            "description": self.description,
        }


@dataclass
class AffectedCommand:
    """A CLI command affected by the proposed change."""

    command_name: str = ""
    file_path: str = ""
    is_read_only: bool = True
    risk_area: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_name": self.command_name,
            "file_path": self.file_path,
            "is_read_only": self.is_read_only,
            "risk_area": self.risk_area,
        }


@dataclass
class AffectedTest:
    """A test file likely affected by the proposed change."""

    __test__ = False

    test_path: str = ""
    reason: str = ""
    source_file: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_path": self.test_path,
            "reason": self.reason,
            "source_file": self.source_file,
        }


@dataclass
class AffectedDoc:
    """A documentation file likely affected by the proposed change."""

    doc_path: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_path": self.doc_path,
            "reason": self.reason,
        }


@dataclass
class AffectedEvidence:
    """An evidence contract or artifact convention affected."""

    artifact_path: str = ""
    contract_type: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_path": self.artifact_path,
            "contract_type": self.contract_type,
            "description": self.description,
        }


@dataclass
class HighRiskFlag:
    """A high-risk area flagged for extra scrutiny."""

    risk_area: str = "none"
    file_path: str = ""
    reason: str = ""
    impact_level: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_area": self.risk_area,
            "file_path": self.file_path,
            "reason": self.reason,
            "impact_level": self.impact_level,
        }


@dataclass
class ImpactScope:
    """Complete impact scope for a proposed change."""

    scope_id: str = ""
    proposal_id: str = ""
    changed_files: list[str] = field(default_factory=list)
    affected_symbols: list[AffectedSymbol] = field(default_factory=list)
    affected_commands: list[AffectedCommand] = field(default_factory=list)
    affected_tests: list[AffectedTest] = field(default_factory=list)
    affected_docs: list[AffectedDoc] = field(default_factory=list)
    affected_evidence: list[AffectedEvidence] = field(default_factory=list)
    high_risk_flags: list[HighRiskFlag] = field(default_factory=list)
    overall_impact: str = "low"
    requires_full_suite: bool = False
    full_suite_reason: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.scope_id:
            self.scope_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope_id": self.scope_id,
            "proposal_id": self.proposal_id,
            "changed_files": sorted(self.changed_files),
            "affected_symbols": [s.to_dict() for s in self.affected_symbols],
            "affected_commands": [c.to_dict() for c in self.affected_commands],
            "affected_tests": [t.to_dict() for t in self.affected_tests],
            "affected_docs": [d.to_dict() for d in self.affected_docs],
            "affected_evidence": [e.to_dict() for e in self.affected_evidence],
            "high_risk_flags": [f.to_dict() for f in self.high_risk_flags],
            "overall_impact": self.overall_impact,
            "requires_full_suite": self.requires_full_suite,
            "full_suite_reason": self.full_suite_reason,
            "total_files": len(self.changed_files),
            "total_symbols": len(self.affected_symbols),
            "total_commands": len(self.affected_commands),
            "total_tests": len(self.affected_tests),
            "total_docs": len(self.affected_docs),
            "total_evidence": len(self.affected_evidence),
            "total_risk_flags": len(self.high_risk_flags),
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Risk area detection
# ---------------------------------------------------------------------------

_HIGH_RISK_PATHS: list[tuple[str, str, str]] = [
    ("artifacts/", RiskArea.EVIDENCE.value, "Evidence artifact convention"),
    ("src/axiom_core/database.py", RiskArea.PERSISTENCE.value, "Database layer"),
    ("src/axiom_core/models.py", RiskArea.PERSISTENCE.value, "ORM models"),
    ("src/axiom_core/persistence.py", RiskArea.PERSISTENCE.value, "Persistence layer"),
    ("src/axiom_core/runner/", RiskArea.RUNNER.value, "Runner subsystem"),
    ("src/axiom_core/patch_application.py", RiskArea.MUTATION.value, "Patch application"),
    ("src/axiom_core/automation_bridge.py", RiskArea.REVIT_BRIDGE.value, "Revit bridge"),
    ("src/axiom_core/run_spine.py", RiskArea.GOVERNANCE.value, "Run spine governance"),
    ("src/axiom_core/mcp_layer.py", RiskArea.GOVERNANCE.value, "MCP layer"),
    ("tools/local_runner/", RiskArea.RUNNER.value, "Local runner"),
    ("src/axiom_core/input_normalization.py", RiskArea.SECURITY.value, "Input normalization"),
    ("src/axiom_core/dialog_watcher.py", RiskArea.SECURITY.value, "Dialog watcher"),
]

_EVIDENCE_KEYWORDS: list[str] = [
    "pass_fail.json", "evidence", "artifacts/", "_request.json",
    "_result.json", "_summary.md",
]

_COMMAND_FILE = "src/axiom_cli/main.py"
_REGISTRY_FILE = "src/axiom_core/runner/command_registry.py"


# ---------------------------------------------------------------------------
# Core analyzer
# ---------------------------------------------------------------------------


class PatchImpactAnalyzer:
    """Analyzes impact of proposed changes before patch application."""

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

    # -- ID validation ------------------------------------------------------

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if ".." in value or "/" in value or "\\" in value:
            msg = f"{name} must not contain '..', '/', or '\\': {value!r}"
            raise ValueError(msg)

    # -- Analyze from proposal ----------------------------------------------

    def analyze_proposal(self, proposal_id: str) -> dict[str, Any]:
        """Analyze impact of a patch proposal by ID."""
        self._validate_id_segment(proposal_id, "proposal_id")

        proposal = self._load_proposal(proposal_id)
        if proposal is None:
            msg = f"Proposal not found: {proposal_id}"
            raise ValueError(msg)

        changed_files = [
            fc.get("file_path", "") if isinstance(fc, dict) else fc.file_path
            for fc in (proposal.get("file_changes", [])
                       if isinstance(proposal, dict)
                       else proposal.file_changes)
        ]
        return self.analyze_files(
            changed_files=changed_files,
            proposal_id=proposal_id,
        )

    # -- Analyze from file list ---------------------------------------------

    def analyze_files(
        self,
        changed_files: list[str],
        proposal_id: str = "",
    ) -> dict[str, Any]:
        """Analyze impact of a set of changed files."""
        run_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        scope = ImpactScope(
            scope_id=run_id,
            proposal_id=proposal_id,
            changed_files=list(changed_files),
        )

        for fpath in changed_files:
            self._detect_symbols(fpath, scope)
            self._detect_commands(fpath, scope)
            self._detect_tests(fpath, scope)
            self._detect_docs(fpath, scope)
            self._detect_evidence(fpath, scope)
            self._detect_high_risk(fpath, scope)

        self._compute_overall_impact(scope)

        # Deterministic ordering
        scope.affected_symbols.sort(key=lambda s: (s.file_path, s.name))
        scope.affected_commands.sort(key=lambda c: c.command_name)
        scope.affected_tests.sort(key=lambda t: t.test_path)
        scope.affected_docs.sort(key=lambda d: d.doc_path)
        scope.affected_evidence.sort(key=lambda e: e.artifact_path)
        scope.high_risk_flags.sort(
            key=lambda f: (
                _IMPACT_RANK.get(f.impact_level, 99),
                f.risk_area,
                f.file_path,
            ),
        )

        result = {
            "run_id": run_id,
            "generated_at": now,
            "proposal_id": proposal_id,
            "scope": scope.to_dict(),
        }
        return result

    # -- Symbol detection ---------------------------------------------------

    def _detect_symbols(self, fpath: str, scope: ImpactScope) -> None:
        """Detect symbols likely affected in the changed file."""
        try:
            from axiom_core.codebase_inventory import CodeSymbolRegistry

            registry = CodeSymbolRegistry(db_path=self._db_path)
            symbols = registry.list_symbols(file_path=fpath)
            for sym in symbols:
                s = sym if isinstance(sym, dict) else sym.to_dict()
                scope.affected_symbols.append(AffectedSymbol(
                    name=s.get("name", ""),
                    kind=s.get("kind", ""),
                    file_path=fpath,
                    description=s.get("description", ""),
                ))
        except Exception:
            _logger.warning(
                "Could not load symbols for %s", fpath, exc_info=True,
            )

    # -- Command detection --------------------------------------------------

    def _detect_commands(self, fpath: str, scope: ImpactScope) -> None:
        """Detect CLI commands affected by changes to this file."""
        if fpath == _COMMAND_FILE or fpath == _REGISTRY_FILE:
            scope.affected_commands.append(AffectedCommand(
                command_name="(all CLI commands — main.py/registry changed)",
                file_path=fpath,
                is_read_only=True,
                risk_area=RiskArea.CLI.value,
            ))
        elif fpath.startswith("src/axiom_core/") and fpath.endswith(".py"):
            module_stem = Path(fpath).stem
            scope.affected_commands.append(AffectedCommand(
                command_name=f"(commands consuming {module_stem})",
                file_path=fpath,
                is_read_only=True,
                risk_area=RiskArea.NONE.value,
            ))

    # -- Test detection -----------------------------------------------------

    def _detect_tests(self, fpath: str, scope: ImpactScope) -> None:
        """Detect test files likely affected by changes to this file."""
        try:
            from axiom_core.test_selection_engine import TestSelectionEngine

            engine = TestSelectionEngine(db_path=self._db_path)
            plan = engine.select_from_files([fpath])
            plan_dict = plan.to_dict() if hasattr(plan, "to_dict") else plan
            for test in plan_dict.get("selected_tests", []):
                test_path = test.get("test_path", "")
                if test_path and not any(
                    t.test_path == test_path for t in scope.affected_tests
                ):
                    scope.affected_tests.append(AffectedTest(
                        test_path=test_path,
                        reason=test.get("reason", ""),
                        source_file=fpath,
                    ))
        except Exception:
            _logger.warning(
                "Could not determine tests for %s", fpath, exc_info=True,
            )
            stem = Path(fpath).stem
            if fpath.startswith("src/") and fpath.endswith(".py"):
                scope.affected_tests.append(AffectedTest(
                    test_path=f"tests/test_{stem}.py",
                    reason="convention_fallback",
                    source_file=fpath,
                ))

    # -- Doc detection ------------------------------------------------------

    def _detect_docs(self, fpath: str, scope: ImpactScope) -> None:
        """Detect documentation files likely affected."""
        if fpath.startswith("docs/"):
            scope.affected_docs.append(AffectedDoc(
                doc_path=fpath,
                reason="direct_change",
            ))
        elif fpath.startswith("src/axiom_core/") and fpath.endswith(".py"):
            stem = Path(fpath).stem
            doc_path = f"docs/architecture/{stem.replace('_', '-')}.md"
            scope.affected_docs.append(AffectedDoc(
                doc_path=doc_path,
                reason="module_convention",
            ))

    # -- Evidence contract detection ----------------------------------------

    def _detect_evidence(self, fpath: str, scope: ImpactScope) -> None:
        """Detect evidence contracts affected."""
        lower = fpath.lower()
        for kw in _EVIDENCE_KEYWORDS:
            if kw in lower:
                scope.affected_evidence.append(AffectedEvidence(
                    artifact_path=fpath,
                    contract_type="evidence_bundle",
                    description=f"File touches evidence convention: {kw}",
                ))
                return

    # -- High-risk area detection -------------------------------------------

    def _detect_high_risk(self, fpath: str, scope: ImpactScope) -> None:
        """Flag high-risk areas for extra scrutiny."""
        for path_prefix, risk_area, desc in _HIGH_RISK_PATHS:
            if fpath.startswith(path_prefix) or fpath == path_prefix.rstrip("/"):
                impact = ImpactLevel.HIGH.value
                if risk_area in (
                    RiskArea.MUTATION.value,
                    RiskArea.SECURITY.value,
                ):
                    impact = ImpactLevel.CRITICAL.value
                scope.high_risk_flags.append(HighRiskFlag(
                    risk_area=risk_area,
                    file_path=fpath,
                    reason=desc,
                    impact_level=impact,
                ))
                return

    # -- Overall impact computation -----------------------------------------

    def _compute_overall_impact(self, scope: ImpactScope) -> None:
        """Compute overall impact level and full-suite requirement."""
        if any(
            f.impact_level == ImpactLevel.CRITICAL.value
            for f in scope.high_risk_flags
        ):
            scope.overall_impact = ImpactLevel.CRITICAL.value
            scope.requires_full_suite = True
            scope.full_suite_reason = "Critical-risk area affected"
        elif any(
            f.impact_level == ImpactLevel.HIGH.value
            for f in scope.high_risk_flags
        ):
            scope.overall_impact = ImpactLevel.HIGH.value
            scope.requires_full_suite = True
            scope.full_suite_reason = "High-risk area affected"
        elif len(scope.changed_files) > 5:
            scope.overall_impact = ImpactLevel.MEDIUM.value
            scope.requires_full_suite = True
            scope.full_suite_reason = "Large change set (>5 files)"
        elif scope.affected_commands:
            scope.overall_impact = ImpactLevel.MEDIUM.value
        else:
            scope.overall_impact = ImpactLevel.LOW.value

    # -- Load proposal ------------------------------------------------------

    def _load_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        """Load a patch proposal by ID."""
        try:
            from axiom_core.patch_proposal import PatchProposalRegistry

            registry = PatchProposalRegistry(db_path=self._db_path)
            proposal = registry.get_proposal(proposal_id)
            if proposal is None:
                return None
            return proposal.to_dict()
        except Exception:
            _logger.warning(
                "Could not load proposal %s", proposal_id, exc_info=True,
            )
            return None

    # -- Evidence writing ---------------------------------------------------

    def write_evidence(self, result: dict[str, Any]) -> str:
        """Write evidence bundle for the impact analysis run."""
        run_id = result.get("run_id", str(uuid4()))
        self._validate_id_segment(run_id, "run_id")

        evidence_dir = Path(self._artifacts_root) / "impact_analysis" / run_id
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "run_id": run_id,
            "generated_at": result.get("generated_at", ""),
            "proposal_id": result.get("proposal_id", ""),
            "total_files": result.get("scope", {}).get("total_files", 0),
        }
        (evidence_dir / "impact_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
        )

        scope = result.get("scope", {})
        summary_lines = [
            "# Patch Impact Analysis Summary\n",
            f"- Run ID: {run_id}",
            f"- Proposal: {result.get('proposal_id', 'N/A')}",
            f"- Generated: {result.get('generated_at', '')}",
            f"- Files changed: {scope.get('total_files', 0)}",
            f"- Symbols affected: {scope.get('total_symbols', 0)}",
            f"- Commands affected: {scope.get('total_commands', 0)}",
            f"- Tests affected: {scope.get('total_tests', 0)}",
            f"- Docs affected: {scope.get('total_docs', 0)}",
            f"- Evidence contracts: {scope.get('total_evidence', 0)}",
            f"- Risk flags: {scope.get('total_risk_flags', 0)}",
            f"- Overall impact: {scope.get('overall_impact', '')}",
            f"- Requires full suite: {scope.get('requires_full_suite', False)}",
        ]
        if scope.get("full_suite_reason"):
            summary_lines.append(
                f"- Full suite reason: {scope['full_suite_reason']}",
            )
        (evidence_dir / "impact_summary.md").write_text(
            "\n".join(summary_lines) + "\n",
        )

        pass_fail = {
            "passed": True,
            "run_id": run_id,
            "overall_impact": scope.get("overall_impact", ""),
            "requires_full_suite": scope.get("requires_full_suite", False),
            "total_risk_flags": scope.get("total_risk_flags", 0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
        )

        (evidence_dir / "impact_result.json").write_text(
            json.dumps(result, indent=2, default=str),
        )

        return str(evidence_dir)


# Semantic impact ordering for deterministic sorting
_IMPACT_RANK: dict[str, int] = {
    ImpactLevel.CRITICAL.value: 0,
    ImpactLevel.HIGH.value: 1,
    ImpactLevel.MEDIUM.value: 2,
    ImpactLevel.LOW.value: 3,
    ImpactLevel.NONE.value: 4,
}
