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

    # Check for arithmetic/progressive spacing sequences early
    arith_clarification = _check_arithmetic_spacing(lower, prompt)
    if arith_clarification is not None:
        return arith_clarification

    params = dict(_GRID_DEFAULTS)
    assumptions: list[str] = []

    # Extract counts
    h_count, v_count = _extract_counts(lower)

    has_vertical = h_count is not None
    has_horizontal = v_count is not None

    # Detect explicit orientation keywords in prompt
    has_orientation_keyword = (
        "vert" in lower or "column" in lower
        or "horiz" in lower or "row" in lower
    )

    if h_count is not None:
        params["HorizontalCount"] = h_count
    if v_count is not None:
        params["VerticalCount"] = v_count

    # Extract variable spacing (table format and comma lists)
    h_spacings, v_spacings, has_vertical, has_horizontal = _extract_variable_spacings(
        prompt, lower, has_vertical, has_horizontal
    )

    # Also try inline comma spacings ("spaced 5, 6, and 20 feet apart")
    if h_spacings is None and v_spacings is None:
        inline = _parse_inline_spacings(lower)
        if inline is not None:
            if has_vertical and not has_horizontal:
                h_spacings = inline
            elif has_horizontal and not has_vertical:
                v_spacings = inline
            elif "vert" in lower or "column" in lower:
                h_spacings = inline
                has_vertical = True
            elif "horiz" in lower or "row" in lower:
                v_spacings = inline
                has_horizontal = True
            else:
                h_spacings = inline
                has_vertical = True

    # Determine the requested count for the primary orientation
    primary_count = None
    spacings_found = h_spacings or v_spacings

    if spacings_found is not None:
        if h_spacings is not None:
            primary_count = h_count
        elif v_spacings is not None:
            primary_count = v_count

        # Validate spacing count vs grid count mismatch
        if primary_count is not None:
            expected_intervals = primary_count - 1
            actual_intervals = len(spacings_found)
            if expected_intervals > 0 and actual_intervals != expected_intervals:
                return ResolvedPrompt(
                    capability_name="CreateGrids",
                    params=dict(_GRID_DEFAULTS),
                    assumptions=[],
                    raw_prompt=prompt,
                    status="clarification_needed",
                    clarification_message=(
                        f"You requested {primary_count} grids but provided "
                        f"{actual_intervals} spacing value{'s' if actual_intervals != 1 else ''}. "
                        f"{primary_count} grids require {expected_intervals} spacing "
                        f"interval{'s' if expected_intervals != 1 else ''}.\n"
                        f"Did you mean:\n"
                        f"- {actual_intervals + 1} grids with spacings "
                        f"{spacings_found}?\n"
                        f"- Or {primary_count} grids with "
                        f"{expected_intervals} spacing values?"
                    ),
                )

        # Clarify when variable spacing provided but no orientation keyword
        if not has_orientation_keyword:
            spacings_list = spacings_found
            return ResolvedPrompt(
                capability_name="CreateGrids",
                params=dict(_GRID_DEFAULTS),
                assumptions=[],
                raw_prompt=prompt,
                status="clarification_needed",
                clarification_message=(
                    f"Variable spacing {spacings_list} was specified but "
                    f"no grid orientation (vertical or horizontal) was given.\n"
                    f"Did you mean:\n"
                    f"- Vertical grids with spacings {spacings_list}?\n"
                    f"- Horizontal grids with spacings {spacings_list}?\n"
                    f"- A grid layout (both orientations)?\n"
                    f"Please specify the orientation "
                    f"(e.g. 'Create {len(spacings_list) + 1} vertical grids "
                    f"with spacings {spacings_list}')."
                ),
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
    Also handles "and" before the last value: "spacings 5, 6, and 20"
    """
    match = re.search(
        r"spacings?\s+([\d]+\.?\d*(?:\s*[,]\s*(?:and\s+)?[\d]+\.?\d*)+)",
        lower,
    )
    if not match:
        return None

    raw = match.group(1)
    # Normalize "and" to comma
    cleaned = re.sub(r"\band\b", ",", raw)
    parts = cleaned.split(",")
    values: list[float] = []
    for part in parts:
        trimmed = part.strip().rstrip("'").strip()
        if not trimmed:
            continue
        # Remove trailing unit words
        trimmed = re.sub(r"\s*(ft|feet|foot)\s*$", "", trimmed).strip()
        if not trimmed:
            continue
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


def _check_arithmetic_spacing(
    lower: str, original_prompt: str
) -> Optional[ResolvedPrompt]:
    """Detect arithmetic/progressive spacing phrases.

    Catches patterns like "spaced 5, 10, 15 and so on" or
    "spacing 5', 10', 15' etc" where the user implies a continuing
    arithmetic sequence rather than a fixed list of intervals.
    """
    sequence_phrases = [
        r"and\s+so\s+on",
        r"etc\.?",
        r"and\s+so\s+forth",
        r"continuing",
        r"\.{3}",  # ellipsis "..."
    ]
    has_sequence_phrase = any(
        re.search(phrase, lower) for phrase in sequence_phrases
    )
    if not has_sequence_phrase:
        return None

    # Extract numbers from the spacing context only (near "spaced" or "spacing")
    spacing_context = re.search(
        r"(?:spaced?|spacing)\s+([\d',.\s]+(?:and\s+so\s+on|etc\.?|\.{3}|and\s+so\s+forth|continuing))",
        lower,
    )
    if spacing_context:
        context_str = spacing_context.group(1)
        nums = re.findall(r"(\d+\.?\d*)", context_str)
    else:
        # Fallback: extract all numbers but skip the first (likely a count)
        all_nums = re.findall(r"(\d+\.?\d*)", lower)
        nums = all_nums[1:] if len(all_nums) > 2 else all_nums
    if len(nums) < 2:
        return None

    # Check if values form an arithmetic progression
    values = [float(n) for n in nums[:5]]  # cap at 5 for detection
    if len(values) >= 3:
        diffs = [values[i + 1] - values[i] for i in range(len(values) - 1)]
        step = diffs[0]
        is_arithmetic = all(abs(d - step) < 0.01 for d in diffs)
    else:
        is_arithmetic = True
        step = values[1] - values[0]

    if is_arithmetic and step > 0:
        clarification_msg = (
            f"It looks like you want spacing that increases by "
            f"{step:g} ft each interval ({', '.join(str(v) for v in values)}, ...).\n"
            f"Axiom currently supports uniform spacing or explicit per-bay "
            f"spacing lists.\n"
            f"Did you mean:\n"
            f"- Uniform spacing of {values[0]:g} ft?\n"
            f"- An explicit list of spacing values "
            f"(e.g. 'spacings {', '.join(str(v) for v in values)}')?\n"
            f"Please provide the exact spacing values for each bay."
        )
    else:
        clarification_msg = (
            f"It looks like you want a progressive spacing sequence "
            f"({', '.join(str(v) for v in values)}, ...).\n"
            f"Axiom currently supports uniform spacing or explicit per-bay "
            f"spacing lists.\n"
            f"Please provide the exact spacing values for each bay."
        )

    return ResolvedPrompt(
        capability_name="CreateGrids",
        params=dict(_GRID_DEFAULTS),
        assumptions=[],
        raw_prompt=original_prompt,
        status="clarification_needed",
        clarification_message=clarification_msg,
    )


def _parse_inline_spacings(lower: str) -> Optional[list[float]]:
    """Parse inline comma-separated spacing values without 'spacings' keyword.

    Matches: "spaced 5, 6, and 20 feet apart" or "spaced 5, 6 and 20 ft apart"
    """
    match = re.search(
        r"spaced?\s+([\d]+\.?\d*\s*(?:[',]\s*(?:and\s+)?[\d]+\.?\d*)+)"
        r"\s*['\s]*(?:ft|feet|foot)?",
        lower,
    )
    if not match:
        return None

    raw = match.group(1)
    # Clean up: remove 'and', commas, foot marks
    cleaned = re.sub(r"\band\b", ",", raw)
    parts = cleaned.split(",")
    values: list[float] = []
    for part in parts:
        trimmed = part.strip().rstrip("'").strip()
        if not trimmed:
            continue
        # Remove trailing unit words
        trimmed = re.sub(r"\s*(ft|feet|foot)\s*$", "", trimmed).strip()
        if not trimmed:
            continue
        try:
            val = float(trimmed)
            if val <= 0:
                return None
            values.append(val)
        except ValueError:
            return None

    return values if len(values) >= 2 else None


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
    "inventory parameters",
    "run full inventorymodel",
    "full inventory",
    "inventory sample",
    "inventory plan",
    "extraction plan",
]

_KNOWN_CATEGORIES = [
    "walls", "doors", "windows", "floors", "roofs", "ceilings",
    "columns", "beams", "stairs", "railings", "curtain panels",
    "curtain wall mullions", "furniture", "plumbing fixtures",
    "mechanical equipment", "electrical fixtures", "lighting fixtures",
    "generic models", "structural foundations", "structural framing",
    "duct systems", "ducts", "pipe systems", "pipes",
    "rooms", "areas", "levels", "views", "sheets",
]

_FULL_SCAN_BLOCKED_MESSAGE = (
    "Full value extraction is currently disabled for live Revit sessions. "
    "Full element+parameter value scans have caused Revit crashes on large models.\n\n"
    "Safe workflow:\n"
    "  1. Run InventoryModel (summary counts only)\n"
    "  2. Run InventoryModel schema (parameter definitions, no values)\n"
    "  3. Run 'axiom inventory-plan --file <summary.json>' for extraction plan\n"
    "  4. Constrained sample values:\n"
    "     - \"Run InventoryModel sample values for Walls\" (category samples)\n"
    "     - \"Run InventoryModel sample values for Walls max 25\"\n"
    "     - \"Run InventoryModel sample values on Level 1 max 25\"\n"
    "  5. Category scans for small categories:\n"
    "     - \"Run InventoryModel for Walls\" (category value extraction)\n"
    "     - \"Run InventoryModel for Walls schema\" (category schema only)\n"
    "     - \"Run InventoryModel on Level 1\" (level scan)\n"
    "     - \"Run InventoryModel sample\" (first 100 elements)\n\n"
    "Schema discovery collects parameter metadata without extracting values.\n"
    "Whole-model value sampling is blocked — use category/level constraints.\n"
    "Full value extraction remains blocked.\n\n"
    "Do not run unbounded value extraction. Use schema or constrained sample modes."
)

_PARAMETER_SCHEMA_BLOCKED_MESSAGE = (
    "Whole-model parameter schema discovery is disabled for live Revit sessions. "
    "It crashed Revit 2027 on large models due to iterating all elements.\n\n"
    "Use category or level-constrained parameter schema instead:\n"
    "  - \"Run InventoryModel for Walls parameter schema\"\n"
    "  - \"Run InventoryModel for Ceilings parameter schema\"\n"
    "  - \"Run InventoryModel for Plumbing Fixtures parameter schema\"\n"
    "  - \"Run InventoryModel parameter schema on Level 1\"\n"
    "  - \"Run InventoryModel for Walls on Level 1 parameter schema\"\n\n"
    "For whole-model learning, use the planner-driven workflow:\n"
    "  1. Run InventoryModel (summary)\n"
    "  2. axiom inventory-plan --file <summary.json>\n"
    "  3. Execute category-by-category parameter schema commands\n\n"
    "For whole-model element inventory (no parameters):\n"
    "  - \"Run InventoryModel schema\" (object_schema — validated safe)"
)

_SAMPLE_VALUES_BLOCKED_MESSAGE = (
    "Whole-model value sampling is disabled for live Revit sessions. "
    "It crashed Revit 2027 on large models due to expensive value accessors.\n\n"
    "Use constrained sample values instead:\n"
    "  - \"Run InventoryModel sample values for Walls\"\n"
    "  - \"Run InventoryModel sample values for Plumbing Fixtures\"\n"
    "  - \"Run InventoryModel sample values for Walls max 25\"\n"
    "  - \"Run InventoryModel sample values on Level 1 max 25\"\n"
    "  - \"Run InventoryModel sample values for Walls on Level 1 max 25\"\n\n"
    "For whole-model learning, use object schema:\n"
    "  - \"Run InventoryModel schema\" (object_schema — element inventory, no values)\n"
    "For parameter definitions, use category-constrained parameter schema:\n"
    "  - \"Run InventoryModel for Walls parameter schema\"\n\n"
    "Hard caps: max 25 elements per sample run, 5 samples per parameter."
)


def _is_inventory_prompt(lower: str) -> bool:
    """Check if the prompt requests a model inventory."""
    if any(kw in lower for kw in _INVENTORY_KEYWORDS):
        return True
    # Category-scoped: "inventory walls", "inventory for doors"
    if "inventory" in lower and "grid" not in lower:
        return True
    return False


def _extract_level_filter(lower: str) -> str | None:
    """Extract level filter from inventory prompt, e.g. 'on level 1'."""
    # Match level name but stop before keywords that start a new clause
    level_match = re.search(
        r"(?:on |for |at )level\s+(\S+(?:\s+\S+)??)(?:\s+(?:max|limit|first|top|batch|with|and|then|parameter|param|schema|sample)\b|$)",
        lower,
    )
    if level_match:
        raw = level_match.group(1).strip()
        if raw not in ("s", "keyword"):
            return raw.title()
    return None


def _resolve_inventory_prompt(original_prompt: str) -> ResolvedPrompt:
    """Resolve an inventory prompt with staged safety parameters.

    Supported modes:
      - summary (default): counts and categories only
      - schema: parameter definitions/metadata, no values (safe for whole model)
      - sample_values: limited value samples per parameter (safe with caps)
      - sample: first 100 elements with parameters
      - category: single category with parameters (safe for small categories)
      - category_schema: category parameter definitions only
      - category_sample_values: category with limited value samples
      - level: single level with parameters
      - category_level: single category + level with parameters
      - plan: build extraction plan from summary (CLI-side)
      - full/full_values: BLOCKED — returns clarification_needed
    """
    lower = original_prompt.lower().strip()
    params: dict = {}
    assumptions: list[str] = ["Read-only model inventory scan"]

    is_full = ("full inventory" in lower or "run full inventorymodel" in lower
                or "full scan" in lower or "complete inventory" in lower
                or "full values" in lower)
    is_sample_values = "sample values" in lower or "sample value" in lower
    is_sample = "sample" in lower and not is_sample_values
    is_parameter_schema_plan = ("parameter schema plan" in lower or "param schema plan" in lower)
    is_parameter_schema = ("parameter schema" in lower or "param schema" in lower) and not is_parameter_schema_plan
    is_schema = "schema" in lower and not is_parameter_schema and not is_parameter_schema_plan
    is_plan = "inventory plan" in lower or "extraction plan" in lower

    # Check for category filter
    category_filter = None
    for cat in _KNOWN_CATEGORIES:
        if (f"inventory for {cat}" in lower
                or f"inventory {cat}" in lower
                or f"inventorymodel for {cat}" in lower
                or f"inventory parameters for {cat}" in lower
                or f"values for {cat}" in lower
                or f"schema for {cat}" in lower):
            category_filter = cat.title()
            break

    # Check for level filter
    level_filter = _extract_level_filter(lower)

    # Check for batch size: "max 500", "limit 1000", "batch 10000"
    # Semantics: continuation/pagination — process in batches of N,
    # not "take first N and stop".
    batch_size = None
    batch_match = re.search(r"(?:max|limit|first|top|batch)\s+(\d+)", lower)
    if batch_match and not is_sample:
        batch_size = int(batch_match.group(1))

    if is_full:
        return ResolvedPrompt(
            capability_name="InventoryModel",
            params={},
            assumptions=["Full value extraction is currently disabled for live Revit sessions"],
            raw_prompt=original_prompt,
            status="clarification_needed",
            clarification_message=_FULL_SCAN_BLOCKED_MESSAGE,
        )
    elif is_parameter_schema_plan:
        # Plan execution: category-by-category parameter schema.
        # Handled by C# PromptCommand — reads plan JSON, dispatches per category.
        is_resume = "resume" in lower
        is_priority_only = "priority only" in lower or "priority-only" in lower
        max_categories = 0
        max_match = re.search(r"(?:max|limit|first|top)\s+(\d+)", lower)
        if max_match:
            max_categories = int(max_match.group(1))

        plan_assumptions = ["Category-by-category parameter schema plan execution"]
        if is_resume:
            plan_assumptions.append("Resume mode: skip previously completed categories")
        if is_priority_only:
            plan_assumptions.append("Priority categories only")
        if max_categories > 0:
            plan_assumptions.append(f"Max {max_categories} categories")

        return ResolvedPrompt(
            capability_name="InventoryModel",
            params={
                "ScanMode": "parameter_schema_plan",
                "PlanExecution": True,
                "IsResume": is_resume,
                "PriorityOnly": is_priority_only,
                "MaxCategories": max_categories,
            },
            assumptions=plan_assumptions,
            raw_prompt=original_prompt,
            status="ok",
        )
    elif is_plan:
        return ResolvedPrompt(
            capability_name="InventoryPlan",
            params={},
            assumptions=[
                "Extraction plan requested",
                "Run summary mode first, then use 'axiom inventory-plan --file <summary.json>'",
            ],
            raw_prompt=original_prompt,
            status="clarification_needed",
            clarification_message=(
                "To build an extraction plan:\n"
                "  1. Run InventoryModel (summary mode) in Revit\n"
                "  2. Copy the exported JSON path from the dialog\n"
                "  3. Run: axiom inventory-plan --file \"<path to summary.json>\"\n\n"
                "The plan will group categories by discipline, isolate large categories, "
                "and chunk very large ones into safe batches.\n"
                "Adjust thresholds with --max-group, --isolate-threshold, --max-chunk."
            ),
        )
    elif is_sample:
        params = {
            "SummaryOnly": False,
            "MaxElements": 100,
            "IncludeParameters": True,
            "ScanMode": "sample",
        }
        assumptions.append("Sample scan: first 100 elements with parameters")
    elif is_parameter_schema and (category_filter or level_filter):
        # Constrained parameter schema: requires category or level.
        # Whole-model parameter_schema crashed Revit 2027.
        params = {
            "SummaryOnly": False,
            "ParameterSchemaOnly": True,
            "IncludeParameters": False,
            "ScanMode": "category_parameter_schema",
        }
        if category_filter:
            params["CategoryFilter"] = [category_filter]
        if level_filter:
            params["LevelFilter"] = [level_filter]
        scope_parts = []
        if category_filter:
            scope_parts.append(category_filter)
        if level_filter:
            scope_parts.append(f"on {level_filter}")
        scope = " ".join(scope_parts)
        assumptions.append(f"Constrained parameter schema: {scope} parameter definitions only (no values)")
        if batch_size:
            params["BatchSize"] = batch_size
            assumptions.append(f"Batched parameter schema: {batch_size} elements per batch")
    elif is_parameter_schema:
        # Whole-model parameter schema: BLOCKED — crashed Revit 2027.
        return ResolvedPrompt(
            capability_name="InventoryModel",
            params={},
            assumptions=["Whole-model parameter schema is disabled for live Revit sessions"],
            raw_prompt=original_prompt,
            status="clarification_needed",
            clarification_message=_PARAMETER_SCHEMA_BLOCKED_MESSAGE,
        )
    elif is_schema and category_filter:
        # Category object schema: element/class/category inventory, no parameters
        params = {
            "SummaryOnly": False,
            "SchemaOnly": True,
            "CategoryFilter": [category_filter],
            "IncludeParameters": False,
            "ScanMode": "category_object_schema",
        }
        assumptions.append(f"Category object schema: {category_filter} elements (ElementId, Category, ClassName, Name, LevelName, IsType) — no parameters")
        if batch_size:
            params["BatchSize"] = batch_size
            assumptions.append(f"Batched object schema: {batch_size} elements per batch")
    elif is_sample_values and (category_filter or level_filter):
        # Constrained sample values: requires category, level, or max constraint.
        # Whole-model sample values is blocked (crashed Revit 2027).
        params = {
            "SummaryOnly": False,
            "SampleValues": True,
            "SampleLimit": 5,
            "MaxElements": batch_size if batch_size else 25,
            "IncludeParameters": True,
            "ScanMode": "category_sample_values",
        }
        if category_filter:
            params["CategoryFilter"] = [category_filter]
        if level_filter:
            params["LevelFilter"] = [level_filter]
        scope_parts = []
        if category_filter:
            scope_parts.append(category_filter)
        if level_filter:
            scope_parts.append(f"on {level_filter}")
        scope = " ".join(scope_parts)
        assumptions.append(
            f"Constrained value sampling: {scope}, max {params['MaxElements']} elements, "
            f"{params['SampleLimit']} samples/param"
        )
    elif is_schema:
        # Whole-model object schema: element/class/category inventory, no parameters
        params = {
            "SummaryOnly": False,
            "SchemaOnly": True,
            "IncludeParameters": False,
            "ScanMode": "object_schema",
        }
        assumptions.append("Whole-model object schema: elements (ElementId, Category, ClassName, Name, LevelName, IsType) — no parameters. Includes both instances and types.")
        if batch_size:
            params["BatchSize"] = batch_size
            assumptions.append(f"Batched object schema: {batch_size} elements per batch")
    elif is_sample_values:
        # Whole-model sample values: BLOCKED — crashed Revit 2027.
        # Requires category, level, or max constraint.
        return ResolvedPrompt(
            capability_name="InventoryModel",
            params={},
            assumptions=["Whole-model value sampling is disabled for live Revit sessions"],
            raw_prompt=original_prompt,
            status="clarification_needed",
            clarification_message=_SAMPLE_VALUES_BLOCKED_MESSAGE,
        )
    elif category_filter and level_filter:
        params = {
            "SummaryOnly": False,
            "CategoryFilter": [category_filter],
            "LevelFilter": [level_filter],
            "IncludeParameters": True,
            "ScanMode": "category_level",
        }
        assumptions.append(f"Category+level scan: {category_filter} on {level_filter}")
        if batch_size:
            params["BatchSize"] = batch_size
            assumptions.append(f"Batched extraction: {batch_size} elements per batch")
    elif category_filter:
        params = {
            "SummaryOnly": False,
            "CategoryFilter": [category_filter],
            "IncludeParameters": True,
            "ScanMode": "category",
        }
        assumptions.append(f"Category scan: {category_filter} only")
        if batch_size:
            params["BatchSize"] = batch_size
            assumptions.append(f"Batched extraction: {batch_size} elements per batch")
    elif level_filter:
        params = {
            "SummaryOnly": False,
            "LevelFilter": [level_filter],
            "IncludeParameters": True,
            "ScanMode": "level",
        }
        assumptions.append(f"Level scan: {level_filter} only")
        if batch_size:
            params["BatchSize"] = batch_size
            assumptions.append(f"Batched extraction: {batch_size} elements per batch")
    elif batch_size:
        # Whole-model batch without schema/sample/category/level:
        # Default to object_schema-batched extraction (safe), not full value extraction.
        params = {
            "SummaryOnly": False,
            "SchemaOnly": True,
            "IncludeParameters": False,
            "BatchSize": batch_size,
            "ScanMode": "object_schema",
        }
        assumptions.append(
            f"Whole-model object schema in batches of {batch_size}"
        )
        assumptions.append(
            "Object schema collects elements (ElementId, Category, ClassName) without parameters — safe for large models"
        )
    else:
        params = {
            "SummaryOnly": True,
            "IncludeParameters": False,
            "ScanMode": "summary",
        }
        assumptions.append("Safe summary scan: counts and categories only, no parameter dump")

    return ResolvedPrompt(
        capability_name="InventoryModel" if not is_plan else "InventoryPlan",
        params=params,
        assumptions=assumptions,
        raw_prompt=original_prompt,
    )
