"""Validation script for safe InventoryModel replacement path.

Executes every supported prompt mode and captures detailed results:
  - prompt used
  - resolved scan mode
  - category filter
  - level filter
  - max threshold
  - capability name
  - status (resolved / clarification_needed)
  - whether unbounded extraction is possible

This runs against the Python prompt resolver (no live Revit).
Real-model Revit validation requires running these prompts in Revit 2027.
"""

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from axiom_core.prompt_resolver import resolve_prompt


@dataclass
class ValidationResult:
    test_id: str
    category: str
    prompt: str
    capability_name: str = ""
    status: str = ""
    scan_mode: str = ""
    category_filter: list = field(default_factory=list)
    level_filter: list = field(default_factory=list)
    max_threshold: int | None = None
    summary_only: bool | None = None
    include_parameters: bool | None = None
    clarification_message: str = ""
    assumptions: list = field(default_factory=list)
    is_blocked: bool = False
    is_unbounded: bool = False
    runtime_ms: float = 0.0
    passed: bool = False
    failure_reason: str = ""
    notes: str = ""


def run_validation(test_id: str, category: str, prompt: str,
                   expect_mode: str | None = None,
                   expect_blocked: bool = False,
                   expect_capability: str = "InventoryModel",
                   expect_category: list | None = None,
                   expect_level: list | None = None,
                   expect_max: int | None = None,
                   notes: str = "") -> ValidationResult:
    result = ValidationResult(
        test_id=test_id,
        category=category,
        prompt=prompt,
        notes=notes,
    )

    start = time.perf_counter()
    resolved = resolve_prompt(prompt)
    elapsed = (time.perf_counter() - start) * 1000
    result.runtime_ms = round(elapsed, 2)

    if resolved is None:
        result.failure_reason = "resolve_prompt returned None"
        return result

    result.capability_name = resolved.capability_name
    result.status = resolved.status
    result.scan_mode = resolved.params.get("ScanMode", "")
    result.category_filter = resolved.params.get("CategoryFilter", [])
    result.level_filter = resolved.params.get("LevelFilter", [])
    result.max_threshold = resolved.params.get("BatchSize") or resolved.params.get("MaxElements")
    result.summary_only = resolved.params.get("SummaryOnly")
    result.include_parameters = resolved.params.get("IncludeParameters")
    result.clarification_message = resolved.clarification_message
    result.assumptions = resolved.assumptions
    result.is_blocked = resolved.status == "clarification_needed"
    result.is_unbounded = (
        result.scan_mode == "full"
        or (result.summary_only is False
            and not result.category_filter
            and not result.level_filter
            and result.max_threshold is None
            and result.scan_mode not in ("sample", "batched", "schema",
                                        "object_schema", "parameter_schema",
                                        "sample_values", "category_schema",
                                        "category_object_schema",
                                        "category_parameter_schema",
                                        "category_sample_values", ""))
    )

    # Validate expectations
    passed = True
    reasons = []

    if expect_blocked and not result.is_blocked:
        passed = False
        reasons.append(f"Expected blocked, got status={result.status}")
    if not expect_blocked and result.is_blocked:
        # Plan prompts are intentionally blocked (clarification) — that's safe
        if result.capability_name != "InventoryPlan":
            passed = False
            reasons.append(f"Expected resolved, got blocked: {result.clarification_message[:80]}")
    if expect_mode and result.scan_mode != expect_mode and not expect_blocked:
        passed = False
        reasons.append(f"Expected mode={expect_mode}, got {result.scan_mode}")
    if expect_capability and result.capability_name != expect_capability:
        passed = False
        reasons.append(f"Expected capability={expect_capability}, got {result.capability_name}")
    if expect_category and result.category_filter != expect_category:
        passed = False
        reasons.append(f"Expected category={expect_category}, got {result.category_filter}")
    if expect_level and result.level_filter != expect_level:
        passed = False
        reasons.append(f"Expected level={expect_level}, got {result.level_filter}")
    if expect_max is not None and result.max_threshold != expect_max:
        passed = False
        reasons.append(f"Expected max={expect_max}, got {result.max_threshold}")
    if result.is_unbounded:
        passed = False
        reasons.append("CRITICAL: Resolves to unbounded extraction!")

    result.passed = passed
    result.failure_reason = "; ".join(reasons)
    return result


