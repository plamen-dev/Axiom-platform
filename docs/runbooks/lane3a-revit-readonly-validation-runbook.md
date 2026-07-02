# Lane-3A Revit Read-Only Validation Runbook

## Purpose

Prove the Revit-facing substrate on the operator machine (furnace, AXIOM-01)
**without mutating any model**: environment discovery, add-in
deployment/load, a read-only InventoryModel interaction, artifact capture,
Local Runner compatibility where applicable, and evidence-summary emission.

This is the **lane-3A** gate. It sits between lane-2 (Windows non-Revit loop —
passed 2026-07-02 at main `017fb1e` / post-#63) and lane-3B (real-Revit
mutation, e.g. SetParameterValue / PR C).

> **Rule: lane-3A read-only success does NOT imply lane-3B mutation
> readiness.** Lane-3A evidence must never be cited as mutation readiness.
> Lane-3B requires its own controlled single-mutation runbook and explicit
> operator gate.

### Evidence lanes (do not conflate)

| Lane | Meaning | Status |
|------|---------|--------|
| 1 — Devin/Ubuntu | repo proof | green |
| 2 — Windows non-Revit loop | target-environment substrate proof | passed 2026-07-02 |
| 3A — Revit read-only | environment + add-in + read-only interaction proof | **this runbook** |
| 3B — Revit mutation | real model mutation (PR C, SetParameterValue) | out of scope — NOT unlocked by 3A |

## Operator target: Revit 2026

**Revit 2026 is the explicit validation target for lane-3A.** The 2024
baseline (`baseline-001-revit-2024-capability-platform`) and the isolated
2027 compatibility work are mentioned below only as build/path context —
they are not the lane-3A target.

2026 build/deploy context (confirm on the machine; record actuals):

- Revit 2025+ runs add-ins on modern .NET (not .NET Framework 4.8). The
  repo has verified build paths for 2024 (`net48`) and 2027
  (`net10.0-windows`) but **no verified 2026 build target yet**. Use the
  MSBuild `RevitVersion` override strategy from
  `revit-multi-version-runbook.md` (or an SDK-style build against
  `C:\Program Files\Autodesk\Revit 2026\RevitAPI.dll`) and **record exactly
  what was needed** — that record becomes the 2026 section of the
  multi-version runbook.
