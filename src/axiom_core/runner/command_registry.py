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