def run_all_validations() -> list[ValidationResult]:
    results = []

    # === 1. Summary mode ===
    results.append(run_validation(
        "VAL-001", "1. Summary mode",
        "Run InventoryModel",
        expect_mode="summary",
        notes="Default safe mode — counts and categories only",
    ))
    results.append(run_validation(
        "VAL-002", "1. Summary mode",
        "InventoryModel",
        expect_mode="summary",
    ))
    results.append(run_validation(
        "VAL-003", "1. Summary mode",
        "model inventory",
        expect_mode="summary",
    ))

    # === 2. Sample mode ===
    results.append(run_validation(
        "VAL-010", "2. Sample mode",
        "Run InventoryModel sample",
        expect_mode="sample",
        expect_max=100,
        notes="Capped at 100 elements",
    ))
    results.append(run_validation(
        "VAL-011", "2. Sample mode",
        "inventory sample",
        expect_mode="sample",
        expect_max=100,
    ))

    # === 3. Single-category mode ===
    for cat_prompt, cat_expected in [
        ("Run InventoryModel for Walls", ["Walls"]),
        ("Inventory doors", ["Doors"]),
        ("Run InventoryModel for Levels", ["Levels"]),
        ("Inventory rooms", ["Rooms"]),
        ("Run InventoryModel for Mechanical Equipment", ["Mechanical Equipment"]),
        ("Inventory parameters for windows", ["Windows"]),
    ]:
        results.append(run_validation(
            f"VAL-02{len(results) - 7}", "3. Single-category mode",
            cat_prompt,
            expect_mode="category",
            expect_category=cat_expected,
        ))

    # === 4. Level-only mode ===
    results.append(run_validation(
        "VAL-040", "4. Level-only mode",
        "Run InventoryModel on Level 1",
        expect_mode="level",
        expect_level=["1"],
        notes="Level 1 filtering",
    ))
    results.append(run_validation(
        "VAL-041", "4. Level-only mode",
        "Run InventoryModel on Level Ground",
        expect_mode="level",
        expect_level=["Ground"],
        notes="Named level filtering",
    ))
    results.append(run_validation(
        "VAL-042", "4. Level-only mode",
        "Run InventoryModel for Level 2",
        expect_mode="level",
        expect_level=["2"],
    ))
    results.append(run_validation(
        "VAL-043", "4. Level-only mode",
        "Run InventoryModel at Level Basement",
        expect_mode="level",
        expect_level=["Basement"],
    ))

    # === 5. Category+level mode ===
    results.append(run_validation(
        "VAL-050", "5. Category+level mode",
        "Run InventoryModel for Walls on Level 1",
        expect_mode="category_level",
        expect_category=["Walls"],
        expect_level=["1"],
        notes="Category + level combined",
    ))
    results.append(run_validation(
        "VAL-051", "5. Category+level mode",
        "Run InventoryModel for Doors on Level 1",
        expect_mode="category_level",
        expect_category=["Doors"],
        expect_level=["1"],
    ))
    results.append(run_validation(
        "VAL-052", "5. Category+level mode",
        "Inventory doors on Level 2",
        expect_mode="category_level",
        expect_category=["Doors"],
        expect_level=["2"],
    ))
    results.append(run_validation(
        "VAL-053", "5. Category+level mode",
        "Run InventoryModel for Floors on Level Ground",
        expect_mode="category_level",
        expect_category=["Floors"],
        expect_level=["Ground"],
    ))

    # === 6. Max threshold mode ===
    results.append(run_validation(
        "VAL-060", "6. Max threshold mode",
        "Run InventoryModel for Walls max 500",
        expect_mode="category",
        expect_category=["Walls"],
        expect_max=500,
        notes="Category + max element cap",
    ))
    results.append(run_validation(
        "VAL-061", "6. Max threshold mode",
        "Run InventoryModel for Doors max 500",
        expect_mode="category",
        expect_category=["Doors"],
        expect_max=500,
    ))
    results.append(run_validation(
        "VAL-062", "6. Max threshold mode",
        "Run InventoryModel on Level 1 limit 1000",
        expect_mode="level",
        expect_level=["1"],
        expect_max=1000,
    ))
    results.append(run_validation(
        "VAL-063", "6. Max threshold mode",
        "Run InventoryModel for Walls on Level 1 max 200",
        expect_mode="category_level",
        expect_category=["Walls"],
        expect_level=["1"],
        expect_max=200,
    ))
    results.append(run_validation(
        "VAL-064", "6. Max threshold mode",
        "Run InventoryModel for Walls first 50",
        expect_mode="category",
        expect_category=["Walls"],
        expect_max=50,
        notes="'first N' variant",
    ))

    # === 7. Full scan blocked ===
    for full_prompt in [
        "Run full InventoryModel",
        "full inventory",
        "Run full scan InventoryModel",
        "Run complete inventory",
        "full inventory scan of the model",
        "run full inventorymodel please",
    ]:
        results.append(run_validation(
            f"VAL-07{len(results) - 27}", "7. Full scan blocked",
            full_prompt,
            expect_blocked=True,
            notes="Must return clarification_needed, never execute",
        ))

    # === 8. No unbounded path ===
    edge_cases = [
        ("Run InventoryModel", "InventoryModel"),
        ("Run InventoryModel sample", "InventoryModel"),
        ("Run InventoryModel for Walls", "InventoryModel"),
        ("Inventory doors", "InventoryModel"),
        ("Run InventoryModel on Level 1", "InventoryModel"),
        ("Run InventoryModel for Walls on Level 1", "InventoryModel"),
        ("Run InventoryModel for Walls max 500", "InventoryModel"),
        ("inventory plan", "InventoryPlan"),
        ("Create an extraction plan", "InventoryPlan"),
        ("model inventory", "InventoryModel"),
        ("scan model parameters", "InventoryModel"),
        ("extract model parameters", "InventoryModel"),
        ("inventory parameters for walls", "InventoryModel"),
    ]
    for prompt, expected_cap in edge_cases:
        results.append(run_validation(
            f"VAL-08{len(results) - 33}", "8. No unbounded extraction",
            prompt,
            expect_capability=expected_cap,
            notes="Verify no prompt resolves to ScanMode=full or unbounded",
        ))

    # === Plan prompt ===
    results.append(run_validation(
        "VAL-090", "Plan prompt",
        "inventory plan",
        expect_capability="InventoryPlan",
        expect_blocked=True,
        notes="Returns guidance to use CLI planner",
    ))
    results.append(run_validation(
        "VAL-091", "Plan prompt",
        "Create an extraction plan",
        expect_capability="InventoryPlan",
        expect_blocked=True,
    ))
    results.append(run_validation(
        "VAL-092", "Plan prompt",
        "Build an extraction plan for my model",
        expect_capability="InventoryPlan",
        expect_blocked=True,
    ))

    return results


