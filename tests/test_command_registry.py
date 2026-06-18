"""Tests for the Runner Command Registry (PR #22).

Governance-layer tests only: schema integrity, catalog coverage, classification,
the first-class named types (CommandRegistry / AllowedCommand / ExecutionContext
/ EvidenceOutput / Timeout / FailureClassification), prerequisite gating,
unknown-command denial, and the CLI list/inspect surface. No command execution.
"""

from __future__ import annotations

import json

from axiom_cli.main import cli
from axiom_core.runner import (
    DEFAULT_REGISTRY,
    AllowedCommand,
    CommandClass,
    CommandRegistry,
    CommandSpec,
    EvidenceOutput,
    ExecutionContext,
    FailureClassification,
    Prerequisite,
    SafetyLevel,
    Timeout,
    command_names,
    commands_by_classification,
    get_command,
    is_allowed,
    list_commands,
    validate_catalog,
)
from click.testing import CliRunner

# The seed commands from the original task statement.
SEED_COMMANDS = {
    "pytest",
    "ruff",
    "dotnet-build",
    "bridge-execute",
    "validation-run",
    "inventory-import",
    "discovery-run",
}

# Every built-in axiom CLI command must be cataloged (extended scope).
EXPECTED_AXIOM_COMMANDS = {
    "bridge-execute", "capability-plan", "capability-run", "capability-state",
    "classify-failure",
    "demo", "discovery-run", "evidence-run",
    "evidence-update", "execute",
    "inventory-combine", "inventory-export", "inventory-import",
    "inventory-import-batch", "inventory-model", "inventory-plan",
    "inventory-plan-status", "inventory-summary", "jobs",
    "knowledge-graph",
    "knowledge-objects", "knowledge-provenance", "knowledge-relationships",
    "knowledge-review-create", "knowledge-reviews", "knowledge-sources",
    "learning-candidates",
    "local-runner",
    "plan-review", "plan-review-create", "plan-reviews",
    "retrieve",
    "parameter-registry-build", "plan", "plans", "pr-snapshot", "promotion-check",
    "prompt",
    "runner-commands", "set-parameter-value", "stats", "submit", "test-grids",
    "test-levels", "tools", "trusted-capabilities", "trusted-capability",
    "trusted-capability-promote", "trusted-capability-revoke",
    "validation-orchestrate", "validation-registry",
    "validation-request", "validation-request-create", "validation-requests",
    "validation-run", "workflows",
}
TOOLCHAIN_COMMANDS = {"pytest", "ruff", "dotnet-build"}


# --- catalog integrity & coverage ------------------------------------------


def test_catalog_is_structurally_valid():
    validate_catalog()
    DEFAULT_REGISTRY.validate()


def test_seed_commands_present():
    assert SEED_COMMANDS.issubset(set(command_names()))


def test_all_builtin_axiom_commands_cataloged():
    # The registry must cover every command registered on the CLI.
    cli_commands = set(cli.commands.keys())
    cataloged = set(command_names())
    assert cli_commands.issubset(cataloged), cli_commands - cataloged
    # And the toolchain commands are cataloged on top of the axiom commands.
    assert TOOLCHAIN_COMMANDS.issubset(cataloged)


def test_catalog_matches_expected_set():
    cataloged = set(command_names())
    assert EXPECTED_AXIOM_COMMANDS.issubset(cataloged)
    # No stray entries beyond axiom commands + toolchain.
    assert cataloged == EXPECTED_AXIOM_COMMANDS | TOOLCHAIN_COMMANDS


def test_every_command_has_required_governance_fields():
    for spec in list_commands():
        assert isinstance(spec, AllowedCommand)
        assert spec.command.strip()
        assert spec.description.strip()
        assert isinstance(spec.classification, CommandClass)
        assert isinstance(spec.safety_level, SafetyLevel)
        assert spec.timeout_seconds > 0
        assert spec.evidence_outputs
        assert spec.failure_modes
        for ev in spec.evidence_outputs:
            assert isinstance(ev, EvidenceOutput)
            assert ev.location.strip()
        for fm in spec.failure_modes:
            assert isinstance(fm.code, FailureClassification)
            assert fm.description.strip()
            assert isinstance(fm.retryable, bool)
        for pre in spec.prerequisites:
            assert isinstance(pre, Prerequisite)


# --- named types -----------------------------------------------------------


def test_command_spec_is_allowed_command_alias():
    assert CommandSpec is AllowedCommand


def test_failure_classification_is_the_taxonomy_enum():
    assert FailureClassification.TIMEOUT.value == "timeout"
    # Each FailureMode code is a member of the taxonomy.
    for spec in list_commands():
        for fm in spec.failure_modes:
            assert isinstance(fm.code, FailureClassification)


def test_timeout_type_on_command():
    spec = get_command("pytest")
    assert isinstance(spec.timeout, Timeout)
    assert spec.timeout.seconds == spec.timeout_seconds
    assert spec.timeout.kill_on_expire is True
    assert spec.timeout.classification_on_expire is FailureClassification.TIMEOUT


def test_evidence_output_type_and_coercion():
    # Strings in the catalog are coerced to EvidenceOutput.
    spec = get_command("discovery-run")
    assert all(isinstance(e, EvidenceOutput) for e in spec.evidence_outputs)
    # Direct construction keeps explicit fields.
    e = EvidenceOutput(location="x", description="d", required=False)
    assert e.required is False and e.description == "d"


