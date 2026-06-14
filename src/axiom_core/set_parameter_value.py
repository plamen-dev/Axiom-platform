"""SetParameterValue v0 — constrained text parameter edit with preview/apply.

Safety constraints:
- Category-constrained only (no whole-model edits)
- Text parameters only (DataTypeLabel == "Text")
- Writable parameters only (IsReadOnly == False)
- Instance parameters only (IsInstanceParam == True)
- Explicit element count required
- Hard cap: 5 elements
- Preview (dry-run) by default; apply requires explicit "apply" keyword

This module provides:
- Prompt parsing (parse_set_parameter_prompt)
- Registry validation (validate_against_registry)
- Preview/apply execution simulation
- Evidence artifact generation
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_ELEMENT_COUNT = 5

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SetParameterRequest:
    """Parsed request from a natural-language prompt."""

    raw_prompt: str = ""
    mode: str = "preview"  # "preview" or "apply"
    category: str = ""
    parameter_name: str = ""
    value: str = ""
    element_count: int = 0
    parse_errors: list[str] = field(default_factory=list)


@dataclass
class RegistryMatch:
    """Result of looking up a parameter in the registry."""

    found: bool = False
    category: str = ""
    parameter_name: str = ""
    data_type_label: str = ""
    storage_type: str = ""
    is_read_only: bool = False
    is_instance_param: bool = False
    is_type_param: bool = False
    observed_count: int = 0
    ambiguous_categories: list[str] = field(default_factory=list)
    ambiguous_parameters: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class ElementPreview:
    """Preview of one element's parameter state."""

    element_id: int = 0
    category: str = ""
    old_value: str = ""
    new_value: str = ""
    status: str = "pending"  # "pending", "success", "failed", "skipped"
    error: str = ""


@dataclass
class SetParameterResult:
    """Full result of a SetParameterValue operation."""

    run_id: str = ""
    mode: str = "preview"
    status: str = "pending"  # "success", "rejected", "error"
    category: str = ""
    parameter_name: str = ""
    requested_value: str = ""
    data_type: str = ""
    is_instance_param: bool = True
    element_count: int = 0
    elements: list[ElementPreview] = field(default_factory=list)
    model_modified: bool = False
    model_name: str = ""
    rejection_reason: str = ""
    errors: list[str] = field(default_factory=list)
    artifact_dir: str = ""
    raw_prompt: str = ""


# ---------------------------------------------------------------------------
# Prompt parser
# ---------------------------------------------------------------------------

# Word-to-number mapping for small counts
_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def parse_set_parameter_prompt(prompt: str) -> SetParameterRequest:
    """Parse a SetParameterValue prompt into a structured request.

    Supported formats (quoted and unquoted values):
        Set <Parameter> to "<Value>" for <N> <Category>
        Set <Parameter> to <Value> for <N> <Category>
        Apply Set <Parameter> to "<Value>" for <N> <Category>
        Apply Set <Parameter> to <Value> for <N> <Category>

    Parsing strategy: find the trailing ``for <N> <Category>`` pattern
    first, then split the remainder at ``to`` to separate the parameter
    name from the value.  This allows unquoted multi-word values
    (important for PowerShell where inner quotes are stripped).

    Returns a SetParameterRequest with parse_errors if the prompt is malformed.
    """
    req = SetParameterRequest(raw_prompt=prompt)

    if not prompt or not prompt.strip():
        req.parse_errors.append("Empty prompt.")
        return req

    text = prompt.strip()

    # Detect apply mode
    if re.match(r"(?i)^apply\b", text):
        req.mode = "apply"
        text = re.sub(r"(?i)^apply\s+", "", text)
    else:
        req.mode = "preview"

    # Must start with "set"
    if not re.match(r"(?i)^set\b", text):
        req.parse_errors.append(
            "Prompt must follow: [Apply] Set <Parameter> to <Value> "
            "for <N> <Category>"
        )
        return req

    # Strip leading "set"
    text = re.sub(r"(?i)^set\s+", "", text)

    # Find trailing "for <N> <Category>" from the end.
    # <N> is a digit or word-number, <Category> is one or more words.
    # Use greedy .* prefix so the regex engine finds the *last* "for".
    trailing = re.search(
        r"^(.*)\bfor\s+(\w+)\s+(.+)$",
        text,
        re.IGNORECASE,
    )
    if not trailing:
        req.parse_errors.append(
            "Prompt must follow: [Apply] Set <Parameter> to <Value> "
            "for <N> <Category>"
        )
        return req

    count_str = trailing.group(2).strip().lower()
    req.category = trailing.group(3).strip()

    # Everything before the trailing "for ..." is "<Parameter> to <Value>"
    before_for = trailing.group(1).strip()

    # Split at " to " to separate parameter from value
    to_match = re.search(r"\bto\s+", before_for, re.IGNORECASE)
    if not to_match:
        req.parse_errors.append(
            "Prompt must follow: [Apply] Set <Parameter> to <Value> "
            "for <N> <Category>"
        )
        return req

    req.parameter_name = before_for[: to_match.start()].strip()
    raw_value = before_for[to_match.end():].strip()

    # Strip surrounding quotes if present
    if len(raw_value) >= 2 and raw_value[0] == '"' and raw_value[-1] == '"':
        req.value = raw_value[1:-1]
    else:
        req.value = raw_value

    if not req.parameter_name:
        req.parse_errors.append("Parameter name is empty.")
        return req

    if not req.value and req.value != "":
        req.parse_errors.append("Value is empty.")
        return req

    # Parse count
    if count_str.isdigit():
        req.element_count = int(count_str)
    elif count_str in _WORD_NUMBERS:
        req.element_count = _WORD_NUMBERS[count_str]
    else:
        req.parse_errors.append(f"Cannot parse element count: '{count_str}'")

    return req