def generate_markdown_report(results: list[ValidationResult], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    lines = [
        "# Safe InventoryModel Replacement — Validation Report",
        "",
        f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "**Branch:** `revit-2027-compatibility`",
        f"**Total tests:** {total}",
        f"**Passed:** {passed}",
        f"**Failed:** {failed}",
        "**Environment:** Python prompt resolver (no live Revit)",
        "",
        "---",
        "",
        "## Architecture Note: Level Filtering",
        "",
        "**Flag: Level filter is NOT pre-collector.** The C# `ModelInventoryService.CollectInventory()` "
        "uses `FilteredElementCollector(doc).WhereElementIsNotElementType()` which iterates ALL elements. "
        "Level filtering is applied inside the `foreach` loop (line 58-63) — **after** the element is "
        "retrieved from the collector but **before** parameter extraction (`CollectParameters()`).",
        "",
        "This means:",
        "- The Revit collector still enumerates all elements in the model",
        "- Level lookup (`GetElementLevelName`) runs for every element (lightweight — reads one parameter)",
        "- **Parameter extraction is skipped for filtered-out elements** — this is the expensive operation",
        "- For category filter, same pattern: all elements enumerated, non-matching skipped before extraction",
        "",
        "**Recommendation for future optimization:** Use `FilteredElementCollector` with "
        "`.WherePasses(new ElementLevelFilter(levelId))` for true pre-collector filtering. "
        "This would avoid even enumerating non-matching elements. Current approach is safe but not optimal.",
        "",
        "---",
        "",
        "## Results by Category",
        "",
    ]

    # Group by category
    categories = {}
    for r in results:
        categories.setdefault(r.category, []).append(r)

    for cat, cat_results in categories.items():
        cat_passed = sum(1 for r in cat_results if r.passed)
        cat_total = len(cat_results)
        status_icon = "PASS" if cat_passed == cat_total else "FAIL"
        lines.append(f"### {cat} — {status_icon} ({cat_passed}/{cat_total})")
        lines.append("")
        lines.append("| ID | Prompt | Mode | Category | Level | Max | Status | Result |")
        lines.append("|-----|--------|------|----------|-------|-----|--------|--------|")
        for r in cat_results:
            status = "blocked" if r.is_blocked else "resolved"
            result_str = "PASS" if r.passed else f"FAIL: {r.failure_reason}"
            cat_str = ", ".join(r.category_filter) if r.category_filter else "—"
            lvl_str = ", ".join(r.level_filter) if r.level_filter else "—"
            max_str = str(r.max_threshold) if r.max_threshold else "—"
            mode_str = r.scan_mode if r.scan_mode else "(plan)" if r.capability_name == "InventoryPlan" else "—"
            lines.append(
                f"| {r.test_id} | `{r.prompt}` | {mode_str} | {cat_str} | {lvl_str} | {max_str} | {status} | {result_str} |"
            )
        lines.append("")

    # Detailed failures
    failures = [r for r in results if not r.passed]
    if failures:
        lines.append("## Failures (Detail)")
        lines.append("")
        for r in failures:
            lines.append(f"### {r.test_id}: `{r.prompt}`")
            lines.append(f"- **Reason:** {r.failure_reason}")
            lines.append(f"- **Capability:** {r.capability_name}")
            lines.append(f"- **Status:** {r.status}")
            lines.append(f"- **Scan mode:** {r.scan_mode}")
            lines.append(f"- **Unbounded:** {r.is_unbounded}")
            lines.append("")

    # Safety summary
    lines.append("## Safety Summary")
    lines.append("")
    unbounded = [r for r in results if r.is_unbounded]
    if unbounded:
        lines.append(f"**CRITICAL: {len(unbounded)} prompt(s) resolve to unbounded extraction!**")
        for r in unbounded:
            lines.append(f"- `{r.prompt}` → ScanMode={r.scan_mode}")
    else:
        lines.append("**No prompt path resolves to unbounded full extraction.**")
    lines.append("")

    blocked = [r for r in results if r.category == "7. Full scan blocked"]
    blocked_pass = sum(1 for r in blocked if r.passed)
    lines.append(f"**Full scan blocked:** {blocked_pass}/{len(blocked)} variants correctly blocked")
    lines.append("")

    lines.append("## Real-Model Validation (Pending)")
    lines.append("")
    lines.append("The following require live Revit 2027 validation:")
    lines.append("- [ ] Summary mode produces category_counts from real model")
    lines.append("- [ ] Level scan actually filters elements by level in Revit")
    lines.append("- [ ] Category+level scan produces correct subset")
    lines.append("- [ ] Max threshold caps output correctly")
    lines.append("- [ ] No Revit crash on any chunked scan mode")
    lines.append("- [ ] `axiom inventory-plan` produces valid plan from real summary")
    lines.append("- [ ] Level filter performance acceptable (see architecture note above)")
    lines.append("")

    md_path = output_dir / "validation_report.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    # Also write JSON
    json_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_tests": total,
        "passed": passed,
        "failed": failed,
        "environment": "Python prompt resolver (no live Revit)",
        "level_filter_architecture": "post-collector, pre-extraction (not optimal, but safe)",
        "results": [asdict(r) for r in results],
    }
    json_path = output_dir / "validation_results.json"
    json_path.write_text(json.dumps(json_data, indent=2), encoding="utf-8")

    return md_path


if __name__ == "__main__":
    results = run_all_validations()
    output_dir = Path("artifacts/validation_runs/safe_inventory_modes")
    md_path = generate_markdown_report(results, output_dir)

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    print(f"\nValidation complete: {passed}/{total} passed, {failed} failed")
    print(f"Report: {md_path}")
    print(f"JSON:   {output_dir / 'validation_results.json'}")

    if failed > 0:
        print("\nFailed tests:")
        for r in results:
            if not r.passed:
                print(f"  {r.test_id}: {r.prompt} — {r.failure_reason}")
