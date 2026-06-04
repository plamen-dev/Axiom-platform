"""Capability Validation Registry — the governed catalog of how Axiom
capabilities are validated.

This is the **validation governance layer**: a declarative, read-only catalog
that states, for each capability, *how* it is validated (the procedure), *what
evidence* is required, *how pass/fail is determined*, *when retries are
allowed*, and *when a capability becomes promotion-eligible*. It does NOT
execute, schedule, score, promote, or learn — it is consulted by future
validation loops before they act.

Architecture boundary (see docs/architecture/capability-validation-registry.md):
  - This module is pure governance/metadata. No subprocess, no I/O, no Revit.
    Optional SQLite persistence lives in ``axiom_core.validation.persistence``.
  - Unknown capabilities are denied by default: ``is_known`` returns False for
    anything not explicitly cataloged here.

Scope (PR #23): governance/validation infrastructure only. No autonomous
execution, no scheduling, no promotion engine, no learning loop, no workflow
generation. Promotion eligibility is a *contract* (a pure predicate), not an
engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# ---------------------------------------------------------------------------
# Classification enums
# ---------------------------------------------------------------------------


class CapabilityType(str, Enum):
    """The nature of the capability being validated."""

    INVENTORY = "inventory"      # model inventory / export (InventoryModel)
    DISCOVERY = "discovery"      # interpretation over an export (DiscoveryHarness)
    MUTATION = "mutation"        # changes model/repo state (SetParameterValue)
    BRIDGE = "bridge"            # request/response over the Revit pipe (BridgeExecute)
    CREATION = "creation"        # creates elements (CreateGrids/CreateLevels — future)


class EnvironmentRequirement(str, Enum):
    """A runtime condition a validation procedure needs before it can run.

    Mirrors the ``requires_*`` vocabulary requested for PR #23, plus a few
    toolchain conditions shared with the Runner Command Registry (PR #22).
    """

    POETRY_ENV = "poetry_env"                    # poetry virtualenv available
    REQUIRES_REVIT = "requires_revit"            # a running Revit add-in
    REQUIRES_MODEL_OPEN = "requires_model_open"  # a document open in Revit
    REQUIRES_TEST_MODEL = "requires_test_model"  # a disposable/sample model to mutate
    REQUIRES_RUNNER = "requires_runner"          # the AXIOM-01 local runner online
    REQUIRES_INVENTORY_EXPORT = "requires_inventory_export"  # an InventoryModel export
    REQUIRES_DB_PATH = "requires_db_path"        # writable SQLite db path


class EvidenceKind(str, Enum):
    """The kind of evidence a procedure requires."""

    ARTIFACT = "artifact"        # a file on disk (request.json, parameters.parquet…)
    LOG = "log"                  # a captured log / console transcript
    CHECKPOINT = "checkpoint"    # a recorded progress checkpoint
    STATE = "state"              # a before/after state snapshot


class PassCondition(str, Enum):
    """A condition that, when satisfied, contributes to a passing validation."""

    ARTIFACTS_EXIST = "artifacts_exist"
    ROW_COUNTS_POSITIVE = "row_counts_positive"
    CATEGORIES_DISCOVERED = "categories_discovered"
    PARAMETERS_DISCOVERED = "parameters_discovered"
    CANDIDATES_GENERATED = "candidates_generated"
    DISCOVERY_COMPLETE = "discovery_complete"
    PARAMETER_VALUE_MATCHES = "parameter_value_matches"
    ELEMENT_CREATED = "element_created"
    ELEMENT_COUNT_MATCHES = "element_count_matches"
    RESULT_RECEIVED = "result_received"
    CHECKPOINTS_PRESENT = "checkpoints_present"
    EVIDENCE_BUNDLE_PRESENT = "evidence_bundle_present"


class FailureCondition(str, Enum):
    """A condition that classifies a failed validation."""

    EXCEPTION = "exception"
    TIMEOUT = "timeout"
    INCORRECT_RESULT = "incorrect_result"
    MISSING_EVIDENCE = "missing_evidence"
    VALUE_MISMATCH = "value_mismatch"
    ZERO_ROWS = "zero_rows"
    INCOMPLETE_DISCOVERY = "incomplete_discovery"
    PIPE_UNAVAILABLE = "pipe_unavailable"


class ValidationStatus(str, Enum):
    """The outcome status recorded on a :class:`ValidationResult`.

    This is the contract a future validation loop would record. Nothing in this
    module produces a non-``UNTESTED`` status — execution is out of scope.
    """

    UNTESTED = "untested"
    PASSED = "passed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"


# ---------------------------------------------------------------------------
# Evidence contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceItem:
    """A single required piece of evidence (an artifact, log, checkpoint, or
    state snapshot)."""

    kind: EvidenceKind
    name: str
    description: str = ""
    required: bool = True

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "name": self.name,
            "description": self.description,
            "required": self.required,
        }


@dataclass(frozen=True)
class ValidationEvidence:
    """The evidence contract for a validation procedure.

    Groups the required artifacts, logs, and checkpoints (the three evidence
    classes requested for PR #23). Plain strings are accepted for brevity in the
    catalog and coerced to :class:`EvidenceItem` of the matching kind.
    """

    required_artifacts: tuple[EvidenceItem, ...] = ()
    required_logs: tuple[EvidenceItem, ...] = ()
    required_checkpoints: tuple[EvidenceItem, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_artifacts",
                           self._coerce(self.required_artifacts, EvidenceKind.ARTIFACT))
        object.__setattr__(self, "required_logs",
                           self._coerce(self.required_logs, EvidenceKind.LOG))
        object.__setattr__(self, "required_checkpoints",
                           self._coerce(self.required_checkpoints, EvidenceKind.CHECKPOINT))

    @staticmethod
    def _coerce(items, kind: EvidenceKind) -> tuple[EvidenceItem, ...]:
        return tuple(
            it if isinstance(it, EvidenceItem) else EvidenceItem(kind=kind, name=str(it))
            for it in items
        )

    def all_items(self) -> list[EvidenceItem]:
        return [*self.required_artifacts, *self.required_logs, *self.required_checkpoints]

    def required_items(self) -> list[EvidenceItem]:
        return [it for it in self.all_items() if it.required]

    def to_dict(self) -> dict:
        return {
            "required_artifacts": [it.to_dict() for it in self.required_artifacts],
            "required_logs": [it.to_dict() for it in self.required_logs],
            "required_checkpoints": [it.to_dict() for it in self.required_checkpoints],
        }


# ---------------------------------------------------------------------------
# Retry + promotion contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetryPolicy:
    """When a failed validation may be retried.

    Contract only — this module never retries anything. ``should_retry`` is a
    pure predicate a future loop can consult.
    """

    max_retries: int = 0
    retry_delay_seconds: int = 0
    retry_conditions: tuple[FailureCondition, ...] = ()

    def should_retry(self, condition: FailureCondition) -> bool:
        """Whether ``condition`` is a retryable failure under this policy."""
        return self.max_retries > 0 and condition in self.retry_conditions

    def to_dict(self) -> dict:
        return {
            "max_retries": self.max_retries,
            "retry_delay_seconds": self.retry_delay_seconds,
            "retry_conditions": [c.value for c in self.retry_conditions],
        }


@dataclass(frozen=True)
class PromotionEligibility:
    """The contract for when a capability becomes promotion-eligible.

    Contract only — PR #23 does NOT implement promotion. ``is_eligible`` is a
    pure predicate that evaluates the contract against observed counts; it has
    no state, no scoring engine, and triggers nothing.
    """

    minimum_successes: int = 3
    minimum_evidence_sets: int = 3
    required_confidence: float = 0.8

    def is_eligible(self, successes: int, evidence_sets: int, confidence: float) -> bool:
        """Pure evaluation of the contract — does NOT promote anything."""
        return (
            successes >= self.minimum_successes
            and evidence_sets >= self.minimum_evidence_sets
            and confidence >= self.required_confidence
        )

    def to_dict(self) -> dict:
        return {
            "minimum_successes": self.minimum_successes,
            "minimum_evidence_sets": self.minimum_evidence_sets,
            "required_confidence": self.required_confidence,
        }


# ---------------------------------------------------------------------------
# Validation result (record contract)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationResult:
    """The record a future validation loop produces for one validation attempt.

    Pure data — defining this type does not execute or evaluate anything. Status
    defaults to :attr:`ValidationStatus.UNTESTED` because PR #23 ships no
    executor.
    """

    capability_name: str
    validation_procedure_id: str
    status: ValidationStatus = ValidationStatus.UNTESTED
    pass_conditions_met: tuple[PassCondition, ...] = ()
    failure_condition: FailureCondition | None = None
    evidence_refs: tuple[str, ...] = ()
    attempts: int = 0
    notes: str = ""

    @property
    def passed(self) -> bool:
        return self.status is ValidationStatus.PASSED

    def to_dict(self) -> dict:
        return {
            "capability_name": self.capability_name,
            "validation_procedure_id": self.validation_procedure_id,
            "status": self.status.value,
            "pass_conditions_met": [c.value for c in self.pass_conditions_met],
            "failure_condition": self.failure_condition.value if self.failure_condition else None,
            "evidence_refs": list(self.evidence_refs),
            "attempts": self.attempts,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Validation procedure (the catalog entry)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationProcedure:
    """How a single capability is validated — the per-capability catalog entry.

    Combines identity, the procedure steps, input contract, environment
    requirements, evidence contract, pass/failure criteria, retry policy, and
    promotion-eligibility contract. This is governance metadata only; nothing
    here executes a validation.
    """

    # --- identity ---------------------------------------------------------
    capability_name: str
    capability_type: CapabilityType
    adapter: str
    version: str

    # --- validation procedure --------------------------------------------
    validation_procedure_id: str
    validation_name: str
    validation_description: str
    steps: tuple[str, ...] = ()

    # --- inputs -----------------------------------------------------------
    required_inputs: tuple[str, ...] = ()
    optional_inputs: tuple[str, ...] = ()
    environment_requirements: tuple[EnvironmentRequirement, ...] = ()

    # --- evidence / criteria ---------------------------------------------
    evidence: ValidationEvidence = field(default_factory=ValidationEvidence)
    pass_conditions: tuple[PassCondition, ...] = ()
    failure_conditions: tuple[FailureCondition, ...] = ()

    # --- retry / promotion contracts -------------------------------------
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    promotion_eligibility: PromotionEligibility = field(default_factory=PromotionEligibility)

    notes: str = ""

    # --- explicit, first-class environment predicates --------------------

    @property
    def requires_revit(self) -> bool:
        return EnvironmentRequirement.REQUIRES_REVIT in self.environment_requirements

    @property
    def requires_model_open(self) -> bool:
        return EnvironmentRequirement.REQUIRES_MODEL_OPEN in self.environment_requirements

    @property
    def requires_test_model(self) -> bool:
        return EnvironmentRequirement.REQUIRES_TEST_MODEL in self.environment_requirements

    @property
    def requires_runner(self) -> bool:
        return EnvironmentRequirement.REQUIRES_RUNNER in self.environment_requirements

    @property
    def is_mutation(self) -> bool:
        return self.capability_type is CapabilityType.MUTATION

    def to_dict(self) -> dict:
        return {
            "capability_name": self.capability_name,
            "capability_type": self.capability_type.value,
            "adapter": self.adapter,
            "version": self.version,
            "validation_procedure_id": self.validation_procedure_id,
            "validation_name": self.validation_name,
            "validation_description": self.validation_description,
            "steps": list(self.steps),
            "required_inputs": list(self.required_inputs),
            "optional_inputs": list(self.optional_inputs),
            "environment_requirements": [e.value for e in self.environment_requirements],
            "evidence": self.evidence.to_dict(),
            "pass_conditions": [c.value for c in self.pass_conditions],
            "failure_conditions": [c.value for c in self.failure_conditions],
            "retry_policy": self.retry_policy.to_dict(),
            "promotion_eligibility": self.promotion_eligibility.to_dict(),
            "requires_revit": self.requires_revit,
            "requires_model_open": self.requires_model_open,
            "requires_test_model": self.requires_test_model,
            "requires_runner": self.requires_runner,
            "is_mutation": self.is_mutation,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Seed catalog — initial validation definitions (PR #23)
# ---------------------------------------------------------------------------

_CATALOG: dict[str, ValidationProcedure] = {}


def _register(proc: ValidationProcedure) -> None:
    if proc.capability_name in _CATALOG:
        raise ValueError(f"Duplicate capability in registry: {proc.capability_name}")
    _CATALOG[proc.capability_name] = proc


_register(
    ValidationProcedure(
        capability_name="InventoryModel",
        capability_type=CapabilityType.INVENTORY,
        adapter="revit",
        version="v1",
        validation_procedure_id="inventory_model.export_and_verify",
        validation_name="InventoryModel export + artifact verification",
        validation_description=(
            "Run a parameter-collecting InventoryModel export, then verify the "
            "run folder contains the expected artifacts with non-zero row counts."
        ),
        steps=(
            "Execute",
            "Export inventory",
            "Verify artifacts exist",
            "Verify row counts > 0",
            "Generate evidence",
        ),
        required_inputs=("source_model",),
        optional_inputs=("category_filter", "summary_only", "max_elements"),
        environment_requirements=(
            EnvironmentRequirement.POETRY_ENV,
            EnvironmentRequirement.REQUIRES_REVIT,
            EnvironmentRequirement.REQUIRES_MODEL_OPEN,
        ),
        evidence=ValidationEvidence(
            required_artifacts=(
                "elements.jsonl",
                "parameters.parquet",
                "parameters.csv",
                "run_metadata.json",
                "summary.md",
            ),
            required_logs=("inventory-import console summary",),
            required_checkpoints=("persist_inventory completed",),
        ),
        pass_conditions=(
            PassCondition.ARTIFACTS_EXIST,
            PassCondition.ROW_COUNTS_POSITIVE,
        ),
        failure_conditions=(
            FailureCondition.EXCEPTION,
            FailureCondition.TIMEOUT,
            FailureCondition.MISSING_EVIDENCE,
            FailureCondition.ZERO_ROWS,
        ),
        retry_policy=RetryPolicy(
            max_retries=1,
            retry_delay_seconds=0,
            retry_conditions=(FailureCondition.TIMEOUT,),
        ),
        promotion_eligibility=PromotionEligibility(
            minimum_successes=3, minimum_evidence_sets=3, required_confidence=0.8
        ),
        notes=(
            "Summary-mode InventoryModel emits zero parameters by design; "
            "ROW_COUNTS_POSITIVE requires a parameter-collecting scan, not a "
            "summary scan."
        ),
    )
)


_register(
    ValidationProcedure(
        capability_name="DiscoveryHarness",
        capability_type=CapabilityType.DISCOVERY,
        adapter="revit",
        version="v1",
        validation_procedure_id="discovery_harness.run_and_verify",
        validation_name="DiscoveryHarness run + completeness verification",
        validation_description=(
            "Run discovery over an InventoryModel export folder and verify that "
            "categories, parameters, and candidate capabilities are discovered "
            "and that discovery reports complete."
        ),
        steps=(
            "Run discovery",
            "Verify categories discovered",
            "Verify parameters discovered",
            "Verify candidates generated",
            "Verify discovery_complete",
        ),
        required_inputs=("inventory_export_path",),
        optional_inputs=("db_path", "adapter"),
        environment_requirements=(
            EnvironmentRequirement.POETRY_ENV,
            EnvironmentRequirement.REQUIRES_INVENTORY_EXPORT,
        ),
        evidence=ValidationEvidence(
            required_artifacts=(
                "summary.json",
                "categories.csv",
                "parameters.csv",
                "candidate_capabilities.csv",
            ),
            required_logs=("discovery-run console summary",),
            required_checkpoints=("discovery_complete flag recorded",),
        ),
        pass_conditions=(
            PassCondition.CATEGORIES_DISCOVERED,
            PassCondition.PARAMETERS_DISCOVERED,
            PassCondition.CANDIDATES_GENERATED,
            PassCondition.DISCOVERY_COMPLETE,
        ),
        failure_conditions=(
            FailureCondition.INCOMPLETE_DISCOVERY,
            FailureCondition.ZERO_ROWS,
            FailureCondition.MISSING_EVIDENCE,
            FailureCondition.EXCEPTION,
        ),
        retry_policy=RetryPolicy(max_retries=0),
        promotion_eligibility=PromotionEligibility(
            minimum_successes=3, minimum_evidence_sets=3, required_confidence=0.8
        ),
        notes=(
            "Read-only over an export. Discovery is deterministic, so retries "
            "are not expected to change the result (max_retries=0)."
        ),
    )
)


_register(
    ValidationProcedure(
        capability_name="SetParameterValue",
        capability_type=CapabilityType.MUTATION,
        adapter="revit",
        version="v0",
        validation_procedure_id="set_parameter_value.write_read_compare",
        validation_name="SetParameterValue write/read/compare (definition only)",
        validation_description=(
            "Validation DEFINITION ONLY — not executed in PR #23. Describes how a "
            "future loop would prove a parameter write: create a test element, "
            "read, write, read back, and compare."
        ),
        steps=(
            "Create test element",
            "Read value",
            "Write value",
            "Read value",
            "Compare",
            "Generate evidence",
        ),
        required_inputs=("category", "parameter_name", "new_value", "element_selector"),
        optional_inputs=("max_elements",),
        environment_requirements=(
            EnvironmentRequirement.POETRY_ENV,
            EnvironmentRequirement.REQUIRES_REVIT,
            EnvironmentRequirement.REQUIRES_MODEL_OPEN,
            EnvironmentRequirement.REQUIRES_TEST_MODEL,
        ),
        evidence=ValidationEvidence(
            required_artifacts=(
                "request.json",
                "response.json",
                "pass_fail.json",
            ),
            required_logs=("SetParameterValue evidence bundle",),
            required_checkpoints=(
                EvidenceItem(EvidenceKind.STATE, "before_state"),
                EvidenceItem(EvidenceKind.STATE, "after_state"),
                EvidenceItem(EvidenceKind.CHECKPOINT, "preview_verified"),
                EvidenceItem(EvidenceKind.CHECKPOINT, "apply_completed"),
            ),
        ),
        pass_conditions=(PassCondition.PARAMETER_VALUE_MATCHES,),
        failure_conditions=(
            FailureCondition.EXCEPTION,
            FailureCondition.TIMEOUT,
            FailureCondition.VALUE_MISMATCH,
            FailureCondition.MISSING_EVIDENCE,
            FailureCondition.PIPE_UNAVAILABLE,
        ),
        retry_policy=RetryPolicy(
            max_retries=1,
            retry_delay_seconds=0,
            retry_conditions=(FailureCondition.PIPE_UNAVAILABLE, FailureCondition.TIMEOUT),
        ),
        promotion_eligibility=PromotionEligibility(
            minimum_successes=5, minimum_evidence_sets=5, required_confidence=0.9
        ),
        notes=(
            "DEFINITION ONLY — PR #23 does not execute SetParameterValue. A "
            "mutation must be previewed before apply and validated on a "
            "disposable/sample model first; higher promotion bar than read-only "
            "capabilities."
        ),
    )
)


_register(
    ValidationProcedure(
        capability_name="BridgeExecute",
        capability_type=CapabilityType.BRIDGE,
        adapter="revit",
        version="v0",
        validation_procedure_id="bridge_execute.request_response_verify",
        validation_name="Bridge Execute request/response verification",
        validation_description=(
            "Send a request over the Revit automation bridge, receive the "
            "result, and verify the recorded checkpoints and evidence bundle."
        ),
        steps=(
            "Send request",
            "Receive result",
            "Verify checkpoints",
            "Verify evidence bundle",
        ),
        required_inputs=("capability", "args"),
        optional_inputs=("timeout",),
        environment_requirements=(
            EnvironmentRequirement.POETRY_ENV,
            EnvironmentRequirement.REQUIRES_REVIT,
            EnvironmentRequirement.REQUIRES_RUNNER,
        ),
        evidence=ValidationEvidence(
            required_artifacts=(
                "request.json",
                "response.json",
            ),
            required_logs=("pipe transcript",),
            required_checkpoints=("bridge checkpoints recorded",),
        ),
        pass_conditions=(
            PassCondition.RESULT_RECEIVED,
            PassCondition.CHECKPOINTS_PRESENT,
            PassCondition.EVIDENCE_BUNDLE_PRESENT,
        ),
        failure_conditions=(
            FailureCondition.PIPE_UNAVAILABLE,
            FailureCondition.TIMEOUT,
            FailureCondition.EXCEPTION,
            FailureCondition.MISSING_EVIDENCE,
        ),
        retry_policy=RetryPolicy(
            max_retries=2,
            retry_delay_seconds=2,
            retry_conditions=(FailureCondition.PIPE_UNAVAILABLE, FailureCondition.TIMEOUT),
        ),
        promotion_eligibility=PromotionEligibility(
            minimum_successes=3, minimum_evidence_sets=3, required_confidence=0.8
        ),
        notes=(
            "The bridge is the transport for live-Revit capabilities; "
            "pipe-unavailable and timeout are the expected transient failures."
        ),
    )
)


# ---------------------------------------------------------------------------
# CapabilityValidationRegistry — the governed catalog as an object
# ---------------------------------------------------------------------------


class CapabilityValidationRegistry:
    """The validation governance layer: the set of capabilities Axiom knows how
    to validate, plus governance queries over them.

    Read-only governance — it answers "how is this capability validated, what
    evidence is required, and when is it promotion-eligible?". It never executes
    a validation. Unknown capabilities are denied by default.
    """

    def __init__(self, procedures: dict[str, ValidationProcedure]):
        self._procedures = dict(procedures)

    def list_procedures(self) -> list[ValidationProcedure]:
        """All validation procedures, sorted by capability name."""
        return [self._procedures[name] for name in sorted(self._procedures)]

    def procedure_names(self) -> list[str]:
        return sorted(self._procedures)

    def get(self, capability_name: str) -> ValidationProcedure | None:
        """The procedure for ``capability_name``, or None if not cataloged."""
        return self._procedures.get(capability_name)

    def is_known(self, capability_name: str) -> bool:
        """Whether ``capability_name`` is cataloged. Unknown ⇒ denied."""
        return capability_name in self._procedures

    def by_capability_type(self, capability_type: CapabilityType) -> list[ValidationProcedure]:
        return [p for p in self.list_procedures()
                if p.capability_type is capability_type]

    def by_adapter(self, adapter: str) -> list[ValidationProcedure]:
        return [p for p in self.list_procedures() if p.adapter == adapter]

    def validate(self) -> None:
        """Assert structural integrity. Raises ValueError on problems. No I/O."""
        seen_ids: set[str] = set()
        for name, proc in self._procedures.items():
            if name != proc.capability_name:
                raise ValueError(
                    f"Registry key '{name}' != capability_name '{proc.capability_name}'")
            if not proc.validation_procedure_id.strip():
                raise ValueError(f"'{name}' has an empty validation_procedure_id")
            if proc.validation_procedure_id in seen_ids:
                raise ValueError(
                    f"Duplicate validation_procedure_id '{proc.validation_procedure_id}'")
            seen_ids.add(proc.validation_procedure_id)
            if not proc.validation_name.strip():
                raise ValueError(f"'{name}' has no validation_name")
            if not proc.validation_description.strip():
                raise ValueError(f"'{name}' has no validation_description")
            if not proc.steps:
                raise ValueError(f"'{name}' declares no procedure steps")
            if not proc.pass_conditions:
                raise ValueError(f"'{name}' declares no pass conditions")
            if not proc.failure_conditions:
                raise ValueError(f"'{name}' declares no failure conditions")
            if not proc.evidence.required_items():
                raise ValueError(f"'{name}' declares no required evidence")
            if not isinstance(proc.capability_type, CapabilityType):
                raise ValueError(f"'{name}' has an invalid capability_type")
            if not 0.0 <= proc.promotion_eligibility.required_confidence <= 1.0:
                raise ValueError(f"'{name}' has required_confidence outside [0,1]")
            for cond in proc.retry_policy.retry_conditions:
                if cond not in proc.failure_conditions:
                    raise ValueError(
                        f"'{name}' retry condition '{cond.value}' is not a "
                        f"declared failure condition")


# The default registry, built from the module catalog above.
DEFAULT_REGISTRY = CapabilityValidationRegistry(_CATALOG)


# ---------------------------------------------------------------------------
# Public API (module-level convenience — delegate to DEFAULT_REGISTRY)
# ---------------------------------------------------------------------------


def list_procedures() -> list[ValidationProcedure]:
    """Return all cataloged validation procedures, sorted by capability name."""
    return DEFAULT_REGISTRY.list_procedures()


def procedure_names() -> list[str]:
    """Return the known capability names, sorted."""
    return DEFAULT_REGISTRY.procedure_names()


def get_procedure(capability_name: str) -> ValidationProcedure | None:
    """Return the procedure for ``capability_name``, or None if not cataloged."""
    return DEFAULT_REGISTRY.get(capability_name)


def is_known(capability_name: str) -> bool:
    """Whether ``capability_name`` is cataloged. Unknown commands denied by default."""
    return DEFAULT_REGISTRY.is_known(capability_name)


def procedures_by_capability_type(capability_type: CapabilityType) -> list[ValidationProcedure]:
    """All cataloged procedures with the given capability type, sorted by name."""
    return DEFAULT_REGISTRY.by_capability_type(capability_type)


def validate_registry() -> None:
    """Assert structural integrity of the default registry. Raises on problems."""
    DEFAULT_REGISTRY.validate()


# Fail fast at import if the seed registry is structurally broken.
validate_registry()
