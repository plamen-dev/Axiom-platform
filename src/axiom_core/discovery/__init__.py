"""DiscoveryHarness v1 - interpret InventoryModel exports into registries.

Pure interpreter that sits ABOVE InventoryModel (the single source of truth for
extraction). It reads existing InventoryModel exports and converts them into the
ProductObjectRegistry, ProductPropertyRegistry, DiscoveryEvidence, discovery run
reports, and candidate capability definitions. It never scans, mutates, or
executes candidates.
"""

from .harness import DiscoveryRunResult, run_discovery
from .interpret import (
    CandidateCapability,
    DiscoveredCategory,
    DiscoveredProperty,
    DiscoveryMetrics,
    Interpretation,
    interpret_export,
)

__all__ = [
    "run_discovery",
    "DiscoveryRunResult",
    "interpret_export",
    "Interpretation",
    "DiscoveredCategory",
    "DiscoveredProperty",
    "CandidateCapability",
    "DiscoveryMetrics",
]
