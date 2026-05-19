# Prompt Simulation Coverage — Grid Vertical Slice

Date: 2026-05-07
Branch: `devin/1778113509-vertical-slice`
Mode: `--simulate` (mock execution, no Revit)

---

## Results Matrix

| # | Prompt | Status | H | V | Spacing | Length | Assumptions | Notes |
|---|--------|--------|---|---|---------|--------|-------------|-------|
| 1 | `Create 10 vertical gridlines, 50 ft long, spaced 10 ft apart` | PASS | 5* | 10 | 10.0 | 50.0 | H defaulted | **Primary acceptance prompt — correct** |
| 2 | `Create 5 grids spaced 30 ft apart` | PASS | 5 | 5 | 30.0 | 0* | L derived | Generic "5 grids" → both H=5, V=5. Reasonable. |
| 3 | `Create 8 vertical grids at 20 foot spacing` | PASS | 5* | 8 | 20.0 | 0* | H defaulted, L derived | Correct |
| 4 | `Create 6 horizontal grids spaced 25 feet apart` | PASS | 6 | 5* | 25.0 | 0* | V defaulted, L derived | Correct |
| 5 | `Create 10 vertical gridlines` | PASS | 5* | 10 | 30.0* | 0* | H, S, L defaulted | Correct — minimal prompt, all defaults reasonable |
| 6 | `Create grids every 10 feet` | PASS | 5* | 5* | **30.0*** | 0* | H, V, S, L defaulted | **BUG: "every 10 feet" not parsed as spacing** |
| 7 | `Create 4 by 6 grid layout spaced 30 ft` | PASS | **6** | **6** | 30.0 | 0* | L derived | **BUG: "4 by 6" → H=6,V=6 (4 lost)** |
| 8 | `Create 10 vertical gridlines 50 feet long` | PASS | 5* | 10 | 30.0* | 50.0 | H, S defaulted | Correct |
| 9 | `Create 10 grids, spacing 10` | PASS | 10 | 10 | 10.0 | 0* | L derived | Generic "10 grids" → both H=10, V=10. Reasonable. |
| 10 | `Create 10 vertical gridlines, 50' long, spaced 10' apart` | PASS | 5* | 10 | 10.0 | 50.0 | H defaulted | **Foot-mark notation works — correct** |

`*` = defaulted value

---

## Findings

### All 10 prompts simulate successfully (no crashes or FAILED status)

### 2 parameter resolution issues found:

**Issue A — Test 6: "every N feet" not parsed as spacing**

- Prompt: `Create grids every 10 feet`
- Expected: SpacingFeet=10.0
- Actual: SpacingFeet=30.0 (default)
- Cause: `_extract_spacing()` regex patterns don't match "every N feet". Current patterns require "spaced", "spacing", or "apart" keywords.
- Severity: **Low — fix recommended.** Adding `r"every\s+([\d.]+)['\s]*(?:ft|feet|foot)?"` is a small, low-risk pattern addition.

**Issue B — Test 7: "N by M" grid layout not parsed correctly**

- Prompt: `Create 4 by 6 grid layout spaced 30 ft`
- Expected: HorizontalCount=4, VerticalCount=6
- Actual: HorizontalCount=6, VerticalCount=6 (both set from generic "6 grid" match)
- Cause: `_extract_counts()` has no "N by M" pattern. The generic regex `(\d+)\s*(?:grid|grids)` matches "6 grid" and sets both H and V to 6. The "4" is lost.
- Severity: **Low — fix recommended.** Adding `r"(\d+)\s*(?:by|x)\s*(\d+)"` pattern is small and unambiguous.

### No issues found:

- Primary acceptance prompt (#1) — fully correct
- Foot-mark notation (`50' long`, `10' apart`) — works (#10)
- Orientation keywords (horizontal/vertical) — correctly parsed (#3, #4, #5, #8)
- Generic count ("N grids" without orientation) — both H and V set to N. Reasonable default (#2, #9).
- "spacing N" without units — works (#9)
- All defaults filled correctly when not specified
- Assumptions tracked and reported for every defaulted value

---

## Recommendation

| Issue | Fix? | Risk | Rationale |
|-------|------|------|-----------|
| A: "every N feet" | Yes | Very low | Single regex addition, directly tied to grid spacing |
| B: "N by M" layout | Yes | Low | Unambiguous pattern, directly tied to grid counts |

Both fixes are small regex additions in `_extract_spacing()` and `_extract_counts()` — no architectural changes, no scope expansion.