# ---------------------------------------------------------------------------
# Registry validator
# ---------------------------------------------------------------------------


def validate_against_registry(
    req: SetParameterRequest,
    registry_entries: list[dict],
) -> RegistryMatch:
    """Validate a parsed request against parameter registry data.

    Args:
        req: Parsed SetParameterRequest.
        registry_entries: List of registry JSONL dicts with fields:
            ObjectCategory, ParameterName, DataTypeLabel, StorageType,
            IsReadOnly, IsInstanceParam, IsTypeParam, ObservedCount, etc.

    Returns:
        RegistryMatch with validation results and any errors.
    """
    result = RegistryMatch()

    if not registry_entries:
        result.errors.append("Registry is empty — cannot validate parameter.")
        return result

    # Find matching categories (case-insensitive, singular/plural)
    cat_lower = req.category.lower().rstrip("s")
    matching_categories = set()
    for entry in registry_entries:
        entry_cat = entry.get("ObjectCategory", "")
        if not entry_cat:
            continue
        entry_cat_lower = entry_cat.lower().rstrip("s")
        if entry_cat_lower == cat_lower or entry_cat.lower() == req.category.lower():
            matching_categories.add(entry_cat)

    if not matching_categories:
        result.errors.append(
            f"Category '{req.category}' not found in registry."
        )
        return result

    if len(matching_categories) > 1:
        result.ambiguous_categories = sorted(matching_categories)
        result.errors.append(
            f"Ambiguous category match: {result.ambiguous_categories}"
        )
        return result

    resolved_category = matching_categories.pop()
    result.category = resolved_category

    # Find matching parameters within the resolved category
    param_lower = req.parameter_name.lower()
    matching_params: list[dict] = []
    for entry in registry_entries:
        if entry.get("ObjectCategory", "") != resolved_category:
            continue
        entry_param = entry.get("ParameterName", "")
        if entry_param.lower() == param_lower:
            matching_params.append(entry)

    if not matching_params:
        result.errors.append(
            f"Parameter '{req.parameter_name}' not found for category "
            f"'{resolved_category}' in registry."
        )
        return result

    if len(matching_params) > 1:
        result.ambiguous_parameters = [
            p.get("ParameterName", "") for p in matching_params
        ]
        result.errors.append(
            f"Ambiguous parameter match: {result.ambiguous_parameters}"
        )
        return result

    param_entry = matching_params[0]
    result.found = True
    result.parameter_name = param_entry.get("ParameterName", "")
    result.data_type_label = param_entry.get("DataTypeLabel", "")
    result.storage_type = param_entry.get("StorageType", "")
    result.is_read_only = param_entry.get("IsReadOnly", False)
    result.is_instance_param = param_entry.get("IsInstanceParam", False)
    result.is_type_param = param_entry.get("IsTypeParam", False)
    result.observed_count = param_entry.get("ObservedCount", 0)

    return result


# ---------------------------------------------------------------------------
# Safety validation
# ---------------------------------------------------------------------------