- Deployed add-in folder for 2026: the version-specific Addins folder
  `...\Autodesk\Revit\Addins\2026\` (ProgramData for all-users is the 2024
  pattern; 2027 deviates to Program Files — record which location 2026
  actually loads from).
- Deployment set: `Axiom.RevitAddin.addin` (manifest, `<Assembly>` pointing
  at the deployed DLL), `Axiom.RevitAddin.dll`, `Axiom.Core.dll`,
  `Newtonsoft.Json.dll`.

If a 2026 build cannot be produced (API/framework break), STOP: that is a
lane-3A finding to report, not a reason to fall back silently to 2024/2027.

## Scope

In scope: Revit environment discovery, add-in build/deploy/load verification,
read-only InventoryModel (summary → constrained modes only), artifact capture
under `artifacts/model_inventory_runs/`, Local Runner compatibility for the
non-Revit-attached steps, `emit_evidence_summary` after the run.

Non-goals — **strictly forbidden in lane-3A**:

- No model mutation of any kind: no CreateGrids, no CreateLevels, no
  SetParameterValue (not even preview→apply), no batch mutation.
- No operation that requires saving the model.
- No full or whole-model-value InventoryModel scans — `Run full
  InventoryModel`, unconstrained `parameter schema`, and unconstrained
  `sample values` remain **blocked** (BUG-017 / inventory safety rules).
- No PR C implementation, no lane-3B claims.

## Operator fields (fill in before starting; return with the report)

| Field | Value |
|-------|-------|
| Revit version + build | e.g. Revit 2026.x, build ____ |
| Model name/path | ____ |
| Model disposable/copied/backed up? | must be YES (disposable or a copy) — state which |
| Add-in path (deployed DLLs) | e.g. `...\Autodesk\Revit\Addins\2026\` |
| Manifest path | `...\Addins\2026\Axiom.RevitAddin.addin` |
| Expected artifact directory | `artifacts/model_inventory_runs/lane3a_<date>/` + `artifacts/validation_runs/<summary_id>/` |
| Cleanup action | default: **close model WITHOUT saving** (state if you chose otherwise) |
| Repo commit (`git rev-parse HEAD`) | ____ |

## Prerequisites

- Windows 10/11, repo at `C:\Dev\Axiom\Code\Axiom-platform`, `main` at or
  past PR #64; `git status --short` clean.
- `poetry install` done; `python -m poetry run axiom --help` works.
- Revit 2026 installed and licensed.
- A **disposable or copied** test model (never a production model), openable
  in Revit 2026.
- WDAC note: invoke Axiom directly via module form
  (`python -m poetry run axiom ...`); the Local Runner already emits
  Windows-safe invocation.

## Gates

### Gate 1 — Environment discovery (no Revit needed)

```
git rev-parse HEAD
git status --short
python -m poetry run axiom --help
python -m poetry run axiom runner-commands | findstr /i inventory
```

**PASS:** repo at expected commit, tree clean, CLI lists `inventory-model`,
`inventory-summary`, `local-runner`; registry catalogs the inventory
commands. **FAIL:** any command errors or commands missing.

### Gate 2 — Add-in build + deploy for Revit 2026 (read-only w.r.t. models)

- Build against Revit 2026 API per the multi-version strategy (record the
  exact commands/property overrides used).
- Deploy manifest + DLL set to the 2026 Addins folder; verify all four files
  exist and the manifest `<Assembly>` points at the deployed DLL.

**PASS:** build succeeds; manifest + DLLs present at the 2026 per-version
path. **FAIL:** build/API errors (report as a lane-3A finding — do not fall
back to another Revit version silently).

### Gate 3 — Add-in load smoke (Revit open, no document interaction yet)

- Start Revit 2026; accept the add-in load prompt if shown.
- Confirm the Axiom add-in loaded (no load-error dialog).
- Open the disposable test model.

**PASS:** add-in loaded, no errors, model open. **FAIL:** load error dialog
or missing add-in.

### Gate 4 — Read-only InventoryModel (staged, constrained only)

With Revit + model open:

```
python -m poetry run axiom inventory-model --output-dir artifacts/model_inventory_runs --run-id lane3a_<date>
```

This sends the `Run InventoryModel` prompt (summary mode — counts +
categories, no parameter dump). Optionally, if summary succeeds, ONE
constrained follow-up is allowed for depth:

```
python -m poetry run axiom prompt "Run InventoryModel schema"
```

Forbidden: `Run full InventoryModel`, whole-model `parameter schema`,
unconstrained `sample values`.

**PASS:** summary returns nonzero instance/type counts and a category
breakdown; Revit does not crash; nothing prompts to modify/save the model;
`git status --short` shows no tracked-file changes. **FAIL:** crash, empty
inventory on a non-empty model, or any mutation/save prompt (a crash during
a *constrained* mode is a lane-3A FAIL and blocks lane-3B planning until
triaged).

### Gate 5 — Artifact capture

```
dir artifacts\model_inventory_runs\lane3a_<date>
python -m poetry run axiom inventory-summary --latest --base-dir artifacts/model_inventory_runs
```

**PASS:** run directory exists with the run's Parquet/JSON +
`run_metadata.json` (raw prompt recorded); `inventory-summary` renders it.
Zero parameters in summary mode is expected — NOT a failure. **FAIL:**
missing run dir/metadata or unreadable artifacts.

### Gate 6 — Local Runner compatibility (where applicable)

The Local Runner allowlist has no Revit-attached action (by design — Revit
interaction is operator-driven). Applicable check: the runner still operates
on this machine in the same session/state:

```
python -m poetry run axiom local-runner --task tools/local_runner/examples/git_status.task.json
```

**PASS:** action succeeds; run artifacts under
`artifacts/local_runner_runs/`. **FAIL:** runner error.

### Gate 7 — Evidence summary emission (attested → captured)

```
python -m poetry run axiom local-runner --task tools/local_runner/examples/emit_evidence_summary.task.json
```

Note: this summarizes the newest **execution-chain** bundle (deterministic
substrate loop), not the inventory run — expected; lane-3A's Revit evidence
is the inventory artifact set from Gate 5. If no chain bundle exists on this
checkout, run the lane-2 loop (`execution_chain_run` +
`capability_evidence_apply`) first, then emit.

**PASS:** `artifacts/validation_runs/<summary_id>/evidence_summary.{json,md}`
written; source paths relative; decision/quality fields populated. **FAIL:**
blocked without a resolvable bundle after the lane-2 loop, absolute paths, or
missing fields.

### Gate 8 — Commit captured evidence

Commit ONLY: `artifacts/validation_runs/<summary_id>/` and (optionally) the
lane-3A report. Inventory run dirs under `artifacts/model_inventory_runs/`
are durable local learning outputs — commit only if small and non-sensitive;
otherwise reference the run_id in the report.

**PASS:** evidence committed or explicitly referenced. **FAIL:** evidence
left only as gitignored scratch.

## Pass/fail summary

Lane-3A passes only if **all 8 gates pass**. Any failure: record as a
bug/evidence entry (`docs/logs/bug-validation-log.md`, plus
`behavior-change-ledger.md` if behavioral), not just a chat note.

## Cleanup

- **Default: close the test model WITHOUT saving** (belt-and-suspenders for
  the read-only claim). If you explicitly choose otherwise, state why in the
  report.
- `git status --short` — confirm no unintended tracked changes.
- Optionally prune large local inventory run dirs after the report
  references them.
- Do not uninstall the add-in (lane-3B will need it).

## Evidence to return

- Filled operator-fields table (above).
- Per-gate PASS/FAIL with the observed values (counts, categories, paths).
- Exact 2026 build/deploy commands used (feeds the multi-version runbook).
- `run_id`(s) and `summary_id`.
- The committed `evidence_summary.{json,md}` (or the commit hash containing
  them).
- Any deviations from this runbook and why.

On full pass, lane-3A is validated. Lane-3B (controlled single mutation,
PR C) remains a separate explicit gate with its own runbook — do not begin
it on lane-3A evidence alone.
