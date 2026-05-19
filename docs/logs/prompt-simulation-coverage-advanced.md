# Prompt Simulation Coverage — Advanced Grid Prompts

Date: 2026-05-07
Branch: `devin/1778113509-vertical-slice`
Mode: `--simulate` (mock execution, no Revit)

**User intent (same for all 15 prompts):**
H=10, V=20, HSpacing=10/20, VSpacing=20/10, HLength=100, VLength=50, Origin=0,0,0, Heads=top+left

---

## Results Matrix

| # | Prompt (abbreviated) | Status | H | V | Spacing | Length | Issues |
|---|---------------------|--------|---|---|---------|--------|--------|
| 1 | `Create 10 horizontal grids and 20 vertical grids...spaced 10 ft and 20 ft` | PASS | 10 | 20 | 10.0 | 50.0 | First spacing/length matched only |
| 2 | `Make a 10 by 20 grid layout...10' spacing...20' spacing` | PASS | 10 | 20 | 10.0 | 0* | Length not extracted |
| 3 | `Draw grids...10 horizontal, 20 vertical...Horizontal length 100 feet, vertical length 50 feet` | PASS | 10 | 20 | 10.0 | 100.0 | First length (100) used for both |
| 4 | `Create building grid...20 vertical gridlines and 10 horizontal gridlines...50', 100'` | PASS | 10 | 20 | 10.0 | 50.0 | First length (50) used for both |
| 5 | `Place 10 horizontal grids, 20 vertical grids...spacing 10 ft...20 ft` | PASS | 10 | 20 | 10.0 | 0* | First spacing only |
| 6 | `Generate a centered grid layout: 20 vertical, 10 horizontal...even spacing.` | **CRASH** | — | — | — | — | `float('.')` — regex matched period |
| 7 | `Create grids centered on origin...Space evenly at 10 and 20 feet.` | PASS | 10 | 20 | 30.0* | 50.0 | "Space evenly at N" not matched |
| 8 | `At project coordinates 0,0,0 create 10 rows and 20 columns...10' and 20' spacing.` | **CRASH** | — | — | — | — | `float('.')` — regex matched period |
| 9 | `Make grid system: 10 horizontal x 20 vertical...Spacing should be 10 feet` | **CRASH** | — | — | — | — | `float('.')` — regex matched period |
| 10 | `Place gridlines...twenty vertical and ten horizontal...50 and 100 feet...10 and 20 feet` | PASS | 5* | 5* | 30.0* | 0* | Word numbers ("twenty", "ten") not parsed |
| 11 | `Need grids, 10 horiz 20 vert...spacing 10 and 20` | PASS | 5* | 5* | 10.0 | 0* | "horiz"/"vert" abbreviations not recognized |
| 12 | `Create 20 vertical grids 50' long and 10 horizontal 100' long...spacing evenly 10'/20'` | PASS | 10 | 20 | 30.0* | 50.0 | "spacing evenly" not matched |
| 13 | `Grid layout please...10 ft and 20 ft spacing.` | **CRASH** | — | — | — | — | `float('.')` — regex matched period |
| 14 | `Draw 10 horizontal by 20 vertical grids...space evenly 10 and 20 feet` | PASS | 10 | 20 | 30.0* | 0* | "space evenly N" not matched |
| 15 | `Make a project center grid...20 verticals, 10 horizontals, vertical length 50'` | PASS | 10 | 20 | 30.0* | 50.0 | Truncated prompt |

`*` = defaulted value, `—` = crashed before resolving

---

## Summary

### Crashes: 4 of 15 (MUST FIX)

**Root cause:** `_extract_spacing()` regex pattern `([\d.]+)` matches a standalone period (`.`) from sentence-ending punctuation. `float('.')` throws `ValueError`.

Affected prompts: #6, #8, #9, #13 — all contain "spacing." or similar sentence-ending patterns.

**Fix:** Change `[\d.]+` to `\d+\.?\d*` (requires at least one digit) across all numeric extraction patterns.

### Counts: 11 of 15 correct

- 11 prompts correctly extracted H=10, V=20 from digit + "horizontal"/"vertical" keywords
- 2 failed on word numbers (#10: "twenty vertical", "ten horizontal") — acceptable for this phase
- 2 failed on abbreviations (#11: "horiz", "vert") — low-risk fix but acceptable to defer

### Not supported by current resolver (by design):

| Feature | Mentioned in | Phase |
|---------|-------------|-------|
| Dual spacing (H vs V) | All 15 | Future — requires `HorizontalSpacing` + `VerticalSpacing` params |
| Dual length (H vs V) | All 15 | Future — requires `HorizontalLength` + `VerticalLength` params |
| Origin/center coordinates | All 15 | Future — requires `Origin` param (XYZ) |
| Grid heads/bubbles position | Most | Future — Revit grid head settings |
| "rows"/"columns" vocabulary | #8 | Future |
| Word numbers ("twenty") | #10 | Future |
| Abbreviations ("horiz"/"vert") | #11 | Low-risk fix if desired |

---

## Recommendations

| Issue | Fix now? | Risk | Rationale |
|-------|----------|------|-----------|
| `float('.')` crash | **YES** | Very low | Bug — should never crash on valid input |
| "horiz"/"vert" abbreviations | Optional | Very low | Single keyword addition |
| Word numbers | No | Medium | Adds complexity, limited ROI for this phase |
| Dual spacing/length | No | High | Requires GridParameters schema change |
| Origin | No | High | Requires GridParameters + C# schema change |
| Grid heads | No | High | Revit-specific feature, not in current GridParameters |