def test_requires_revit_and_model_open_flags():
    spv = get_command("set-parameter-value")
    assert spv.requires_revit is True
    assert spv.requires_model_open is True
    assert spv.requires_live_revit is True  # back-compat alias
    pytest_cmd = get_command("pytest")
    assert pytest_cmd.requires_revit is False
    assert pytest_cmd.requires_model_open is False


def test_read_only_and_mutation_predicates():
    assert get_command("stats").is_read_only is True
    assert get_command("stats").is_mutation is False
    assert get_command("prompt").is_mutation is True
    assert get_command("prompt").is_read_only is False


# --- classification expectations -------------------------------------------


def test_classification_mapping():
    assert get_command("pytest").classification is CommandClass.TEST
    assert get_command("ruff").classification is CommandClass.READ_ONLY
    assert get_command("dotnet-build").classification is CommandClass.BUILD
    assert get_command("bridge-execute").classification is CommandClass.LIVE_REVIT_REQUIRED
    assert get_command("inventory-model").classification is CommandClass.LIVE_REVIT_REQUIRED
    assert get_command("discovery-run").classification is CommandClass.READ_ONLY


def test_mutation_commands_are_high_risk():
    mutations = commands_by_classification(CommandClass.MUTATION)
    assert {"prompt", "execute", "set-parameter-value"}.issubset(
        {m.name for m in mutations})
    for m in mutations:
        assert m.safety_level is SafetyLevel.HIGH_RISK


def test_live_revit_flag_derivation():
    for spec in list_commands():
        if Prerequisite.REVIT_RUNNING in spec.prerequisites:
            assert spec.requires_revit is True


# --- denial & lookup -------------------------------------------------------


def test_unknown_commands_denied_by_default():
    assert is_allowed("pytest") is True
    assert is_allowed("rm -rf /") is False
    assert is_allowed("python") is False
    assert get_command("does-not-exist") is None


# --- ExecutionContext prerequisite gating ----------------------------------


def test_execution_context_gates_prerequisites():
    spv = get_command("set-parameter-value")
    # Default dev context: no Revit, no open model.
    ctx = ExecutionContext()
    unmet = spv.unmet_prerequisites(ctx)
    assert Prerequisite.REVIT_RUNNING in unmet
    assert Prerequisite.MODEL_OPEN in unmet
    assert spv.can_run(ctx) is False
    # With Revit + model open, it becomes runnable.
    ctx2 = ExecutionContext(revit_running=True, model_open=True)
    assert spv.can_run(ctx2) is True
    assert spv.unmet_prerequisites(ctx2) == []


def test_execution_context_none_prerequisite_always_satisfied():
    ctx = ExecutionContext(poetry_env=False)
    assert ctx.satisfies(Prerequisite.NONE) is True
    assert ctx.satisfies(Prerequisite.POETRY_ENV) is False


def test_registry_runnable_in_context():
    # A read-only inspector with only poetry_env is runnable in the default ctx.
    ctx = ExecutionContext()
    runnable = {c.name for c in DEFAULT_REGISTRY.runnable_in(ctx)}
    assert "stats" in runnable
    # Live-Revit commands are not runnable without Revit.
    assert "set-parameter-value" not in runnable
    assert "bridge-execute" not in runnable


def test_command_registry_is_independent_instance():
    reg = CommandRegistry({c.name: c for c in list_commands()})
    assert reg.command_names() == command_names()
    assert reg.is_allowed("evil") is False
    reg.validate()


# --- serialization ---------------------------------------------------------


def test_to_dict_is_json_serializable_with_named_types():
    for spec in list_commands():
        d = spec.to_dict()
        s = json.dumps(d)
        assert isinstance(s, str)
        assert d["classification"] == spec.classification.value
        assert d["timeout"]["seconds"] == spec.timeout_seconds
        assert all(isinstance(e["location"], str) for e in d["evidence_outputs"])
        assert all(isinstance(fm["code"], str) for fm in d["failure_modes"])
        assert isinstance(d["requires_revit"], bool)
        assert isinstance(d["requires_model_open"], bool)


# --- CLI surface -----------------------------------------------------------


def test_cli_list_shows_commands():
    result = CliRunner().invoke(cli, ["runner-commands"])
    assert result.exit_code == 0
    assert "Axiom Runner Command Registry" in result.output


def test_cli_json_list_is_complete_and_parseable():
    result = CliRunner().invoke(cli, ["runner-commands", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert {c["name"] for c in data} == set(command_names())


def test_cli_inspect_single_command_json():
    result = CliRunner().invoke(
        cli, ["runner-commands", "--name", "discovery-run", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["name"] == "discovery-run"
    assert data["classification"] == "read_only"
    assert data["failure_modes"]
    assert data["timeout"]["seconds"] > 0


def test_cli_unknown_command_denied_nonzero():
    result = CliRunner().invoke(cli, ["runner-commands", "--name", "evil-cmd"])
    assert result.exit_code == 2
    assert "not allowed" in result.output.lower()


def test_cli_unknown_command_denied_json():
    result = CliRunner().invoke(
        cli, ["runner-commands", "--name", "evil-cmd", "--json"])
    assert result.exit_code == 2
    data = json.loads(result.output)
    assert data["allowed"] is False
    assert data["name"] == "evil-cmd"


def test_cli_classification_filter():
    result = CliRunner().invoke(
        cli, ["runner-commands", "--classification", "build", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert {c["name"] for c in data} == {"dotnet-build"}


def test_cli_invalid_classification_rejected():
    result = CliRunner().invoke(
        cli, ["runner-commands", "--classification", "nonsense"])
    assert result.exit_code == 2
    assert "invalid classification" in result.output.lower()
