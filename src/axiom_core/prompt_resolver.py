"""Prompt-to-capability resolver.

Parses natural-language prompts into structured capability parameters.
Supports CreateGrids, CreateLevels, and InventoryModel.

Grid prompts support uniform spacing and variable per-bay spacing
via comma-separated lists or pasted table format.

Level prompts support uniform floor-to-floor heights, variable
elevations via comma lists, and named levels via table format.

InventoryModel prompts trigger a read-only model scan.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from axiom_core.word_numbers import replace_word_numbers


@dataclass
class ResolvedPrompt:
    """Result of resolving a user prompt into capability parameters."""

    capability_name: str
    params: dict
    assumptions: list[str] = field(default_factory=list)
    raw_prompt: str = ""
    status: str = "resolved"  # "resolved" or "clarification_needed"
    clarification_message: str = ""


# Grid parameter defaults from revit_grid_parameter_model_001.txt
_GRID_DEFAULTS = {
    "HorizontalCount": 5,
    "VerticalCount": 5,
    "SpacingFeet": 30.0,
    "Length": 0,
    "Naming": "Default",
}


def resolve_prompt(prompt: str) -> Optional[ResolvedPrompt]:
    """Resolve a natural-language prompt to a capability call.

    Supports grid creation and level creation prompts.
    Returns None if the prompt cannot be resolved.
    Returns a clarification-needed result if the prompt is ambiguous.
    """
    lower = prompt.lower().strip()

    # Check for inventory prompts first (read-only, no ambiguity)
    if _is_inventory_prompt(lower):
        return _resolve_inventory_prompt(prompt)

    # Check for level prompts (before grids, since "level" is unambiguous)
    # But only if not also a grid prompt — grid keywords are more specific
    if _is_level_prompt(lower) and not _is_grid_prompt(lower):
        return _resolve_level_prompt(prompt, lower)

    if not _is_grid_prompt(lower):
        # Check for level clarification (floors/stories without "level")
        # Only if the prompt doesn't contain explicit grid keywords
        level_clarification = _check_level_clarification(lower, prompt)
        if level_clarification is not None:
            return level_clarification
        # Check if prompt uses rows/columns without explicit grid keyword
        clarification = _check_grid_clarification(lower, prompt)
        if clarification is not None:
            return clarification
        return None

    # Normalize word numbers to digits before extraction
    lower = replace_word_numbers(lower)

    params = dict(_GRID_DEFAULTS)
    assumptions: list[str] = []

    # Extract counts
    h_count, v_count = _extract_counts(lower)

    has_vertical = h_count is not None
    has_horizontal = v_count is not None

    if h_count is not None:
        params["HorizontalCount"] = h_count
    if v_count is not None:
        params["VerticalCount"] = v_count

    # Extract variable spacing (table format and comma lists)
    h_spacings, v_spacings, has_vertical, has_horizontal = _extract_variable_spacings(
        prompt, lower, has_vertical, has_horizontal
    )

    if h_spacings is not None:
        params["HorizontalSpacingsFeet"] = h_spacings
        params["HorizontalCount"] = len(h_spacings) + 1
        has_vertical = True
        assumptions.append(
            f"Variable vertical grid spacing: {h_spacings}"
        )
    if v_spacings is not None:
        params["VerticalSpacingsFeet"] = v_spacings
        params["VerticalCount"] = len(v_spacings) + 1
        has_horizontal = True
        assumptions.append(
            f"Variable horizontal grid spacing: {v_spacings}"
        )

    # When only one orientation is explicitly specified, the other defaults to 0
    # (not the layout default of 5). Full-layout defaults apply only when neither
    # orientation is specified.
    if not has_vertical and not has_horizontal:
        assumptions.append(f"HorizontalCount defaulted to {_GRID_DEFAULTS['HorizontalCount']}")
        assumptions.append(f"VerticalCount defaulted to {_GRID_DEFAULTS['VerticalCount']}")
    elif not has_vertical:
        params["HorizontalCount"] = 0
        assumptions.append("No vertical grids created (only horizontal grids requested)")
    elif not has_horizontal:
        params["VerticalCount"] = 0
        assumptions.append("No horizontal grids created (only vertical grids requested)")

    # Extract uniform spacing (only if no variable spacing was found)
    if h_spacings is None and v_spacings is None:
        spacing = _extract_spacing(lower)
        if spacing is not None:
            params["SpacingFeet"] = spacing
        else:
            assumptions.append(f"SpacingFeet defaulted to {_GRID_DEFAULTS['SpacingFeet']}")

    # Extract length
    length = _extract_length(lower)
    if length is not None:
        params["Length"] = length
    else:
        assumptions.append("Length will be derived from grid extents")

    return ResolvedPrompt(
        capability_name="CreateGrids",
        params=params,
        assumptions=assumptions,
        raw_prompt=prompt,
    )


def _is_grid_prompt(lower: str) -> bool:
    """Check if this prompt is explicitly about grid creation."""
    grid_keywords = ["grid", "grids", "gridline", "gridlines"]
    return any(kw in lower for kw in grid_keywords)


def _check_grid_clarification(
    lower: str, original_prompt: str
) -> Optional[ResolvedPrompt]:
    """Check if the prompt uses rows/columns without the word 'grid'.

    If so, return a clarification-needed result instead of executing.
    """
    row_match = re.search(r"(\d+)\s*rows?", lower)
    if not row_match:
        row_match = re.search(r"rows?\s*(\d+)", lower)
    col_match = re.search(r"(\d+)\s*columns?", lower)
    if not col_match:
        col_match = re.search(r"columns?\s*(\d+)", lower)

    if not row_match and not col_match:
        return None

    # Build clarification message
    parts: list[str] = []
    h_count = 0
    v_count = 0
    if row_match:
        v_count = int(row_match.group(1))
        parts.append(f"{v_count} horizontal row{'s' if v_count != 1 else ''}")
    if col_match:
        h_count = int(col_match.group(1))
        parts.append(f"{h_count} vertical column{'s' if h_count != 1 else ''}")

    arrangement = " and ".join(parts)
    clarification_msg = (
        f"Did you mean Revit gridlines arranged as {arrangement}?\n"
        f"If so, please rephrase with 'gridlines' or 'grids' "
        f"(e.g. 'Create {arrangement} of gridlines ...')."
    )

    # Build tentative params (what would be resolved if confirmed)
    params = dict(_GRID_DEFAULTS)
    if h_count > 0:
        params["HorizontalCount"] = h_count
    if v_count > 0:
        params["VerticalCount"] = v_count
    if h_count > 0 and v_count == 0:
        params["VerticalCount"] = 0
    elif v_count > 0 and h_count == 0:
        params["HorizontalCount"] = 0

    return ResolvedPrompt(
        capability_name="CreateGrids",
        params=params,
        assumptions=["Prompt uses rows/columns without explicit grid keyword"],
        raw_prompt=original_prompt,
        status="clarification_needed",
        clarification_message=clarification_msg,
    )


def _extract_counts(lower: str) -> tuple[Optional[int], Optional[int]]:
    """Extract grid counts from prompt.

    Returns (h_count, v_count) mapped to C# GridCreationService semantics:
      h_count → HorizontalCount (creates vertical/numeric lines in Revit)
      v_count → VerticalCount (creates horizontal/alphabetic lines in Revit)

    User says "vertical" → h_count (HorizontalCount makes vertical lines).
    User says "horizontal" → v_count (VerticalCount makes horizontal lines).
    """
    h_count = None  # HorizontalCount → vertical lines in Revit
    v_count = None  # VerticalCount → horizontal lines in Revit

    # "10 horizontal" or "10 rows" → user wants horizontal lines → VerticalCount
    horiz_match = re.search(r"(\d+)\s*(?:horiz(?:ontal)?s?|rows?)", lower)
    if not horiz_match:
        horiz_match = re.search(r"(?:horiz(?:ontal)?s?|rows?)\s*(\d+)", lower)
    if horiz_match:
        v_count = int(horiz_match.group(1))

    # "10 vertical" or "10 columns" → user wants vertical lines → HorizontalCount
    vert_match = re.search(r"(\d+)\s*(?:vert(?:ical)?s?|columns?)", lower)
    if not vert_match:
        vert_match = re.search(r"(?:vert(?:ical)?s?|columns?)\s*(\d+)", lower)
    if vert_match:
        h_count = int(vert_match.group(1))

    # "4 by 6 grid" or "4x6 grid" — first = HorizontalCount, second = VerticalCount
    by_match = re.search(r"(\d+)\s*(?:by|x)\s*(\d+)", lower)
    if by_match and h_count is None and v_count is None:
        h_count = int(by_match.group(1))
        v_count = int(by_match.group(2))

    # "create 10 grids" — if no orientation specified, assume both
    if h_count is None and v_count is None:
        generic_match = re.search(r"(\d+)\s*(?:grid|grids|gridline|gridlines)", lower)
        if generic_match:
            count = int(generic_match.group(1))
            if "vert" in lower or "column" in lower:
                h_count = count  # vertical lines → HorizontalCount
            elif "horiz" in lower or "row" in lower:
                v_count = count  # horizontal lines → VerticalCount
            else:
                h_count = count
                v_count = count

    return h_count, v_count


def _extract_variable_spacings(
    original_prompt: str,
    lower: str,
    has_vertical: bool,
    has_horizontal: bool,
) -> tuple[Optional[list[float]], Optional[list[float]], bool, bool]:
    """Extract variable spacing arrays from prompt text.

    Supports two formats:
    1. Comma-separated: "spacings 10, 5, 20, 10"
    2. Table format with sections:
       Vertical:
       1-2 = 10'
       2-3 = 5'

    Returns (h_spacings, v_spacings, has_vertical, has_horizontal).
    h_spacings → HorizontalSpacingsFeet (vertical grid bay spacings)
    v_spacings → VerticalSpacingsFeet (horizontal grid bay spacings)
    """
    h_spacings = None
    v_spacings = None

    # Try table format first (more specific)
    vert_table = _parse_table_spacings(original_prompt, "vertical")
    horiz_table = _parse_table_spacings(original_prompt, "horizontal")

    if vert_table is not None:
        h_spacings = vert_table  # vertical grids → HorizontalSpacingsFeet
        has_vertical = True
    if horiz_table is not None:
        v_spacings = horiz_table  # horizontal grids → VerticalSpacingsFeet
        has_horizontal = True

    # If no section headers found, try unsectioned table entries
    if h_spacings is None and v_spacings is None:
        unsectioned = _parse_unsectioned_table(original_prompt)
        if unsectioned is not None:
            if has_vertical and not has_horizontal:
                h_spacings = unsectioned
            elif has_horizontal and not has_vertical:
                v_spacings = unsectioned
            elif "vert" in lower or "column" in lower:
                h_spacings = unsectioned
                has_vertical = True
            elif "horiz" in lower or "row" in lower:
                v_spacings = unsectioned
                has_horizontal = True
            else:
                h_spacings = unsectioned
                has_vertical = True

    # Try comma-separated format if no table found
    if h_spacings is None and v_spacings is None:
        comma_spacings = _parse_comma_spacings(lower)
        if comma_spacings is not None:
            if has_vertical and not has_horizontal:
                h_spacings = comma_spacings
            elif has_horizontal and not has_vertical:
                v_spacings = comma_spacings
            elif "vert" in lower or "column" in lower:
                h_spacings = comma_spacings
                has_vertical = True
            elif "horiz" in lower or "row" in lower:
                v_spacings = comma_spacings
                has_horizontal = True
            else:
                # Default to vertical when ambiguous
                h_spacings = comma_spacings
                has_vertical = True

    return h_spacings, v_spacings, has_vertical, has_horizontal


def _parse_unsectioned_table(text: str) -> Optional[list[float]]:
    """Parse table-format entries that aren't under a section header.

    Matches lines like "1-2 = 10'" anywhere in the prompt.
    """
    table_pattern = re.compile(
        r"[\w]+-[\w]+\s*=\s*(\d+\.?\d*)\s*['\s]*(?:ft|feet|foot)?",
        re.IGNORECASE,
    )
    matches = table_pattern.findall(text)
    if not matches:
        return None

    values: list[float] = []
    for val_str in matches:
        try:
            val = float(val_str)
            if val <= 0:
                return None
            values.append(val)
        except ValueError:
            return None

    return values if values else None


def _parse_comma_spacings(lower: str) -> Optional[list[float]]:
    """Parse comma-separated spacing values.

    Matches: "spacings 10, 5, 20, 10" or "with spacings 10,5,20"
    """
    match = re.search(
        r"spacings?\s+([\d]+\.?\d*(?:\s*,\s*[\d]+\.?\d*)+)", lower
    )
    if not match:
        return None

    parts = match.group(1).split(",")
    values: list[float] = []
    for part in parts:
        trimmed = part.strip().rstrip("'")
        try:
            val = float(trimmed)
            if val <= 0:
                return None
            values.append(val)
        except ValueError:
            return None

    return values if values else None


def _parse_table_spacings(
    text: str, section: str
) -> Optional[list[float]]:
    """Parse table-format spacing from prompt text.

    Matches lines like "1-2 = 10'" or "A-B = 15'" under
    Vertical: / Horizontal: section headers.
    """
    lower = text.lower()
    section_key = section.lower() + ":"
    section_idx = lower.find(section_key)
    if section_idx < 0:
        return None

    after_section = text[section_idx + len(section_key) :]

    # Find the next section header to bound the current section
    other_sections = ["vertical:", "horizontal:"]
    next_section_idx = -1
    for hdr in other_sections:
        if hdr == section_key:
            continue
        idx = after_section.lower().find(hdr)
        if idx >= 0 and (next_section_idx < 0 or idx < next_section_idx):
            next_section_idx = idx

    section_text = (
        after_section[:next_section_idx]
        if next_section_idx >= 0
        else after_section
    )

    table_pattern = re.compile(
        r"[\w]+-[\w]+\s*=\s*(\d+\.?\d*)\s*['\s]*(?:ft|feet|foot)?",
        re.IGNORECASE,
    )

    matches = table_pattern.findall(section_text)
    if not matches:
        return None

    values: list[float] = []
    for val_str in matches:
        try:
            val = float(val_str)
            if val <= 0:
                return None
            values.append(val)
        except ValueError:
            return None

    return values if values else None


def _extract_spacing(lower: str) -> Optional[float]:
    """Extract uniform grid spacing from prompt."""
    patterns = [
        r"(\d+\.?\d*)['\s]*(?:ft|feet|foot)?\s*(?:spacing|apart|between)",
        r"spaced?\s+(?:evenly\s+)?(?:at\s+)?(\d+\.?\d*)['\s]*(?:ft|feet|foot)?",
        r"spacing\s*(?:of\s+|evenly\s+)?(?:at\s+)?(\d+\.?\d*)['\s]*(?:ft|feet|foot)?",
        r"every\s+(\d+\.?\d*)['\s]*(?:ft|feet|foot)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            return float(match.group(1))
    return None


def _extract_length(lower: str) -> Optional[float]:
    """Extract grid length from prompt."""
    patterns = [
        r"(\d+\.?\d*)['\s]*(?:ft|feet|foot)?\s*long",
        r"length\s*(?:of\s*)?(\d+\.?\d*)['\s]*(?:ft|feet|foot)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            return float(match.group(match.lastindex))
    return None


# ---------------------------------------------------------------------------
# CreateLevels resolver functions
# ---------------------------------------------------------------------------


def _is_level_prompt(lower: str) -> bool:
    """Check if this prompt is explicitly about level creation."""
    level_keywords = ["level", "levels"]
    create_keywords = ["create", "add", "make", "build", "generate"]
    has_level = any(kw in lower for kw in level_keywords)
    has_create = any(kw in lower for kw in create_keywords)
    return has_level and has_create


def _check_level_clarification(
    lower: str, original_prompt: str
) -> Optional[ResolvedPrompt]:
    """Check if the prompt uses floors/stories without 'level'.

    If so, return a clarification-needed result instead of executing.
    """
    # Only trigger if it looks like a creation prompt
    create_keywords = ["create", "add", "make", "build", "generate"]
    if not any(kw in lower for kw in create_keywords):
        return None

    # Match "floors" or "stories" without "level" keyword
    floor_match = re.search(r"(\d+)\s*(?:floors?|stories|storeys?)", lower)
    if not floor_match:
        floor_match = re.search(r"(?:floors?|stories|storeys?)\s+(?:at\s+)?", lower)

    if not floor_match:
        return None

    # Don't trigger if "level" is also present
    if "level" in lower:
        return None

    # Build clarification
    count_match = re.search(r"(\d+)\s*(?:floors?|stories|storeys?)", lower)
    if count_match:
        count = int(count_match.group(1))
        # Check for spacing
        spacing_match = re.search(
            r"(\d+\.?\d*)['\s]*(?:ft|feet|foot)?\s*(?:apart|spacing|spaced|floor)",
            lower,
        )
        spacing_str = ""
        if spacing_match:
            spacing_str = f" spaced {spacing_match.group(1)} ft apart"
        clarification_msg = (
            f"Did you mean Revit building levels — {count} levels{spacing_str}?\n"
            f"If so, please rephrase with 'levels' "
            f"(e.g. 'Create {count} levels{spacing_str}')."
        )
    else:
        clarification_msg = (
            "Did you mean Revit building levels?\n"
            "If so, please rephrase with 'levels' "
            "(e.g. 'Create 5 levels spaced 12 ft apart')."
        )

    return ResolvedPrompt(
        capability_name="CreateLevels",
        params={},
        assumptions=["Prompt uses floors/stories without explicit level keyword"],
        raw_prompt=original_prompt,
        status="clarification_needed",
        clarification_message=clarification_msg,
    )


def _resolve_level_prompt(
    original_prompt: str, lower: str
) -> ResolvedPrompt:
    """Parse a level creation prompt into CreateLevels parameters."""
    lower = replace_word_numbers(lower)

    params: dict = {}
    assumptions: list[str] = []

    # Try named level table format first:
    # "Create levels:\n  Basement = -10'\n  Ground = 0'"
    names, elevations = _parse_named_level_table(original_prompt)
    if names is not None and elevations is not None:
        params["LevelCount"] = len(names)
        params["LevelNames"] = names
        params["VariableElevationsFeet"] = elevations
        assumptions.append(f"Parsed named level table: {len(names)} levels")
        return ResolvedPrompt(
            capability_name="CreateLevels",
            params=params,
            assumptions=assumptions,
            raw_prompt=original_prompt,
        )

    # Try variable elevations: "at elevations 0, 12, 24, 36" or "at 0, 12, 24"
    var_elevations = _parse_variable_elevations(lower)
    if var_elevations is not None:
        params["LevelCount"] = len(var_elevations)
        params["VariableElevationsFeet"] = var_elevations
        assumptions.append(f"Variable elevations: {var_elevations}")
        return ResolvedPrompt(
            capability_name="CreateLevels",
            params=params,
            assumptions=assumptions,
            raw_prompt=original_prompt,
        )

    # Extract count
    count = _extract_level_count(lower)
    if count is not None:
        params["LevelCount"] = count
    else:
        params["LevelCount"] = 1
        assumptions.append("LevelCount defaulted to 1")

    # Extract floor-to-floor spacing
    ftf = _extract_floor_to_floor(lower)
    if ftf is not None:
        params["FloorToFloorFeet"] = ftf

    # Extract start elevation
    start_elev = _extract_start_elevation(lower)
    if start_elev is not None:
        params["StartElevationFeet"] = start_elev
    else:
        params["StartElevationFeet"] = 0.0
        assumptions.append("StartElevationFeet defaulted to 0.0")

    # Extract level names: "named Level 1, Level 2, Level 3"
    level_names = _parse_level_names(lower)
    if level_names is not None:
        params["LevelNames"] = level_names
        # If count wasn't explicitly extracted, derive from names
        if count is None:
            params["LevelCount"] = len(level_names)
            assumptions = [a for a in assumptions if "LevelCount" not in a]

    return ResolvedPrompt(
        capability_name="CreateLevels",
        params=params,
        assumptions=assumptions,
        raw_prompt=original_prompt,
    )


def _extract_level_count(lower: str) -> Optional[int]:
    """Extract level count from prompt."""
    patterns = [
        r"(\d+)\s+levels?\b",
        r"\blevels\s+(\d+)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            return int(match.group(1))
    return None


def _extract_floor_to_floor(lower: str) -> Optional[float]:
    """Extract floor-to-floor height from prompt."""
    patterns = [
        r"(-?\d+\.?\d*)['\s]*(?:ft|feet|foot)?\s*(?:floor[\s-]*to[\s-]*floor|ftf)",
        r"spaced?\s+(?:at\s+)?(-?\d+\.?\d*)['\s]*(?:ft|feet|foot)?(?:\s*apart)?",
        r"(?:floor[\s-]*(?:to[\s-]*floor)?|ftf)\s+(?:height\s+)?(?:of\s+)?(-?\d+\.?\d*)['\s]*(?:ft|feet|foot)?",
        r"(?:height|tall)\s+(?:of\s+)?(-?\d+\.?\d*)['\s]*(?:ft|feet|foot)?",
        r"(-?\d+\.?\d*)['\s]*(?:ft|feet|foot)\s*(?:apart|spacing|spaced)",
    ]
    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            return float(match.group(match.lastindex))
    return None


def _extract_start_elevation(lower: str) -> Optional[float]:
    """Extract start elevation from prompt."""
    patterns = [
        r"start(?:ing)?\s+(?:at|from)\s+(-?\d+\.?\d*)['\s]*(?:ft|feet|foot)?",
        r"(?:from|at)\s+elevation\s+(-?\d+\.?\d*)['\s]*(?:ft|feet|foot)?",
        r"elevation\s+(-?\d+\.?\d*)['\s]*(?:ft|feet|foot)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            return float(match.group(1))
    return None


def _parse_variable_elevations(lower: str) -> Optional[list[float]]:
    """Parse variable elevation values from prompt.

    Matches: "at elevations 0, 12, 24, 36" or "at 0, 14, 28, 40, 52 feet"
    """
    patterns = [
        r"(?:elevations?|at)\s+(-?\d+\.?\d*(?:\s*,\s*(?:and\s+)?-?\d+\.?\d*)+)['\s]*(?:ft|feet|foot)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            raw = match.group(1)
            # Remove "and" from comma list
            raw = re.sub(r"\band\b", "", raw)
            parts = raw.split(",")
            values: list[float] = []
            for part in parts:
                trimmed = part.strip().rstrip("'")
                if not trimmed:
                    continue
                try:
                    values.append(float(trimmed))
                except ValueError:
                    return None
            if len(values) >= 2:
                return values
    return None


def _parse_named_level_table(text: str) -> tuple[Optional[list[str]], Optional[list[float]]]:
    """Parse named level table format.

    Matches:
      Basement = -10'
      Ground = 0'
      Level 2 = 12'
    """
    # Look for lines matching "Name = elevation"
    pattern = re.compile(
        r"^\s*([A-Za-z][A-Za-z0-9 ]*?)\s*=\s*(-?\d+\.?\d*)\s*['\s]*(?:ft|feet|foot)?\s*$",
        re.MULTILINE,
    )
    matches = pattern.findall(text)
    if len(matches) < 2:
        return None, None

    names: list[str] = []
    elevations: list[float] = []
    for name_str, elev_str in matches:
        names.append(name_str.strip())
        elevations.append(float(elev_str))

    return names, elevations


def _parse_level_names(lower: str) -> Optional[list[str]]:
    """Parse level names from 'named X, Y, Z' pattern."""
    match = re.search(r"named\s+(.+?)(?:\s+(?:spaced|at|starting|from)\b|$)", lower)
    if not match:
        return None
    raw = match.group(1)
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) < 1 or not parts[0]:
        return None
    return parts


# ---------------------------------------------------------------------------
# InventoryModel prompt detection and resolution
# ---------------------------------------------------------------------------

_INVENTORY_KEYWORDS = [
    "run inventorymodel",
    "inventory model",
    "inventorymodel",
    "list all model elements",
    "scan model parameters",
    "extract model parameters",
    "extract all parameters",
    "show writable parameters",
    "model inventory",
]


def _is_inventory_prompt(lower: str) -> bool:
    """Check if the prompt requests a model inventory."""
    return any(kw in lower for kw in _INVENTORY_KEYWORDS)


def _resolve_inventory_prompt(original_prompt: str) -> ResolvedPrompt:
    """Resolve an inventory prompt — no parameters needed."""
    return ResolvedPrompt(
        capability_name="InventoryModel",
        params={},
        assumptions=["Read-only model inventory scan"],
        raw_prompt=original_prompt,
    )
