# Validation Automation Loop v0 — Runbook

The Validation Automation Loop is Axiom's **throughput tool**: it automates
everything *around* the single remaining human step (the live Revit
interaction) so a branch/scenario can be validated repeatably and classified
deterministically.

It is **not** the discovery / bounded-retry / promotion-scoring machinery —
that is the next implementation target (spec §9) and is intentionally out of
scope for v0. See `Axiom_Autonomous_Verification_Loop_Spec_v1` for strategic
context.

## What it automates

```
pre phase                          [ HUMAN ]            scan phase
─────────────────────────────────  ─────────  ─────────────────────────────────
1. record user/admin context        perform     9.  scan evidence across ALL
2. record git branch + commit        the live        user profiles
3. (optional) pull target branch     Revit       10. validate evidence conditions
4. run Python tests                  step        11. classify pass/fail/needs_human
   - tests/test_set_parameter_value.py           12. write result_summary.md
   - tests/test_local_runner.py
5. run ruff
6. (optional) build/deploy Revit 2027
7. capture deployed DLL timestamps
8. print exact manual Revit steps
```

Live Revit remains a human step. The runner handles everything before and
after it.

## Commands

### Python CLI

```bash
# PRE: record context/git, run tests + ruff, (optionally) deploy, print steps
poetry run axiom validation-run \
  --scenario set_parameter_preview_apply \
  --branch set-parameter-revit-bridge \
  --revit-version 2027 \
  --phase pre

# Perform the live Revit step (see manual_revit_steps.md), then:

# SCAN: scan evidence across user profiles, validate, classify
poetry run axiom validation-run --scenario set_parameter_preview_apply --phase scan
```

`--phase all` runs `pre` then `scan` in one shot (only when the live step has
already been done).

### PowerShell wrapper (Windows)

```powershell
# Before live Revit (tests + manual steps)
.\scripts\local\run-validation-loop.ps1 -Phase pre -Branch main

# Deploy too, elevating ONLY the deploy step from a non-admin shell
.\scripts\local\run-validation-loop.ps1 -Phase pre -Deploy -ElevateDeploy

# After live Revit (evaluate evidence)
.\scripts\local\run-validation-loop.ps1 -Phase scan
```

## Bounded retry budget (`--max-attempts`)

The Revit add-in writes evidence asynchronously after the human performs the
live step. The `scan`/`all` phases therefore re-scan up to a bounded number of
attempts until an apply run appears.

- Default: `DEFAULT_MAX_ATTEMPTS = 5`.
- Override to confirm larger testing concepts:

```bash
poetry run axiom validation-run --phase scan --max-attempts 20
```

```powershell
.\scripts\local\run-validation-loop.ps1 -Phase scan -MaxAttempts 20
```

The budget and how much of it was used are recorded in `request.json` and
`pass_fail.json` as `max_attempts` and `attempts_made`. When the budget is
exhausted without evidence, the loop classifies `evidence_missing` /
`revit_manual_step_pending` and writes a `human_action_required.md` packet.

## Scenario v0

`set_parameter_preview_apply_wall_comments` (alias:
`set_parameter_preview_apply`) — validates Set Comments → "Axiom test 001" for
1 Wall via preview → apply with linked evidence.

### Evidence conditions checked (12)

| Condition | Source |
|-----------|--------|
| latest apply run exists | `changes.json` present in a run folder |
| `result_summary.md` exists | apply run folder |
| `request.json` exists | apply run folder |
| `changes.json` exists | apply run folder |
| `linked_preview.json` exists | apply run folder |
| `linked_preview_metadata.json` exists | apply run folder |
| `initiated_from = preview_approval` | changes/request/metadata |
| `targeted_by_ids = true` | changes/request |
| `target_ids_match = true` | linked_preview_metadata |
| `model_modified = true` | changes.json |
| changed element count ≥ 1 | changes.json elements |
| no failed elements | changes.json elements |

## Evidence search (all user profiles)

Evidence is searched under every user profile to avoid IMSAdmin vs Plamen
`LOCALAPPDATA` confusion:

```
C:\Users\*\AppData\Local\Axiom\parameter_edit_runs\spv_*
```

Override with `--evidence-root <dir>` (repeatable) for testing.

## Admin / non-admin handling

- git, tests, and evidence scanning run in the **normal** (non-admin) shell.
- **Only deploy** needs admin. The PowerShell wrapper either:
  - runs deploy in the current elevated shell, or
  - with `-ElevateDeploy`, relaunches **only** the deploy step elevated, then
    continues the loop non-elevated, or
  - reports `needs_admin` and stops without touching the rest of the loop.

## Failure classification (ordered precedence)

```
tests_failed
  → needs_admin
    → deploy_failed
      → revit_manual_step_pending
        → evidence_missing
          → evidence_mismatch
            → pass
```

- `evidence_missing` — a required artifact file is absent (or no apply run).
- `evidence_mismatch` — files exist but a field value is wrong (e.g.
  `target_ids_match=false`, failed elements, `model_modified=false`).

## Artifact bundle

```
artifacts/validation_runs/<run_id>/
├── request.json
├── environment.json
├── git_state.json
├── test_results.json              # pre/all
├── deploy_result.json             # pre/all
├── deployed_dll_timestamps.json   # pre/all
├── manual_revit_steps.md          # pre/all
├── evidence_scan.json
├── pass_fail.json
├── result_summary.md
└── human_action_required.md       # when human action is needed
```

Generated runs (`vrun_*`) are gitignored; curated reports under
`artifacts/validation_runs/` are kept.

## Safety / boundaries

- **No arbitrary shell execution.** Every subprocess is a fixed argv list
  (never a shell string). Branch/scenario inputs are validated against
  conservative patterns.
- No new Revit features; no Selection/Filter engine.
- No changes to CreateGrids / CreateLevels / InventoryModel.
- No changes to SetParameterValue behavior — its evidence is consumed
  read-only.

## Tests

```bash
poetry run pytest tests/test_validation_loop.py
poetry run pytest tests/test_local_runner.py
poetry run ruff check .
```

Local Runner action: `test_validation_loop`
(`tools/local_runner/examples/test_validation_loop.task.json`).
