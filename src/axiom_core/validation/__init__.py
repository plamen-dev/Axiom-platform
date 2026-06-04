"""Axiom capability validation governance — the validation policy layer.

The Capability Validation Registry declares, for each Axiom capability, how it
is validated: the procedure, required inputs/environment, evidence contract,
pass/failure criteria, retry policy, and promotion-eligibility contract. It is
pure metadata (no execution); validation loops consult it before acting.
Unknown capabilities are denied by default.

Scope: governance/validation infrastructure only — no autonomous execution,
scheduling, promotion engine, learning loop, or workflow generation.
"""

from __future__ import annotations

from axiom_core.validation.evidence_runner import (
    EXIT_CODES,
    CheckResult,
    EvidenceOutcome,
    EvidenceRunner,
    SupportedValidation,
    ValidationRunResult,
)
from axiom_core.validation.persistence import (
    load_procedure_names,
    persist_default_registry,
    upsert_procedures,
)
from axiom_core.validation.validation_registry import (
    DEFAULT_REGISTRY,
    CapabilityType,
    CapabilityValidationRegistry,
    EnvironmentRequirement,
    EvidenceItem,
    EvidenceKind,
    FailureCondition,
    PassCondition,
    PromotionEligibility,
    RetryPolicy,
    ValidationEvidence,
    ValidationProcedure,
    ValidationResult,
    ValidationStatus,
    get_procedure,
    is_known,
    list_procedures,
    procedure_names,
    procedures_by_capability_type,
    validate_registry,
)

__all__ = [
    "DEFAULT_REGISTRY",
    "CapabilityType",
    "CapabilityValidationRegistry",
    "EnvironmentRequirement",
    "EvidenceItem",
    "EvidenceKind",
    "FailureCondition",
    "PassCondition",
    "PromotionEligibility",
    "RetryPolicy",
    "ValidationEvidence",
    "ValidationProcedure",
    "ValidationResult",
    "ValidationStatus",
    "get_procedure",
    "is_known",
    "list_procedures",
    "procedure_names",
    "procedures_by_capability_type",
    "validate_registry",
    # persistence
    "load_procedure_names",
    "persist_default_registry",
    "upsert_procedures",
    # evidence runner (PR #25)
    "EvidenceRunner",
    "EvidenceOutcome",
    "ValidationRunResult",
    "CheckResult",
    "SupportedValidation",
    "EXIT_CODES",
]
