"""Data models for the grid test harness."""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class GridTestCase:
    """A single test case for CreateGrids."""

    test_id: str
    prompt: str
    expected_capability: Optional[str]
    expected_parameters: dict[str, Any]
    expected_created_count: int
    expected_success: bool
    mode: str  # "simulate" or "real"
    notes: str = ""
    expected_failure_reason: Optional[str] = None
    expected_status: Optional[str] = None  # e.g. "CLARIFICATION_NEEDED"


@dataclass
class GridTestResult:
    """Result of running a single grid test case."""

    test_id: str
    prompt: str
    mode: str
    git_commit: str
    git_branch: str
    timestamp: str

    # Resolution
    resolved_capability: Optional[str] = None
    resolved_parameters: dict[str, Any] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)

    # Execution
    pipe_available: bool = False
    status: str = ""  # SUCCESS, FAILED, UNRESOLVED
    created_count: int = 0
    created_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0

    # Verdict
    expected_success: bool = True
    expected_created_count: int = 0
    expected_capability: Optional[str] = None
    expected_parameters: dict[str, Any] = field(default_factory=dict)
    passed: bool = False
    failure_category: str = ""
    failure_detail: str = ""
    notes: str = ""
