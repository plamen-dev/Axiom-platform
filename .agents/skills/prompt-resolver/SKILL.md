---
name: prompt-resolver
description: Operate and verify the prompt resolver / planner domain — natural-language prompt resolution into capability plans, clarification behavior, and regression fixtures. Use when testing or changing prompt resolution, planning, or clarification logic.
---

# Prompt resolver / planner

**status: scaffold** — populate sections the first time verified operational knowledge exists for this domain (same PR as the change; see `.agents/skills/README.md`).

## Domain

Resolves natural-language objectives into structured capability plans. Source: `src/axiom_core/prompt_resolver.py`, `automation_planner.py`, `capability_planner.py`.

## Commands

_(to be populated)_

## Registry pointers

- Regression fixtures: `tests/fixtures/behavior_regressions/`.
- User-visible behavior changes go to `docs/logs/behavior-change-ledger.md`.

## Verification checklists

Protected behaviors (prefer CLARIFICATION_NEEDED over silent wrong execution):
- Arithmetic/progressive spacing ("5, 10, 15 and so on") must not silently become uniform spacing.
- Spacing-count/grid-count mismatch or missing orientation must clarify.
- Grid + level prompts resolve to CreateGrids when grid intent is explicit.
- Rows/columns without the word "grid" must clarify, not assume grids.
- Floors/stories may require clarification before CreateLevels.

## Tests

Targeted resolver/planner test files; add regression fixtures for any behavior change. Full pytest only at PR checkpoints.

## Notes / gotchas

_(to be populated)_
