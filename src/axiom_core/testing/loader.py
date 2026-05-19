"""Load grid test cases from YAML fixture files."""

from pathlib import Path
from typing import Optional

import yaml

from axiom_core.testing.models import GridTestCase


def load_test_cases(
    case_file: Optional[str] = None,
    mode_filter: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[GridTestCase]:
    """Load test cases from a YAML fixture file.

    Args:
        case_file: Path to YAML file. Defaults to the built-in create_grids.yaml.
        mode_filter: If set, only return cases matching this mode ("simulate" or "real").
        limit: Maximum number of cases to return.
    """
    if case_file is None:
        case_file = str(
            Path(__file__).resolve().parents[2]
            / ".."
            / "tests"
            / "fixtures"
            / "grid_test_cases"
            / "create_grids.yaml"
        )

    path = Path(case_file)
    if not path.exists():
        raise FileNotFoundError(f"Test case file not found: {case_file}")

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    raw_cases = data.get("test_cases", [])
    cases: list[GridTestCase] = []

    for raw in raw_cases:
        case = GridTestCase(
            test_id=raw["test_id"],
            prompt=raw["prompt"].strip(),
            expected_capability=raw.get("expected_capability"),
            expected_parameters=raw.get("expected_parameters", {}),
            expected_created_count=raw.get("expected_created_count", 0),
            expected_success=raw.get("expected_success", True),
            mode=raw.get("mode", "simulate"),
            notes=raw.get("notes", ""),
            expected_failure_reason=raw.get("expected_failure_reason"),
            expected_status=raw.get("expected_status"),
        )
        cases.append(case)

    if mode_filter:
        cases = [c for c in cases if c.mode == mode_filter]

    if limit is not None and limit > 0:
        cases = cases[:limit]

    return cases
