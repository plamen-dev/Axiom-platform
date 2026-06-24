"""Runner Command Registry — governed catalog of commands the AXIOM-01 runner
is allowed to execute.

This is the **execution policy layer**: a declarative, read-only catalog that
states *which* local commands are permitted, *under what conditions*
(prerequisites), *how their outputs are validated* (evidence outputs), and
*how failures are classified*. It does NOT execute anything — it is consulted
by runners/automation loops before they act.

Architecture boundary (see docs/architecture/runner-command-registry.md):
  - This module is pure governance/metadata. No subprocess, no I/O, no Revit.
  - The Local Runner (``tools/local_runner``) remains the execution harness;
    this registry is the policy it (and future automation loops) consults.
  - Unknown commands are denied by default: ``is_allowed`` returns False for
    anything not explicitly cataloged here.

Scope (PR #22): governance/infrastructure only. No autonomous execution, no
scheduling, no model mutation, no promotion loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------------------
# Classification enums
# ---------------------------------------------------------------------------


class CommandClass(str, Enum):
    """Primary effect classification for a cataloged command.

    These are the governance categories requested for PR #22:
    read-only / mutation / build / test / live-Revit-required.
    """

    READ_ONLY = "read_only"          # produces artifacts only; no model/repo mutation
    TEST = "test"                    # verification gate (pytest, validation loop)
    BUILD = "build"                  # compiles/produces binaries
    MUTATION = "mutation"            # mutates the model or repository state
    LIVE_REVIT_REQUIRED = "live_revit_required"  # talks to a running Revit add-in


class SafetyLevel(str, Enum):
    """How much caution a command requires before it may run."""

    SAFE = "safe"            # no side effects beyond artifacts; runnable anytime
    GUARDED = "guarded"      # has prerequisites / environment constraints
    HIGH_RISK = "high_risk"  # mutates model/state; must be explicitly gated


class Prerequisite(str, Enum):
    """Conditions that must hold before a command may be dispatched."""

    NONE = "none"
    POETRY_ENV = "poetry_env"                          # poetry virtualenv available
    DOTNET_SDK = "dotnet_sdk"                          # .NET SDK on PATH (Windows build)
    REVIT_RUNNING = "revit_running"                    # Revit process up with add-in
    MODEL_OPEN = "model_open"                          # a document is open in Revit
    BRANCH_CHECKED_OUT = "branch_checked_out"          # target git branch checked out
    WORKSPACE_CLEAN = "workspace_clean"                # no uncommitted changes
    DB_PATH_AVAILABLE = "db_path_available"            # writable SQLite db path
    INVENTORY_EXPORT_AVAILABLE = "inventory_export_available"  # an InventoryModel export exists


class FailureClass(str, Enum):
    """Stable taxonomy for classifying how a command failed.

    Automation loops use this to decide retry vs. escalate. Whether a given
    occurrence is retryable is recorded per-command on :class:`FailureMode`.
    """

    NONZERO_EXIT = "nonzero_exit"              # process returned a non-zero code
    TIMEOUT = "timeout"                        # exceeded the command timeout
    MISSING_PREREQUISITE = "missing_prerequisite"  # a declared prerequisite was not met
    ENVIRONMENT_ERROR = "environment_error"    # toolchain/interpreter/SDK problem
    PIPE_UNAVAILABLE = "pipe_unavailable"      # Revit named-pipe bridge not reachable
    MALFORMED_INPUT = "malformed_input"        # input artifact missing/unparseable
    BUILD_ERROR = "build_error"                # compilation failure
    TEST_FAILURE = "test_failure"              # one or more tests/assertions failed
    LINT_VIOLATION = "lint_violation"          # linter reported violations
    INCOMPLETE_DISCOVERY = "incomplete_discovery"  # ran but produced no usable result
    MISSING_EVIDENCE = "missing_evidence"      # expected evidence artifact absent


# ``FailureClassification`` is the public name for the failure taxonomy enum.
# ``FailureClass`` is kept as a short alias used throughout the catalog.
FailureClassification = FailureClass


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FailureMode:
    """A classified way a command can fail, with retry guidance.

    ``code`` is the stable :class:`FailureClassification`; ``retryable`` tells a
    future automation loop whether this failure is worth a bounded retry.
    """

    code: FailureClassification
    description: str
    retryable: bool = False

    def to_dict(self) -> dict:
        return {
            "code": self.code.value,
            "description": self.description,
            "retryable": self.retryable,
        }


@dataclass(frozen=True)
class EvidenceOutput:
    """A declared place to look to validate a command's result.

    ``location`` is a path/pattern or console descriptor; ``required`` marks
    whether its absence should be treated as a ``missing_evidence`` failure.
    """

    location: str
    description: str = ""
    required: bool = True

    def to_dict(self) -> dict:
        return {
            "location": self.location,
            "description": self.description,
            "required": self.required,
        }


@dataclass(frozen=True)
class Timeout:
    """A typed command timeout.

    On expiry the runner should kill the process (``kill_on_expire``) and
    classify the result as :attr:`FailureClassification.TIMEOUT`.
    """

    seconds: int
    kill_on_expire: bool = True

    @property
    def classification_on_expire(self) -> FailureClassification:
        return FailureClassification.TIMEOUT

    def to_dict(self) -> dict:
        return {
            "seconds": self.seconds,
            "kill_on_expire": self.kill_on_expire,
            "classification_on_expire": self.classification_on_expire.value,
        }


# Maps each prerequisite to the boolean attribute on ExecutionContext that
# satisfies it. ``NONE`` is always satisfied.
_PREREQ_CONTEXT_ATTR: dict[Prerequisite, str] = {
    Prerequisite.POETRY_ENV: "poetry_env",
    Prerequisite.DOTNET_SDK: "dotnet_sdk",
    Prerequisite.REVIT_RUNNING: "revit_running",
    Prerequisite.MODEL_OPEN: "model_open",
    Prerequisite.BRANCH_CHECKED_OUT: "branch_checked_out",
    Prerequisite.WORKSPACE_CLEAN: "workspace_clean",
    Prerequisite.DB_PATH_AVAILABLE: "db_path_available",
    Prerequisite.INVENTORY_EXPORT_AVAILABLE: "inventory_export_available",
}


@dataclass(frozen=True)
class ExecutionContext:
    """The runtime conditions a runner reports when asking whether a command
    may run. Pure data — consulted by the policy layer, never executes anything.

    Defaults describe a plain dev checkout: a Poetry env on a checked-out
    branch, with no Revit, no .NET SDK, no inventory export, and an unverified
    (possibly dirty) workspace.
    """

    poetry_env: bool = True
    dotnet_sdk: bool = False
    revit_running: bool = False
    model_open: bool = False
    branch_checked_out: bool = True
    workspace_clean: bool = False
    db_path_available: bool = False
    inventory_export_available: bool = False

    def satisfies(self, prerequisite: Prerequisite) -> bool:
        if prerequisite is Prerequisite.NONE:
            return True
        attr = _PREREQ_CONTEXT_ATTR.get(prerequisite)
        return bool(getattr(self, attr)) if attr else False


@dataclass(frozen=True)
class AllowedCommand:
    """A single governed command entry — a command the runner is allowed to run.

    Carries its safety classification, prerequisites, evidence expectations,
    timeout, and failure classification. This is policy metadata only; nothing
    here executes a command.
    """

    name: str
    command: str
    description: str
    classification: CommandClass
    safety_level: SafetyLevel
    prerequisites: tuple[Prerequisite, ...] = ()
    evidence_outputs: tuple[EvidenceOutput, ...] = ()
    timeout_seconds: int = 300
    failure_modes: tuple[FailureMode, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        # Allow plain strings in evidence_outputs for catalog brevity; coerce
        # them to EvidenceOutput so the public type is always EvidenceOutput.
        coerced = tuple(
            e if isinstance(e, EvidenceOutput) else EvidenceOutput(location=str(e))
            for e in self.evidence_outputs
        )
        object.__setattr__(self, "evidence_outputs", coerced)

    # --- explicit, first-class predicates ---------------------------------

    @property
    def requires_revit(self) -> bool:
        """RequiresRevit: the command needs a running Revit add-in."""
        return (
            self.classification is CommandClass.LIVE_REVIT_REQUIRED
            or Prerequisite.REVIT_RUNNING in self.prerequisites
        )

    # Back-compat alias.
    requires_live_revit = requires_revit

    @property
    def requires_model_open(self) -> bool:
        """RequiresModelOpen: the command needs a document open in Revit."""
        return Prerequisite.MODEL_OPEN in self.prerequisites

    @property
    def is_read_only(self) -> bool:
        return self.classification is CommandClass.READ_ONLY

    @property
    def is_mutation(self) -> bool:
        return self.classification is CommandClass.MUTATION

    @property
    def timeout(self) -> Timeout:
        """Typed timeout view of ``timeout_seconds``."""
        return Timeout(seconds=self.timeout_seconds)

    def unmet_prerequisites(self, context: ExecutionContext) -> list[Prerequisite]:
        """Prerequisites NOT satisfied by ``context`` (empty == runnable)."""
        return [p for p in self.prerequisites if not context.satisfies(p)]

    def can_run(self, context: ExecutionContext) -> bool:
        """Whether all prerequisites are satisfied by ``context``."""
        return not self.unmet_prerequisites(context)

    def to_dict(self) -> dict:
        """JSON-serializable view (enum values flattened to strings)."""
        return {
            "name": self.name,
            "command": self.command,
            "description": self.description,
            "classification": self.classification.value,
            "safety_level": self.safety_level.value,
            "prerequisites": [p.value for p in self.prerequisites],
            "evidence_outputs": [e.to_dict() for e in self.evidence_outputs],
            "timeout": self.timeout.to_dict(),
            "timeout_seconds": self.timeout_seconds,
            "failure_modes": [fm.to_dict() for fm in self.failure_modes],
            "requires_revit": self.requires_revit,
            "requires_model_open": self.requires_model_open,
            "is_read_only": self.is_read_only,
            "is_mutation": self.is_mutation,
            "notes": self.notes,
        }


# Back-compat alias for the original name used during initial implementation.
CommandSpec = AllowedCommand


# ---------------------------------------------------------------------------
# Reusable failure modes (keep the catalog DRY)
# ---------------------------------------------------------------------------

FM_TIMEOUT = FailureMode(FailureClass.TIMEOUT,
                         "Exceeded the command timeout.", retryable=True)
FM_NONZERO = FailureMode(FailureClass.NONZERO_EXIT,
                         "Command returned a non-zero exit code.", retryable=False)
FM_ENV = FailureMode(FailureClass.ENVIRONMENT_ERROR,
                     "Toolchain / interpreter / poetry env problem.", retryable=False)
FM_PIPE = FailureMode(FailureClass.PIPE_UNAVAILABLE,
                      "Revit add-in pipe not reachable (Revit not running).",
                      retryable=True)
FM_MALFORMED = FailureMode(FailureClass.MALFORMED_INPUT,
                           "Required input artifact missing or unparseable.",
                           retryable=False)
FM_MISSING_PRE = FailureMode(FailureClass.MISSING_PREREQUISITE,
                             "A declared prerequisite was not met.", retryable=False)

# Common evidence for commands whose only output is console + exit code.
EV_CONSOLE = ("stdout/stderr: human-readable output", "exit code: 0 = success")


# ---------------------------------------------------------------------------
# Catalog — covers all built-in axiom CLI commands + dev toolchain (PR #22)
# ---------------------------------------------------------------------------

_CATALOG: dict[str, CommandSpec] = {}


def _register(spec: CommandSpec) -> None:
    if spec.name in _CATALOG:
        raise ValueError(f"Duplicate command name in catalog: {spec.name}")
    _CATALOG[spec.name] = spec


_register(
    CommandSpec(
        name="pytest",
        command="poetry run pytest",
        description="Run the full Python test suite via Poetry.",
        classification=CommandClass.TEST,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            "stdout/stderr: pass/fail summary and tracebacks",
            "exit code: 0 = all tests passed",
        ),
        timeout_seconds=1800,
        failure_modes=(
            FailureMode(FailureClass.TEST_FAILURE,
                        "One or more tests failed (non-zero exit).", retryable=False),
            FailureMode(FailureClass.ENVIRONMENT_ERROR,
                        "Collection/import error before tests ran.", retryable=False),
            FailureMode(FailureClass.TIMEOUT,
                        "Suite exceeded the timeout.", retryable=True),
        ),
    )
)

_register(
    CommandSpec(
        name="ruff",
        command="poetry run ruff check .",
        description="Run the ruff linter over the workspace (no autofix).",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            "stdout: lint findings (file:line:rule)",
            "exit code: 0 = clean",
        ),
        timeout_seconds=300,
        failure_modes=(
            FailureMode(FailureClass.LINT_VIOLATION,
                        "Linter reported violations (non-zero exit).", retryable=False),
            FailureMode(FailureClass.ENVIRONMENT_ERROR,
                        "ruff not installed / poetry env missing.", retryable=False),
        ),
        notes="Read-only check: `ruff check .` does not modify files (no --fix).",
    )
)

_register(
    CommandSpec(
        name="dotnet-build",
        command="dotnet build src/axiom_revit/Axiom.Revit.2027.sln -c Release -p:Platform=x64",
        description="Build the Revit 2027 add-in solution (Release|x64). Does not deploy.",
        classification=CommandClass.BUILD,
        safety_level=SafetyLevel.GUARDED,
        prerequisites=(Prerequisite.DOTNET_SDK,),
        evidence_outputs=(
            "stdout: MSBuild log (warnings/errors)",
            "exit code: 0 = build succeeded",
            "bin/Release output assemblies under src/axiom_revit/**",
        ),
        timeout_seconds=1200,
        failure_modes=(
            FailureMode(FailureClass.BUILD_ERROR,
                        "Compilation errors (non-zero exit).", retryable=False),
            FailureMode(FailureClass.ENVIRONMENT_ERROR,
                        "Missing .NET SDK / Revit API references.", retryable=False),
            FailureMode(FailureClass.TIMEOUT,
                        "Build exceeded the timeout.", retryable=True),
        ),
        notes="Windows runner only. Preserves the 2024 baseline; builds the 2027 adapter.",
    )
)

_register(
    CommandSpec(
        name="bridge-execute",
        command="axiom bridge-execute --capability InventoryModel",
        description=(
            "Send ONE capability request to a running Revit add-in over the "
            "named-pipe bridge and record durable evidence. Default args are "
            "safe summary mode ({\"SummaryOnly\": true})."
        ),
        classification=CommandClass.LIVE_REVIT_REQUIRED,
        safety_level=SafetyLevel.GUARDED,
        prerequisites=(
            Prerequisite.POETRY_ENV,
            Prerequisite.REVIT_RUNNING,
            Prerequisite.MODEL_OPEN,
        ),
        evidence_outputs=(
            "artifacts/validation_runs/<run_id>/request.json",
            "artifacts/validation_runs/<run_id>/response.json",
            "artifacts/validation_runs/<run_id>/summary + pass/fail record",
        ),
        timeout_seconds=600,
        failure_modes=(
            FailureMode(FailureClass.PIPE_UNAVAILABLE,
                        "Revit add-in pipe not reachable (Revit not running).",
                        retryable=True),
            FailureMode(FailureClass.NONZERO_EXIT,
                        "Capability returned an error response.", retryable=False),
            FailureMode(FailureClass.TIMEOUT,
                        "No response within the timeout.", retryable=True),
        ),
        notes="`--simulate` uses the mock path (no Revit) for off-Windows driver/evidence proof.",
    )
)

_register(
    CommandSpec(
        name="validation-run",
        command="axiom validation-run --scenario <id> --phase <pre|scan|all>",
        description=(
            "Validation Automation Loop v0 — automate everything around the "
            "single live-Revit human step and classify the result."
        ),
        classification=CommandClass.TEST,
        safety_level=SafetyLevel.GUARDED,
        prerequisites=(
            Prerequisite.POETRY_ENV,
            Prerequisite.BRANCH_CHECKED_OUT,
        ),
        evidence_outputs=(
            "artifacts/validation_runs/<run_id>/ (pre/scan evidence)",
            "classification result (pass/fail/retry) in the run bundle",
        ),
        timeout_seconds=1800,
        failure_modes=(
            FailureMode(FailureClass.TEST_FAILURE,
                        "Pre-phase tests/ruff failed.", retryable=False),
            FailureMode(FailureClass.MISSING_EVIDENCE,
                        "Scan phase found no live-Revit evidence to evaluate.",
                        retryable=True),
            FailureMode(FailureClass.TIMEOUT,
                        "A phase exceeded the timeout.", retryable=True),
        ),
        notes="The live Revit step is performed manually between the pre and scan phases.",
    )
)

_register(
    CommandSpec(
        name="inventory-import",
        command="axiom inventory-import --latest",
        description=(
            "Import a Revit InventoryModel JSON export into the Python artifact "
            "pipeline (elements + enriched parameters)."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(
            Prerequisite.POETRY_ENV,
            Prerequisite.INVENTORY_EXPORT_AVAILABLE,
        ),
        evidence_outputs=(
            "artifacts/model_inventory_runs/<run_id>/elements.jsonl + elements.parquet",
            "artifacts/model_inventory_runs/<run_id>/parameters.parquet|csv|jsonl",
            "artifacts/model_inventory_runs/<run_id>/run_metadata.json + summary.md",
        ),
        timeout_seconds=600,
        failure_modes=(
            FailureMode(FailureClass.MISSING_PREREQUISITE,
                        "No inventory export found to import.", retryable=False),
            FailureMode(FailureClass.MALFORMED_INPUT,
                        "Export JSON missing/unparseable.", retryable=False),
            FailureMode(FailureClass.NONZERO_EXIT,
                        "Import failed for another reason.", retryable=False),
        ),
        notes="Produces artifacts only; does not mutate the Revit model or repo source.",
    )
)

_register(
    CommandSpec(
        name="discovery-run",
        command=(
            "axiom discovery-run --adapter revit "
            "--inventory-export-path <run_folder> --db-path discovery.db"
        ),
        description=(
            "Discovery Harness v1 — interpret an InventoryModel export into the "
            "ProductObject/ProductProperty registries, candidate capabilities, "
            "and a reviewable report bundle. Read-only discovery."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(
            Prerequisite.POETRY_ENV,
            Prerequisite.INVENTORY_EXPORT_AVAILABLE,
            Prerequisite.DB_PATH_AVAILABLE,
        ),
        evidence_outputs=(
            "artifacts/discovery_runs/<run_id>/summary.json + summary.md",
            "artifacts/discovery_runs/<run_id>/categories.csv + parameters.csv",
            "artifacts/discovery_runs/<run_id>/candidate_capabilities.csv",
            "artifacts/discovery_runs/<run_id>/discovery_evidence.jsonl",
        ),
        timeout_seconds=600,
        failure_modes=(
            FailureMode(FailureClass.MALFORMED_INPUT,
                        "Export folder/file missing or unsupported format.",
                        retryable=False),
            FailureMode(FailureClass.INCOMPLETE_DISCOVERY,
                        "Ran but discovered 0 parameters (category-only).",
                        retryable=False),
            FailureMode(FailureClass.NONZERO_EXIT,
                        "Discovery failed for another reason.", retryable=False),
        ),
        notes="--db-path is optional; omit to skip registry persistence (DB_PATH_AVAILABLE then N/A).",
    )
)

# --- Live-Revit / model-mutating capability commands -----------------------

_register(
    CommandSpec(
        name="inventory-model",
        command="axiom inventory-model",
        description=(
            "Run a read-only model inventory (InventoryModel capability) by "
            "sending the InventoryModel prompt to a running Revit add-in. "
            "Summary mode by default — counts/categories only, no parameter dump."
        ),
        classification=CommandClass.LIVE_REVIT_REQUIRED,
        safety_level=SafetyLevel.GUARDED,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.REVIT_RUNNING,
                       Prerequisite.MODEL_OPEN),
        evidence_outputs=(
            "artifacts/model_inventory_runs/<run_id>/elements.* + parameters.*",
            "artifacts/model_inventory_runs/<run_id>/summary.md",
        ),
        timeout_seconds=900,
        failure_modes=(FM_PIPE, FM_NONZERO, FM_TIMEOUT),
        notes="Read-only scan. Full/whole-model value extraction is blocked/guarded "
              "(crashed Revit 2027); use category/level/sample modes for parameters.",
    )
)

_register(
    CommandSpec(
        name="prompt",
        command="axiom prompt \"<natural language>\"",
        description=(
            "Resolve and EXECUTE a natural-language prompt (e.g. CreateGrids/"
            "CreateLevels) in Revit. Executes live by default; --simulate "
            "validates only."
        ),
        classification=CommandClass.MUTATION,
        safety_level=SafetyLevel.HIGH_RISK,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.REVIT_RUNNING,
                       Prerequisite.MODEL_OPEN),
        evidence_outputs=(
            "execution plan + result status (console)",
            "capability execution log / job + plan records",
        ),
        timeout_seconds=600,
        failure_modes=(
            FM_PIPE,
            FailureMode(FailureClass.NONZERO_EXIT,
                        "Prompt could not be resolved or execution failed.",
                        retryable=False),
            FM_TIMEOUT,
        ),
        notes="DEFAULT IS LIVE EXECUTION and can mutate the model. Use --simulate "
              "to validate only (safe). Prefer simulate before any live apply.",
    )
)

_register(
    CommandSpec(
        name="execute",
        command="axiom execute <plan_id>",
        description=(
            "Execute a previously generated plan. Simulation by default; "
            "--production executes against the live model."
        ),
        classification=CommandClass.MUTATION,
        safety_level=SafetyLevel.HIGH_RISK,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.REVIT_RUNNING,
                       Prerequisite.MODEL_OPEN),
        evidence_outputs=(
            "execution result + per-step status (console)",
            "execution log / updated job + plan records",
        ),
        timeout_seconds=600,
        failure_modes=(FM_PIPE, FM_NONZERO, FM_TIMEOUT),
        notes="Simulation by default (safe). --production mutates the live model — "
              "high risk; gate explicitly.",
    )
)

_register(
    CommandSpec(
        name="set-parameter-value",
        command="axiom set-parameter-value \"<edit prompt>\"",
        description=(
            "Preview or apply a constrained text parameter edit (v0: text/"
            "instance/writable/category-constrained, max 5 elements). Preview "
            "by default; apply mutates the model."
        ),
        classification=CommandClass.MUTATION,
        safety_level=SafetyLevel.HIGH_RISK,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.REVIT_RUNNING,
                       Prerequisite.MODEL_OPEN),
        evidence_outputs=(
            "preview/apply summary (before/after values, console)",
            "SetParameterValue evidence bundle under artifacts/",
        ),
        timeout_seconds=600,
        failure_modes=(FM_PIPE, FM_NONZERO, FM_TIMEOUT),
        notes="Preview by default (safe). Apply mutates the model — preview must be "
              "verified first; apply on a disposable/sample model before production.",
    )
)

# --- Test harnesses --------------------------------------------------------

_register(
    CommandSpec(
        name="test-grids",
        command="axiom test-grids --mode simulate",
        description="Run the CreateGrids deterministic test harness (simulate by default).",
        classification=CommandClass.TEST,
        safety_level=SafetyLevel.GUARDED,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            "artifacts/<run_id>/ test results (+ optional CSV/XLSX/MD with --review-output)",
            "exit code: 0 = all cases passed",
        ),
        timeout_seconds=600,
        failure_modes=(
            FailureMode(FailureClass.TEST_FAILURE,
                        "One or more grid test cases failed.", retryable=False),
            FM_PIPE, FM_TIMEOUT,
        ),
        notes="--mode real requires a Revit pipe and CREATES grids in the model "
              "(treat real mode as live-Revit/mutation).",
    )
)

_register(
    CommandSpec(
        name="test-levels",
        command="axiom test-levels --mode simulate",
        description="Run the CreateLevels deterministic test harness (simulate by default).",
        classification=CommandClass.TEST,
        safety_level=SafetyLevel.GUARDED,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            "artifacts/<run_id>/ test results (+ optional CSV/XLSX/MD with --review-output)",
            "exit code: 0 = all cases passed",
        ),
        timeout_seconds=600,
        failure_modes=(
            FailureMode(FailureClass.TEST_FAILURE,
                        "One or more level test cases failed.", retryable=False),
            FM_PIPE, FM_TIMEOUT,
        ),
        notes="--mode real requires a Revit pipe and CREATES levels in the model "
              "(treat real mode as live-Revit/mutation).",
    )
)

# --- Inventory pipeline (artifact-producing, read-only) --------------------

_register(
    CommandSpec(
        name="inventory-export",
        command="axiom inventory-export --file <export.json> --chunk-by discipline",
        description="Import a Revit inventory JSON and extract it by discipline chunks.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.INVENTORY_EXPORT_AVAILABLE),
        evidence_outputs=(
            "artifacts/model_inventory_runs/<run_id>/<discipline>/ CSV + XLSX + Markdown",
        ),
        timeout_seconds=600,
        failure_modes=(FM_MALFORMED, FM_NONZERO),
        notes="Produces artifacts only; does not mutate the model.",
    )
)

_register(
    CommandSpec(
        name="inventory-combine",
        command="axiom inventory-combine --batch-dir <dir>",
        description=(
            "Combine multiple batch inventory JSON files into a single inventory "
            "(optionally run discipline extraction on the result)."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.INVENTORY_EXPORT_AVAILABLE),
        evidence_outputs=(
            "artifacts/model_inventory_runs/<run_id>/ combined inventory + review files",
        ),
        timeout_seconds=600,
        failure_modes=(FM_MALFORMED, FM_NONZERO),
        notes="Reads batch_*.json (or a manifest); produces artifacts only.",
    )
)

_register(
    CommandSpec(
        name="inventory-import-batch",
        command="axiom inventory-import-batch --dir <dir>",
        description=(
            "Batch-import all matching inventory JSON exports from a directory or "
            "manifest (optionally filtered by scan_mode)."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.INVENTORY_EXPORT_AVAILABLE),
        evidence_outputs=(
            "artifacts/model_inventory_runs/<run_id>/ per imported export",
        ),
        timeout_seconds=900,
        failure_modes=(FM_MALFORMED, FM_NONZERO),
        notes="Produces artifacts only; does not mutate the model.",
    )
)

_register(
    CommandSpec(
        name="inventory-plan",
        command="axiom inventory-plan --file <summary.json>",
        description=(
            "Build an adaptive extraction plan from a summary-mode inventory "
            "export (groups small categories, isolates/chunks large ones)."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.INVENTORY_EXPORT_AVAILABLE),
        evidence_outputs=(
            "inventory_extraction_plan.json + .md + .xlsx under the output dir",
        ),
        timeout_seconds=300,
        failure_modes=(FM_MALFORMED, FM_NONZERO),
        notes="Planning only; does not extract or mutate anything.",
    )
)

_register(
    CommandSpec(
        name="inventory-plan-status",
        command="axiom inventory-plan-status",
        description="Show status of the latest parameter schema plan and handoff paths.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only status inspector.",
    )
)

_register(
    CommandSpec(
        name="inventory-summary",
        command="axiom inventory-summary --latest",
        description="Inspect and summarize an InventoryModel run from Parquet artifacts.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.INVENTORY_EXPORT_AVAILABLE),
        evidence_outputs=("inventory summary tables (console)",) + EV_CONSOLE,
        timeout_seconds=120,
        failure_modes=(FM_MISSING_PRE, FM_NONZERO),
        notes="Read-only. Summary-mode runs with zero parameters are valid (not an error).",
    )
)

_register(
    CommandSpec(
        name="parameter-registry-build",
        command="axiom parameter-registry-build --from-inventory <dir>",
        description=(
            "Build a property registry candidate from multiple category parameter "
            "schema runs (dedup + coverage summary)."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.INVENTORY_EXPORT_AVAILABLE),
        evidence_outputs=(
            "registry candidate + coverage summary under the output dir",
        ),
        timeout_seconds=600,
        failure_modes=(FM_MALFORMED, FM_NONZERO),
        notes="Produces a registry candidate artifact; read-only over inventory runs.",
    )
)

# --- Job / plan orchestration (internal state, no model mutation) ----------

_register(
    CommandSpec(
        name="submit",
        command="axiom submit <excel_file>",
        description="Submit a new job from an Excel file (--dry-run validates only).",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("created job id + parsed job summary (console)",) + EV_CONSOLE,
        timeout_seconds=120,
        failure_modes=(FM_MALFORMED, FM_NONZERO),
        notes="Creates an internal job record; does not touch the Revit model. "
              "Requires a valid Excel input file.",
    )
)

_register(
    CommandSpec(
        name="plan",
        command="axiom plan <job_id>",
        description="Generate an execution plan for a job (--approve auto-approves).",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("generated plan id + plan steps (console)",) + EV_CONSOLE,
        timeout_seconds=120,
        failure_modes=(FM_MISSING_PRE, FM_NONZERO),
        notes="Planning only — generates/approves a plan record; no execution, no "
              "model mutation. Execute the plan with `execute`.",
    )
)

_register(
    CommandSpec(
        name="jobs",
        command="axiom jobs",
        description="List all jobs (optionally filtered by status).",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("jobs table (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only query over the job store.",
    )
)

_register(
    CommandSpec(
        name="plans",
        command="axiom plans",
        description="List all plans.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("plans table (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only query over the plan store.",
    )
)

_register(
    CommandSpec(
        name="stats",
        command="axiom stats",
        description="Show storage statistics.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("storage statistics (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only.",
    )
)

_register(
    CommandSpec(
        name="tools",
        command="axiom tools",
        description="List available tools in the MCP layer.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("MCP tools list (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only.",
    )
)

_register(
    CommandSpec(
        name="demo",
        command="axiom demo <excel_file>",
        description="Run a complete demo: submit, plan, simulate, and report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("end-to-end demo report (console)",) + EV_CONSOLE,
        timeout_seconds=600,
        failure_modes=(FM_MALFORMED, FM_NONZERO),
        notes="Simulation only (no live Revit, no production execution). Creates "
              "internal job/plan records; requires a valid Excel input file.",
    )
)

# --- Evidence / snapshots --------------------------------------------------

_register(
    CommandSpec(
        name="pr-snapshot",
        command="axiom pr-snapshot --pr <n> --title <t> --branch <b> --status <s>",
        description=(
            "Capture a durable PR review/evidence snapshot as repo-native "
            "artifacts (JSON + Markdown). No GitHub API dependency."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            "artifacts/pr_reviews/pr_NNNN/review_snapshot.json + .md",
        ),
        timeout_seconds=120,
        failure_modes=(FM_MALFORMED, FM_NONZERO),
        notes="Writes snapshot artifacts under artifacts/pr_reviews/; no model mutation.",
    )
)

_register(
    CommandSpec(
        name="evidence-update",
        command="axiom evidence-update --from-pr-snapshot <dir>",
        description=(
            "Generate proposed ledger entries from a PR snapshot. Prints + saves "
            "to the snapshot dir by default; --apply appends to ledger files."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.GUARDED,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            "proposed ledger Markdown blocks (saved to the snapshot dir)",
        ),
        timeout_seconds=120,
        failure_modes=(FM_MALFORMED, FM_NONZERO),
        notes="Default is read-only (writes to the snapshot dir). --apply MUTATES "
              "docs/logs ledger files — treat that form as a docs mutation.",
    )
)

# --- Meta-executor + governance inspector ----------------------------------

_register(
    CommandSpec(
        name="local-runner",
        command="axiom local-runner --task <task.json>",
        description=(
            "Execute an allowlisted local action from a task.json (restricted "
            "harness — only named allowlisted actions, no arbitrary shell)."
        ),
        classification=CommandClass.MUTATION,
        safety_level=SafetyLevel.HIGH_RISK,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.WORKSPACE_CLEAN),
        evidence_outputs=(
            "artifacts/<run_id>/ captured stdout/stderr + result/failure summary",
        ),
        timeout_seconds=1800,
        failure_modes=(FM_MISSING_PRE, FM_NONZERO, FM_ENV, FM_TIMEOUT),
        notes="Meta-executor: effect depends on the action it runs (tests/build/"
              "deploy). Deploy actions mutate the installed Revit add-in. Bounded "
              "by the local_runner allowlist + workspace policy; classified at its "
              "worst-case (mutation) for governance.",
    )
)

_register(
    CommandSpec(
        name="runner-commands",
        command="axiom runner-commands",
        description=(
            "List/inspect this Runner Command Registry (the execution policy "
            "layer). Read-only governance inspector — executes nothing."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("command catalog table / JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Self-describing: this command is itself cataloged. Unknown commands "
              "are denied by default.",
    )
)

_register(
    CommandSpec(
        name="validation-registry",
        command="axiom validation-registry",
        description=(
            "List/inspect the Capability Validation Registry (how each capability "
            "is validated). Read-only governance inspector — executes nothing."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("validation definition table / JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Governance only: prints validation contracts. Unknown capabilities "
              "are denied by default.",
    )
)

_register(
    CommandSpec(
        name="evidence-run",
        command="axiom evidence-run --validation <name>",
        description=(
            "Validation Evidence Runner: run a safe/read-only validation and write "
            "a durable evidence bundle. Consumes the validation registry and gates "
            "the command it drives against this command registry."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("artifacts/validation_evidence/<validation>/<evr_id>/",
                           "Evidence bundle directory."),
            EvidenceOutput("artifacts/validation_evidence/<validation>/<evr_id>/pass_fail.json",
                           "Machine-readable pass/fail verdict."),
        ) + EV_CONSOLE,
        timeout_seconds=600,
        failure_modes=(FM_NONZERO, FM_TIMEOUT),
        notes="Read-only evidence generation only. Unknown validations are denied "
              "by default; mutation/high-risk validations are refused (no mutation "
              "allowance). No scheduling, promotion, learning, or model mutation.",
    )
)

_register(
    CommandSpec(
        name="capability-run",
        command="axiom capability-run --capability <name>",
        description=(
            "Capability Execution Runner: execute an explicitly allowed safe/"
            "read-only capability through the Automation Bridge and write a "
            "durable evidence bundle. Gates the command it drives against this "
            "command registry and maps the capability to its validation contract."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("artifacts/capability_runs/<capability>/<run_id>/",
                           "Evidence bundle directory."),
            EvidenceOutput("artifacts/capability_runs/<capability>/<run_id>/pass_fail.json",
                           "Machine-readable pass/fail verdict."),
        ) + EV_CONSOLE,
        timeout_seconds=900,
        failure_modes=(FM_NONZERO, FM_TIMEOUT),
        notes="Governed execution of safe/read-only capabilities only. Unknown "
              "capabilities are denied by default; mutation/high-risk capabilities "
              "(and unbounded InventoryModel scans) are refused (no mutation "
              "allowance). No SetParameterValue execution, scheduling, retry, "
              "promotion, learning, or model mutation.",
    )
)

_register(
    CommandSpec(
        name="capability-state",
        command="axiom capability-state",
        description=(
            "Capability State Registry: list/inspect durable capability lifecycle "
            "state summarized from the command/validation registries and recent "
            "evidence bundles. Read-only unless --refresh rebuilds state from "
            "those sources into SQLite."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            "capability state table / JSON (console)",
            EvidenceOutput("capability_states (SQLite table)",
                           "Persisted per-capability lifecycle state (with --refresh)."),
        ) + EV_CONSOLE,
        timeout_seconds=120,
        failure_modes=(FM_NONZERO,),
        notes="State/governance memory only: summarizes existing registries and "
              "evidence artifacts. Executes nothing; no retry, promotion, "
              "scheduling, or learning. Unknown capability lookup exits non-zero. "
              "promotion_candidate is a non-binding derived flag.",
    )
)

_register(
    CommandSpec(
        name="classify-failure",
        command="axiom classify-failure --evidence-path <path>",
        description=(
            "Failure Classification Engine: classify an evidence bundle "
            "outcome into a durable failure category, severity level, and "
            "retry decision. Works on capability-run and validation-run "
            "bundles. Writes failure_classification.json + .md without "
            "overwriting pass_fail.json."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("failure_classification.json",
                           "Machine-readable category/severity/retry decision."),
            EvidenceOutput("failure_classification.md",
                           "Human-readable classification summary."),
        ) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Classification/governance only: classify and recommend. "
              "No automatic retry execution, promotion, scheduling, or "
              "learning. Does not modify original evidence bundles.",
    )
)

_register(
    CommandSpec(
        name="promotion-check",
        command="axiom promotion-check --capability <name> | --all",
        description=(
            "Promotion Eligibility Engine: decide whether a capability is "
            "eligible to be promoted toward trusted status by summarizing the "
            "Capability State Registry, Validation Registry, Command Registry, "
            "and failure-classification artifacts. Writes optional "
            "promotion_decision.json + .md under artifacts/promotion_checks."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("promotion_decision.json",
                           "Machine-readable promotion eligibility decision(s)."),
            EvidenceOutput("promotion_decision.md",
                           "Human-readable promotion eligibility summary."),
        ) + EV_CONSOLE,
        timeout_seconds=120,
        failure_modes=(FM_NONZERO,),
        notes="Eligibility/governance only: decide and recommend. No automatic "
              "promotion, registry/state mutation, retry, scheduling, or "
              "learning. Mutation/high-risk capabilities are not eligible in "
              "v1. Unknown capability lookup exits non-zero.",
    )
)


_register(
    CommandSpec(
        name="knowledge-sources",
        command="axiom knowledge-sources [--json-output] [--name <filter>] [--refresh] [--include-disabled]",
        description=(
            "Knowledge Source Registry: list registered knowledge sources "
            "with human-readable table or machine-readable JSON output. "
            "Metadata and governance only — no retrieval, no embeddings."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Knowledge sources table/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only registry query. No model mutation, no external calls.",
    )
)


_register(
    CommandSpec(
        name="knowledge-objects",
        command="axiom knowledge-objects [--json-output] [--name <filter>] [--type <type>]",
        description=(
            "Knowledge Object Model: list registered knowledge objects "
            "with human-readable table or machine-readable JSON output. "
            "Metadata and governance only — no graph traversal, no inference."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Knowledge objects table/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only registry query. No model mutation, no external calls.",
    )
)


_register(
    CommandSpec(
        name="knowledge-relationships",
        command="axiom knowledge-relationships [--json-output] [--object-id <id>] [--type <type>]",
        description=(
            "Knowledge Relationships: list relationships between knowledge "
            "objects. Supports filtering by object ID or relationship type. "
            "Metadata and governance only — no graph traversal, no inference."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Knowledge relationships table/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only registry query. No model mutation, no external calls.",
    )
)


_register(
    CommandSpec(
        name="knowledge-provenance",
        command="axiom knowledge-provenance [--json-output] [--name <filter>] [--trust-level <level>] [--include-deprecated]",
        description=(
            "Knowledge Provenance & Trust: list provenance records with trust "
            "levels and confidence scores. Supports filtering by name or trust "
            "level. Metadata and governance only — no automatic trust updates."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Knowledge provenance table/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only registry query. No model mutation, no external calls.",
    )
)


_register(
    CommandSpec(
        name="workflows",
        command="axiom workflows [--json-output] [--name <filter>] [--include-deprecated]",
        description=(
            "Workflow Knowledge Registry: list registered workflow definitions "
            "with steps, inputs, outputs, and rules. Supports filtering by name. "
            "Metadata and governance only — no execution, no automation."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Workflow definitions table/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only registry query. No model mutation, no external calls.",
    )
)


_register(
    CommandSpec(
        name="learning-candidates",
        command="axiom learning-candidates [--json-output] [--name <filter>] [--type <type>] [--include-dismissed]",
        description=(
            "Learning Candidate Engine: list patterns identified as worth "
            "learning. Shows candidates with strength, confidence score, "
            "observation count. Does not learn or mutate registries."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Learning candidates table/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only registry query. No model mutation, no external calls.",
    )
)


_register(
    CommandSpec(
        name="knowledge-reviews",
        command="axiom knowledge-reviews [--json-output] [--name <filter>] [--decision <decision>] [--status <status>]",
        description=(
            "Knowledge Review & Approval: list review and approval records "
            "with deterministic ordering by decision priority. Supports "
            "filtering by name, decision, or status. Governance only — "
            "no autonomous approval or knowledge mutation."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Knowledge reviews table/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only registry query. No model mutation, no external calls.",
    )
)


_register(
    CommandSpec(
        name="knowledge-review-create",
        command="axiom knowledge-review-create --knowledge-id <id> --knowledge-name <name> --decision <decision> --reason <reason> [--notes <notes>] [--reviewer <reviewer>] [--json-output]",
        description=(
            "Knowledge Review & Approval: create a new review record for a "
            "knowledge item. Persists the decision to SQLite. No mutation of "
            "the knowledge item itself — governance only."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Created review confirmation/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Creates a review record in SQLite. Does not mutate any knowledge registries.",
    )
)


_register(
    CommandSpec(
        name="knowledge-graph",
        command="axiom knowledge-graph [--json-output] [--refresh] [--node <id>] [--neighbors <id>] [--depth <n>]",
        description=(
            "Knowledge Graph Foundation: navigable structure connecting knowledge "
            "objects, workflows, provenance, evidence, reviews, and candidates. "
            "Supports summary, node lookup, neighbor traversal, and refresh. "
            "Structural/navigation only — no semantic retrieval, no embeddings."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Knowledge graph summary/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=120,
        failure_modes=(FM_NONZERO,),
        notes="Read-only graph queries. --refresh rebuilds from registries (writes to SQLite but no external calls).",
    )
)


_register(
    CommandSpec(
        name="retrieve",
        command='axiom retrieve "<query>" [--json-output] [--type <type>] [--max-results <n>]',
        description=(
            "Semantic Retrieval Engine: retrieves knowledge from existing "
            "registries and the knowledge graph.  Supports exact, partial, "
            "type-filtered, and relationship-aware queries with deterministic "
            "ranking, trust/approval weighting, and explanations.  "
            "Read-only — never mutates knowledge."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Retrieval results table/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only knowledge retrieval. Queries the knowledge graph — no external calls, no mutations.",
    )
)

_register(
    CommandSpec(
        name="capability-plan",
        command='axiom capability-plan "<objective>" [--json-output] [--max-steps <n>]',
        description=(
            "Knowledge-Aware Capability Planner: generates structured plans "
            "from knowledge objects, workflows, retrieval results, and graph "
            "relationships.  Plans are read-only recommendations — they never "
            "execute capabilities or mutate knowledge."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Planning steps table/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only planning. Consumes retrieval + graph — no external calls, no mutations.",
    )
)


_register(
    CommandSpec(
        name="plan-reviews",
        command="axiom plan-reviews [--json-output] [--name <filter>] [--decision <decision>] [--status <status>] [--plan-id <id>]",
        description=(
            "Plan Review Queue: list plan review and approval records "
            "with deterministic ordering by decision priority. Supports "
            "filtering by name, decision, status, or plan ID. Governance only — "
            "no plan execution, no automatic approval."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Plan reviews table/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only registry query. No plan execution, no mutations.",
    )
)


_register(
    CommandSpec(
        name="plan-review",
        command="axiom plan-review --plan-id <id> [--json-output]",
        description=(
            "Plan Review Queue: show review details and history for a "
            "specific plan ID. Returns full decision history with "
            "latest decision summary."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Plan review details/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only review lookup. Returns exit 2 for unknown plan IDs.",
    )
)


_register(
    CommandSpec(
        name="plan-review-create",
        command="axiom plan-review-create --plan-id <id> --decision <decision> --reason <reason> [--plan-name <name>] [--notes <notes>] [--reviewer <reviewer>] [--json-output]",
        description=(
            "Plan Review Queue: create a new review record for a capability "
            "plan. Persists the decision to SQLite. No execution of the plan — "
            "governance only."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Created plan review confirmation/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Creates a plan review record in SQLite. Does not execute any plans.",
    )
)


_register(
    CommandSpec(
        name="discovery-loop",
        command="axiom discovery-loop [--source <folder>] [--simulate] [--json-output]",
        description=(
            "Controlled Discovery Loop: first end-to-end loop chaining discovery, "
            "candidate generation, state, validation, classification, and promotion "
            "checks. No automatic promotion. No mutations. Evidence always written."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Loop result/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=120,
        failure_modes=(FM_NONZERO,),
        notes="Runs controlled loop. Mutations always refused. Promotions never applied.",
    )
)


_register(
    CommandSpec(
        name="trusted-capabilities",
        command="axiom trusted-capabilities [--json-output] [--status <status>]",
        description=(
            "Trusted Capability Registry: list capabilities with their trust status. "
            "Separates eligible from trusted. No execution."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Trusted capabilities table/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only registry query. No execution, no mutations.",
    )
)


_register(
    CommandSpec(
        name="trusted-capability",
        command="axiom trusted-capability --name <name> [--json-output]",
        description=(
            "Trusted Capability Registry: show trust details for a specific capability."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Trust details/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only lookup. Returns exit 2 for unknown capabilities.",
    )
)


_register(
    CommandSpec(
        name="trusted-capability-promote",
        command="axiom trusted-capability-promote --capability <name> [--by <actor>] [--json-output]",
        description=(
            "Trusted Capability Registry: explicitly promote a capability to trusted. "
            "Refuses blocked/mutation capabilities. Refuses capabilities with failures."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Promotion result/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Explicit promotion only. Never automatic. Blocked caps always refused.",
    )
)


_register(
    CommandSpec(
        name="trusted-capability-revoke",
        command="axiom trusted-capability-revoke --capability <name> [--by <actor>] [--reason <text>] [--json-output]",
        description=(
            "Trusted Capability Registry: revoke trust from a capability."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Revocation result/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Revokes trust. History preserved. Returns exit 2 for unknown capabilities.",
    )
)


_register(
    CommandSpec(
        name="validation-requests",
        command="axiom validation-requests [--json-output] [--status <status>] [--plan-id <id>]",
        description=(
            "Validation Request Generator: list validation requests generated "
            "from approved plans. Supports filtering by status or plan ID. "
            "Governance only — no execution."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Validation requests table/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only registry query. No execution, no mutations.",
    )
)


_register(
    CommandSpec(
        name="validation-request",
        command="axiom validation-request --id <id> [--json-output]",
        description=(
            "Validation Request Generator: show details for a specific "
            "validation request including steps, blockers, and evidence requirements."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Validation request details/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only request lookup. Returns exit 2 for unknown request IDs.",
    )
)


_register(
    CommandSpec(
        name="validation-request-create",
        command="axiom validation-request-create --plan-id <id> [--plan-name <name>] [--json-output]",
        description=(
            "Validation Request Generator: generate a validation request from "
            "an approved plan. Refuses rejected plans. No execution — creates "
            "a work description only."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Created validation request confirmation/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Generates a validation request. Requires an approved plan review. No execution.",
    )
)


_register(
    CommandSpec(
        name="validation-orchestrate",
        command="axiom validation-orchestrate --request-id <id> [--simulate] [--json-output]",
        description=(
            "Controlled Validation Orchestrator: execute or simulate a "
            "validation orchestration from an approved validation request. "
            "Refuses mutation capabilities and unsafe procedures. "
            "Evidence is always written."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Orchestration result/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=120,
        failure_modes=(FM_NONZERO,),
        notes="Executes safe validations only. Mutations always refused. Evidence always written.",
    )
)


_register(
    CommandSpec(
        name="work-items",
        command="axiom work-items [--json-output] [--status <status>] [--type <type>]",
        description=(
            "Autonomous Work Item Registry: list work items. "
            "Supports filtering by status or type. No execution."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Work items table/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only registry query. No execution, no mutations.",
    )
)


_register(
    CommandSpec(
        name="work-item",
        command="axiom work-item --id <id> [--json-output]",
        description=(
            "Autonomous Work Item Registry: show details for a specific work item."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Work item details/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only lookup. Returns exit 2 for unknown item IDs.",
    )
)


_register(
    CommandSpec(
        name="work-item-create",
        command="axiom work-item-create --title <title> --type <type> [--description <text>] [--priority <level>] [--created-by <creator>] [--json-output]",
        description=(
            "Autonomous Work Item Registry: create a new work item. "
            "No code generation. No execution."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Created work item confirmation/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Creates a work item record in SQLite. No code generation. No execution.",
    )
)


_register(
    CommandSpec(
        name="work-item-update",
        command="axiom work-item-update --id <id> [--status <status>] [--title <title>] [--description <text>] [--priority <level>] [--assigned-to <assignee>] [--by <actor>] [--reason <text>] [--json-output]",
        description=(
            "Autonomous Work Item Registry: update a work item's status or fields. "
            "Status changes preserve history. No execution."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Updated work item confirmation/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Updates work item. Status changes are audited. No code generation. No execution.",
    )
)


# ---------------------------------------------------------------------------
# Codebase Inventory and Symbol Registry commands (PR #57)
# ---------------------------------------------------------------------------


_register(
    CommandSpec(
        name="code-inventory",
        command="axiom code-inventory [--refresh] [--category <category>] [--json-output]",
        description=(
            "Codebase Inventory: list or refresh the file inventory. "
            "Read-only scan — never modifies source files."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("File inventory table/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=120,
        failure_modes=(FM_NONZERO,),
        notes="Read-only repo scan. --refresh rescans all files. No code modification.",
    )
)


_register(
    CommandSpec(
        name="code-symbols",
        command="axiom code-symbols [--kind <kind>] [--file <path>] [--json-output]",
        description=(
            "Codebase Symbol Registry: list code symbols. "
            "Read-only query over persisted symbol inventory."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Symbol list table/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only symbol query. Requires code-inventory --refresh first.",
    )
)


_register(
    CommandSpec(
        name="code-symbol",
        command="axiom code-symbol --name <symbol> [--json-output]",
        description=(
            "Codebase Symbol Registry: show details for a specific symbol "
            "by name or qualified name."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Symbol details/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only symbol lookup. Returns exit 2 for unknown symbols.",
    )
)


# ---------------------------------------------------------------------------
# Implementation Plan Generator commands (PR #58)
# ---------------------------------------------------------------------------


_register(
    CommandSpec(
        name="implementation-plan",
        command="axiom implementation-plan --work-item <id> [--json-output]",
        description=(
            "Implementation Plan Generator: generate a structured implementation "
            "plan from an approved work item. Read-only — never modifies files."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Implementation plan table/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=120,
        failure_modes=(FM_NONZERO,),
        notes="Read-only plan generation. Requires approved work item + code inventory.",
    )
)


# ---------------------------------------------------------------------------
# Patch Proposal commands (PR #59)
# ---------------------------------------------------------------------------


_register(
    CommandSpec(
        name="patch-proposal-create",
        command="axiom patch-proposal-create --plan-id <id> [--json-output]",
        description=(
            "Create a patch proposal from an implementation plan. "
            "Read-only — never edits files or runs git."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Patch proposal summary/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Creates a durable patch record. Requires existing implementation plan.",
    )
)

_register(
    CommandSpec(
        name="patch-proposals",
        command="axiom patch-proposals [--status <status>] [--json-output]",
        description=(
            "List patch proposals, optionally filtered by status. "
            "Read-only governance view."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Patch proposals table/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only listing. No file modifications.",
    )
)

_register(
    CommandSpec(
        name="patch-proposal",
        command="axiom patch-proposal --id <id> [--json-output]",
        description=(
            "Show details for a specific patch proposal including "
            "file changes, test commands, risks, and evidence requirements."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Patch proposal details/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only detail view. Returns exit 2 for unknown proposals.",
    )
)


# ---------------------------------------------------------------------------
# Patch Review commands (PR #60)
# ---------------------------------------------------------------------------


_register(
    CommandSpec(
        name="patch-review-create",
        command="axiom patch-review-create --proposal-id <id> --decision <decision> [--reason <text>] [--reviewer <name>] [--json-output]",
        description=(
            "Create a review for a patch proposal. "
            "Read-only — never edits files or runs git."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Review confirmation/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Creates a review record. Syncs proposal status on approve/reject.",
    )
)

_register(
    CommandSpec(
        name="patch-reviews",
        command="axiom patch-reviews [--proposal-id <id>] [--decision <decision>] [--json-output]",
        description=(
            "List patch reviews, optionally filtered by proposal or decision. "
            "Read-only governance view."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Patch reviews table/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only listing. No file modifications.",
    )
)

_register(
    CommandSpec(
        name="patch-review",
        command="axiom patch-review --proposal-id <id> [--json-output]",
        description=(
            "Show the latest review and full history for a patch proposal."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Review details + history/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only detail view. Returns exit 2 for unknown proposals.",
    )
)


# ---------------------------------------------------------------------------
# Patch Application commands (PR #61)
# ---------------------------------------------------------------------------


_register(
    CommandSpec(
        name="patch-apply",
        command="axiom patch-apply --proposal-id <id> [--simulate] [--json-output]",
        description=(
            "Apply an approved patch proposal. Refuses rejected, unknown, "
            "deprecated, superseded, and unapproved proposals. "
            "Writes evidence to artifacts/patch_runs/<run_id>/."
        ),
        classification=CommandClass.MUTATION,
        safety_level=SafetyLevel.HIGH_RISK,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=(
            "patch_request.json",
            "patch_result.json",
            "patch_summary.md",
            "pass_fail.json",
            "applied_changes/",
            "rollback_info/",
        ) + EV_CONSOLE,
        timeout_seconds=120,
        failure_modes=(FM_NONZERO,),
        notes=(
            "First MUTATION command in Axiom. Modifies source files. "
            "Simulate mode (--simulate) performs all steps without writing. "
            "Requires explicit proposal approval via patch-review-create."
        ),
    )
)


# ---------------------------------------------------------------------------
# Code Validation commands (PR #62)
# ---------------------------------------------------------------------------


_register(
    CommandSpec(
        name="code-validate",
        command="axiom code-validate --patch-run-id <id> [--simulate] [--json-output]",
        description=(
            "Validate a patch application run. Runs targeted tests, full pytest, "
            "ruff, and placeholder stages. Refuses unknown or unsuccessful patch runs. "
            "Writes evidence to artifacts/code_validation_runs/<run_id>/."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=(
            "validation_request.json",
            "validation_result.json",
            "validation_summary.md",
            "pass_fail.json",
            "test_outputs/",
            "ruff_output/",
            "walkthroughs/",
        ) + EV_CONSOLE,
        timeout_seconds=300,
        failure_modes=(FM_NONZERO,),
        notes=(
            "Validates patch application results. Executes only allowlisted "
            "commands (pytest, ruff). Simulate mode writes evidence without "
            "executing commands. No git operations, no network dependency."
        ),
    )
)

_register(
    CommandSpec(
        name="code-validation-runs",
        command="axiom code-validation-runs [--json-output]",
        description="List all code validation runs from evidence artifacts.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Validation run listing (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only listing of validation runs.",
    )
)

_register(
    CommandSpec(
        name="code-validation-run",
        command="axiom code-validation-run --run-id <id> [--json-output]",
        description="Show details of a specific code validation run.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Validation run details/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only detail view. Returns exit 2 for unknown run IDs.",
    )
)


# ---------------------------------------------------------------------------
# PR Draft Generator commands (PR #63)
# ---------------------------------------------------------------------------


_register(
    CommandSpec(
        name="pr-draft",
        command="axiom pr-draft --work-item <id> | --validation-run-id <id> [--json-output]",
        description=(
            "Generate a PR draft from a work item or validation run. Produces "
            "commit title, extended description, validation section, strategic "
            "significance, and evidence bundles. No GitHub API, no PR creation, "
            "no merge behavior."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=(
            "pr_request.json",
            "pr_result.json",
            "pr_summary.md",
            "pass_fail.json",
        ) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes=(
            "Generates PR draft artifacts from validation evidence. "
            "No GitHub API, no PR creation, no merge, no network dependency, "
            "no Git operations."
        ),
    )
)

_register(
    CommandSpec(
        name="pr-drafts",
        command="axiom pr-drafts [--json-output]",
        description="List all PR drafts from artifact directories.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("PR draft listing (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only listing of PR drafts.",
    )
)

_register(
    CommandSpec(
        name="pr-draft-show",
        command="axiom pr-draft-show --draft-id <id> [--json-output]",
        description="Show details of a specific PR draft.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("PR draft details/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only detail view. Returns exit 2 for unknown draft IDs.",
    )
)


# ---------------------------------------------------------------------------
# Review Finding Ingestion commands (PR #64)
# ---------------------------------------------------------------------------


_register(
    CommandSpec(
        name="review-findings",
        command="axiom review-findings [--category <cat>] [--severity <sev>] [--status <status>] [--pattern <kind>] [--json-output]",
        description="List review findings with optional filters.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Review findings listing (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only listing of review findings.",
    )
)

_register(
    CommandSpec(
        name="review-finding",
        command="axiom review-finding --id <id> [--json-output]",
        description="Show details of a specific review finding.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Review finding details/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only detail view. Returns exit 2 for unknown finding IDs.",
    )
)

_register(
    CommandSpec(
        name="review-finding-ingest",
        command="axiom review-finding-ingest [--draft-id <id>] [--source-dir <dir>] [--json-output]",
        description=(
            "Ingest review findings from evidence bundles. Scans PR draft "
            "artifacts and validation runs for findings. No automatic "
            "repair, no code modification."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=(
            "review_request.json",
            "review_result.json",
            "review_summary.md",
            "pass_fail.json",
        ) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes=(
            "Ingests findings from evidence bundles. No automatic repair, "
            "no code modification, no GitHub API, no network dependency."
        ),
    )
)

_register(
    CommandSpec(
        name="review-finding-create",
        command="axiom review-finding-create --title <title> [--category <cat>] [--severity <sev>] [--source-pr <pr>] [--source-file <file>] [--draft-id <id>] [--json-output]",
        description="Create a new review finding manually.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Review finding details/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Creates a finding record in SQLite. No code modification.",
    )
)

_register(
    CommandSpec(
        name="review-finding-update",
        command="axiom review-finding-update --id <id> [--status <status>] [--resolution <text>] [--json-output]",
        description="Update a review finding's status or resolution.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Review finding details/JSON (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Updates finding status/resolution. No code modification.",
    )
)

_register(
    CommandSpec(
        name="review-patterns",
        command="axiom review-patterns [--kind <kind>] [--json-output]",
        description="List detected review finding patterns.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Review patterns listing (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only listing of detected review patterns.",
    )
)

# ---------------------------------------------------------------------------
# Self-Improvement Loop v1 (PR #65)
# ---------------------------------------------------------------------------

_register(
    CommandSpec(
        name="self-improvement",
        command="axiom self-improvement [--json-output]",
        description=(
            "Run the self-improvement analysis loop. Studies engineering "
            "history from review findings and generates improvement "
            "candidates. No automatic code changes, no self-modification."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=(
            EvidenceOutput("improvement_request.json", required=True),
            EvidenceOutput("improvement_result.json", required=True),
            EvidenceOutput("improvement_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ) + EV_CONSOLE,
        timeout_seconds=120,
        failure_modes=(FM_NONZERO,),
        notes=(
            "Analyzes review findings for patterns, generates improvement "
            "candidates. No code changes, no patches, no GitHub API, "
            "no network dependency."
        ),
    )
)

_register(
    CommandSpec(
        name="improvement-candidates",
        command=(
            "axiom improvement-candidates [--category <cat>] "
            "[--priority <pri>] [--status <status>] [--json-output]"
        ),
        description="List improvement candidates generated from analysis.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Improvement candidates listing (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only listing of improvement candidates with filters.",
    )
)

_register(
    CommandSpec(
        name="improvement-candidate",
        command="axiom improvement-candidate --id <id> [--json-output]",
        description=(
            "Show details of a specific improvement candidate. "
            "Exit 2 if not found."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Improvement candidate detail (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only detail view of a single improvement candidate.",
    )
)

_register(
    CommandSpec(
        name="improvement-patterns",
        command="axiom improvement-patterns [--json-output]",
        description="List detected improvement patterns from analysis.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=("Improvement patterns listing (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only listing of detected improvement patterns.",
    )
)

# ---------------------------------------------------------------------------
# Test Selection Engine v1 (PR #66)
# ---------------------------------------------------------------------------

_register(
    CommandSpec(
        name="test-selection",
        command=(
            "axiom test-selection [--changed-files <f>] [--work-item <id>] "
            "[--plan-id <id>] [--proposal-id <id>] [--full-suite] [--json-output]"
        ),
        description=(
            "Select targeted tests based on changed files, work items, "
            "implementation plans, or patch proposals. No test execution."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=(
            EvidenceOutput("selection_request.json", required=True),
            EvidenceOutput("selection_result.json", required=True),
            EvidenceOutput("selection_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes=(
            "Deterministic test selection. No test execution, no code "
            "modification, no GitHub API, no network dependency."
        ),
    )
)

_register(
    CommandSpec(
        name="test-selection-files",
        command="axiom test-selection-files <files...> [--json-output]",
        description=(
            "Select tests from a list of changed files. "
            "Convenience command for quick file-based selection."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=("Test selection output (console)",) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only test selection from changed file paths.",
    )
)


# ---------------------------------------------------------------------------
# Regression Test Generator v1 (PR #67)
# ---------------------------------------------------------------------------

_register(
    CommandSpec(
        name="regression-test-generate",
        command="axiom regression-test-generate [--json-output]",
        description=(
            "Generate regression test candidates from review findings. "
            "Advisory-only — does not modify test files."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=(
            EvidenceOutput("regression_request.json", required=True),
            EvidenceOutput("regression_result.json", required=True),
            EvidenceOutput("regression_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ) + EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes=(
            "Reads review findings from DB, generates test recommendations. "
            "No test file modification, no code generation, no network."
        ),
    )
)

_register(
    CommandSpec(
        name="regression-test-create",
        command=(
            "axiom regression-test-create --title <t> "
            "--failure-origin <origin> [--bug-class <c>] "
            "[--target-file <f>] [--finding-id <id>] "
            "[--work-item-id <id>] [--json-output]"
        ),
        description=(
            "Create a single regression test candidate from explicit input."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Creates and persists one regression test candidate.",
    )
)

_register(
    CommandSpec(
        name="regression-test-candidates",
        command=(
            "axiom regression-test-candidates [--bug-class <c>] "
            "[--status <s>] [--priority <p>] [--json-output]"
        ),
        description="List regression test candidates with optional filters.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only listing of regression test candidates.",
    )
)

_register(
    CommandSpec(
        name="regression-test-candidate",
        command=(
            "axiom regression-test-candidate --id <id> [--json-output]"
        ),
        description="Show a single regression test candidate by ID.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only retrieval of a single regression test candidate.",
    )
)

_register(
    CommandSpec(
        name="regression-test-update",
        command=(
            "axiom regression-test-update --id <id> --status <s> "
            "[--json-output]"
        ),
        description="Update a regression test candidate status.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Updates candidate status (proposed/accepted/rejected/etc).",
    )
)

_register(
    CommandSpec(
        name="regression-test-patterns",
        command="axiom regression-test-patterns [--json-output]",
        description="List detected bug patterns from regression analysis.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=EV_CONSOLE,
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only listing of detected bug patterns.",
    )
)


# -- PR #68: Patch Impact Analyzer v1 commands ---------------------------------

_register(
    CommandSpec(
        name="impact-analyze",
        command="axiom impact-analyze --proposal-id <id> [--files <f>] [--json-output]",
        description="Analyze impact of a patch proposal or file set before application.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=(
            EvidenceOutput("impact_request.json", required=True),
            EvidenceOutput("impact_result.json", required=True),
            EvidenceOutput("impact_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=120,
        failure_modes=(FM_NONZERO,),
        notes="Deterministic impact analysis for proposed changes.",
    )
)

_register(
    CommandSpec(
        name="impact-analyze-files",
        command="axiom impact-analyze-files <file1> <file2> ... [--json-output]",
        description="Analyze impact of specific changed files.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=(
            EvidenceOutput("impact_request.json", required=True),
            EvidenceOutput("impact_result.json", required=True),
            EvidenceOutput("impact_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=120,
        failure_modes=(FM_NONZERO,),
        notes="Positional-arg variant for analyzing file lists.",
    )
)


# ---------------------------------------------------------------------------
# Coding Session Orchestrator v1 (PR #71)
# ---------------------------------------------------------------------------

_register(
    CommandSpec(
        name="orchestration-create",
        command=(
            "axiom orchestration-create --session-id <id> "
            "[--title <t>] [--json-output]"
        ),
        description="Create a new coding session orchestration plan.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=(
            EvidenceOutput("orchestration_request.json", required=True),
            EvidenceOutput("orchestration_result.json", required=True),
            EvidenceOutput("orchestration_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Creates a deterministic orchestration plan with evidence.",
    )
)

_register(
    CommandSpec(
        name="orchestrations",
        command="axiom orchestrations [--status <s>] [--json-output]",
        description="List all orchestration plans.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=EV_CONSOLE,
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Read-only listing of orchestration plans.",
    )
)

_register(
    CommandSpec(
        name="orchestration",
        command="axiom orchestration --plan-id <id> [--json-output]",
        description="Show a single orchestration plan by ID.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=(
            EvidenceOutput("orchestration_result.json", required=True),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Read-only orchestration detail.",
    )
)

_register(
    CommandSpec(
        name="orchestration-advance",
        command=(
            "axiom orchestration-advance --plan-id <id> "
            "[--reason <r>] [--json-output]"
        ),
        description="Advance orchestration to the next stage.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=(
            EvidenceOutput("orchestration_result.json", required=True),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Deterministic stage advancement.",
    )
)

_register(
    CommandSpec(
        name="orchestration-block",
        command=(
            "axiom orchestration-block --plan-id <id> "
            "--reason <r> [--json-output]"
        ),
        description="Block the current orchestration stage.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=(
            EvidenceOutput("orchestration_result.json", required=True),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Records blocker observation and marks stage blocked.",
    )
)

_register(
    CommandSpec(
        name="orchestration-complete",
        command="axiom orchestration-complete --plan-id <id> [--json-output]",
        description="Mark an orchestration as completed.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=(
            EvidenceOutput("orchestration_request.json", required=True),
            EvidenceOutput("orchestration_result.json", required=True),
            EvidenceOutput("orchestration_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Completes session orchestration with evidence.",
    )
)

_register(
    CommandSpec(
        name="orchestration-summary",
        command="axiom orchestration-summary --plan-id <id> [--json-output]",
        description="Generate a summary for an orchestration plan.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=EV_CONSOLE,
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Read-only orchestration summary generation.",
    )
)


# ---------------------------------------------------------------------------
# Code Review Policy Engine v1 (PR #69)
# ---------------------------------------------------------------------------

_register(
    CommandSpec(
        name="policy-evaluate",
        command="axiom policy-evaluate --files <f1> [--files <f2>] [--json-output]",
        description="Evaluate code review policies against changed files.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("policy_request.json", required=True),
            EvidenceOutput("policy_result.json", required=True),
            EvidenceOutput("policy_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=120,
        failure_modes=(FM_NONZERO,),
        notes="Deterministic policy evaluation for proposed changes.",
    )
)

_register(
    CommandSpec(
        name="policy-evaluate-files",
        command="axiom policy-evaluate-files <file1> <file2> ... [--json-output]",
        description="Evaluate policies against specific changed files.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("policy_request.json", required=True),
            EvidenceOutput("policy_result.json", required=True),
            EvidenceOutput("policy_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=120,
        failure_modes=(FM_NONZERO,),
        notes="Positional-arg variant for policy evaluation.",
    )
)

_register(
    CommandSpec(
        name="policy-list",
        command="axiom policy-list [--json-output]",
        description="List all registered code review policies.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=EV_CONSOLE,
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Read-only listing of registered review policies.",
    )
)


# ---------------------------------------------------------------------------
# Autonomous Coding Session Registry v1 (PR #70)
# ---------------------------------------------------------------------------

_register(
    CommandSpec(
        name="coding-session-create",
        command=(
            "axiom coding-session-create --title <t> "
            "[--description <d>] [--work-item-id <id>] [--json-output]"
        ),
        description="Create a new autonomous coding session.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=(
            EvidenceOutput("session_request.json", required=True),
            EvidenceOutput("session_result.json", required=True),
            EvidenceOutput("session_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Creates a durable coding session with evidence bundle.",
    )
)

_register(
    CommandSpec(
        name="coding-sessions",
        command="axiom coding-sessions [--status <s>] [--json-output]",
        description="List all coding sessions.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=(
            EvidenceOutput("session_list.json", required=True),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Read-only listing of coding sessions.",
    )
)

_register(
    CommandSpec(
        name="coding-session",
        command="axiom coding-session --session-id <id> [--json-output]",
        description="Show a single coding session by ID.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=(
            EvidenceOutput("session_result.json", required=True),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Read-only session detail.",
    )
)

_register(
    CommandSpec(
        name="coding-session-update",
        command=(
            "axiom coding-session-update --session-id <id> "
            "--status <s> [--json-output]"
        ),
        description="Update a coding session status.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=(
            EvidenceOutput("session_result.json", required=True),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Status update for session lifecycle.",
    )
)

_register(
    CommandSpec(
        name="coding-session-add-step",
        command=(
            "axiom coding-session-add-step --session-id <id> "
            "--kind <k> --description <d> [--json-output]"
        ),
        description="Add a step to a coding session.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=(
            EvidenceOutput("session_result.json", required=True),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Append a step to session history.",
    )
)

_register(
    CommandSpec(
        name="coding-session-add-artifact",
        command=(
            "axiom coding-session-add-artifact --session-id <id> "
            "--kind <k> [--reference-id <r>] [--path <p>] "
            "[--description <d>] [--json-output]"
        ),
        description="Add an artifact to a coding session.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=(
            EvidenceOutput("session_result.json", required=True),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Append an artifact reference to session.",
    )
)

_register(
    CommandSpec(
        name="coding-session-link",
        command=(
            "axiom coding-session-link --session-id <id> "
            "--field <f> --id <linked_id> [--json-output]"
        ),
        description="Link an ID to a coding session field.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV, Prerequisite.DB_PATH_AVAILABLE),
        evidence_outputs=(
            EvidenceOutput("session_result.json", required=True),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Link work item, patch, or validation IDs to session.",
    )
)


# ---------------------------------------------------------------------------
# Session Plan Registry v1 (PR #72)
# ---------------------------------------------------------------------------

_register(
    CommandSpec(
        name="session-plan-create",
        command=(
            "axiom session-plan-create --title <t> "
            "[--session-id <id>] [--work-item-id <id>] "
            "[--rationale <r>] [--json-output]"
        ),
        description="Create a new session plan.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("session_plan_request.json", required=True),
            EvidenceOutput("session_plan_result.json", required=True),
            EvidenceOutput("session_plan.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Create durable session plan artifact.",
    )
)

_register(
    CommandSpec(
        name="session-plans",
        command="axiom session-plans [--status <s>] [--json-output]",
        description="List all session plans.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List session plans with optional status filter.",
    )
)

_register(
    CommandSpec(
        name="session-plan-show",
        command="axiom session-plan-show --plan-id <id> [--json-output]",
        description="Show a single session plan.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Inspect a session plan by ID.",
    )
)

_register(
    CommandSpec(
        name="session-plan-export",
        command="axiom session-plan-export --plan-id <id> [--json-output]",
        description="Export a session plan as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export session plan as markdown document.",
    )
)


# ---------------------------------------------------------------------------
# Session Question Registry v1 (PR #73)
# ---------------------------------------------------------------------------

_register(
    CommandSpec(
        name="question-create",
        command=(
            "axiom question-create --text <t> "
            "[--context <c>] [--priority <p>] "
            "[--plan-id <id>] [--work-item-id <id>] "
            "[--rationale <r>] [--json-output]"
        ),
        description="Create a new session question.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("question_request.json", required=True),
            EvidenceOutput("question_result.json", required=True),
            EvidenceOutput("question_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Create durable session question artifact.",
    )
)

_register(
    CommandSpec(
        name="questions",
        command="axiom questions [--status <s>] [--plan-id <id>] [--json-output]",
        description="List all session questions.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List session questions with optional status/plan filter.",
    )
)

_register(
    CommandSpec(
        name="question-show",
        command="axiom question-show --question-id <id> [--json-output]",
        description="Show a single session question.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Inspect a session question by ID.",
    )
)

_register(
    CommandSpec(
        name="question-resolve",
        command=(
            "axiom question-resolve --question-id <id> "
            "--answer <a> [--source <s>] "
            "[--rationale <r>] [--json-output]"
        ),
        description="Resolve a session question with an answer.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("question_request.json", required=True),
            EvidenceOutput("question_result.json", required=True),
            EvidenceOutput("question_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Resolve a session question with evidence bundle.",
    )
)


# ---------------------------------------------------------------------------
# Assertion Registry v1 (PR #74)
# ---------------------------------------------------------------------------

_register(
    CommandSpec(
        name="assertion-create",
        command=(
            "axiom assertion-create --type <t> --description <d> "
            "[--expected-value <v>] [--severity <s>] "
            "[--plan-id <id>] [--question-id <id>] "
            "[--work-item-id <id>] [--capability <c>] "
            "[--rationale <r>] [--json-output]"
        ),
        description="Create a new assertion.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("assertion_request.json", required=True),
            EvidenceOutput("assertion_result.json", required=True),
            EvidenceOutput("assertion_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Create durable assertion artifact.",
    )
)

_register(
    CommandSpec(
        name="assertions",
        command=(
            "axiom assertions [--status <s>] [--type <t>] "
            "[--capability <c>] [--json-output]"
        ),
        description="List all assertions.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List assertions with optional filters.",
    )
)

_register(
    CommandSpec(
        name="assertion-results",
        command="axiom assertion-results --assertion-id <id> [--json-output]",
        description="List results for an assertion.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Inspect assertion evaluation results.",
    )
)

# -- Session Report Generator v1 -------------------------------------------

_register(
    CommandSpec(
        name="session-report",
        command=(
            "axiom session-report --title <t> "
            "[--session-id <id>] [--plan-id <id>] "
            "[--work-item-id <id>] [--rationale <r>] "
            "[--json-output]"
        ),
        description="Create a new session report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("report_request.json", required=True),
            EvidenceOutput("report_result.json", required=True),
            EvidenceOutput("session_report.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Create durable session report artifact.",
    )
)

_register(
    CommandSpec(
        name="session-reports",
        command="axiom session-reports [--status <s>] [--json-output]",
        description="List all session reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List session reports with optional status filter.",
    )
)

_register(
    CommandSpec(
        name="session-report-show",
        command="axiom session-report-show <report_id> [--json-output]",
        description="Show details of a session report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Inspect a session report by ID.",
    )
)

_register(
    CommandSpec(
        name="session-report-export",
        command="axiom session-report-export <report_id> [--json-output]",
        description="Export a session report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export report to markdown.",
    )
)


# -- Session Review Registry v1 ---------------------------------------------

_register(
    CommandSpec(
        name="review-create",
        command=(
            "axiom review-create --title <t> "
            "[--source <s>] [--severity <sev>] "
            "[--pr-id <id>] [--coding-session-id <id>] "
            "[--session-report-id <id>] [--rationale <r>] "
            "[--json-output]"
        ),
        description="Create a new session review.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("review_request.json", required=True),
            EvidenceOutput("review_result.json", required=True),
            EvidenceOutput("session_review.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Create durable session review artifact.",
    )
)

_register(
    CommandSpec(
        name="review-add-finding",
        command=(
            "axiom review-add-finding <review_id> "
            "--summary <s> [--details <d>] [--severity <sev>] "
            "[--source <src>] [--file-path <p>] [--line-number <n>] "
            "[--json-output]"
        ),
        description="Add a finding to a session review.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Add finding to an existing review.",
    )
)

_register(
    CommandSpec(
        name="review-resolve",
        command=(
            "axiom review-resolve <review_id> "
            "--finding-id <fid> --status <s> "
            "[--note <n>] [--resolved-by <r>] [--commit-id <c>] "
            "[--json-output]"
        ),
        description="Resolve a finding in a session review.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Mark a finding as fixed/acknowledged/rejected/deferred.",
    )
)

_register(
    CommandSpec(
        name="reviews",
        command="axiom reviews [--status <s>] [--source <src>] [--json-output]",
        description="List all session reviews.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List session reviews with optional status/source filter.",
    )
)

_register(
    CommandSpec(
        name="review-show",
        command="axiom review-show <review_id> [--json-output]",
        description="Show details of a session review.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Inspect a session review by ID.",
    )
)

_register(
    CommandSpec(
        name="review-export",
        command="axiom review-export <review_id> [--json-output]",
        description="Export a session review as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export review to markdown.",
    )
)


# -- Escalation Framework v1 ------------------------------------------------

_register(
    CommandSpec(
        name="escalation-create",
        command=(
            "axiom escalation-create --title <t> "
            "[--description <d>] [--reason <r>] "
            "[--severity <sev>] [--category <cat>] "
            "[--source <s>] [--json-output]"
        ),
        description="Create a new escalation.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("escalation_request.json", required=True),
            EvidenceOutput("escalation_result.json", required=True),
            EvidenceOutput("escalation_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Create durable escalation artifact.",
    )
)

_register(
    CommandSpec(
        name="escalations",
        command=(
            "axiom escalations [--status <s>] "
            "[--severity <sev>] [--category <cat>] "
            "[--json-output]"
        ),
        description="List all escalations.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List escalations with optional filters.",
    )
)

_register(
    CommandSpec(
        name="escalation-show",
        command="axiom escalation-show <escalation_id> [--json-output]",
        description="Show details of an escalation.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Inspect an escalation by ID.",
    )
)

_register(
    CommandSpec(
        name="escalation-export",
        command="axiom escalation-export <escalation_id> [--json-output]",
        description="Export an escalation as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export escalation to markdown.",
    )
)


# -- Repair Proposal Framework v1 -------------------------------------------

_register(
    CommandSpec(
        name="repair-proposal-create",
        command=(
            "axiom repair-proposal-create --title <t> "
            "[--escalation-id <eid>] [--description <d>] "
            "[--source <s>] [--proposal-type <pt>] "
            "[--rationale <r>] [--recommendations <rec>] "
            "[--json-output]"
        ),
        description="Create a new repair proposal.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("repair_proposal_request.json", required=True),
            EvidenceOutput("repair_proposal_result.json", required=True),
            EvidenceOutput("repair_proposal_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Create durable repair proposal artifact.",
    )
)

_register(
    CommandSpec(
        name="repair-proposals",
        command=(
            "axiom repair-proposals [--status <s>] "
            "[--proposal-type <pt>] [--source <src>] "
            "[--json-output]"
        ),
        description="List all repair proposals.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List repair proposals with optional filters.",
    )
)

_register(
    CommandSpec(
        name="repair-proposal-show",
        command="axiom repair-proposal-show <proposal_id> [--json-output]",
        description="Show details of a repair proposal.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Inspect a repair proposal by ID.",
    )
)

_register(
    CommandSpec(
        name="repair-proposal-export",
        command="axiom repair-proposal-export <proposal_id> [--json-output]",
        description="Export a repair proposal as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export repair proposal to markdown.",
    )
)


# -- Repair Decision Framework v1 -------------------------------------------

_register(
    CommandSpec(
        name="repair-decision-create",
        command=(
            "axiom repair-decision-create --title <t> "
            "[--proposal-id <pid>] [--description <d>] "
            "[--source <s>] [--status <st>] [--reason <r>] "
            "[--rationale <rat>] [--notes <n>] "
            "[--json-output]"
        ),
        description="Create a new repair decision.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("repair_decision_request.json", required=True),
            EvidenceOutput("repair_decision_result.json", required=True),
            EvidenceOutput("repair_decision_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Create durable repair decision artifact.",
    )
)

_register(
    CommandSpec(
        name="repair-decisions",
        command=(
            "axiom repair-decisions [--status <s>] "
            "[--reason <r>] [--source <src>] "
            "[--json-output]"
        ),
        description="List all repair decisions.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List repair decisions with optional filters.",
    )
)

_register(
    CommandSpec(
        name="repair-decision-show",
        command="axiom repair-decision-show <decision_id> [--json-output]",
        description="Show details of a repair decision.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Inspect a repair decision by ID.",
    )
)

_register(
    CommandSpec(
        name="repair-decision-export",
        command="axiom repair-decision-export <decision_id> [--json-output]",
        description="Export a repair decision as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export repair decision to markdown.",
    )
)


# -- Conflict Resolution Framework v1 ---------------------------------------

_register(
    CommandSpec(
        name="conflict-create",
        command=(
            "axiom conflict-create --title <t> "
            "[--description <d>] [--conflict-type <ct>] "
            "[--severity <s>] [--source <src>] "
            "[--left-ref <l>] [--right-ref <r>] "
            "[--rationale <rat>] [--recommendation <rec>] "
            "[--json-output]"
        ),
        description="Create a new conflict.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("conflict_request.json", required=True),
            EvidenceOutput("conflict_result.json", required=True),
            EvidenceOutput("conflict_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Create durable conflict artifact.",
    )
)

_register(
    CommandSpec(
        name="conflicts",
        command=(
            "axiom conflicts [--status <s>] "
            "[--severity <sev>] [--conflict-type <ct>] "
            "[--source <src>] [--json-output]"
        ),
        description="List all conflicts.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List conflicts with optional filters.",
    )
)

_register(
    CommandSpec(
        name="conflict-show",
        command="axiom conflict-show <conflict_id> [--json-output]",
        description="Show details of a conflict.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Inspect a conflict by ID.",
    )
)

_register(
    CommandSpec(
        name="conflict-export",
        command="axiom conflict-export <conflict_id> [--json-output]",
        description="Export a conflict as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export conflict to markdown.",
    )
)


# -- Session State Machine v1 -----------------------------------------------

_register(
    CommandSpec(
        name="session-state-create",
        command=(
            "axiom session-state-create --session-id <sid> "
            "[--current-state <cs>] [--reason <r>] "
            "[--source <src>] [--rationale <rat>] "
            "[--json-output]"
        ),
        description="Create a new session state.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("session_state_request.json", required=True),
            EvidenceOutput("session_state_result.json", required=True),
            EvidenceOutput("session_state_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Create durable session state artifact.",
    )
)

_register(
    CommandSpec(
        name="session-states",
        command=(
            "axiom session-states [--session-id <sid>] "
            "[--current-state <cs>] [--source <src>] "
            "[--json-output]"
        ),
        description="List all session states.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List session states with optional filters.",
    )
)

_register(
    CommandSpec(
        name="session-state-show",
        command="axiom session-state-show <state_id> [--json-output]",
        description="Show details of a session state.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Inspect a session state by ID.",
    )
)

_register(
    CommandSpec(
        name="session-state-transition",
        command=(
            "axiom session-state-transition <state_id> "
            "--to-state <ts> [--reason <r>] "
            "[--source <src>] [--rationale <rat>] "
            "[--json-output]"
        ),
        description="Transition a session state.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("session_state_request.json", required=True),
            EvidenceOutput("session_state_result.json", required=True),
            EvidenceOutput("session_state_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Transition session state with validation.",
    )
)

_register(
    CommandSpec(
        name="session-state-export",
        command="axiom session-state-export <state_id> [--json-output]",
        description="Export a session state as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export session state to markdown.",
    )
)


# -- Session Task Graph v1 --------------------------------------------------

_register(
    CommandSpec(
        name="session-task-create",
        command=(
            "axiom session-task-create --title <t> "
            "[--parent-task-id <pid>] [--description <d>] "
            "[--task-type <tt>] [--status <s>] "
            "[--json-output]"
        ),
        description="Create a new session task.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("session_task_request.json", required=True),
            EvidenceOutput("session_task_result.json", required=True),
            EvidenceOutput("session_task_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Create durable session task artifact.",
    )
)

_register(
    CommandSpec(
        name="session-tasks",
        command=(
            "axiom session-tasks [--task-type <tt>] "
            "[--status <s>] [--parent-task-id <pid>] "
            "[--json-output]"
        ),
        description="List all session tasks.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List session tasks with optional filters.",
    )
)

_register(
    CommandSpec(
        name="session-task-show",
        command="axiom session-task-show <task_id> [--json-output]",
        description="Show details of a session task.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Inspect a session task by ID.",
    )
)

_register(
    CommandSpec(
        name="session-task-export",
        command="axiom session-task-export <task_id> [--json-output]",
        description="Export a session task as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export session task to markdown.",
    )
)


# -- Live Coding Trial v1 ---------------------------------------------------

_register(
    CommandSpec(
        name="live-coding-trial",
        command=(
            "axiom live-coding-trial [--code-file <cf>] "
            "[--test-file <tf>] [--function-name <fn>] "
            "[--description <d>] [--json-output]"
        ),
        description="Run a minimal live coding trial.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("live_coding_trial_request.json", required=True),
            EvidenceOutput("live_coding_trial_result.json", required=True),
            EvidenceOutput("live_coding_trial_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=180,
        failure_modes=(FM_NONZERO,),
        notes="Run minimal live coding trial with evidence generation.",
    )
)


# -- Parser Coding Trial v1 -------------------------------------------------

_register(
    CommandSpec(
        name="parser-coding-trial",
        command=(
            "axiom parser-coding-trial [--code-file <cf>] "
            "[--test-file <tf>] [--function-name <fn>] "
            "[--description <d>] [--json-output]"
        ),
        description="Run a minimal parser coding trial.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("parser_coding_trial_request.json", required=True),
            EvidenceOutput("parser_coding_trial_result.json", required=True),
            EvidenceOutput("parser_coding_trial_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=180,
        failure_modes=(FM_NONZERO,),
        notes="Run minimal parser coding trial with evidence generation.",
    )
)


# -- Structured Configuration v1 --------------------------------------------

_register(
    CommandSpec(
        name="config-load",
        command=(
            "axiom config-load [--text <t>] [--file <f>] "
            "[--file-name <fn>] [--json-output]"
        ),
        description="Load and validate a key=value configuration.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("configuration_request.json", required=True),
            EvidenceOutput("configuration_result.json", required=True),
            EvidenceOutput("configuration_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Load key=value text, validate, persist, generate evidence.",
    )
)

_register(
    CommandSpec(
        name="config-show",
        command="axiom config-show <config_id> [--json-output]",
        description="Show a configuration by ID.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Display a persisted configuration.",
    )
)

_register(
    CommandSpec(
        name="config-export",
        command="axiom config-export <config_id> [--json-output]",
        description="Export a configuration as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a configuration as markdown.",
    )
)


# -- Structured Configuration Validation v1 ---------------------------------

_register(
    CommandSpec(
        name="config-validate",
        command=(
            "axiom config-validate [--text <t>] [--file <f>] "
            "[--require-keys <rk>] [--non-empty-keys <nek>] [--json-output]"
        ),
        description="Validate a key=value configuration against rules.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("config_validation_request.json", required=True),
            EvidenceOutput("config_validation_result.json", required=True),
            EvidenceOutput("config_validation_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Validate key=value config against rules, generate evidence.",
    )
)

_register(
    CommandSpec(
        name="config-validation-show",
        command="axiom config-validation-show <report_id> [--json-output]",
        description="Show a configuration validation report by ID.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Display a persisted validation report.",
    )
)

_register(
    CommandSpec(
        name="config-validation-export",
        command="axiom config-validation-export <report_id> [--json-output]",
        description="Export a configuration validation report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a validation report as markdown.",
    )
)


# ---------------------------------------------------------------------------
# Configuration Repair Recommendation commands
# ---------------------------------------------------------------------------


_register(
    CommandSpec(
        name="config-repair-recommend",
        command="axiom config-repair-recommend [--text <t>] [--file <f>] [--require-keys <rk>] [--non-empty-keys <nek>] [--json-output]",
        description="Generate repair recommendations for key=value config violations.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("config_repair_request.json", required=True),
            EvidenceOutput("config_repair_result.json", required=True),
            EvidenceOutput("config_repair_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Generate repair recommendations for key=value config violations.",
    )
)

_register(
    CommandSpec(
        name="config-repair-show",
        command="axiom config-repair-show <report_id> [--json-output]",
        description="Show a repair recommendation report by ID.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a repair recommendation report by ID.",
    )
)

_register(
    CommandSpec(
        name="config-repair-export",
        command="axiom config-repair-export <report_id> [--json-output]",
        description="Export a repair recommendation report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a repair recommendation report as markdown.",
    )
)


# ---------------------------------------------------------------------------
# Configuration Explanation commands
# ---------------------------------------------------------------------------


_register(
    CommandSpec(
        name="config-explain",
        command="axiom config-explain [--text <t>] [--file <f>] [--require-keys <rk>] [--non-empty-keys <nek>] [--json-output]",
        description="Generate explanations for configuration validation and repair.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("config_explanation_request.json", required=True),
            EvidenceOutput("config_explanation_result.json", required=True),
            EvidenceOutput("config_explanation_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Generate explanations for config validation and repair recommendations.",
    )
)

_register(
    CommandSpec(
        name="config-explanation-show",
        command="axiom config-explanation-show <report_id> [--json-output]",
        description="Show an explanation report by ID.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show an explanation report by ID.",
    )
)

_register(
    CommandSpec(
        name="config-explanation-export",
        command="axiom config-explanation-export <report_id> [--json-output]",
        description="Export an explanation report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export an explanation report as markdown.",
    )
)


_register(
    CommandSpec(
        name="config-execute",
        command="axiom config-execute [--text <t>] [--file <f>] [--require-keys <rk>] [--non-empty-keys <nek>] [--actions <a>] [--json-output]",
        description="Execute configuration actions with evidence generation.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("config_execution_request.json", required=True),
            EvidenceOutput("config_execution_result.json", required=True),
            EvidenceOutput("config_execution_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Execute configuration actions deterministically with evidence.",
    )
)

_register(
    CommandSpec(
        name="config-execution-show",
        command="axiom config-execution-show <report_id> [--json-output]",
        description="Show an execution report by ID.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show an execution report by ID.",
    )
)

_register(
    CommandSpec(
        name="config-execution-export",
        command="axiom config-execution-export <report_id> [--json-output]",
        description="Export an execution report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export an execution report as markdown.",
    )
)


_register(
    CommandSpec(
        name="config-rollback",
        command="axiom config-rollback [--text <t>] [--file <f>] [--require-keys <rk>] [--non-empty-keys <nek>] [--actions <a>] [--json-output]",
        description="Roll back configuration execution actions.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("config_rollback_request.json", required=True),
            EvidenceOutput("config_rollback_result.json", required=True),
            EvidenceOutput("config_rollback_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Roll back configuration execution actions deterministically.",
    )
)

_register(
    CommandSpec(
        name="config-rollback-show",
        command="axiom config-rollback-show <report_id> [--json-output]",
        description="Show a rollback report by ID.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a rollback report by ID.",
    )
)

_register(
    CommandSpec(
        name="config-rollback-export",
        command="axiom config-rollback-export <report_id> [--json-output]",
        description="Export a rollback report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a rollback report as markdown.",
    )
)


_register(
    CommandSpec(
        name="config-history-create",
        command="axiom config-history-create [--text <t>] [--file <f>] [--require-keys <rk>] [--non-empty-keys <nek>] [--json-output]",
        description="Create configuration change history from lifecycle events.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("config_history_request.json", required=True),
            EvidenceOutput("config_history_result.json", required=True),
            EvidenceOutput("config_history_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create configuration change history deterministically.",
    )
)

_register(
    CommandSpec(
        name="config-history-show",
        command="axiom config-history-show <report_id> [--json-output]",
        description="Show a history report by ID.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a history report by ID.",
    )
)

_register(
    CommandSpec(
        name="config-history-export",
        command="axiom config-history-export <report_id> [--json-output]",
        description="Export a history report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a history report as markdown.",
    )
)

_register(
    CommandSpec(
        name="config-diff",
        command="axiom config-diff [--left-text <lt>] [--right-text <rt>] [--left-file <lf>] [--right-file <rf>] [--json-output]",
        description="Diff two configuration states with evidence generation.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("config_diff_request.json", required=True),
            EvidenceOutput("config_diff_result.json", required=True),
            EvidenceOutput("config_diff_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Diff two configuration states deterministically.",
    )
)

_register(
    CommandSpec(
        name="config-diff-show",
        command="axiom config-diff-show <report_id> [--json-output]",
        description="Show a diff report by ID.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a diff report by ID.",
    )
)

_register(
    CommandSpec(
        name="config-diff-export",
        command="axiom config-diff-export <report_id> [--json-output]",
        description="Export a diff report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a diff report as markdown.",
    )
)

_register(
    CommandSpec(
        name="config-merge",
        command="axiom config-merge [--left-text <lt>] [--right-text <rt>] [--left-file <lf>] [--right-file <rf>] [--strategy <s>] [--json-output]",
        description="Merge two configuration states with evidence generation.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("config_merge_request.json", required=True),
            EvidenceOutput("config_merge_result.json", required=True),
            EvidenceOutput("config_merge_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Merge two configuration states deterministically.",
    )
)

_register(
    CommandSpec(
        name="config-merge-show",
        command="axiom config-merge-show <report_id> [--json-output]",
        description="Show a merge report by ID.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a merge report by ID.",
    )
)

_register(
    CommandSpec(
        name="config-merge-export",
        command="axiom config-merge-export <report_id> [--json-output]",
        description="Export a merge report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a merge report as markdown.",
    )
)

_register(
    CommandSpec(
        name="config-policy-check",
        command="axiom config-policy-check [--config-text <ct>] [--config-file <cf>] [--policy-file <pf>] [--json-output]",
        description="Check a configuration against a policy with evidence generation.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("config_policy_request.json", required=True),
            EvidenceOutput("config_policy_result.json", required=True),
            EvidenceOutput("config_policy_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Evaluate a configuration against policy rules deterministically.",
    )
)

_register(
    CommandSpec(
        name="config-policy-show",
        command="axiom config-policy-show <report_id> [--json-output]",
        description="Show a policy report by ID.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a policy report by ID.",
    )
)

_register(
    CommandSpec(
        name="config-policy-export",
        command="axiom config-policy-export <report_id> [--json-output]",
        description="Export a policy report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a policy report as markdown.",
    )
)

_register(
    CommandSpec(
        name="config-scenario-run",
        command="axiom config-scenario-run [--scenario-file <sf>] [--policy-passed <bool>] [--policy-blocker-count <int>] [--validation-passed <bool>] [--execution-status <s>] [--json-output]",
        description="Run a configuration scenario evaluation with evidence generation.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("config_scenario_request.json", required=True),
            EvidenceOutput("config_scenario_result.json", required=True),
            EvidenceOutput("config_scenario_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Evaluate a configuration scenario deterministically.",
    )
)

_register(
    CommandSpec(
        name="config-scenario-show",
        command="axiom config-scenario-show <report_id> [--json-output]",
        description="Show a scenario report by ID.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a scenario report by ID.",
    )
)

_register(
    CommandSpec(
        name="config-scenario-export",
        command="axiom config-scenario-export <report_id> [--json-output]",
        description="Export a scenario report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a scenario report as markdown.",
    )
)

_register(
    CommandSpec(
        name="config-batch-run",
        command="axiom config-batch-run [--scenarios-file <sf>] [--execution-mode <mode>] [--json-output]",
        description="Run a batch of configuration scenarios with evidence generation.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("config_batch_request.json", required=True),
            EvidenceOutput("config_batch_result.json", required=True),
            EvidenceOutput("config_batch_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Execute batch of scenarios deterministically.",
    )
)

_register(
    CommandSpec(
        name="config-batch-show",
        command="axiom config-batch-show <report_id> [--json-output]",
        description="Show a batch execution report by ID.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a batch execution report by ID.",
    )
)

_register(
    CommandSpec(
        name="config-batch-export",
        command="axiom config-batch-export <report_id> [--json-output]",
        description="Export a batch execution report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a batch execution report as markdown.",
    )
)

_register(
    CommandSpec(
        name="config-dependency-create",
        command="axiom config-dependency-create [--dependencies-file <df>] [--known-ids <ids>] [--json-output]",
        description="Create a configuration dependency graph with evidence generation.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("config_dependency_request.json", required=True),
            EvidenceOutput("config_dependency_result.json", required=True),
            EvidenceOutput("config_dependency_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create a dependency graph deterministically.",
    )
)

_register(
    CommandSpec(
        name="config-dependencies",
        command="axiom config-dependencies [--json-output]",
        description="List all dependency reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List all dependency reports.",
    )
)

_register(
    CommandSpec(
        name="config-dependency-show",
        command="axiom config-dependency-show <report_id> [--json-output]",
        description="Show a dependency report by ID.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a dependency report by ID.",
    )
)

_register(
    CommandSpec(
        name="config-dependency-export",
        command="axiom config-dependency-export <report_id> [--json-output]",
        description="Export a dependency report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a dependency report as markdown.",
    )
)

_register(
    CommandSpec(
        name="capability-create",
        command="axiom capability-create [--capabilities-file <cf>] [--known-dependency-ids <ids>] [--json-output]",
        description="Create a capability registry with evidence generation.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("capability_request.json", required=True),
            EvidenceOutput("capability_result.json", required=True),
            EvidenceOutput("capability_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create a capability registry deterministically.",
    )
)

_register(
    CommandSpec(
        name="capabilities",
        command="axiom capabilities [--json-output]",
        description="List all capability reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List all capability reports.",
    )
)

_register(
    CommandSpec(
        name="capability-show",
        command="axiom capability-show <report_id> [--json-output]",
        description="Show a capability report by ID.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a capability report by ID.",
    )
)

_register(
    CommandSpec(
        name="capability-export",
        command="axiom capability-export <report_id> [--json-output]",
        description="Export a capability report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a capability report as markdown.",
    )
)

_register(
    CommandSpec(
        name="capability-input-create",
        command="axiom capability-input-create [--inputs-file <if>] [--capability-id <cid>] [--known-capability-ids <ids>] [--json-output]",
        description="Create capability inputs and validate them with evidence generation.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("capability_input_request.json", required=True),
            EvidenceOutput("capability_input_result.json", required=True),
            EvidenceOutput("capability_input_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and validate capability inputs deterministically.",
    )
)

_register(
    CommandSpec(
        name="capability-inputs",
        command="axiom capability-inputs [--json-output]",
        description="List all capability input reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List all capability input reports.",
    )
)

_register(
    CommandSpec(
        name="capability-input-show",
        command="axiom capability-input-show <report_id> [--json-output]",
        description="Show a capability input report by ID.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a capability input report by ID.",
    )
)

_register(
    CommandSpec(
        name="capability-input-export",
        command="axiom capability-input-export <report_id> [--json-output]",
        description="Export a capability input report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a capability input report as markdown.",
    )
)

_register(
    CommandSpec(
        name="capability-output-create",
        command="axiom capability-output-create [--outputs-file <of>] [--capability-id <cid>] [--known-capability-ids <ids>] [--json-output]",
        description="Create capability outputs and validate them with evidence generation.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("capability_output_request.json", required=True),
            EvidenceOutput("capability_output_result.json", required=True),
            EvidenceOutput("capability_output_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and validate capability outputs deterministically.",
    )
)

_register(
    CommandSpec(
        name="capability-outputs",
        command="axiom capability-outputs [--json-output]",
        description="List all capability output reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List all capability output reports.",
    )
)

_register(
    CommandSpec(
        name="capability-output-show",
        command="axiom capability-output-show <report_id> [--json-output]",
        description="Show a capability output report by ID.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a capability output report by ID.",
    )
)

_register(
    CommandSpec(
        name="capability-output-export",
        command="axiom capability-output-export <report_id> [--json-output]",
        description="Export a capability output report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a capability output report as markdown.",
    )
)

_register(
    CommandSpec(
        name="capability-report-create",
        command="axiom capability-report-create [--capability-id <cid>] [--execution-status <s>] [--duration-ms <ms>] [--events-file <ef>] [--json-output]",
        description="Create a capability execution report with events and evidence.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("capability_execution_request.json", required=True),
            EvidenceOutput("capability_execution_result.json", required=True),
            EvidenceOutput("capability_execution_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and persist a capability execution report deterministically.",
    )
)

_register(
    CommandSpec(
        name="capability-reports",
        command="axiom capability-reports [--json-output]",
        description="List all capability execution reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List all capability execution reports.",
    )
)

_register(
    CommandSpec(
        name="capability-report-show",
        command="axiom capability-report-show <report_id> [--json-output]",
        description="Show a capability execution report by ID.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a capability execution report by ID.",
    )
)

_register(
    CommandSpec(
        name="capability-report-export",
        command="axiom capability-report-export <report_id> [--json-output]",
        description="Export a capability execution report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("EV_CONSOLE", required=False),
        ),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a capability execution report as markdown.",
    )
)


# ---------------------------------------------------------------------------
# Capability Failure commands
# ---------------------------------------------------------------------------

_register(
    CommandSpec(
        name="capability-failure-create",
        command="axiom capability-failure-create [--failures-file <ff>] [--report-id <rid>] [--json-output]",
        description="Create a capability failure report with deterministic ordering.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("capability_failure_request.json", required=True),
            EvidenceOutput("capability_failure_result.json", required=True),
            EvidenceOutput("capability_failure_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and persist a capability failure report deterministically.",
    )
)

_register(
    CommandSpec(
        name="capability-failures",
        command="axiom capability-failures [--json-output]",
        description="List all capability failure reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List capability failure reports.",
    )
)

_register(
    CommandSpec(
        name="capability-failure-show",
        command="axiom capability-failure-show <report_id> [--json-output]",
        description="Show a capability failure report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a capability failure report by ID.",
    )
)

_register(
    CommandSpec(
        name="capability-failure-export",
        command="axiom capability-failure-export <report_id> [--json-output]",
        description="Export a capability failure report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a capability failure report as markdown.",
    )
)


# ---------------------------------------------------------------------------
# Capability Repair Outcome commands
# ---------------------------------------------------------------------------

_register(
    CommandSpec(
        name="capability-repair-outcome-create",
        command="axiom capability-repair-outcome-create [--outcomes-file <of>] [--json-output]",
        description="Create a capability repair outcome report with deterministic ordering.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("capability_repair_outcome_request.json", required=True),
            EvidenceOutput("capability_repair_outcome_result.json", required=True),
            EvidenceOutput("capability_repair_outcome_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and persist a capability repair outcome report deterministically.",
    )
)

_register(
    CommandSpec(
        name="capability-repair-outcomes",
        command="axiom capability-repair-outcomes [--json-output]",
        description="List all capability repair outcome reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List capability repair outcome reports.",
    )
)

_register(
    CommandSpec(
        name="capability-repair-outcome-show",
        command="axiom capability-repair-outcome-show <report_id> [--json-output]",
        description="Show a capability repair outcome report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a capability repair outcome report by ID.",
    )
)

_register(
    CommandSpec(
        name="capability-repair-outcome-export",
        command="axiom capability-repair-outcome-export <report_id> [--json-output]",
        description="Export a capability repair outcome report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a capability repair outcome report as markdown.",
    )
)


# ---------------------------------------------------------------------------
# Capability Confidence commands
# ---------------------------------------------------------------------------

_register(
    CommandSpec(
        name="capability-confidence-create",
        command="axiom capability-confidence-create [--capability-id <cid>] [--execution-count <n>] [--success-count <n>] [--failure-count <n>] [--repair-count <n>] [--recovery-count <n>] [--json-output]",
        description="Create a capability confidence report with deterministic scoring.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("capability_confidence_request.json", required=True),
            EvidenceOutput("capability_confidence_result.json", required=True),
            EvidenceOutput("capability_confidence_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and persist a capability confidence report deterministically.",
    )
)

_register(
    CommandSpec(
        name="capability-confidences",
        command="axiom capability-confidences [--json-output]",
        description="List all capability confidence reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List capability confidence reports.",
    )
)

_register(
    CommandSpec(
        name="capability-confidence-show",
        command="axiom capability-confidence-show <report_id> [--json-output]",
        description="Show a capability confidence report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a capability confidence report by ID.",
    )
)

_register(
    CommandSpec(
        name="capability-confidence-export",
        command="axiom capability-confidence-export <report_id> [--json-output]",
        description="Export a capability confidence report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a capability confidence report as markdown.",
    )
)


# ---------------------------------------------------------------------------
# Capability History commands
# ---------------------------------------------------------------------------

_register(
    CommandSpec(
        name="capability-history-create",
        command="axiom capability-history-create [--capability-id <cid>] [--events-file <ef>] [--json-output]",
        description="Create a capability history report with deterministic chronological ordering.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("capability_history_request.json", required=True),
            EvidenceOutput("capability_history_result.json", required=True),
            EvidenceOutput("capability_history_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and persist a capability history report deterministically.",
    )
)

_register(
    CommandSpec(
        name="capability-history-show",
        command="axiom capability-history-show <report_id> [--json-output]",
        description="Show a capability history report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a capability history report by ID.",
    )
)

_register(
    CommandSpec(
        name="capability-history-export",
        command="axiom capability-history-export <report_id> [--json-output]",
        description="Export a capability history report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a capability history report as markdown.",
    )
)


# ---------------------------------------------------------------------------
# Capability Skill commands
# ---------------------------------------------------------------------------

_register(
    CommandSpec(
        name="capability-skill-create",
        command="axiom capability-skill-create [--capability-id <cid>] [--skills-file <sf>] [--json-output]",
        description="Create a capability skill report with deterministic ordering.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("capability_skill_request.json", required=True),
            EvidenceOutput("capability_skill_result.json", required=True),
            EvidenceOutput("capability_skill_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and persist a capability skill report deterministically.",
    )
)

_register(
    CommandSpec(
        name="capability-skill-show",
        command="axiom capability-skill-show <report_id> [--json-output]",
        description="Show a capability skill report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a capability skill report by ID.",
    )
)

_register(
    CommandSpec(
        name="capability-skill-export",
        command="axiom capability-skill-export <report_id> [--json-output]",
        description="Export a capability skill report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a capability skill report as markdown.",
    )
)


# ---------------------------------------------------------------------------
# Work Queue commands
# ---------------------------------------------------------------------------

_register(
    CommandSpec(
        name="work-create",
        command="axiom work-create [--items-file <if>] [--json-output]",
        description="Create a work queue report with deterministic ordering.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("work_queue_request.json", required=True),
            EvidenceOutput("work_queue_result.json", required=True),
            EvidenceOutput("work_queue_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and persist a work queue report deterministically.",
    )
)

_register(
    CommandSpec(
        name="work-show",
        command="axiom work-show <report_id> [--json-output]",
        description="Show a work queue report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a work queue report by ID.",
    )
)

_register(
    CommandSpec(
        name="work-export",
        command="axiom work-export <report_id> [--json-output]",
        description="Export a work queue report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a work queue report as markdown.",
    )
)


# ---------------------------------------------------------------------------
# Work Item Dependency commands
# ---------------------------------------------------------------------------

_register(
    CommandSpec(
        name="work-dependency-create",
        command="axiom work-dependency-create [--deps-file <df>] [--json-output]",
        description="Create a work dependency graph report with cycle detection.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("work_dependency_request.json", required=True),
            EvidenceOutput("work_dependency_result.json", required=True),
            EvidenceOutput("work_dependency_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and persist a work dependency graph deterministically.",
    )
)

_register(
    CommandSpec(
        name="work-dependency-show",
        command="axiom work-dependency-show <report_id> [--json-output]",
        description="Show a work dependency graph report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a work dependency graph report by ID.",
    )
)

_register(
    CommandSpec(
        name="work-dependency-export",
        command="axiom work-dependency-export <report_id> [--json-output]",
        description="Export a work dependency graph report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a work dependency graph report as markdown.",
    )
)


# ---------------------------------------------------------------------------
# Work Prioritization commands
# ---------------------------------------------------------------------------

_register(
    CommandSpec(
        name="work-priority-create",
        command=(
            "axiom work-priority-create [--rules-file <rf>] "
            "[--factors-file <ff>] [--json-output]"
        ),
        description="Create a work prioritization report with deterministic ranking.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("work_priority_request.json", required=True),
            EvidenceOutput("work_priority_result.json", required=True),
            EvidenceOutput("work_priority_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and persist a work prioritization report deterministically.",
    )
)

_register(
    CommandSpec(
        name="work-priority-show",
        command="axiom work-priority-show <report_id> [--json-output]",
        description="Show a work prioritization report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a work prioritization report by ID.",
    )
)

_register(
    CommandSpec(
        name="work-priority-export",
        command="axiom work-priority-export <report_id> [--json-output]",
        description="Export a work prioritization report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a work prioritization report as markdown.",
    )
)


# ---------------------------------------------------------------------------
# Execution Attempt commands
# ---------------------------------------------------------------------------

_register(
    CommandSpec(
        name="execution-attempt-create",
        command="axiom execution-attempt-create [--attempts-file <af>] [--json-output]",
        description="Create an execution attempt report with status/duration tracking.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("execution_attempt_request.json", required=True),
            EvidenceOutput("execution_attempt_result.json", required=True),
            EvidenceOutput("execution_attempt_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and persist an execution attempt report deterministically.",
    )
)

_register(
    CommandSpec(
        name="execution-attempt-show",
        command="axiom execution-attempt-show <report_id> [--json-output]",
        description="Show an execution attempt report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show an execution attempt report by ID.",
    )
)

_register(
    CommandSpec(
        name="execution-attempt-export",
        command="axiom execution-attempt-export <report_id> [--json-output]",
        description="Export an execution attempt report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export an execution attempt report as markdown.",
    )
)

_register(
    CommandSpec(
        name="execution-outcome-create",
        command="axiom execution-outcome-create [--outcomes-file <of>] [--json-output]",
        description="Create an execution outcome report with outcome-type/status counts.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("execution_outcome_request.json", required=True),
            EvidenceOutput("execution_outcome_result.json", required=True),
            EvidenceOutput("execution_outcome_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and persist an execution outcome report deterministically.",
    )
)

_register(
    CommandSpec(
        name="execution-outcome-show",
        command="axiom execution-outcome-show <report_id> [--json-output]",
        description="Show an execution outcome report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show an execution outcome report by ID.",
    )
)

_register(
    CommandSpec(
        name="execution-outcome-export",
        command="axiom execution-outcome-export <report_id> [--json-output]",
        description="Export an execution outcome report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export an execution outcome report as markdown.",
    )
)

_register(
    CommandSpec(
        name="failure-classification-create",
        command=(
            "axiom failure-classification-create "
            "[--classifications-file <cf>] [--json-output]"
        ),
        description=(
            "Create a failure classification report with severity/category counts."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("failure_classification_request.json", required=True),
            EvidenceOutput("failure_classification_result.json", required=True),
            EvidenceOutput("failure_classification_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and persist a failure classification report deterministically.",
    )
)

_register(
    CommandSpec(
        name="failure-classification-show",
        command="axiom failure-classification-show <report_id> [--json-output]",
        description="Show a failure classification report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a failure classification report by ID.",
    )
)

_register(
    CommandSpec(
        name="failure-classification-export",
        command="axiom failure-classification-export <report_id> [--json-output]",
        description="Export a failure classification report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a failure classification report as markdown.",
    )
)

_register(
    CommandSpec(
        name="recovery-recommendation-create",
        command=(
            "axiom recovery-recommendation-create "
            "[--recommendations-file <rf>] [--json-output]"
        ),
        description=(
            "Create a recovery recommendation report with priority counts."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("recovery_recommendation_request.json", required=True),
            EvidenceOutput("recovery_recommendation_result.json", required=True),
            EvidenceOutput("recovery_recommendation_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and persist a recovery recommendation report deterministically.",
    )
)

_register(
    CommandSpec(
        name="recovery-recommendation-show",
        command="axiom recovery-recommendation-show <report_id> [--json-output]",
        description="Show a recovery recommendation report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a recovery recommendation report by ID.",
    )
)

_register(
    CommandSpec(
        name="recovery-recommendation-export",
        command="axiom recovery-recommendation-export <report_id> [--json-output]",
        description="Export a recovery recommendation report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a recovery recommendation report as markdown.",
    )
)

_register(
    CommandSpec(
        name="recovery-execution-create",
        command=(
            "axiom recovery-execution-create "
            "[--executions-file <ef>] [--json-output]"
        ),
        description=(
            "Create a recovery execution report with status counts."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("recovery_execution_request.json", required=True),
            EvidenceOutput("recovery_execution_result.json", required=True),
            EvidenceOutput("recovery_execution_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and persist a recovery execution report deterministically.",
    )
)

_register(
    CommandSpec(
        name="recovery-execution-show",
        command="axiom recovery-execution-show <report_id> [--json-output]",
        description="Show a recovery execution report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a recovery execution report by ID.",
    )
)

_register(
    CommandSpec(
        name="recovery-execution-export",
        command="axiom recovery-execution-export <report_id> [--json-output]",
        description="Export a recovery execution report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a recovery execution report as markdown.",
    )
)

_register(
    CommandSpec(
        name="session-memory-create",
        command=(
            "axiom session-memory-create [--entries-file <ef>] [--json-output]"
        ),
        description=(
            "Create a session memory report with memory-type counts."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("session_memory_request.json", required=True),
            EvidenceOutput("session_memory_result.json", required=True),
            EvidenceOutput("session_memory_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and persist a session memory report deterministically.",
    )
)

_register(
    CommandSpec(
        name="session-memory-show",
        command="axiom session-memory-show <report_id> [--json-output]",
        description="Show a session memory report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a session memory report by ID.",
    )
)

_register(
    CommandSpec(
        name="session-memory-export",
        command="axiom session-memory-export <report_id> [--json-output]",
        description="Export a session memory report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a session memory report as markdown.",
    )
)

_register(
    CommandSpec(
        name="skill-composition-create",
        command=(
            "axiom skill-composition-create "
            "[--compositions-file <cf>] [--json-output]"
        ),
        description=(
            "Create a skill composition report with composition-type counts."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("skill_composition_request.json", required=True),
            EvidenceOutput("skill_composition_result.json", required=True),
            EvidenceOutput("skill_composition_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and persist a skill composition report deterministically.",
    )
)

_register(
    CommandSpec(
        name="skill-composition-show",
        command="axiom skill-composition-show <report_id> [--json-output]",
        description="Show a skill composition report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a skill composition report by ID.",
    )
)

_register(
    CommandSpec(
        name="skill-composition-export",
        command="axiom skill-composition-export <report_id> [--json-output]",
        description="Export a skill composition report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a skill composition report as markdown.",
    )
)

_register(
    CommandSpec(
        name="capability-routing-create",
        command=(
            "axiom capability-routing-create "
            "[--routing-file <rf>] [--json-output]"
        ),
        description=(
            "Create a capability routing report with per-capability counts."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("capability_routing_request.json", required=True),
            EvidenceOutput("capability_routing_result.json", required=True),
            EvidenceOutput("capability_routing_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and persist a capability routing report deterministically.",
    )
)

_register(
    CommandSpec(
        name="capability-routing-show",
        command="axiom capability-routing-show <report_id> [--json-output]",
        description="Show a capability routing report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a capability routing report by ID.",
    )
)

_register(
    CommandSpec(
        name="capability-routing-export",
        command="axiom capability-routing-export <report_id> [--json-output]",
        description="Export a capability routing report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a capability routing report as markdown.",
    )
)

_register(
    CommandSpec(
        name="capability-selection-create",
        command=(
            "axiom capability-selection-create "
            "[--selection-file <sf>] [--json-output]"
        ),
        description=(
            "Create a capability selection report with per-capability counts."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("capability_selection_request.json", required=True),
            EvidenceOutput("capability_selection_result.json", required=True),
            EvidenceOutput("capability_selection_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and persist a capability selection report deterministically.",
    )
)

_register(
    CommandSpec(
        name="capability-selection-show",
        command="axiom capability-selection-show <report_id> [--json-output]",
        description="Show a capability selection report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a capability selection report by ID.",
    )
)

_register(
    CommandSpec(
        name="capability-selection-export",
        command="axiom capability-selection-export <report_id> [--json-output]",
        description="Export a capability selection report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a capability selection report as markdown.",
    )
)


_register(
    CommandSpec(
        name="capability-chain-create",
        command=(
            "axiom capability-chain-create "
            "[--chain-file <cf>] [--json-output]"
        ),
        description=(
            "Create a capability chain report with per-chain type counts."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("capability_chain_request.json", required=True),
            EvidenceOutput("capability_chain_result.json", required=True),
            EvidenceOutput("capability_chain_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and persist a capability chain report deterministically.",
    )
)

_register(
    CommandSpec(
        name="capability-chain-show",
        command="axiom capability-chain-show <report_id> [--json-output]",
        description="Show a capability chain report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a capability chain report by ID.",
    )
)

_register(
    CommandSpec(
        name="capability-chain-export",
        command="axiom capability-chain-export <report_id> [--json-output]",
        description="Export a capability chain report as markdown.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a capability chain report as markdown.",
    )
)


_register(
    CommandSpec(
        name="global-capability-create",
        command=(
            "axiom global-capability-create "
            "[--registry-file <rf>] [--json-output]"
        ),
        description=(
            "Create a global capability registry report (canonical identity)."
        ),
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("global_capability_request.json", required=True),
            EvidenceOutput("global_capability_result.json", required=True),
            EvidenceOutput("global_capability_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and persist a global capability registry deterministically.",
    )
)

_register(
    CommandSpec(
        name="global-capability-list",
        command="axiom global-capability-list [--json-output]",
        description="List global capability registry reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List all persisted global capability registry reports.",
    )
)

_register(
    CommandSpec(
        name="global-capability-show",
        command="axiom global-capability-show <report_id> [--json-output]",
        description="Show a global capability registry report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a global capability registry report by ID.",
    )
)

_register(
    CommandSpec(
        name="global-capability-export",
        command=(
            "axiom global-capability-export <report_id> "
            "[--format markdown|json|csv]"
        ),
        description="Export a global capability registry report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a global capability registry report as markdown/json/csv.",
    )
)


_register(
    CommandSpec(
        name="capability-event-create",
        command=(
            "axiom capability-event-create "
            "[--timeline-file <tf>] [--json-output]"
        ),
        description="Create a capability event timeline from events.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("capability_event_request.json", required=True),
            EvidenceOutput("capability_event_result.json", required=True),
            EvidenceOutput("capability_event_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Create and persist a capability event timeline deterministically.",
    )
)

_register(
    CommandSpec(
        name="capability-event-append",
        command=(
            "axiom capability-event-append <timeline_id> "
            "[--timeline-file <tf>] [--json-output]"
        ),
        description="Append events to a capability event timeline (append-only).",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("capability_event_request.json", required=True),
            EvidenceOutput("capability_event_result.json", required=True),
            EvidenceOutput("capability_event_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Append events to an existing timeline; existing events preserved.",
    )
)

_register(
    CommandSpec(
        name="capability-event-list",
        command="axiom capability-event-list [--json-output]",
        description="List capability event timelines.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List all persisted capability event timelines.",
    )
)

_register(
    CommandSpec(
        name="capability-event-show",
        command="axiom capability-event-show <timeline_id> [--json-output]",
        description="Show a capability event timeline.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a capability event timeline by ID.",
    )
)

_register(
    CommandSpec(
        name="capability-event-export",
        command=(
            "axiom capability-event-export <timeline_id> "
            "[--format markdown|json|csv]"
        ),
        description="Export a capability event timeline.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a capability event timeline as markdown/json/csv.",
    )
)

_register(
    CommandSpec(
        name="github-import",
        command=(
            "axiom github-import [--metadata-file <mf>] [--repo owner/name] "
            "[--pr <n>] [--global-capability-number <n>] [--json-output]"
        ),
        description="Import GitHub PR metadata into registry/timeline shapes.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("github_import_request.json", required=True),
            EvidenceOutput("github_import_result.json", required=True),
            EvidenceOutput("github_import_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only deterministic ingestion; no GitHub mutation.",
    )
)

_register(
    CommandSpec(
        name="github-import-show",
        command="axiom github-import-show <report_id> [--json-output]",
        description="Show a GitHub metadata import.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a persisted GitHub metadata import by report ID.",
    )
)

_register(
    CommandSpec(
        name="github-import-export",
        command=(
            "axiom github-import-export <report_id> "
            "[--format markdown|json|csv]"
        ),
        description="Export a GitHub metadata import.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a GitHub metadata import as markdown/json/csv.",
    )
)

_register(
    CommandSpec(
        name="capability-summary-create",
        command=(
            "axiom capability-summary-create [--summary-file <sf>] "
            "[--json-output]"
        ),
        description="Create a capability summary report (understanding).",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("capability_summary_request.json", required=True),
            EvidenceOutput("capability_summary_result.json", required=True),
            EvidenceOutput("capability_summary_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Deterministic, append-only understanding layer; no mutation.",
    )
)

_register(
    CommandSpec(
        name="capability-summary-show",
        command="axiom capability-summary-show <report_id> [--json-output]",
        description="Show a capability summary report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a persisted capability summary report by report ID.",
    )
)

_register(
    CommandSpec(
        name="capability-summary-export",
        command=(
            "axiom capability-summary-export <report_id> "
            "[--format markdown|json|csv]"
        ),
        description="Export a capability summary report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a capability summary report as markdown/json/csv.",
    )
)

_register(
    CommandSpec(
        name="devin-session-import",
        command=(
            "axiom devin-session-import [--session-file <sf>] "
            "[--session-id <sid>] [--repo <owner/name>] [--pr <n>] "
            "[--global-capability-number <n>] [--json-output]"
        ),
        description="Import Devin session metadata (worker/session context).",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput(
                "devin_session_import_request.json", required=True
            ),
            EvidenceOutput(
                "devin_session_import_result.json", required=True
            ),
            EvidenceOutput("devin_session_import_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Read-only, deterministic; builds (never mutates) registry/timeline.",
    )
)

_register(
    CommandSpec(
        name="devin-session-show",
        command="axiom devin-session-show <report_id> [--json-output]",
        description="Show a Devin session metadata import.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a persisted Devin session metadata import by report ID.",
    )
)

_register(
    CommandSpec(
        name="devin-session-export",
        command=(
            "axiom devin-session-export <report_id> "
            "[--format markdown|json|csv]"
        ),
        description="Export a Devin session metadata import.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a Devin session metadata import as markdown/json/csv.",
    )
)

_register(
    CommandSpec(
        name="capability-relationship-create",
        command=(
            "axiom capability-relationship-create "
            "[--relationship-file <rf>] [--json-output]"
        ),
        description="Create a capability relationship report (graph edges).",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput(
                "capability_relationship_request.json", required=True
            ),
            EvidenceOutput(
                "capability_relationship_result.json", required=True
            ),
            EvidenceOutput(
                "capability_relationship_summary.md", required=True
            ),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Deterministic, append-only graph edges; no mutation.",
    )
)

_register(
    CommandSpec(
        name="capability-relationships",
        command="axiom capability-relationships [--json-output]",
        description="List capability relationship reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List persisted capability relationship reports.",
    )
)

_register(
    CommandSpec(
        name="capability-relationship-show",
        command=(
            "axiom capability-relationship-show <report_id> [--json-output]"
        ),
        description="Show a capability relationship report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a persisted capability relationship report by report ID.",
    )
)

_register(
    CommandSpec(
        name="capability-relationship-export",
        command=(
            "axiom capability-relationship-export <report_id> "
            "[--format markdown|json|csv]"
        ),
        description="Export a capability relationship report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a capability relationship report as markdown/json/csv.",
    )
)

_register(
    CommandSpec(
        name="capability-impact-create",
        command=(
            "axiom capability-impact-create "
            "[--impact-file <if>] [--json-output]"
        ),
        description="Create a capability impact report (impacts + opps).",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("capability_impact_request.json", required=True),
            EvidenceOutput("capability_impact_result.json", required=True),
            EvidenceOutput("capability_impact_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Deterministic, append-only impacts/opportunities; no mutation.",
    )
)

_register(
    CommandSpec(
        name="capability-impacts",
        command="axiom capability-impacts [--json-output]",
        description="List capability impact reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List persisted capability impact reports.",
    )
)

_register(
    CommandSpec(
        name="capability-impact-show",
        command="axiom capability-impact-show <report_id> [--json-output]",
        description="Show a capability impact report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a persisted capability impact report by report ID.",
    )
)

_register(
    CommandSpec(
        name="capability-impact-export",
        command=(
            "axiom capability-impact-export <report_id> "
            "[--format markdown|json|csv]"
        ),
        description="Export a capability impact report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a capability impact report as markdown/json/csv.",
    )
)

_register(
    CommandSpec(
        name="capability-file-create",
        command=(
            "axiom capability-file-create "
            "[--file-file <ff>] [--json-output]"
        ),
        description="Create a capability file knowledge report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("capability_file_request.json", required=True),
            EvidenceOutput("capability_file_result.json", required=True),
            EvidenceOutput("capability_file_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Deterministic file relationships; dedup + dir aggregation.",
    )
)

_register(
    CommandSpec(
        name="capability-files",
        command="axiom capability-files [--json-output]",
        description="List capability file knowledge reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List persisted capability file knowledge reports.",
    )
)

_register(
    CommandSpec(
        name="capability-file-show",
        command="axiom capability-file-show <report_id> [--json-output]",
        description="Show a capability file knowledge report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a persisted capability file knowledge report by ID.",
    )
)

_register(
    CommandSpec(
        name="capability-file-export",
        command=(
            "axiom capability-file-export <report_id> "
            "[--format markdown|json|csv]"
        ),
        description="Export a capability file knowledge report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a capability file knowledge report (md/json/csv).",
    )
)

_register(
    CommandSpec(
        name="capability-validation-create",
        command=(
            "axiom capability-validation-create "
            "[--validation-file <vf>] [--json-output]"
        ),
        description="Create a capability validation knowledge report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput(
                "capability_validation_request.json", required=True
            ),
            EvidenceOutput(
                "capability_validation_result.json", required=True
            ),
            EvidenceOutput(
                "capability_validation_summary.md", required=True
            ),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Deterministic validations; dedup + unresolved detection.",
    )
)

_register(
    CommandSpec(
        name="capability-validations",
        command="axiom capability-validations [--json-output]",
        description="List capability validation knowledge reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List persisted capability validation knowledge reports.",
    )
)

_register(
    CommandSpec(
        name="capability-validation-show",
        command=(
            "axiom capability-validation-show <report_id> [--json-output]"
        ),
        description="Show a capability validation knowledge report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a persisted capability validation report by ID.",
    )
)

_register(
    CommandSpec(
        name="capability-validation-export",
        command=(
            "axiom capability-validation-export <report_id> "
            "[--format markdown|json|csv]"
        ),
        description="Export a capability validation knowledge report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a capability validation report (md/json/csv).",
    )
)

_register(
    CommandSpec(
        name="capability-graph-create",
        command=(
            "axiom capability-graph-create "
            "[--graph-file <gf>] [--json-output]"
        ),
        description="Create a capability knowledge graph report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("capability_graph_request.json", required=True),
            EvidenceOutput("capability_graph_result.json", required=True),
            EvidenceOutput("capability_graph_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Deterministic graph; dedup nodes/edges + orphan detection.",
    )
)

_register(
    CommandSpec(
        name="capability-graphs",
        command="axiom capability-graphs [--json-output]",
        description="List capability knowledge graph reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List persisted capability knowledge graph reports.",
    )
)

_register(
    CommandSpec(
        name="capability-graph-show",
        command="axiom capability-graph-show <report_id> [--json-output]",
        description="Show a capability knowledge graph report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a persisted capability knowledge graph report by ID.",
    )
)

_register(
    CommandSpec(
        name="capability-graph-export",
        command=(
            "axiom capability-graph-export <report_id> "
            "[--format markdown|json|csv]"
        ),
        description="Export a capability knowledge graph report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export a capability knowledge graph report (md/json/csv).",
    )
)

_register(
    CommandSpec(
        name="execution-context-create",
        command=(
            "axiom execution-context-create "
            "[--context-file <cf>] [--json-output]"
        ),
        description="Create an execution context report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("execution_context_request.json", required=True),
            EvidenceOutput("execution_context_result.json", required=True),
            EvidenceOutput("execution_context_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Deterministic contexts; state aggregation + blocked/failed.",
    )
)

_register(
    CommandSpec(
        name="execution-contexts",
        command="axiom execution-contexts [--json-output]",
        description="List execution context reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List persisted execution context reports.",
    )
)

_register(
    CommandSpec(
        name="execution-context-show",
        command="axiom execution-context-show <report_id> [--json-output]",
        description="Show an execution context report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a persisted execution context report by ID.",
    )
)

_register(
    CommandSpec(
        name="execution-context-export",
        command=(
            "axiom execution-context-export <report_id> "
            "[--format markdown|json|csv]"
        ),
        description="Export an execution context report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export an execution context report (md/json/csv).",
    )
)

_register(
    CommandSpec(
        name="execution-environment-create",
        command=(
            "axiom execution-environment-create "
            "[--environment-file <ef>] [--json-output]"
        ),
        description="Create an execution environment report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput(
                "execution_environment_request.json", required=True
            ),
            EvidenceOutput(
                "execution_environment_result.json", required=True
            ),
            EvidenceOutput(
                "execution_environment_summary.md", required=True
            ),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Deterministic environments; type/status + unavail/degraded.",
    )
)

_register(
    CommandSpec(
        name="execution-environments",
        command="axiom execution-environments [--json-output]",
        description="List execution environment reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List persisted execution environment reports.",
    )
)

_register(
    CommandSpec(
        name="execution-environment-show",
        command=(
            "axiom execution-environment-show <report_id> [--json-output]"
        ),
        description="Show an execution environment report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a persisted execution environment report by ID.",
    )
)

_register(
    CommandSpec(
        name="execution-environment-export",
        command=(
            "axiom execution-environment-export <report_id> "
            "[--format markdown|json|csv]"
        ),
        description="Export an execution environment report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export an execution environment report (md/json/csv).",
    )
)

_register(
    CommandSpec(
        name="execution-resource-create",
        command=(
            "axiom execution-resource-create "
            "[--resource-file <rf>] [--json-output]"
        ),
        description="Create an execution resource report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput(
                "execution_resource_request.json", required=True
            ),
            EvidenceOutput(
                "execution_resource_result.json", required=True
            ),
            EvidenceOutput(
                "execution_resource_summary.md", required=True
            ),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Deterministic resources; type/status + unavail/degraded.",
    )
)

_register(
    CommandSpec(
        name="execution-resources",
        command="axiom execution-resources [--json-output]",
        description="List execution resource reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List persisted execution resource reports.",
    )
)

_register(
    CommandSpec(
        name="execution-resource-show",
        command=(
            "axiom execution-resource-show <report_id> [--json-output]"
        ),
        description="Show an execution resource report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a persisted execution resource report by ID.",
    )
)

_register(
    CommandSpec(
        name="execution-resource-export",
        command=(
            "axiom execution-resource-export <report_id> "
            "[--format markdown|json|csv]"
        ),
        description="Export an execution resource report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export an execution resource report (md/json/csv).",
    )
)

_register(
    CommandSpec(
        name="execution-constraint-create",
        command=(
            "axiom execution-constraint-create "
            "[--constraint-file <cf>] [--json-output]"
        ),
        description="Create an execution constraint report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput(
                "execution_constraint_request.json", required=True
            ),
            EvidenceOutput(
                "execution_constraint_result.json", required=True
            ),
            EvidenceOutput(
                "execution_constraint_summary.md", required=True
            ),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Deterministic constraints; type/severity + critical/error.",
    )
)

_register(
    CommandSpec(
        name="execution-constraints",
        command="axiom execution-constraints [--json-output]",
        description="List execution constraint reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List persisted execution constraint reports.",
    )
)

_register(
    CommandSpec(
        name="execution-constraint-show",
        command=(
            "axiom execution-constraint-show <report_id> [--json-output]"
        ),
        description="Show an execution constraint report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a persisted execution constraint report by ID.",
    )
)

_register(
    CommandSpec(
        name="execution-constraint-export",
        command=(
            "axiom execution-constraint-export <report_id> "
            "[--format markdown|json|csv]"
        ),
        description="Export an execution constraint report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export an execution constraint report (md/json/csv).",
    )
)

_register(
    CommandSpec(
        name="execution-readiness-create",
        command=(
            "axiom execution-readiness-create "
            "[--readiness-file <rf>] [--json-output]"
        ),
        description="Create an execution readiness report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput(
                "execution_readiness_request.json", required=True
            ),
            EvidenceOutput(
                "execution_readiness_result.json", required=True
            ),
            EvidenceOutput(
                "execution_readiness_summary.md", required=True
            ),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Deterministic readiness; status/check + degraded/not-ready.",
    )
)

_register(
    CommandSpec(
        name="execution-readinesses",
        command="axiom execution-readinesses [--json-output]",
        description="List execution readiness reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List persisted execution readiness reports.",
    )
)

_register(
    CommandSpec(
        name="execution-readiness-show",
        command=(
            "axiom execution-readiness-show <report_id> [--json-output]"
        ),
        description="Show an execution readiness report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a persisted execution readiness report by ID.",
    )
)

_register(
    CommandSpec(
        name="execution-readiness-export",
        command=(
            "axiom execution-readiness-export <report_id> "
            "[--format markdown|json|csv]"
        ),
        description="Export an execution readiness report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export an execution readiness report (md/json/csv).",
    )
)

_register(
    CommandSpec(
        name="execution-plan-create",
        command=(
            "axiom execution-plan-create [--plan-file <pf>] [--json-output]"
        ),
        description="Create an execution plan report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("execution_plan_request.json", required=True),
            EvidenceOutput("execution_plan_result.json", required=True),
            EvidenceOutput("execution_plan_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Deterministic plans; status/type + blocked/failed + steps.",
    )
)

_register(
    CommandSpec(
        name="execution-plans",
        command="axiom execution-plans [--json-output]",
        description="List execution plan reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List persisted execution plan reports.",
    )
)

_register(
    CommandSpec(
        name="execution-plan-show",
        command="axiom execution-plan-show <report_id> [--json-output]",
        description="Show an execution plan report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a persisted execution plan report by ID.",
    )
)

_register(
    CommandSpec(
        name="execution-plan-export",
        command=(
            "axiom execution-plan-export <report_id> "
            "[--format markdown|json|csv]"
        ),
        description="Export an execution plan report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export an execution plan report (md/json/csv).",
    )
)

_register(
    CommandSpec(
        name="execution-step-create",
        command=(
            "axiom execution-step-create [--step-file <sf>] [--json-output]"
        ),
        description="Create an execution step report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("execution_step_request.json", required=True),
            EvidenceOutput("execution_step_result.json", required=True),
            EvidenceOutput("execution_step_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Deterministic steps; status/type + blocked/failed + refs.",
    )
)

_register(
    CommandSpec(
        name="execution-steps",
        command="axiom execution-steps [--json-output]",
        description="List execution step reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List persisted execution step reports.",
    )
)

_register(
    CommandSpec(
        name="execution-step-show",
        command="axiom execution-step-show <report_id> [--json-output]",
        description="Show an execution step report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a persisted execution step report by ID.",
    )
)

_register(
    CommandSpec(
        name="execution-step-export",
        command=(
            "axiom execution-step-export <report_id> "
            "[--format markdown|json|csv]"
        ),
        description="Export an execution step report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export an execution step report (md/json/csv).",
    )
)

_register(
    CommandSpec(
        name="execution-attempt-v2-create",
        command=(
            "axiom execution-attempt-v2-create "
            "[--attempt-file <af>] [--json-output]"
        ),
        description="Create an execution attempt (v2) report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("execution_attempt_request.json", required=True),
            EvidenceOutput("execution_attempt_result.json", required=True),
            EvidenceOutput("execution_attempt_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Deterministic attempts; status/result + duration + refs.",
    )
)

_register(
    CommandSpec(
        name="execution-attempts-v2",
        command="axiom execution-attempts-v2 [--json-output]",
        description="List execution attempt (v2) reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List persisted execution attempt reports.",
    )
)

_register(
    CommandSpec(
        name="execution-attempt-v2-show",
        command="axiom execution-attempt-v2-show <report_id> [--json-output]",
        description="Show an execution attempt (v2) report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a persisted execution attempt (v2) report by ID.",
    )
)

_register(
    CommandSpec(
        name="execution-attempt-v2-export",
        command=(
            "axiom execution-attempt-v2-export <report_id> "
            "[--format markdown|json|csv]"
        ),
        description="Export an execution attempt (v2) report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export an execution attempt (v2) report (md/json/csv).",
    )
)

_register(
    CommandSpec(
        name="execution-result-create",
        command=(
            "axiom execution-result-create "
            "[--result-file <rf>] [--json-output]"
        ),
        description="Create an execution result report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("execution_result_request.json", required=True),
            EvidenceOutput("execution_result_result.json", required=True),
            EvidenceOutput("execution_result_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Deterministic results; status/type aggregation + refs.",
    )
)

_register(
    CommandSpec(
        name="execution-results",
        command="axiom execution-results [--json-output]",
        description="List execution result reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List persisted execution result reports.",
    )
)

_register(
    CommandSpec(
        name="execution-result-show",
        command="axiom execution-result-show <report_id> [--json-output]",
        description="Show an execution result report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a persisted execution result report by ID.",
    )
)

_register(
    CommandSpec(
        name="execution-result-export",
        command=(
            "axiom execution-result-export <report_id> "
            "[--format markdown|json|csv]"
        ),
        description="Export an execution result report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export an execution result report (md/json/csv).",
    )
)

_register(
    CommandSpec(
        name="execution-artifact-create",
        command=(
            "axiom execution-artifact-create "
            "[--artifact-file <af>] [--json-output]"
        ),
        description="Create an execution artifact report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(
            EvidenceOutput("execution_artifact_request.json", required=True),
            EvidenceOutput("execution_artifact_result.json", required=True),
            EvidenceOutput("execution_artifact_summary.md", required=True),
            EvidenceOutput("pass_fail.json", required=True),
        ),
        timeout_seconds=60,
        failure_modes=(FM_NONZERO,),
        notes="Deterministic artifacts; status/type aggregation + refs.",
    )
)

_register(
    CommandSpec(
        name="execution-artifacts",
        command="axiom execution-artifacts [--json-output]",
        description="List execution artifact reports.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="List persisted execution artifact reports.",
    )
)

_register(
    CommandSpec(
        name="execution-artifact-show",
        command="axiom execution-artifact-show <report_id> [--json-output]",
        description="Show an execution artifact report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Show a persisted execution artifact report by ID.",
    )
)

_register(
    CommandSpec(
        name="execution-artifact-export",
        command=(
            "axiom execution-artifact-export <report_id> "
            "[--format markdown|json|csv]"
        ),
        description="Export an execution artifact report.",
        classification=CommandClass.READ_ONLY,
        safety_level=SafetyLevel.SAFE,
        prerequisites=(Prerequisite.POETRY_ENV,),
        evidence_outputs=(EV_CONSOLE,),
        timeout_seconds=30,
        failure_modes=(FM_NONZERO,),
        notes="Export an execution artifact report (md/json/csv).",
    )
)


# ---------------------------------------------------------------------------
# CommandRegistry — the governed catalog as an object
# ---------------------------------------------------------------------------


class CommandRegistry:
    """The execution policy layer: the set of commands the runner is allowed to
    run, plus governance queries over them.

    Read-only governance — it answers "is this allowed, and how is its result
    judged?" and "may it run in this :class:`ExecutionContext`?". It never
    executes a command. Unknown commands are denied by default.
    """

    def __init__(self, commands: dict[str, AllowedCommand]):
        self._commands = dict(commands)

    def list_commands(self) -> list[AllowedCommand]:
        """All allowed commands, sorted by name."""
        return [self._commands[name] for name in sorted(self._commands)]

    def command_names(self) -> list[str]:
        return sorted(self._commands)

    def get(self, name: str) -> AllowedCommand | None:
        """The :class:`AllowedCommand` for ``name``, or None if not cataloged."""
        return self._commands.get(name)

    def is_allowed(self, name: str) -> bool:
        """Whether ``name`` is explicitly cataloged. Unknown ⇒ denied."""
        return name in self._commands

    def by_classification(self, classification: CommandClass) -> list[AllowedCommand]:
        return [c for c in self.list_commands()
                if c.classification is classification]

    def runnable_in(self, context: ExecutionContext) -> list[AllowedCommand]:
        """Allowed commands whose prerequisites are all met by ``context``."""
        return [c for c in self.list_commands() if c.can_run(context)]

    def validate(self) -> None:
        """Assert structural integrity. Raises ValueError on problems. No I/O."""
        for name, spec in self._commands.items():
            if name != spec.name:
                raise ValueError(f"Catalog key '{name}' != spec.name '{spec.name}'")
            if not spec.command.strip():
                raise ValueError(f"Command '{name}' has an empty invocation string")
            if not spec.description.strip():
                raise ValueError(f"Command '{name}' has no description")
            if spec.timeout_seconds <= 0:
                raise ValueError(f"Command '{name}' has a non-positive timeout")
            if not spec.failure_modes:
                raise ValueError(f"Command '{name}' declares no failure modes")
            if not spec.evidence_outputs:
                raise ValueError(f"Command '{name}' declares no evidence outputs")
            if not isinstance(spec.classification, CommandClass):
                raise ValueError(f"Command '{name}' has an invalid classification")
            if not isinstance(spec.safety_level, SafetyLevel):
                raise ValueError(f"Command '{name}' has an invalid safety level")
            for ev in spec.evidence_outputs:
                if not isinstance(ev, EvidenceOutput):
                    raise ValueError(f"Command '{name}' has a non-EvidenceOutput output")


# The default registry, built from the module catalog above.
DEFAULT_REGISTRY = CommandRegistry(_CATALOG)


# ---------------------------------------------------------------------------
# Public API (module-level convenience — delegate to DEFAULT_REGISTRY)
# ---------------------------------------------------------------------------


def list_commands() -> list[AllowedCommand]:
    """Return all cataloged commands, sorted by name."""
    return DEFAULT_REGISTRY.list_commands()


def command_names() -> list[str]:
    """Return the allowed command names, sorted."""
    return DEFAULT_REGISTRY.command_names()


def get_command(name: str) -> AllowedCommand | None:
    """Return the :class:`AllowedCommand` for ``name``, or None if not cataloged."""
    return DEFAULT_REGISTRY.get(name)


def is_allowed(name: str) -> bool:
    """Whether ``name`` is an explicitly cataloged (allowed) command.

    Unknown commands are denied by default.
    """
    return DEFAULT_REGISTRY.is_allowed(name)


def commands_by_classification(classification: CommandClass) -> list[AllowedCommand]:
    """All cataloged commands with the given classification, sorted by name."""
    return DEFAULT_REGISTRY.by_classification(classification)


def validate_catalog() -> None:
    """Assert structural integrity of the default catalog. Raises on problems."""
    DEFAULT_REGISTRY.validate()


# Fail fast at import if the catalog is structurally broken.
validate_catalog()