def validate_safety(
    req: SetParameterRequest,
    registry_match: RegistryMatch,
) -> list[str]:
    """Check all v0 safety constraints. Returns list of rejection reasons."""
    rejections: list[str] = []

    # 1. Count must be present
    if req.element_count <= 0:
        rejections.append("Element count is missing or zero.")

    # 2. Count must not exceed hard cap
    if req.element_count > MAX_ELEMENT_COUNT:
        rejections.append(
            f"Element count {req.element_count} exceeds hard cap of "
            f"{MAX_ELEMENT_COUNT}."
        )

    # 3. Registry must have found the parameter
    if not registry_match.found:
        for err in registry_match.errors:
            rejections.append(err)
        return rejections

    # 4. Must be writable
    if registry_match.is_read_only:
        rejections.append(
            f"Parameter '{registry_match.parameter_name}' is read-only."
        )

    # 5. Must be instance parameter (v0)
    if not registry_match.is_instance_param:
        rejections.append(
            f"Parameter '{registry_match.parameter_name}' is not an instance "
            f"parameter. Type parameters are not supported in v0."
        )

    # 6. Must be text data type (v0)
    if registry_match.data_type_label.lower() != "text":
        rejections.append(
            f"Parameter '{registry_match.parameter_name}' has data type "
            f"'{registry_match.data_type_label}', but only Text parameters "
            f"are supported in v0."
        )

    # 7. Ambiguous matches
    if registry_match.ambiguous_categories:
        rejections.append(
            f"Ambiguous category match: {registry_match.ambiguous_categories}"
        )
    if registry_match.ambiguous_parameters:
        rejections.append(
            f"Ambiguous parameter match: {registry_match.ambiguous_parameters}"
        )

    return rejections


# ---------------------------------------------------------------------------
# Preview / Apply simulation
# ---------------------------------------------------------------------------


def run_set_parameter_preview(
    req: SetParameterRequest,
    registry_match: RegistryMatch,
    simulated_elements: list[dict] | None = None,
) -> SetParameterResult:
    """Execute a preview (dry-run) of SetParameterValue.

    In simulation mode (no live Revit), uses simulated_elements to show
    what would happen. In live mode (future), would query Revit for real
    elements.

    Args:
        req: Parsed request.
        registry_match: Validated registry match.
        simulated_elements: Optional list of dicts with keys:
            element_id, category, current_value

    Returns:
        SetParameterResult with preview data.
    """
    result = SetParameterResult(
        run_id=datetime.now(timezone.utc).strftime("spv_%Y%m%d_%H%M%S"),
        mode=req.mode,
        category=registry_match.category or req.category,
        parameter_name=registry_match.parameter_name or req.parameter_name,
        requested_value=req.value,
        data_type=registry_match.data_type_label,
        is_instance_param=registry_match.is_instance_param,
        element_count=req.element_count,
        raw_prompt=req.raw_prompt,
    )

    # Safety check
    rejections = validate_safety(req, registry_match)
    if rejections:
        result.status = "rejected"
        result.rejection_reason = "; ".join(rejections)
        result.errors = rejections
        return result

    # Build element previews
    if simulated_elements:
        for elem in simulated_elements[: req.element_count]:
            preview = ElementPreview(
                element_id=elem.get("element_id", 0),
                category=elem.get("category", result.category),
                old_value=elem.get("current_value", ""),
                new_value=req.value,
                status="preview" if req.mode == "preview" else "pending",
            )
            result.elements.append(preview)
    else:
        # Generate placeholder elements for pure simulation
        for i in range(req.element_count):
            preview = ElementPreview(
                element_id=1000 + i,
                category=result.category,
                old_value="",
                new_value=req.value,
                status="preview" if req.mode == "preview" else "pending",
            )
            result.elements.append(preview)

    if req.mode == "preview":
        result.status = "success"
        result.model_modified = False
    elif req.mode == "apply":
        # In simulation, mark all as success
        for elem in result.elements:
            elem.status = "success"
        result.status = "success"
        result.model_modified = True

    return result


# ---------------------------------------------------------------------------
# Evidence export
# ---------------------------------------------------------------------------


