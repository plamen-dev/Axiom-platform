"""Axiom runner governance — the execution policy layer.

The Runner Command Registry declares which local commands the AXIOM-01 runner
is allowed to execute, with safety classification, prerequisites, evidence
expectations, timeouts, and failure classification. It is pure metadata
(no execution); runners and future automation loops consult it before acting.
"""

from __future__ import annotations

from axiom_core.runner.capability_runner import (
    CapabilityOutcome,
    CapabilityRunner,
    CapabilityRunResult,
)
from axiom_core.runner.capability_state import (
    CapabilityHistory,
    CapabilityHistoryEvent,
    CapabilitySnapshot,
    CapabilityState,
    CapabilityStateRegistry,
    CapabilityStatus,
)
from axiom_core.runner.command_registry import (
    DEFAULT_REGISTRY,
    AllowedCommand,
    CommandClass,
    CommandRegistry,
    CommandSpec,
    EvidenceOutput,
    ExecutionContext,
    FailureClass,
    FailureClassification,
    FailureMode,
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

__all__ = [
    "CapabilityOutcome",
    "CapabilityRunner",
    "CapabilityRunResult",
    "CapabilityHistory",
    "CapabilityHistoryEvent",
    "CapabilitySnapshot",
    "CapabilityState",
    "CapabilityStateRegistry",
    "CapabilityStatus",
    "DEFAULT_REGISTRY",
    "AllowedCommand",
    "CommandClass",
    "CommandRegistry",
    "CommandSpec",
    "EvidenceOutput",
    "ExecutionContext",
    "FailureClass",
    "FailureClassification",
    "FailureMode",
    "Prerequisite",
    "SafetyLevel",
    "Timeout",
    "command_names",
    "commands_by_classification",
    "get_command",
    "is_allowed",
    "list_commands",
    "validate_catalog",
]
