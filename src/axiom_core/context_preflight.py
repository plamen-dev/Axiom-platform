"""Axiom Context Preflight and Live System Map v0.

Live, repo-derived context loader that inspects the current repository and
emits a structured report of what Axiom knows about itself: repo state,
canonical context, integration docs, CLI/command map, evidence topology,
runner/execution substrate, known caveats, overlap guardrails, and a
reusable Context Basis template for future PR bodies.

This is a **read-only inspector** — it never mutates canonical documents,
never commits generated artifacts, and introduces no new knowledge framework
or evidence system.  It reuses existing :class:`CodebaseInventory` for file
scanning and :mod:`axiom_core.runner.command_registry` for command discovery.

Disposition: context preflight / live repo-derived system map.
Consumer: Program 1, Devin task packets, Programs 0/2/5/6/7, future PR
preflight.  Not canonical truth by itself; not a Devin replacement worker.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

# ── Section 1: Git / repo state ──────────────────────────────────────────

def _git_state(repo_root: Path) -> dict[str, Any]:
    """Capture current git branch, commit, dirty status, file counts."""
    result: dict[str, Any] = {}

    def _run(args: list[str]) -> str | None:
        try:
            return subprocess.run(
                ["git"] + args,
                capture_output=True,
                text=True,
                cwd=str(repo_root),
                timeout=15,
            ).stdout.strip() or None
        except Exception:
            return None

    result["branch"] = _run(["rev-parse", "--abbrev-ref", "HEAD"])
    result["commit"] = _run(["rev-parse", "HEAD"])
    result["commit_short"] = _run(["rev-parse", "--short", "HEAD"])

    status_out = _run(["status", "--porcelain"])
    if status_out is None:
        result["dirty"] = None
        result["untracked_count"] = 0
        result["modified_count"] = 0
    else:
        status_lines = [line for line in status_out.splitlines() if line.strip()] if status_out else []
        result["dirty"] = len(status_lines) > 0
        result["untracked_count"] = sum(1 for line in status_lines if line.startswith("??"))
        result["modified_count"] = sum(1 for line in status_lines if not line.startswith("??"))

    tracked = _run(["ls-files"])
    result["tracked_file_count"] = len(tracked.splitlines()) if tracked else 0

    warnings: list[str] = []
    if result.get("dirty"):
        warnings.append(
            "Working tree has uncommitted changes — context may not "
            "match the committed state."
        )
    if result.get("untracked_count", 0) > 0:
        warnings.append(
            f"{result['untracked_count']} untracked file(s) present — "
            "generated artifacts or local files may affect interpretation."
        )
    result["warnings"] = warnings
    return result


# ── Section 2: Canonical context ─────────────────────────────────────────

_CANONICAL_ROOT = "docs/canonical_knowledge_base"
_CANONICAL_DOCS = {
    "00_Readme": f"{_CANONICAL_ROOT}/00_Readme.md",
    "10_Current_Strategic_Context": f"{_CANONICAL_ROOT}/10_Current_Strategic_Context.md",
    "20_Current_Organizational_State": f"{_CANONICAL_ROOT}/20_Current_Organizational_State.md",
    "30_Architectural_Principles": f"{_CANONICAL_ROOT}/30_Architectural_Principles.md",
    "40_Open_Investigations": f"{_CANONICAL_ROOT}/40_Open_Investigations.md",
    "50_Organizational_Communications": f"{_CANONICAL_ROOT}/50_Organizational_Communications.md",
    "60_Reasoning_Quality_Assurance": f"{_CANONICAL_ROOT}/60_Reasoning_Quality_Assurance.md",
}
_IMPACT_LEDGER_FILES = {
    "Canonical_Impact_Ledger": f"{_CANONICAL_ROOT}/impact_ledger/Canonical_Impact_Ledger.md",
    "Program_Inventory_Reconciliation_PR155": (
        f"{_CANONICAL_ROOT}/impact_ledger/Program_Inventory_Reconciliation_PR155.md"
    ),
}


def _canonical_context(repo_root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}

    docs: dict[str, bool] = {}
    for name, rel in _CANONICAL_DOCS.items():
        docs[name] = (repo_root / rel).is_file()
    result["canonical_documents"] = docs
    result["canonical_root_exists"] = (repo_root / _CANONICAL_ROOT).is_dir()

    ledger: dict[str, bool] = {}
    for name, rel in _IMPACT_LEDGER_FILES.items():
        ledger[name] = (repo_root / rel).is_file()
    result["impact_ledger"] = ledger

    open_inv = repo_root / _CANONICAL_ROOT / "40_Open_Investigations.md"
    result["open_investigations_present"] = open_inv.is_file()

    return result


# ── Section 3: Integration / investigation context ───────────────────────

_INTEGRATION_DOCS = {
    "Evidence_Producer_Inventory_PR154": (
        "docs/architecture/integration/Evidence_Producer_Inventory_and_Consumer_Mapping_v1.md"
    ),
    "M2_Evidence_Promotion_Validation_Packet": (
        "docs/architecture/integration/M2_Evidence_Promotion_Validation_Packet.md"
    ),
    "M3_Purpose_Layer_Validation_Packet": (
        "docs/architecture/integration/M3_Purpose_Layer_Validation_Packet.md"
    ),
    "M4_Execution_Chain_Validation_Packet": (
        "docs/architecture/integration/M4_Execution_Chain_Validation_Packet.md"
    ),
    "PR_Purpose_Map_v0": (
        "docs/architecture/integration/PR_Purpose_Map_v0.md"
    ),
    "Duplicate_Alias_Map_v0": (
        "docs/architecture/integration/Duplicate_Alias_Map_v0.md"
    ),
    "Axiom_Current_Context_Pack": (
        "docs/architecture/integration/Axiom_Current_Context_Pack.md"
    ),
}


def _integration_context(repo_root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    docs: dict[str, str] = {}
    for name, rel in _INTEGRATION_DOCS.items():
        docs[name] = "present" if (repo_root / rel).is_file() else "unknown"
    result["integration_documents"] = docs

    # Prior self-discovery / reconciliation docs (optional — unknown, not error)
    optional: dict[str, str] = {}
    for name, rel in [
        ("local_runner_runbook", "docs/runbooks/local-runner-runbook.md"),
        ("validation_loop_runbook", "docs/runbooks/validation-loop-runbook.md"),
        ("evidence_log_maintenance", "docs/runbooks/evidence-log-maintenance.md"),
        ("axiom_doctrine", "docs/architecture/axiom-doctrine.md"),
    ]:
        optional[name] = "present" if (repo_root / rel).is_file() else "unknown"
    result["optional_investigation_documents"] = optional

    return result


# ── Section 4: Command / CLI map ─────────────────────────────────────────

# Known command-to-subsystem mapping for key commands
_SUBSYSTEM_TAGS: dict[str, str] = {
    "execution-chain-run": "execution-chain",
    "capability-evidence-apply": "evidence-promotion",
    "evidence-promotion-apply": "evidence-promotion",
    "cli-validation-record": "cli-validation-recorder",
    "model-health-evidence-apply": "model-health-evidence",
    "model-health-evidence-history": "model-health-evidence",
    "local-runner": "local-runner",
    "runner-commands": "command-registry",
    "context-preflight": "context-preflight",
}


def _cli_command_map(repo_root: Path) -> dict[str, Any]:
    """Discover CLI commands from the command registry + AST scan."""
    result: dict[str, Any] = {}

    # 1. Command Registry commands (runner-governed)
    try:
        from axiom_core.runner.command_registry import command_names as registry_names
        registry_cmds = registry_names()
        result["command_registry_count"] = len(registry_cmds)
    except Exception:
        registry_cmds = []
        result["command_registry_count"] = 0

    # 2. CLI commands (Click-registered) — parse from main.py AST
    cli_path = repo_root / "src" / "axiom_cli" / "main.py"
    cli_commands: list[str] = []
    if cli_path.is_file():
        import ast as _ast
        try:
            tree = _ast.parse(cli_path.read_text(encoding="utf-8"))
            for node in _ast.walk(tree):
                if isinstance(node, _ast.Call):
                    func = node.func
                    if (
                        isinstance(func, _ast.Attribute)
                        and func.attr == "command"
                        and isinstance(func.value, _ast.Name)
                        and func.value.id == "cli"
                    ):
                        if node.args:
                            first_arg = node.args[0]
                            if isinstance(first_arg, _ast.Constant) and isinstance(
                                first_arg.value, str
                            ):
                                cli_commands.append(first_arg.value)
        except Exception:
            pass
    result["cli_command_count"] = len(cli_commands)

    # 3. Subsystem-tagged commands
    tagged: dict[str, list[str]] = {}
    for cmd in cli_commands:
        tag = _SUBSYSTEM_TAGS.get(cmd)
        if tag:
            tagged.setdefault(tag, []).append(cmd)
    result["subsystem_commands"] = tagged

    return result


# ── Section 5: Evidence topology summary ─────────────────────────────────

_EVIDENCE_PRODUCERS = [
    {
        "name": "ExecutionChainOrchestrator",
        "module": "axiom_core.execution_chain_orchestrator",
        "artifact": "chain_evidence.json",
        "artifact_root": "artifacts/execution_chain/",
        "state_mutating": False,
        "consumer": "EvidencePromotionLoop",
    },
    {
        "name": "EvidencePromotionLoop",
        "module": "axiom_core.evidence_promotion",
        "artifact": "evidence_promotion report.json + pass_fail.json",
        "artifact_root": "artifacts/capability_evidence_intake/",
        "state_mutating": True,
        "consumer": "CapabilityConfidenceEngine",
    },
    {
        "name": "CapabilityConfidenceEngine",
        "module": "axiom_core.capability_confidence",
        "artifact": "capability_confidence.json",
        "artifact_root": "artifacts/capability_confidence/",
        "state_mutating": True,
        "consumer": None,
    },
    {
        "name": "ModelHealthReadinessConsumer (PR #156)",
        "module": "axiom_core.model_health_evidence",
        "artifact": "report.json + pass_fail.json (readiness intake)",
        "artifact_root": "artifacts/model_health_readiness_intake/",
        "state_mutating": False,
        "consumer": None,
        "notes": "confidence_mutated always false; readiness NOT routed into confidence",
    },
    {
        "name": "CLIValidationRecorder (PR #153)",
        "module": "axiom_core.validation.cli_validation_recorder",
        "artifact": "validation_run.json + commands.json + environment.json + artifact_manifest.json + report.md",
        "artifact_root": "artifacts/validation_evidence/",
        "state_mutating": False,
        "consumer": None,
        "notes": "traceability-first; consumer deferred by design",
    },
    {
        "name": "ModelHealth producer",
        "module": "axiom_core.model_health",
        "artifact": "axiom_capability_readiness.json",
        "artifact_root": "run-spine artifact folder",
        "state_mutating": False,
        "consumer": "ModelHealthReadinessConsumer",
        "notes": "read-only consumers: server_tools helpers",
    },
]


def _evidence_topology(repo_root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    producers: list[dict[str, Any]] = []
    for p in _EVIDENCE_PRODUCERS:
        entry = dict(p)
        # Check if module is present in repo
        mod_path = p["module"].replace(".", "/")
        candidates = [
            repo_root / "src" / (mod_path + ".py"),
            repo_root / "src" / mod_path / "__init__.py",
        ]
        entry["module_present"] = any(c.is_file() for c in candidates)
        producers.append(entry)
    result["known_producers"] = producers
    result["state_mutating_consumers"] = [
        p["name"] for p in _EVIDENCE_PRODUCERS if p.get("state_mutating")
    ]
    result["read_only_or_traceability"] = [
        p["name"]
        for p in _EVIDENCE_PRODUCERS
        if not p.get("state_mutating") and p.get("consumer") is None
    ]
    return result


# ── Section 6: Runner / execution substrate summary ──────────────────────

def _runner_substrate(repo_root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    result["local_runner_present"] = (repo_root / "tools" / "local_runner").is_dir()
    result["command_registry_present"] = (
        repo_root / "src" / "axiom_core" / "runner" / "command_registry.py"
    ).is_file()
    result["execution_chain_present"] = (
        repo_root / "src" / "axiom_core" / "execution_chain_orchestrator.py"
    ).is_file()
    result["validation_recorder_present"] = (
        repo_root / "src" / "axiom_core" / "validation" / "cli_validation_recorder.py"
    ).is_file()
    result["evidence_promotion_present"] = (
        repo_root / "src" / "axiom_core" / "evidence_promotion.py"
    ).is_file()
    result["model_health_evidence_present"] = (
        repo_root / "src" / "axiom_core" / "model_health_evidence.py"
    ).is_file()
    result["windows_local_evidence_note"] = (
        "Post-PR #151 Windows revalidation pending. "
        "Do not assume Windows substrate is fully validated unless live evidence exists."
    )
    return result


# ── Section 7: Known caveats / unresolved gaps ───────────────────────────

_KNOWN_CAVEATS = [
    {
        "id": "CAV-001",
        "area": "EVID-001",
        "status": "partially_closed",
        "detail": (
            "EVID-001 closed for M2 execution-chain slice and Model Health "
            "readiness slice only. Broader EVID-001 remains open."
        ),
    },
    {
        "id": "CAV-002",
        "area": "GPR",
        "status": "unimplemented",
        "detail": "Global Promotion Registry not implemented unless repo evidence proves otherwise.",
    },
    {
        "id": "CAV-003",
        "area": "Windows Local Runner",
        "status": "revalidation_pending",
        "detail": (
            "Post-PR #151 Windows revalidation pending. Do not assume Windows "
            "substrate is fully validated."
        ),
    },
    {
        "id": "CAV-004",
        "area": "Model Health confidence",
        "status": "untouched",
        "detail": (
            "Model Health readiness intake does NOT mutate confidence math "
            "(confidence_mutated always false). Readiness-to-confidence "
            "doctrine is an open Program 6 question."
        ),
    },
    {
        "id": "CAV-005",
        "area": "Model Health producer",
        "status": "invocation_unproven",
        "detail": (
            "Real execute_health_run producer invocation has not been proven "
            "via durable evidence unless repo evidence exists."
        ),
    },
    {
        "id": "CAV-006",
        "area": "Program 3 / Program 4",
        "status": "out_of_scope",
        "detail": (
            "Program 3 and Program 4 were outside the scope of the PR #155 "
            "reconciliation cycle and should not be represented as pending."
        ),
    },
]


def _known_caveats() -> list[dict[str, str]]:
    return list(_KNOWN_CAVEATS)


# ── Section 8: Overlap / duplication guardrails ──────────────────────────

_OVERLAP_AREAS = [
    {
        "area": "Runner / Orchestrator",
        "existing_components": [
            "tools/local_runner (execution harness)",
            "axiom_core.runner.command_registry (governance catalog)",
            "axiom_core.execution_chain_orchestrator (stage orchestrator)",
        ],
        "check_before_adding": "Any new runner, orchestrator, or execution harness.",
    },
    {
        "area": "Evidence / Report / pass_fail bundle generation",
        "existing_components": [
            "axiom_core.evidence_promotion (EvidencePromotionLoop)",
            "axiom_core.model_health_evidence (ModelHealthReadinessConsumer)",
            "axiom_core.validation.cli_validation_recorder (CLIValidationRecorder)",
            "axiom_core.execution_report (ExecutionReport)",
        ],
        "check_before_adding": "Any new evidence writer, report generator, or bundle emitter.",
    },
    {
        "area": "Failure classification / Recovery",
        "existing_components": [
            "axiom_core.failure_classification_framework",
            "axiom_core.recovery_recommendation",
            "axiom_core.recovery_execution",
        ],
        "check_before_adding": "Any new failure taxonomy, retry logic, or recovery engine.",
    },
    {
        "area": "Capability state / Confidence / Readiness",
        "existing_components": [
            "axiom_core.capability_confidence (CapabilityConfidenceEngine)",
            "axiom_core.capability_state_registry (CapabilityStateRegistry)",
            "axiom_core.model_health_evidence (readiness intake)",
            "axiom_core.model_health (readiness producer)",
        ],
        "check_before_adding": "Any new state tracker, confidence scorer, or readiness mutator.",
    },
    {
        "area": "Task / Work item / Session / Run models",
        "existing_components": [
            "axiom_core.session_memory",
            "axiom_core.session_state_machine",
            "axiom_core.session_task_graph",
            "axiom_core.work_queue",
            "axiom_core.work_prioritization",
            "axiom_core.work_dependency",
        ],
        "check_before_adding": "Any new task model, work-item queue, or session tracker.",
    },
    {
        "area": "Canonical / Ledger / Context docs",
        "existing_components": [
            "docs/canonical_knowledge_base/ (PR #152)",
            "docs/canonical_knowledge_base/impact_ledger/ (PR #155)",
            "docs/architecture/integration/ (PR #154 + M2/M3/M4 packets)",
            "docs/architecture/axiom-doctrine.md",
        ],
        "check_before_adding": "Any new canonical source, ledger, or context index.",
    },
]


def _overlap_guardrails() -> list[dict[str, Any]]:
    return list(_OVERLAP_AREAS)


# ── Section 10: System Atlas ─────────────────────────────────────────────

# Hardcoded from direct repo inspection (PR #157 design pass).
# Each family is a dict with: name, aliases, primary_files, purpose,
# workflow_edge, related_prs, status, overlap_risk, notes.

_COMPONENT_FAMILIES: list[dict[str, Any]] = [
    {
        "name": "Prompt / Input Normalization",
        "aliases": ["NormalizationReport", "FirmMapping", "NormalizationWarning"],
        "primary_files": [
            "src/axiom_core/input_normalization.py",
            "src/axiom_core/prompt_resolver.py",
            "src/axiom_core/word_numbers.py",
        ],
        "purpose": "Transform raw prompts and Excel inputs into NormalizedJob objects.",
        "workflow_edge": "User input → NormalizedJob",
        "related_prs": [],
        "status": "active",
        "overlap_risk": "low",
        "notes": "Stable entry point for all user prompts.",
    },
    {
        "name": "Job / NormalizedJob / Plan / ToolStep / QAReport",
        "aliases": ["Job", "NormalizedJob", "Plan", "ToolStep", "ToolResult", "QAReport", "Violation", "Anomaly"],
        "primary_files": ["src/axiom_core/schemas.py"],
        "purpose": "Core Pydantic data models for the older job→plan→execution→QA pipeline.",
        "workflow_edge": "NormalizedJob → Plan → ToolStep → ToolResult → QAReport",
        "related_prs": [],
        "status": "active",
        "overlap_risk": "medium — overlaps with WorkItem/WorkQueue and ExecutionPlan/Step families",
        "notes": "Older pipeline; coexists with newer execution-chain models.",
    },
    {
        "name": "Orchestrator (legacy job→plan→MCP)",
        "aliases": ["Orchestrator"],
        "primary_files": ["src/axiom_core/orchestrator.py"],
        "purpose": "Convert NormalizedJob into Plan, generate ToolSteps, and execute via MCP bridge.",
        "workflow_edge": "NormalizedJob → Plan → MCP execution → QAReport",
        "related_prs": [],
        "status": "active (legacy pipeline)",
        "overlap_risk": "high — 6+ orchestrator/runner variants exist",
        "notes": "Original execution path. See Duplicate/Alias Map Cluster 2.",
    },
    {
        "name": "Execution Chain Orchestrator (M4)",
        "aliases": ["ExecutionChainOrchestrator"],
        "primary_files": [
            "src/axiom_core/execution_chain_orchestrator.py",
            "tests/test_execution_chain_orchestrator.py",
        ],
        "purpose": "Prove 7-stage linked execution chain: Plan→Step→Attempt→Result→Artifact→Evidence→Report.",
        "workflow_edge": "M4: capability → 7-stage ID flow → evidence bundle",
        "related_prs": ["PR #146"],
        "status": "active / implemented runtime behavior",
        "overlap_risk": "high naming overlap (see Cluster 2) but distinct scope (M4 proof)",
        "notes": "Coordinates existing execution_plan..execution_report modules. Does not replace them.",
    },
    {
        "name": "Execution Plan / Step / Attempt / Result / Artifact / Report",
        "aliases": [
            "ExecutionPlan", "ExecutionStep", "ExecutionAttempt", "ExecutionAttemptV2",
            "ExecutionResult", "ExecutionArtifact", "ExecutionReport",
        ],
        "primary_files": [
            "src/axiom_core/execution_plan.py",
            "src/axiom_core/execution_step.py",
            "src/axiom_core/execution_attempt.py",
            "src/axiom_core/execution_attempt_v2.py",
            "src/axiom_core/execution_result.py",
            "src/axiom_core/execution_artifact.py",
            "src/axiom_core/execution_report.py",
        ],
        "purpose": "Individual execution-chain stage engines. Each manages one stage with is_within_sandbox artifact safety.",
        "workflow_edge": "Plan→Step→Attempt→Result→Artifact→Report (consumed by ExecutionChainOrchestrator)",
        "related_prs": ["PR #137 (Plan)", "PR #138 (Step)", "PR #139 (Attempt v2)", "PR #140 (Result)", "PR #141 (Artifact)", "PR #142 (Report)"],
        "status": "active",
        "overlap_risk": "low within their family; v1 (execution_attempt.py) vs v2 (execution_attempt_v2.py) coexist",
        "notes": "execution_attempt.py (v1, on top of Work Prioritization) and execution_attempt_v2.py (v2, on top of execution_step) coexist.",
    },
    {
        "name": "Evidence Promotion Loop (M2)",
        "aliases": ["EvidencePromotionLoop"],
        "primary_files": [
            "src/axiom_core/evidence_promotion.py",
            "tests/test_evidence_promotion.py",
        ],
        "purpose": "Route execution evidence into CapabilityConfidenceEngine (state mutation). Narrow M2 EVID-001 slice.",
        "workflow_edge": "M2: evidence bundle → pass/fail → confidence state mutation",
        "related_prs": ["PR #147", "PR #148 (hardening)"],
        "status": "active / implemented runtime behavior",
        "overlap_risk": "low — only M2 evidence consumer that mutates confidence",
        "notes": "Does not close broader EVID-001. Duplicate/conflict/stale quarantining via PR #148.",
    },
    {
        "name": "Capability Confidence",
        "aliases": ["CapabilityConfidenceEngine", "CapabilityConfidenceLevel", "CapabilityConfidenceFactors"],
        "primary_files": [
            "src/axiom_core/capability_confidence.py",
            "tests/test_capability_confidence.py",
        ],
        "purpose": "Deterministic confidence scoring from execution pass/fail history.",
        "workflow_edge": "EvidencePromotionLoop → CapabilityConfidenceEngine (terminal state mutator)",
        "related_prs": [],
        "status": "active",
        "overlap_risk": "medium — readiness vs confidence boundary is an open doctrine question (Program 6)",
        "notes": "Execution-derived score. Readiness intake (PR #156) does NOT feed into this.",
    },
    {
        "name": "Model Health / Readiness",
        "aliases": ["ModelHealth", "axiom_capability_readiness.json", "ReadinessCheck"],
        "primary_files": [
            "src/axiom_core/model_health.py",
        ],
        "purpose": "Produce readiness report for active Revit model. Precondition assessment, not execution outcome.",
        "workflow_edge": "Revit model → readiness checks per capability → axiom_capability_readiness.json",
        "related_prs": [],
        "status": "active (producer); real execute_health_run invocation not proven via durable evidence",
        "overlap_risk": "medium — readiness vs confidence doctrine pending (see Cluster 6)",
        "notes": "Read-only consumers exist in server_tools. State-mutating consumer added by PR #156.",
    },
    {
        "name": "Model Health Readiness Consumer",
        "aliases": ["ModelHealthReadinessConsumer"],
        "primary_files": [
            "src/axiom_core/model_health_evidence.py",
            "tests/test_model_health_evidence.py",
        ],
        "purpose": "Ingest, validate, dedup, and record readiness evidence. confidence_mutated=false always.",
        "workflow_edge": "axiom_capability_readiness.json → validate → dedup → intake record (no confidence mutation)",
        "related_prs": ["PR #156"],
        "status": "active / implemented runtime behavior",
        "overlap_risk": "low",
        "notes": "Closes narrow Model Health EVID-001 slice. Broader EVID-001 remains open.",
    },
    {
        "name": "CLI Validation Recorder",
        "aliases": ["CLIValidationRecorder", "cli-validation-record"],
        "primary_files": [
            "src/axiom_core/validation/cli_validation_recorder.py",
            "tests/test_cli_validation_recorder.py",
            "docs/validation_plans/",
        ],
        "purpose": "Run explicit, ordered plans of allowlisted CLI commands; write durable evidence bundles.",
        "workflow_edge": "Validation plan → governed command execution → evidence bundle (traceability-first)",
        "related_prs": ["PR #153"],
        "status": "active / implemented runtime behavior (no consumer yet by design)",
        "overlap_risk": "low if CommandRegistry governance is respected",
        "notes": "Complementary to EvidenceRunner. Consumer deferred intentionally.",
    },
    {
        "name": "Command Registry / Runner Governance",
        "aliases": ["CommandRegistry", "AllowedCommand", "runner-commands"],
        "primary_files": [
            "src/axiom_core/runner/command_registry.py",
            "src/axiom_core/runner/promotion_eligibility.py",
            "src/axiom_core/runner/failure_classification.py",
        ],
        "purpose": "Static catalog of allowed CLI commands with safety classification, timeouts, evidence outputs.",
        "workflow_edge": "Cross-cutting: all CLI command execution must check CommandRegistry",
        "related_prs": [],
        "status": "active",
        "overlap_risk": "low",
        "notes": "369 entries. Safety levels: SAFE, READ_ONLY, MUTATING, DESTRUCTIVE.",
    },
    {
        "name": "Local Runner",
        "aliases": ["LocalRunner", "local-runner"],
        "primary_files": [
            "tools/local_runner/local_runner.py",
            "tools/local_runner/workspace_policy.json",
        ],
        "purpose": "Restricted local subprocess executor with workspace policy, timeout handling, artifact capture.",
        "workflow_edge": "Named allowlisted action → subprocess → stdout/stderr capture → artifact",
        "related_prs": [],
        "status": "active; Windows revalidation pending (post-PR #151)",
        "overlap_risk": "high naming overlap (see Cluster 2) but lowest-level executor",
        "notes": "Security model: no arbitrary shell, allowlisted actions only, workspace restricted.",
    },
    {
        "name": "Failure Classification / Recovery",
        "aliases": [
            "FailureClassificationFramework", "CapabilityFailure",
            "RecoveryRecommendation", "RecoveryExecution",
        ],
        "primary_files": [
            "src/axiom_core/failure_classification_framework.py",
            "src/axiom_core/capability_failure.py",
            "src/axiom_core/recovery_recommendation.py",
            "src/axiom_core/recovery_execution.py",
            "src/axiom_core/runner/failure_classification.py",
        ],
        "purpose": "Classify execution failures and recommend/track recovery actions.",
        "workflow_edge": "Execution outcome → failure classification → recovery recommendation → recovery execution",
        "related_prs": ["PR #113 (classification)", "PR #114 (recommendation)", "PR #115 (execution)"],
        "status": "active",
        "overlap_risk": "medium — two failure classification modules (framework-level + runner-level)",
        "notes": "See Duplicate/Alias Map Cluster 7.",
    },
    {
        "name": "Work Queue / Work Item / Prioritization / Dependency",
        "aliases": [
            "WorkItem", "WorkQueue", "WorkPrioritization", "WorkDependency",
            "WorkItemRegistry", "WorkStatus", "WorkPriority",
        ],
        "primary_files": [
            "src/axiom_core/work_queue.py",
            "src/axiom_core/work_item_registry.py",
            "src/axiom_core/work_prioritization.py",
            "src/axiom_core/work_dependency.py",
        ],
        "purpose": "Autonomous-engineering work backlog: items, priorities, dependencies, SQLite persistence.",
        "workflow_edge": "Gap analysis / review findings → work items → prioritization → dependency tracking",
        "related_prs": [],
        "status": "active (framework exists; no autonomous scheduler or worker dispatches from it)",
        "overlap_risk": "medium — overlaps conceptually with Job/Plan family (Cluster 1)",
        "notes": "Non-goals stated in code: no schedulers, no worker orchestration, no autonomous planning.",
    },
    {
        "name": "Session Memory / State / Task Graph",
        "aliases": [
            "SessionMemory", "SessionStateMachine", "SessionTaskGraph",
            "SessionPlanRegistry",
        ],
        "primary_files": [
            "src/axiom_core/session_memory.py",
            "src/axiom_core/session_state_machine.py",
            "src/axiom_core/session_task_graph.py",
            "src/axiom_core/session_plan_registry.py",
        ],
        "purpose": "Short-term session-scope memory, state management, task dependency graph, plan registry.",
        "workflow_edge": "Attempts/outcomes/failures/recommendations/recoveries → session memory entries",
        "related_prs": ["PR #116 (session memory)"],
        "status": "active (framework exists; no autonomous session manager dispatches from it)",
        "overlap_risk": "low within session scope",
        "notes": "Non-goals: no long-term memory, no autonomous learning.",
    },
    {
        "name": "Capability Knowledge Ecosystem",
        "aliases": [
            "CapabilityKnowledgeGraph", "CapabilityRelationship",
            "CapabilityImpact", "CapabilityFileKnowledge",
            "CapabilityValidationKnowledge", "CapabilitySummary",
            "CapabilityEventTimeline", "CapabilityChain",
            "GlobalCapabilityRegistry",
        ],
        "primary_files": [
            "src/axiom_core/capability_knowledge_graph.py",
            "src/axiom_core/capability_relationship.py",
            "src/axiom_core/capability_impact.py",
            "src/axiom_core/capability_file_knowledge.py",
            "src/axiom_core/capability_validation_knowledge.py",
            "src/axiom_core/capability_summary.py",
            "src/axiom_core/capability_event_timeline.py",
            "src/axiom_core/capability_chain.py",
            "src/axiom_core/global_capability_registry.py",
        ],
        "purpose": "Multi-layer capability knowledge: graph nodes/edges, relationships, impacts, file locations, validation history, summaries, event timeline, chains, global identity.",
        "workflow_edge": "CodebaseInventory → self-model → knowledge graph / relationship / impact / file / validation / summary layers",
        "related_prs": ["PR #121 (registry)", "PR #122 (event timeline)", "PR #123 (summary)", "PR #131 (knowledge graph)"],
        "status": "active (structure exists; consumption depth varies per layer)",
        "overlap_risk": "low (each layer is a distinct concern) but the ecosystem is large",
        "notes": "Read-only knowledge layers. GlobalCapabilityRegistry provides canonical identity.",
    },
    {
        "name": "Self-Model / Gap Analysis / CodebaseInventory",
        "aliases": ["SelfModel", "SelfModelGapAnalysis", "CodebaseInventory"],
        "primary_files": [
            "src/axiom_core/self_model.py",
            "src/axiom_core/self_model_gap_analysis.py",
            "src/axiom_core/codebase_inventory.py",
        ],
        "purpose": "Live repo self-discovery: AST scan → module graph → gap detection → ranked integration backlog.",
        "workflow_edge": "M1: repo files → CodebaseInventory → self-model → gap analysis → backlog",
        "related_prs": ["PR #143 (self-model population)", "PR #144 (gap analysis)"],
        "status": "active / implemented runtime behavior",
        "overlap_risk": "low — unique self-awareness layer",
        "notes": "Adapter/analyzer only. Reuses existing knowledge graph and relationship engines.",
    },
    {
        "name": "Canonical KB / Impact Ledger / Docs",
        "aliases": ["canonical_knowledge_base", "impact_ledger", "behavior-change-ledger", "pr-review-ledger"],
        "primary_files": [
            "docs/canonical_knowledge_base/",
            "docs/canonical_knowledge_base/impact_ledger/",
            "docs/logs/behavior-change-ledger.md",
            "docs/logs/pr-review-ledger.md",
            "docs/runbooks/",
            "docs/architecture/",
        ],
        "purpose": "Durable organizational context, cross-program reconciliation, behavior history, PR audit trail, operational procedures, design specs.",
        "workflow_edge": "Context source for all programs and future PRs",
        "related_prs": ["PR #152 (KB seed)", "PR #155 (impact ledger)"],
        "status": "active",
        "overlap_risk": "medium — multiple context/knowledge docs exist (see Cluster 8)",
        "notes": "Canonical KB is accepted truth. Ledgers are historical records. See Duplicate/Alias Map Cluster 8.",
    },
]


def _system_atlas(repo_root: Path) -> dict[str, Any]:
    """Build a component-family map from hardcoded families + live file presence checks."""
    families: list[dict[str, Any]] = []
    for family in _COMPONENT_FAMILIES:
        entry = dict(family)
        # Check which primary files actually exist
        present: list[str] = []
        missing: list[str] = []
        for rel in family["primary_files"]:
            path = repo_root / rel
            if path.is_file() or path.is_dir():
                present.append(rel)
            else:
                missing.append(rel)
        entry["files_present"] = present
        entry["files_missing"] = missing
        families.append(entry)

    return {
        "family_count": len(families),
        "families": families,
        "data_source": "Hardcoded from PR #157 design pass + live file presence check",
        "reference_docs": [
            "docs/architecture/integration/Duplicate_Alias_Map_v0.md",
            "docs/architecture/integration/PR_Purpose_Map_v0.md",
            "docs/architecture/integration/Evidence_Producer_Inventory_and_Consumer_Mapping_v1.md",
        ],
    }


def _render_atlas_markdown(atlas: dict[str, Any]) -> str:
    """Render the system atlas as human-readable Markdown."""
    lines: list[str] = []
    lines.append("# Axiom System Atlas")
    lines.append("")
    lines.append("Live-generated component-family map. Reflects current repo file presence.")
    lines.append("For curated reconciliation, see the tracked reference docs:")
    lines.append("")
    for ref in atlas.get("reference_docs", []):
        lines.append(f"- `{ref}`")
    lines.append("")
    lines.append(f"**Component families:** {atlas.get('family_count', 0)}")
    lines.append("")

    for family in atlas.get("families", []):
        lines.append(f"## {family['name']}")
        lines.append("")
        lines.append(f"**Aliases:** {', '.join(family.get('aliases', []))}")
        lines.append(f"**Purpose:** {family.get('purpose', 'unknown')}")
        lines.append(f"**Workflow edge:** {family.get('workflow_edge', 'unknown')}")
        lines.append(f"**Status:** {family.get('status', 'unknown')}")
        lines.append(f"**Overlap risk:** {family.get('overlap_risk', 'unknown')}")
        if family.get("related_prs"):
            lines.append(f"**Related PRs:** {', '.join(family['related_prs'])}")
        if family.get("notes"):
            lines.append(f"**Notes:** {family['notes']}")
        lines.append("")
        lines.append("**Files:**")
        lines.append("")
        for f in family.get("files_present", []):
            lines.append(f"- `{f}` (present)")
        for f in family.get("files_missing", []):
            lines.append(f"- `{f}` (missing)")
        lines.append("")

    return "\n".join(lines)


# ── Section 9: Context Basis template ────────────────────────────────────

def _context_basis_template(report: dict[str, Any]) -> dict[str, Any]:
    """Emit a reusable Context Basis section for future PR bodies."""
    canonical_checked = [
        name for name, present in report.get("canonical_context", {}).get(
            "canonical_documents", {}
        ).items() if present
    ]
    ledger_checked = [
        name for name, present in report.get("canonical_context", {}).get(
            "impact_ledger", {}
        ).items() if present
    ]
    integration_checked = [
        name for name, status in report.get("integration_context", {}).get(
            "integration_documents", {}
        ).items() if status == "present"
    ]
    overlap_areas = [a["area"] for a in report.get("overlap_guardrails", [])]

    return {
        "files_and_reports_considered": canonical_checked + ledger_checked + integration_checked,
        "live_repo_scan_used": True,
        "existing_components_checked": overlap_areas,
        "known_overlap_risks": overlap_areas,
        "what_remains_unknown": [
            c["detail"] for c in report.get("known_caveats", [])
            if c.get("status") in ("unimplemented", "revalidation_pending", "invocation_unproven")
        ],
        "why_pr_is_not_duplicating_existing_work": (
            "Checked all overlap areas above; this PR adds/modifies only "
            "the code that addresses a confirmed gap not covered by the "
            "components listed."
        ),
    }


# ── Markdown rendering ───────────────────────────────────────────────────

def _render_markdown(report: dict[str, Any]) -> str:
    """Render the full report as human-readable Markdown."""
    lines: list[str] = []

    lines.append("# Axiom Context Preflight Report")
    lines.append("")
    lines.append(f"Generated: {report['generated_at_utc']}")
    lines.append(f"Run ID: {report['run_id']}")
    lines.append("")

    # 1. Git state
    g = report.get("git_state", {})
    lines.append("## 1. Git / Repo State")
    lines.append("")
    lines.append(f"- **Branch:** {g.get('branch', 'unknown')}")
    lines.append(f"- **Commit:** {g.get('commit_short', 'unknown')} ({g.get('commit', 'unknown')})")
    lines.append(f"- **Dirty:** {'yes' if g.get('dirty') else 'no'}")
    lines.append(f"- **Tracked files:** {g.get('tracked_file_count', 'unknown')}")
    if g.get("untracked_count", 0) > 0:
        lines.append(f"- **Untracked:** {g['untracked_count']}")
    if g.get("modified_count", 0) > 0:
        lines.append(f"- **Modified:** {g['modified_count']}")
    for w in g.get("warnings", []):
        lines.append(f"- **Warning:** {w}")
    lines.append("")

    # 2. Canonical context
    c = report.get("canonical_context", {})
    lines.append("## 2. Canonical Context")
    lines.append("")
    lines.append(f"Canonical root exists: {'yes' if c.get('canonical_root_exists') else 'no'}")
    lines.append("")
    lines.append("| Document | Present |")
    lines.append("|----------|---------|")
    for name, present in c.get("canonical_documents", {}).items():
        lines.append(f"| {name} | {'yes' if present else 'no'} |")
    lines.append("")
    lines.append("**Impact Ledger:**")
    lines.append("")
    for name, present in c.get("impact_ledger", {}).items():
        lines.append(f"- {name}: {'present' if present else 'missing'}")
    lines.append(f"- Open investigations file: {'present' if c.get('open_investigations_present') else 'missing'}")
    lines.append("")

    # 3. Integration context
    ic = report.get("integration_context", {})
    lines.append("## 3. Integration / Investigation Context")
    lines.append("")
    for name, status in ic.get("integration_documents", {}).items():
        lines.append(f"- {name}: {status}")
    lines.append("")
    if ic.get("optional_investigation_documents"):
        lines.append("**Optional investigation documents:**")
        lines.append("")
        for name, status in ic["optional_investigation_documents"].items():
            lines.append(f"- {name}: {status}")
        lines.append("")

    # 4. Command / CLI map
    cm = report.get("cli_command_map", {})
    lines.append("## 4. Command / CLI Map")
    lines.append("")
    lines.append(f"- **CLI commands (Click-registered):** {cm.get('cli_command_count', 0)}")
    lines.append(f"- **Command registry entries:** {cm.get('command_registry_count', 0)}")
    lines.append("")
    if cm.get("subsystem_commands"):
        lines.append("**Subsystem-tagged commands:**")
        lines.append("")
        for subsystem, cmds in cm["subsystem_commands"].items():
            lines.append(f"- `{subsystem}`: {', '.join(cmds)}")
        lines.append("")

    # 5. Evidence topology
    et = report.get("evidence_topology", {})
    lines.append("## 5. Evidence Topology Summary")
    lines.append("")
    if et.get("known_producers"):
        lines.append("| Producer | Module | State-mutating | Consumer | Present |")
        lines.append("|----------|--------|----------------|----------|---------|")
        for p in et["known_producers"]:
            lines.append(
                f"| {p['name']} | `{p['module']}` | "
                f"{'yes' if p.get('state_mutating') else 'no'} | "
                f"{p.get('consumer') or '(none)'} | "
                f"{'yes' if p.get('module_present') else 'no'} |"
            )
        lines.append("")
    if et.get("state_mutating_consumers"):
        lines.append(f"**State-mutating consumers:** {', '.join(et['state_mutating_consumers'])}")
        lines.append("")
    if et.get("read_only_or_traceability"):
        lines.append(f"**Read-only / traceability-only:** {', '.join(et['read_only_or_traceability'])}")
        lines.append("")

    # 6. Runner / execution substrate
    rs = report.get("runner_substrate", {})
    lines.append("## 6. Runner / Execution Substrate Summary")
    lines.append("")
    for key in [
        "local_runner_present",
        "command_registry_present",
        "execution_chain_present",
        "validation_recorder_present",
        "evidence_promotion_present",
        "model_health_evidence_present",
    ]:
        label = key.replace("_present", "").replace("_", " ").title()
        lines.append(f"- **{label}:** {'yes' if rs.get(key) else 'no'}")
    if rs.get("windows_local_evidence_note"):
        lines.append(f"- **Windows note:** {rs['windows_local_evidence_note']}")
    lines.append("")

    # 7. Known caveats
    caveats = report.get("known_caveats", [])
    lines.append("## 7. Known Caveats / Unresolved Gaps")
    lines.append("")
    for cav in caveats:
        lines.append(f"- **{cav['id']}** ({cav['area']}): [{cav['status']}] {cav['detail']}")
    lines.append("")

    # 8. Overlap guardrails
    og = report.get("overlap_guardrails", [])
    lines.append("## 8. Overlap / Duplication Guardrails")
    lines.append("")
    for area in og:
        lines.append(f"### {area['area']}")
        lines.append("")
        lines.append("Existing components:")
        for comp in area["existing_components"]:
            lines.append(f"- {comp}")
        lines.append(f"\nCheck before adding: {area['check_before_adding']}")
        lines.append("")

    # 9. Context Basis template
    cb = report.get("context_basis_template", {})
    lines.append("## 9. Context Basis Template")
    lines.append("")
    lines.append("Paste into future PR bodies:")
    lines.append("")
    lines.append("```")
    lines.append("Context Basis")
    lines.append(f"  Live repo scan used: {cb.get('live_repo_scan_used', False)}")
    lines.append(f"  Files/reports considered: {len(cb.get('files_and_reports_considered', []))}")
    for f in cb.get("files_and_reports_considered", []):
        lines.append(f"    - {f}")
    lines.append(f"  Existing components checked: {len(cb.get('existing_components_checked', []))}")
    for c in cb.get("existing_components_checked", []):
        lines.append(f"    - {c}")
    lines.append("  What remains unknown:")
    for u in cb.get("what_remains_unknown", []):
        lines.append(f"    - {u}")
    lines.append(f"  Why not duplicating: {cb.get('why_pr_is_not_duplicating_existing_work', '')}")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


# ── Main entry point ─────────────────────────────────────────────────────

def run_preflight(
    repo_root: str | Path,
    artifacts_root: str | Path | None = None,
) -> dict[str, Any]:
    """Run the full context preflight and return the structured report.

    Parameters
    ----------
    repo_root:
        Path to the repository root.
    artifacts_root:
        Where to write the generated ``context_preflight/`` artifacts.
        Defaults to ``<repo_root>/artifacts``.

    Returns
    -------
    dict
        The full preflight report (also persisted as JSON + Markdown).
    """
    repo = Path(repo_root).resolve()
    if artifacts_root is None:
        art = repo / "artifacts"
    else:
        art = Path(artifacts_root).resolve()

    run_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()

    report: dict[str, Any] = {
        "run_id": run_id,
        "generated_at_utc": now,
        "repo_root": str(repo),
    }

    report["git_state"] = _git_state(repo)
    report["canonical_context"] = _canonical_context(repo)
    report["integration_context"] = _integration_context(repo)
    report["cli_command_map"] = _cli_command_map(repo)
    report["evidence_topology"] = _evidence_topology(repo)
    report["runner_substrate"] = _runner_substrate(repo)
    report["known_caveats"] = _known_caveats()
    report["overlap_guardrails"] = _overlap_guardrails()
    report["context_basis_template"] = _context_basis_template(report)

    # System Atlas (Deliverable 2)
    atlas = _system_atlas(repo)

    # Persist artifacts
    out_dir = art / "context_preflight" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "context_preflight.json"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    md_text = _render_markdown(report)
    md_path = out_dir / "context_preflight.md"
    md_path.write_text(md_text, encoding="utf-8")

    atlas_json_path = out_dir / "system_atlas.json"
    atlas_json_path.write_text(json.dumps(atlas, indent=2, default=str), encoding="utf-8")

    atlas_md_text = _render_atlas_markdown(atlas)
    atlas_md_path = out_dir / "system_atlas.md"
    atlas_md_path.write_text(atlas_md_text, encoding="utf-8")

    report["system_atlas_summary"] = {
        "family_count": atlas["family_count"],
        "data_source": atlas["data_source"],
    }

    report["artifact_paths"] = {
        "json": str(json_path),
        "markdown": str(md_path),
        "system_atlas_json": str(atlas_json_path),
        "system_atlas_markdown": str(atlas_md_path),
    }

    return report