def write_evidence(
    req: SetParameterRequest,
    registry_match: RegistryMatch,
    result: SetParameterResult,
    artifact_base: str = "artifacts/parameter_edit_runs",
) -> Path:
    """Write evidence artifacts for a SetParameterValue run.

    Creates:
        <artifact_base>/<run_id>/
        ├── request.json
        ├── preview.json
        ├── changes.json       (apply mode only)
        └── result_summary.md

    Returns:
        Path to the artifact directory.
    """
    artifact_dir = Path(artifact_base) / result.run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    result.artifact_dir = str(artifact_dir)

    # request.json
    request_data = {
        "raw_prompt": req.raw_prompt,
        "mode": req.mode,
        "category": req.category,
        "parameter_name": req.parameter_name,
        "value": req.value,
        "element_count": req.element_count,
        "parse_errors": req.parse_errors,
    }
    (artifact_dir / "request.json").write_text(
        json.dumps(request_data, indent=2), encoding="utf-8"
    )

    # preview.json
    preview_data = {
        "run_id": result.run_id,
        "mode": result.mode,
        "status": result.status,
        "category": result.category,
        "parameter_name": result.parameter_name,
        "requested_value": result.requested_value,
        "data_type": result.data_type,
        "is_instance_param": result.is_instance_param,
        "element_count": result.element_count,
        "model_modified": result.model_modified,
        "model_name": result.model_name,
        "rejection_reason": result.rejection_reason,
        "errors": result.errors,
        "elements": [
            {
                "element_id": e.element_id,
                "category": e.category,
                "old_value": e.old_value,
                "new_value": e.new_value,
                "status": e.status,
                "error": e.error,
            }
            for e in result.elements
        ],
    }
    (artifact_dir / "preview.json").write_text(
        json.dumps(preview_data, indent=2), encoding="utf-8"
    )

    # changes.json (apply mode only, where model was actually modified)
    if result.mode == "apply" and result.model_modified:
        changes_data = {
            "run_id": result.run_id,
            "mode": "apply",
            "category": result.category,
            "parameter_name": result.parameter_name,
            "requested_value": result.requested_value,
            "model_modified": True,
            "model_name": result.model_name,
            "changes": [
                {
                    "element_id": e.element_id,
                    "old_value": e.old_value,
                    "new_value": e.new_value,
                    "status": e.status,
                    "error": e.error,
                }
                for e in result.elements
            ],
        }
        (artifact_dir / "changes.json").write_text(
            json.dumps(changes_data, indent=2), encoding="utf-8"
        )

    # result_summary.md
    _write_result_summary(req, registry_match, result, artifact_dir)

    return artifact_dir


def _write_result_summary(
    req: SetParameterRequest,
    registry_match: RegistryMatch,
    result: SetParameterResult,
    artifact_dir: Path,
) -> Path:
    """Write result_summary.md for the run."""
    path = artifact_dir / "result_summary.md"

    success_count = sum(1 for e in result.elements if e.status == "success")
    failed_count = sum(1 for e in result.elements if e.status == "failed")
    preview_count = sum(1 for e in result.elements if e.status == "preview")

    lines = [
        f"# SetParameterValue Result: {result.status}",
        "",
        "## Raw Prompt",
        "",
        result.raw_prompt or "N/A",
        "",
        "## Resolved Parameters",
        "",
        f"- **Mode:** {result.mode}",
        f"- **Category:** {result.category}",
        f"- **Parameter:** {result.parameter_name}",
        f"- **Requested value:** \"{result.requested_value}\"",
        f"- **Data type:** {result.data_type or 'N/A'}",
        f"- **Instance parameter:** {result.is_instance_param}",
        f"- **Element count:** {result.element_count}",
        "",
        "## Execution",
        "",
        f"- **Model modified:** {result.model_modified}",
        f"- **Model name:** {result.model_name or 'N/A (simulation)'}",
        f"- **Run ID:** {result.run_id}",
        "",
    ]

    if result.rejection_reason:
        lines.extend([
            "## Rejection",
            "",
            result.rejection_reason,
            "",
        ])

    if result.elements:
        lines.extend([
            "## Elements",
            "",
            "| Element ID | Category | Old Value | New Value | Status |",
            "|-----------|----------|-----------|-----------|--------|",
        ])
        for e in result.elements:
            lines.append(
                f"| {e.element_id} | {e.category} | "
                f"{e.old_value or '(empty)'} | {e.new_value} | {e.status} |"
            )
        lines.append("")

    lines.extend([
        "## Summary",
        "",
        f"- Preview: {preview_count}",
        f"- Success: {success_count}",
        f"- Failed: {failed_count}",
        "",
        "## Artifacts",
        "",
        "- `request.json`",
        "- `preview.json`",
    ])
    if result.mode == "apply" and result.model_modified:
        lines.append("- `changes.json`")
    lines.extend([
        "- `result_summary.md`",
        "",
    ])

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Registry loader (convenience)
# ---------------------------------------------------------------------------


def load_registry_jsonl(registry_path: str | Path) -> list[dict]:
    """Load a revit_property_registry.jsonl file into a list of dicts."""
    path = Path(registry_path)
    if not path.exists():
        return []
    entries: list[dict] = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries
