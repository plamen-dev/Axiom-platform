"""Test Selection Engine v1 — deterministic test targeting from changed files.

Selects targeted tests based on changed files, work items, implementation
plans, or patch proposals.  Falls back to full pytest when impact or risk
is unknown.  Always includes ruff for Python changes.  Requires full suite
for safety, governance, evidence, runner, and persistence changes.

Non-goals: no test execution, no code modification, no patch application,
no PR creation, no autonomous behavior.
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


class TestSelectionReason(str, Enum):
    """Why a test was selected."""

    __test__ = False

    DIRECT_MAPPING = "direct_mapping"
    MODULE_MATCH = "module_match"
    HIGH_RISK_AREA = "high_risk_area"
    FULL_SUITE_FALLBACK = "full_suite_fallback"
    RUFF_ALWAYS = "ruff_always"
    WORK_ITEM_SCOPE = "work_item_scope"
    PATCH_PROPOSAL_SCOPE = "patch_proposal_scope"
    PLAN_SCOPE = "plan_scope"


class SelectionStrategy(str, Enum):
    """Overall strategy chosen for the test plan."""

    TARGETED = "targeted"
    FULL_SUITE = "full_suite"
    RUFF_ONLY = "ruff_only"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class TestSelectionRequest:
    """Input to the selection engine."""

    __test__ = False

    request_id: str = ""
    changed_files: list[str] = field(default_factory=list)
    work_item_id: str = ""
    plan_id: str = ""
    proposal_id: str = ""
    force_full_suite: bool = False

    def __post_init__(self) -> None:
        if not self.request_id:
            self.request_id = str(uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "changed_files": self.changed_files,
            "work_item_id": self.work_item_id,
            "plan_id": self.plan_id,
            "proposal_id": self.proposal_id,
            "force_full_suite": self.force_full_suite,
        }


@dataclass
class SelectedTest:
    """A single test selected for execution."""

    test_path: str = ""
    reason: str = ""
    source_file: str = ""
    priority: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_path": self.test_path,
            "reason": self.reason,
            "source_file": self.source_file,
            "priority": self.priority,
        }


@dataclass
class SelectedTestPlan:
    """Output of the selection engine."""

    plan_id: str = ""
    request_id: str = ""
    strategy: str = "targeted"
    selected_tests: list[SelectedTest] = field(default_factory=list)
    include_ruff: bool = False
    ruff_targets: list[str] = field(default_factory=list)
    full_suite_reason: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.plan_id:
            self.plan_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "request_id": self.request_id,
            "strategy": self.strategy,
            "selected_tests": [t.to_dict() for t in self.selected_tests],
            "include_ruff": self.include_ruff,
            "ruff_targets": self.ruff_targets,
            "full_suite_reason": self.full_suite_reason,
            "test_count": len(self.selected_tests),
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# File-to-test mapping
# ---------------------------------------------------------------------------

# Direct source file -> test file mapping.
_FILE_TO_TEST: dict[str, str] = {
    "src/axiom_core/automation_bridge.py": "tests/test_automation_bridge.py",
    "src/axiom_core/automation_planner.py": "tests/test_automation_planner.py",
    "src/axiom_core/capability_planner.py": "tests/test_capability_planner.py",
    "src/axiom_core/capability_registry.py": "tests/test_capability_registry.py",
    "src/axiom_core/codebase_inventory.py": "tests/test_codebase_inventory.py",
    "src/axiom_core/code_validation.py": "tests/test_code_validation.py",
    "src/axiom_core/controlled_discovery_loop.py": "tests/test_controlled_discovery_loop.py",
    "src/axiom_core/dialog_watcher.py": "tests/test_dialog_watcher.py",
    "src/axiom_core/execution_log.py": "tests/test_execution_log.py",
    "src/axiom_core/implementation_planner.py": "tests/test_implementation_planner.py",
    "src/axiom_core/input_normalization.py": "tests/test_input_normalization.py",
    "src/axiom_core/knowledge_graph.py": "tests/test_knowledge_graph.py",
    "src/axiom_core/knowledge_objects.py": "tests/test_knowledge_objects.py",
    "src/axiom_core/knowledge_provenance.py": "tests/test_knowledge_provenance.py",
    "src/axiom_core/knowledge_registry.py": "tests/test_knowledge_registry.py",
    "src/axiom_core/knowledge_reviews.py": "tests/test_knowledge_reviews.py",
    "src/axiom_core/learning_candidates.py": "tests/test_learning_candidates.py",
    "src/axiom_core/model_health.py": "tests/test_model_health.py",
    "src/axiom_core/orchestrator.py": "tests/test_orchestrator.py",
    "src/axiom_core/patch_application.py": "tests/test_patch_application.py",
    "src/axiom_core/patch_proposal.py": "tests/test_patch_proposal.py",
    "src/axiom_core/patch_review.py": "tests/test_patch_review.py",
    "src/axiom_core/persistence.py": "tests/test_persistence.py",
    "src/axiom_core/plan_reviews.py": "tests/test_plan_reviews.py",
    "src/axiom_core/pr_draft_generator.py": "tests/test_pr_draft_generator.py",
    "src/axiom_core/prompt_resolver.py": "tests/test_prompt_resolver.py",
    "src/axiom_core/review_finding_registry.py": "tests/test_review_finding_registry.py",
    "src/axiom_core/run_spine.py": "tests/test_run_spine.py",
    "src/axiom_core/schemas.py": "tests/test_schemas.py",
    "src/axiom_core/self_improvement_loop.py": "tests/test_self_improvement_loop.py",
    "src/axiom_core/work_item_registry.py": "tests/test_work_item_registry.py",
    "src/axiom_core/test_selection_engine.py": "tests/test_test_selection_engine.py",
    "src/axiom_core/regression_test_generator.py": "tests/test_regression_test_generator.py",
    "src/axiom_core/patch_impact_analyzer.py": "tests/test_patch_impact_analyzer.py",
    "src/axiom_core/code_review_policy.py": "tests/test_code_review_policy.py",
    "src/axiom_core/coding_session_registry.py": "tests/test_coding_session_registry.py",
    "src/axiom_core/coding_session_orchestrator.py": "tests/test_coding_session_orchestrator.py",
    "src/axiom_core/session_plan_registry.py": "tests/test_session_plan_registry.py",
    "src/axiom_core/session_question_registry.py": "tests/test_session_question_registry.py",
    "src/axiom_core/assertion_registry.py": "tests/test_assertion_registry.py",
    "src/axiom_core/session_report_generator.py": "tests/test_session_report_generator.py",
    "src/axiom_core/session_review_registry.py": "tests/test_session_review_registry.py",
    "src/axiom_core/escalation_registry.py": "tests/test_escalation_registry.py",
    "src/axiom_core/repair_proposal_registry.py": "tests/test_repair_proposal_registry.py",
    "src/axiom_core/repair_decision_registry.py": "tests/test_repair_decision_registry.py",
    "src/axiom_core/conflict_registry.py": "tests/test_conflict_registry.py",
    "src/axiom_core/session_state_machine.py": "tests/test_session_state_machine.py",
    "src/axiom_core/session_task_graph.py": "tests/test_session_task_graph.py",
    "src/axiom_core/text_utils.py": "tests/test_text_utils.py",
    "src/axiom_core/live_coding_trial.py": "tests/test_live_coding_trial.py",
    "src/axiom_core/parser_coding_trial.py": "tests/test_parser_coding_trial.py",
    "src/axiom_core/configuration_registry.py": "tests/test_configuration_registry.py",
    "src/axiom_core/config_validation.py": "tests/test_config_validation.py",
    "src/axiom_core/config_repair.py": "tests/test_config_repair.py",
    "src/axiom_core/config_explanation.py": "tests/test_config_explanation.py",
    "src/axiom_core/config_execution.py": "tests/test_config_execution.py",
    "src/axiom_core/config_rollback.py": "tests/test_config_rollback.py",
    "src/axiom_core/config_history.py": "tests/test_config_history.py",
    "src/axiom_core/config_diff.py": "tests/test_config_diff.py",
    "src/axiom_core/config_merge.py": "tests/test_config_merge.py",
    "src/axiom_core/config_policy.py": "tests/test_config_policy.py",
    "src/axiom_core/config_scenario.py": "tests/test_config_scenario.py",
    "src/axiom_core/config_batch_execution.py": "tests/test_config_batch_execution.py",
    "src/axiom_core/config_dependency.py": "tests/test_config_dependency.py",
    "src/axiom_core/capability_definition.py": "tests/test_capability_definition.py",
    "src/axiom_core/capability_input.py": "tests/test_capability_input.py",
    "src/axiom_core/capability_output.py": "tests/test_capability_output.py",
    "src/axiom_core/capability_execution_report.py": "tests/test_capability_execution_report.py",
    "src/axiom_core/capability_failure.py": "tests/test_capability_failure.py",
    "src/axiom_core/capability_repair_outcome.py": "tests/test_capability_repair_outcome.py",
    "src/axiom_core/capability_confidence.py": "tests/test_capability_confidence.py",
    "src/axiom_core/capability_history.py": "tests/test_capability_history.py",
    "src/axiom_core/capability_skill.py": "tests/test_capability_skill.py",
    "src/axiom_core/work_queue.py": "tests/test_work_queue.py",
    "src/axiom_core/work_dependency.py": "tests/test_work_dependency.py",
    "src/axiom_core/work_prioritization.py": "tests/test_work_prioritization.py",
    "src/axiom_core/execution_attempt.py": "tests/test_execution_attempt.py",
    "src/axiom_core/execution_outcome.py": "tests/test_execution_outcome.py",
    "src/axiom_core/failure_classification_framework.py": (
        "tests/test_failure_classification_framework.py"
    ),
    "src/axiom_core/recovery_recommendation.py": (
        "tests/test_recovery_recommendation.py"
    ),
    "src/axiom_core/recovery_execution.py": (
        "tests/test_recovery_execution.py"
    ),
    "src/axiom_core/session_memory.py": "tests/test_session_memory.py",
    "src/axiom_core/skill_composition.py": "tests/test_skill_composition.py",
    "src/axiom_core/capability_routing.py": "tests/test_capability_routing.py",
    "src/axiom_core/capability_selection.py": "tests/test_capability_selection.py",
    "src/axiom_core/capability_chain.py": "tests/test_capability_chain.py",
    "src/axiom_core/global_capability_registry.py": "tests/test_global_capability_registry.py",
    "src/axiom_core/capability_event_timeline.py": "tests/test_capability_event_timeline.py",
    "src/axiom_core/github_metadata_import.py": "tests/test_github_metadata_import.py",
    "src/axiom_core/capability_summary.py": "tests/test_capability_summary.py",
    "src/axiom_core/devin_session_import.py": "tests/test_devin_session_import.py",
    "src/axiom_core/capability_relationship.py": "tests/test_capability_relationship.py",
    "src/axiom_core/capability_impact.py": "tests/test_capability_impact.py",
    "src/axiom_core/capability_file_knowledge.py": "tests/test_capability_file_knowledge.py",
    "src/axiom_core/capability_validation_knowledge.py": "tests/test_capability_validation_knowledge.py",
    "src/axiom_core/capability_knowledge_graph.py": "tests/test_capability_knowledge_graph.py",
    "src/axiom_core/execution_context.py": "tests/test_execution_context.py",
    "src/axiom_core/execution_environment.py": "tests/test_execution_environment.py",
    "src/axiom_core/execution_resource.py": "tests/test_execution_resource.py",
    "src/axiom_core/execution_constraint.py": "tests/test_execution_constraint.py",
    "src/axiom_core/execution_readiness.py": "tests/test_execution_readiness.py",
    "src/axiom_core/execution_plan.py": "tests/test_execution_plan.py",
    "src/axiom_core/execution_step.py": "tests/test_execution_step.py",
    "src/axiom_cli/main.py": "tests/test_command_registry.py",
}

# Module-level mapping: prefix -> test files (for files not in direct map).
_MODULE_TO_TESTS: dict[str, list[str]] = {
    "src/axiom_core/inventory/": [
        "tests/test_inventory.py",
        "tests/test_extraction_planner.py",
    ],
    "src/axiom_core/discovery/": [
        "tests/test_discovery_harness.py",
        "tests/test_discovery_interpret.py",
        "tests/test_discovery_registries.py",
    ],
    "tools/local_runner/": [
        "tests/test_local_runner.py",
    ],
}

# High-risk areas that require full pytest suite.
_HIGH_RISK_PREFIXES: list[str] = [
    "src/axiom_core/database.py",
    "src/axiom_core/models.py",
    "src/axiom_core/persistence.py",
    "src/axiom_core/run_spine.py",
    "src/axiom_core/runner/command_registry.py",
    "src/axiom_core/runner/capability_runner.py",
    "src/axiom_core/schemas.py",
]

_HIGH_RISK_PATH_SEGMENTS: list[str] = [
    "/runner/",
    "/agents/",
]


# ---------------------------------------------------------------------------
# TestSelectionEngine
# ---------------------------------------------------------------------------


class TestSelectionEngine:
    """Deterministic test selection from changed files and context.

    Safety:
    - No test execution
    - No code modification
    - No patch application
    - No PR creation
    - No autonomous behavior
    - No GitHub API, no network dependency
    """

    __test__ = False

    def __init__(
        self,
        db_path: str | None = None,
        artifacts_root: str | None = None,
    ) -> None:
        self._db_path = db_path or os.environ.get("AXIOM_DB_PATH")
        self._artifacts_root = Path(
            artifacts_root or os.environ.get("AXIOM_ARTIFACTS_ROOT", "artifacts"),
        )

    # -- ID validation ------------------------------------------------------

    @staticmethod
    def _validate_id_segment(value: str, label: str) -> None:
        if not value:
            return
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(
                f"Invalid {label}: must not contain '..', '/', or '\\\\'",
            )

    # -- public API ---------------------------------------------------------

    def select_tests(
        self, request: TestSelectionRequest,
    ) -> SelectedTestPlan:
        """Select tests based on the request.

        Returns a deterministic SelectedTestPlan.
        """
        plan = SelectedTestPlan(request_id=request.request_id)

        # Force full suite if explicitly requested
        if request.force_full_suite:
            return self._full_suite_plan(
                plan, "Explicitly requested via force_full_suite",
            )

        # Gather changed files from all sources
        changed_files = list(request.changed_files)

        # Enrich from work item if provided
        if request.work_item_id:
            wi_files = self._files_from_work_item(request.work_item_id)
            changed_files.extend(wi_files)

        # Enrich from plan if provided
        if request.plan_id:
            plan_files = self._files_from_plan(request.plan_id)
            changed_files.extend(plan_files)

        # Enrich from proposal if provided
        if request.proposal_id:
            proposal_files = self._files_from_proposal(request.proposal_id)
            changed_files.extend(proposal_files)

        # Deduplicate and sort
        changed_files = sorted(set(changed_files))

        if not changed_files:
            return self._full_suite_plan(
                plan, "No changed files identified — running full suite",
            )

        # Check for high-risk areas
        high_risk = self._check_high_risk(changed_files)
        if high_risk:
            return self._full_suite_plan(plan, high_risk)

        # Map files to tests
        selected = self._map_files_to_tests(changed_files)

        if not selected:
            return self._full_suite_plan(
                plan, "No test mapping found for changed files — running full suite",
            )

        # Include ruff for Python changes
        python_files = [f for f in changed_files if f.endswith(".py")]
        if python_files:
            plan.include_ruff = True
            plan.ruff_targets = sorted(python_files)

        plan.strategy = SelectionStrategy.TARGETED.value
        plan.selected_tests = sorted(selected, key=lambda t: (t.priority, t.test_path))
        return plan

    def select_from_files(self, changed_files: list[str]) -> SelectedTestPlan:
        """Convenience: select tests from a list of changed files."""
        request = TestSelectionRequest(changed_files=changed_files)
        return self.select_tests(request)

    def select_from_work_item(self, work_item_id: str) -> SelectedTestPlan:
        """Convenience: select tests from a work item."""
        self._validate_id_segment(work_item_id, "work_item_id")
        request = TestSelectionRequest(work_item_id=work_item_id)
        return self.select_tests(request)

    def select_from_proposal(self, proposal_id: str) -> SelectedTestPlan:
        """Convenience: select tests from a patch proposal."""
        self._validate_id_segment(proposal_id, "proposal_id")
        request = TestSelectionRequest(proposal_id=proposal_id)
        return self.select_tests(request)

    def write_evidence(
        self, plan: SelectedTestPlan, request: TestSelectionRequest,
    ) -> str:
        """Write evidence bundle for a test selection run."""
        run_id = plan.plan_id
        self._validate_id_segment(run_id, "plan_id")
        run_dir = self._artifacts_root / "test_selection" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc).isoformat()

        # selection_request.json
        (run_dir / "selection_request.json").write_text(
            json.dumps({
                "plan_id": run_id,
                "request": request.to_dict(),
                "timestamp": now,
            }, indent=2, default=str),
            encoding="utf-8",
        )

        # selection_result.json
        (run_dir / "selection_result.json").write_text(
            json.dumps(plan.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

        # selection_summary.md
        summary_lines = [
            "# Test Selection Summary",
            "",
            f"**Plan ID:** {run_id}",
            f"**Strategy:** {plan.strategy}",
            f"**Tests selected:** {len(plan.selected_tests)}",
            f"**Include ruff:** {plan.include_ruff}",
            "",
        ]
        if plan.full_suite_reason:
            summary_lines.append(f"**Full suite reason:** {plan.full_suite_reason}")
            summary_lines.append("")
        if plan.selected_tests:
            summary_lines.append("## Selected Tests")
            summary_lines.append("")
            for t in plan.selected_tests:
                summary_lines.append(
                    f"- `{t.test_path}` ({t.reason})"
                    + (f" ← `{t.source_file}`" if t.source_file else ""),
                )
            summary_lines.append("")
        if plan.ruff_targets:
            summary_lines.append("## Ruff Targets")
            summary_lines.append("")
            for rt in plan.ruff_targets:
                summary_lines.append(f"- `{rt}`")
            summary_lines.append("")
        (run_dir / "selection_summary.md").write_text(
            "\n".join(summary_lines), encoding="utf-8",
        )

        # pass_fail.json
        (run_dir / "pass_fail.json").write_text(
            json.dumps({
                "passed": True,
                "run_id": run_id,
                "strategy": plan.strategy,
                "test_count": len(plan.selected_tests),
                "timestamp": now,
            }, indent=2),
            encoding="utf-8",
        )

        return str(run_dir)

    # -- internal helpers ---------------------------------------------------

    def _full_suite_plan(
        self, plan: SelectedTestPlan, reason: str,
    ) -> SelectedTestPlan:
        """Return a plan that runs the full test suite."""
        plan.strategy = SelectionStrategy.FULL_SUITE.value
        plan.full_suite_reason = reason
        plan.include_ruff = True
        plan.ruff_targets = ["src/", "tests/"]
        plan.selected_tests = [
            SelectedTest(
                test_path="tests/",
                reason=TestSelectionReason.FULL_SUITE_FALLBACK.value,
                priority=0,
            ),
        ]
        return plan

    def _check_high_risk(self, changed_files: list[str]) -> str:
        """Check if any changed files are in high-risk areas."""
        for f in changed_files:
            for hr in _HIGH_RISK_PREFIXES:
                if f == hr:
                    return (
                        f"High-risk file changed: {f} — "
                        f"requires full test suite"
                    )
            for seg in _HIGH_RISK_PATH_SEGMENTS:
                if seg in f:
                    return (
                        f"High-risk area changed: {f} (contains '{seg}') — "
                        f"requires full test suite"
                    )
        return ""

    def _map_files_to_tests(
        self, changed_files: list[str],
    ) -> list[SelectedTest]:
        """Map changed files to their corresponding tests."""
        seen: set[str] = set()
        result: list[SelectedTest] = []

        for f in changed_files:
            # Skip non-Python files
            if not f.endswith(".py"):
                continue

            # Skip test files themselves
            if f.startswith("tests/"):
                if f not in seen:
                    seen.add(f)
                    result.append(SelectedTest(
                        test_path=f,
                        reason=TestSelectionReason.DIRECT_MAPPING.value,
                        source_file=f,
                        priority=1,
                    ))
                continue

            # Direct mapping
            if f in _FILE_TO_TEST:
                test_path = _FILE_TO_TEST[f]
                if test_path not in seen:
                    seen.add(test_path)
                    result.append(SelectedTest(
                        test_path=test_path,
                        reason=TestSelectionReason.DIRECT_MAPPING.value,
                        source_file=f,
                        priority=1,
                    ))
                continue

            # Module-level mapping
            matched = False
            for prefix, test_files in _MODULE_TO_TESTS.items():
                if f.startswith(prefix):
                    for tf in test_files:
                        if tf not in seen:
                            seen.add(tf)
                            result.append(SelectedTest(
                                test_path=tf,
                                reason=TestSelectionReason.MODULE_MATCH.value,
                                source_file=f,
                                priority=2,
                            ))
                    matched = True
                    break

            # Convention-based: try test_<module>.py
            if not matched:
                stem = Path(f).stem
                candidate = f"tests/test_{stem}.py"
                if candidate not in seen:
                    seen.add(candidate)
                    result.append(SelectedTest(
                        test_path=candidate,
                        reason=TestSelectionReason.MODULE_MATCH.value,
                        source_file=f,
                        priority=3,
                    ))

        return result

    def _files_from_work_item(self, work_item_id: str) -> list[str]:
        """Extract affected files from a work item."""
        self._validate_id_segment(work_item_id, "work_item_id")
        try:
            from axiom_core.work_item_registry import WorkItemRegistry
            registry = WorkItemRegistry(db_path=self._db_path)
            item = registry.get_work_item(work_item_id)
            if item is None:
                return []
            data = item.to_dict()
            return data.get("affected_files", [])
        except Exception:
            _logger.warning("Failed to load work item %s", work_item_id, exc_info=True)
            return []

    def _files_from_plan(self, plan_id: str) -> list[str]:
        """Extract affected files from an implementation plan."""
        self._validate_id_segment(plan_id, "plan_id")
        try:
            from axiom_core.implementation_planner import ImplementationPlanner
            planner = ImplementationPlanner(db_path=self._db_path)
            plan = planner.get_plan(plan_id)
            if plan is None:
                return []
            data = plan.to_dict() if hasattr(plan, "to_dict") else {}
            files = data.get("affected_files", [])
            if not files:
                file_changes = data.get("file_changes", [])
                files = [fc.get("file_path", "") for fc in file_changes if fc.get("file_path")]
            return files
        except Exception:
            _logger.warning("Failed to load plan %s", plan_id, exc_info=True)
            return []

    def _files_from_proposal(self, proposal_id: str) -> list[str]:
        """Extract affected files from a patch proposal."""
        self._validate_id_segment(proposal_id, "proposal_id")
        try:
            from axiom_core.patch_proposal import PatchProposalRegistry
            registry = PatchProposalRegistry(db_path=self._db_path)
            proposal = registry.get_proposal(proposal_id)
            if proposal is None:
                return []
            data = proposal.to_dict()
            files = data.get("affected_files", [])
            if not files:
                file_changes = data.get("file_changes", [])
                files = [fc.get("file_path", "") for fc in file_changes if fc.get("file_path")]
            return files
        except Exception:
            _logger.warning("Failed to load proposal %s", proposal_id, exc_info=True)
            return []
