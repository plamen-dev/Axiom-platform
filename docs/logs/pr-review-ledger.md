# PR Review Ledger

## PR: Local Runner trusted-workspace policy (fix hard-coded C:\Dev\Axiom)

**Branch:** `devin/1780380235-local-runner-workspace-policy`
**Base:** `main`
**Status:** Open
**Scope:** Replace the Local Runner's single hard-coded allowed workspace (`C:\Dev\Axiom`) with a configurable trusted-workspace policy so it works on the GitHub self-hosted runner (Axiom-01) as well as local dev. Fixes the 16 `test_local_runner` failures observed on the self-hosted runner.

### What changed
- `tools/local_runner/local_runner.py`: new trusted-root assembly (`get_allowed_workspace_roots`) from built-in per-platform defaults + JSON config file (`workspace_policy.json` or `$AXIOM_LOCAL_RUNNER_WORKSPACE_CONFIG`) + `$GITHUB_WORKSPACE` + `$AXIOM_LOCAL_RUNNER_WORKSPACE_ROOTS`. `validate_workspace` now canonicalizes paths (case-insensitive on Windows) and matches only against explicitly approved roots. Built-in defaults retained as fallback; `ALLOWED_WORKSPACE_BASES_*` kept as back-compat aliases.
- New `tools/local_runner/workspace_policy.json` — config-driven approved roots (the place to add future roots, not code); lists the Axiom-01 self-hosted runner work dir explicitly.
- `tests/test_local_runner.py`: new tests (forged `actions-runner/_work` path rejected, `$GITHUB_WORKSPACE` trust, config-file root, env-var root, assembled-roots sanity, shipped-config lists runner root) — preserves all existing block tests.
- `docs/runbooks/local-runner-runbook.md`: documents the trusted-root policy.

### Security note (Devin Review #18)
An earlier revision trusted any path matching the `.../actions-runner/_work/...` layout. Devin Review correctly flagged this as a forgeable bypass (an attacker who can `mkdir` such a path + `pytest` action = arbitrary code execution from `cwd`). Removed the heuristic entirely; the self-hosted runner is now trusted only via `$GITHUB_WORKSPACE` (CI) and an explicit config root (manual). Arbitrary paths are always rejected.

### What behavior changed
- Local Runner now accepts workspaces under any explicitly approved root (defaults/config/`$GITHUB_WORKSPACE`/env), not just `C:\Dev\Axiom`. Arbitrary-path rejection preserved.

### What did NOT change
- No new actions; no arbitrary shell execution; no new Revit capabilities; no CreateGrids/CreateLevels/InventoryModel/SetParameterValue changes; no deploy/copy-to-Addins; no workflow behavior expansion.

### Tests run
- `pytest tests/test_local_runner.py` → 43 passed, 1 skipped.
- `pytest` (3 files) → 128 passed, 1 skipped. `ruff check .` → clean.
- Verified the exact reported Windows runner path (`C:\actions-runner-axiom\actions-runner\_work\Axiom-platform\Axiom-platform`) is trusted via the runner-layout pattern.

### Validation pending
- Re-dispatch **Windows Revit Validation (Axiom-01)** on the self-hosted runner; expect `test_local_runner` to pass there now.

### Known risks
- Runner-layout pattern (`actions-runner/_work`) is a recognized, narrow allowance; `$GITHUB_WORKSPACE` is the primary CI trust source. Config roots are operator-controlled; no broad roots shipped.

- **2024 baseline affected:** No.
- **Revit live validation required:** No.

---

## PR #17: Windows/Revit self-hosted runner foundation (Axiom-01)

**Branch:** `devin/1780371133-windows-revit-self-hosted-runner`
**Base:** `main`
**Status:** Merged
**Scope:** Foundation to run Axiom validation jobs on the real Windows/Revit machine (Axiom-01) via a controlled, manual self-hosted GitHub Actions runner. Infrastructure only.

### What changed
- New `.github/workflows/windows-revit-validation.yml` — `workflow_dispatch`-only workflow on `runs-on: [self-hosted, windows, axiom-01, revit-2027]`: confirm runner/repo context → ensure Poetry → `poetry install` → pytest (validation_loop + local_runner + set_parameter_value) → ruff → optional Revit 2027 add-in **BuildOnly** (no copy) → optional built-DLL timestamps → `validation-run --phase pre --tests --no-deploy` → upload `artifacts/validation_runs/**`. `concurrency` serializes runs.
- New `docs/runbooks/windows-revit-self-hosted-runner.md` — install/register/labels, service-user + Revit-licensing + admin-vs-non-admin warnings, manual trigger, success/failure interpretation, disable/remove, and security warnings (keep repo private, no untrusted PRs, never print/commit tokens).
- New `scripts/local/setup-github-runner-notes.ps1` — checklist + prerequisite probe only; no tokens/secrets, no registration, no downloads.

### What behavior changed
- No runtime/application behavior changed. New CI/infra only (no behavior-change-ledger entry required).

### What did NOT change
- No new Revit capabilities; no Selection/Filter engine.
- No CreateGrids/CreateLevels/InventoryModel/SetParameterValue behavior changes.
- No live Revit model mutation, no automatic prompt execution in Revit, no auto-run on PRs, no Autodesk Assistant/MCP work.

### Tests run
- `ruff check .` → clean. No Python source changed, so the existing suite (123 passed, 1 skipped) is unaffected; workflow references those same 3 test files.
- Workflow YAML parsed/validated; labels and `workflow_dispatch`-only trigger confirmed.

### Validation pending
- Plamen registers the self-hosted runner on Axiom-01 per the runbook and manually dispatches the workflow once to confirm it executes on the machine (tests + ruff + `pre` phase, optionally BuildOnly).

### Known risks
- Self-hosted runners execute workflow code on Axiom-01; mitigated by private repo + `workflow_dispatch`-only + explicit security warnings. Future live-Revit steps will require the interactive Revit-licensed user (documented).

### Strategic fit
- Moves validation execution onto the real Windows/Revit machine — strengthens the verification factory / validation throughput (spec §1/§11). Discovery/bounded-retry/promotion-scoring remains the later target.

- **2024 baseline affected:** No.
- **Revit live validation required:** No for merge (foundation only); runner dispatch is the post-merge validation.

---

## PR #16: Axiom Validation Automation Loop v0 — semi-autonomous PR/live-validation runner

**Branch:** `devin/1780369276-validation-automation-loop`
**Base:** `main`
**Status:** Merged
**Scope:** Throughput tool that automates everything around the single live-Revit human step (per `Axiom_Autonomous_Verification_Loop_Spec_v1`). Not a Revit capability.

### What changed
- New `src/axiom_core/validation_loop.py` — pure-Python orchestrator: context/git recording, optional branch pull, allowlisted Python tests + ruff, optional deploy + deployed-DLL timestamp capture, manual-step rendering, cross-profile evidence scan, 12 v0 evidence conditions, ordered pass/fail classifier, and full artifact-bundle writer.
- New `validation-run` CLI command in `src/axiom_cli/main.py` with `--phase pre|scan|all`, `--max-attempts` (configurable bounded retry, default 5), `--evidence-root`, `--deploy/--no-deploy`, etc.
- New `scripts/local/run-validation-loop.ps1` — Windows wrapper; runs git/tests/scan non-elevated and only deploy elevated (`-ElevateDeploy`) or reports `needs_admin`.
- Local Runner: new `test_validation_loop` allowlisted action (fixed argv `poetry run pytest tests/test_validation_loop.py`) + example task.json.
- New `tests/test_validation_loop.py` (29 tests) + 2 Local Runner allowlist tests.
- New `docs/runbooks/validation-loop-runbook.md`.

### What behavior changed
- New harness behavior only (BHV-025). A single command now produces `artifacts/validation_runs/<run_id>/` and a deterministic classification; previously these steps were manual.

### What did NOT change
- No new Revit workflow features; no Selection/Filter engine.
- No changes to CreateGrids/CreateLevels/InventoryModel.
- No changes to SetParameterValue behavior — its evidence schema is consumed read-only (no validation-metadata change was required).

### Tests run
- `pytest tests/test_validation_loop.py` → 29 passed.
- `pytest tests/test_local_runner.py` → passing (incl. new allowlist tests).
- `pytest tests/test_set_parameter_value.py` → passing.
- Combined: 119 passed, 1 skipped. `ruff check .` clean.
- CLI smoke: `validation-run --phase scan` against mocked evidence → `pass`, full bundle written to `artifacts/validation_runs/<run_id>/`. Local Runner `test_validation_loop` → result_summary reports "29 passed."

### Validation pending
- Live Windows run by Plamen: `--phase pre` (tests + manual steps + optional deploy) then `--phase scan` after the live Revit step, confirming cross-profile evidence scan and `pass` classification on a real apply run.

### Known risks
- `pre`-phase deploy path and DLL-timestamp capture are Windows-only and not exercisable on the Linux dev VM; covered by fixed-argv unit assertions only.

### Strategic fit
- Improves the verification factory / evidence quality and validation throughput (spec §1/§11). Bounded-retry/promotion-scoring discovery machinery (spec §9) is the next target and intentionally out of scope.

- **2024 baseline affected:** No.
- **Revit live validation required:** No for merge (Python harness); yes to exercise the loop end-to-end on Windows.

---

## PR #5: Revit 2027 Compatibility — Discipline Extraction, Safety Guards, Chunked Inventory

**Branch:** `revit-2027-compatibility`
**Base:** `main`
**Status:** Merged (2026-05-06)
**Scope:** Revit 2027 compatibility, schema-centric inventory, adaptive planner, safety hardening, full registry coverage workflow

---

### Key Changes

1. **Full InventoryModel blocked** (BUG-014): Crashes Revit 2027 on large models (~43K instances). Returns `clarification_needed` with safe workflow guidance. Blocked at both Python (prompt_resolver) and C# (PromptDispatcher) layers.

2. **Schema-centric inventory redesign** (BHV-013, BUG-015):
   - `Run InventoryModel schema` — whole-model parameter definitions, no values
   - `Run InventoryModel schema batch 500` — schema in bounded batches
   - `Run InventoryModel sample values` — limited value samples (10 per param)
   - `Run InventoryModel for Walls schema` — category schema only
   - `Run InventoryModel for Walls sample values` — category value samples
   - `Run InventoryModel batch 100` — now resolves to SCHEMA discovery (not full values)
   - `Run InventoryModel full values` — BLOCKED

3. **Safe chunked extraction modes** (BHV-011, BHV-012):
   - `Run InventoryModel for Walls` — category value scan
   - `Run InventoryModel on Level 1` — level scan
   - `Run InventoryModel for Walls on Level 1` — category+level scan
   - `inventory plan` / `extraction plan` — guides to CLI planner

4. **Adaptive extraction planner**: `axiom inventory-plan --file <summary.json>` builds extraction plan from summary counts. Now recommends schema discovery first, then category scans. Never recommends full value extraction.

5. **Batched/continuation extraction** (BHV-012): `limit`/`max`/`batch` sets `BatchSize` for paginated continuation. Each batch saved independently. CLI `inventory-combine` merges batch outputs.

5. **Discipline-based extraction**: `axiom inventory-export --chunk-by discipline` classifies elements by Architectural/Structural/Mechanical/Electrical/Plumbing/Other.

6. **Empty-elements guardrail**: Warning in console, summary markdown, and metadata when discipline split runs on summary-only JSON.

7. **Parameter discovery workflow (BHV-016, BUG-017)**: Complete safe parameter intelligence path: category parameter schema extraction, `inventory-import`/`inventory-summary` support for `parameter_schema.parquet`, `inventory-plan --mode parameter-schema` for copy-paste ready category commands, `parameter-registry-build` for deduplicating across multiple runs. Added Lighting Fixtures, Views, Sheets, Ducts, Pipes to known categories.

### Test Coverage

- 166 inventory tests + 207 other = 373 total pytest passing
- 35/35 grid scenarios, 18/18 level scenarios
- 46/46 validation run (prompt resolution, all modes)
- ruff clean

### Live Revit 2027 Validation

**Phase 1 (2026-05-21):**

| Mode | Result | Details |
|------|--------|---------|
| Summary | PASS | 42,881 instances, 2,276 types, 0 errors, 61ms |
| Category — Ceilings | PASS | 78 instances, 7 types, 1,599 parameters, 0 errors |
| Category — Plumbing Fixtures | PASS | 150 instances, 31 types, 4,119 parameters, 0 errors |
| inventory-import | PASS | Both category exports imported |
| inventory-summary | PASS | Summary works after import |
| Full scan | CRASH | Revit 2027 crashed (remains blocked) |
| Whole-model batch 100 | CRASH | Value extraction too expensive (BUG-015) |
| Object schema | PASS | 16MB JSON, 45,157 elements |
| Whole-model sample values | CRASH | Now blocked (BUG-016) |
| Parameter schema (whole-model) | CRASH | Now blocked (BUG-017) |
| Deployment | PASS | deploy-revit-2027.ps1 succeeded |

**Phase 2 (2026-05-23):**

| Mode | Result | Details |
|------|--------|---------|
| Walls parameter schema | PASS | 1,241 instances, 85 types, 104 parameter definitions |
| Plan execution max 10 | PASS | 10/10 categories completed, 0 failed, Revit stable |
| Plan execution priority only | PASS | 16/16 categories completed, 0 failed, Revit stable |
| inventory-import-batch | PASS | Manifest import worked |
| parameter-registry-build | PASS | 1,030 unique definitions, 21 source runs |
| Deploy script syntax fix | PASS | PowerShell parse clean |
| Structured dispatch | PASS | All categories dispatch correctly (no BLOCKED_UNSAFE) |

### Architecture Flag

Level filter is **post-collector / pre-extraction**: C# iterates all elements, skips non-matching levels before expensive parameter extraction. Recommendation: optimize with `ElementLevelFilter` for true pre-collector filtering in future.

### Remaining Validation

- [x] Summary mode on real model — PASS
- [x] Category scan on real model — PASS (Ceilings, Plumbing Fixtures)
- [x] Deployment — PASS
- [x] Full scan confirmed crash — remains blocked
- [x] Object schema on real model — PASS
- [x] Whole-model sample values — CRASH (now blocked)
- [x] Parameter schema on real model — CRASH (now blocked)
- [x] Category parameter schema — PASS (Walls: 104 param defs)
- [x] Plan execution queue max 10 — PASS (10/10)
- [x] Plan execution queue priority only — PASS (16/16)
- [x] inventory-import-batch --manifest — PASS
- [x] parameter-registry-build with object registry — PASS
- [x] Deploy script syntax fix — PASS
- [ ] Level scan on real model
- [ ] Category+level scan on real model
- [ ] Constrained sample values
- [ ] Level filter performance profiling

**Phase 3: Full plan execution + export collision fix (2026-05-06):**

| Mode | Result | Details |
|------|--------|---------|
| Full parameter schema plan | PASS | 278 successful exports, 1 skipped unsupported ((No Category)), 0 failed |
| Export collision fix (PR #9) | PASS | 278 distinct export paths, 0 duplicates (was 26 before fix) |
| inventory-import-batch | PASS | All 278 exports imported |
| parameter-registry-build | PASS | 6,444 unique definitions, 1,878 parameter names, 1,748 runs, 5 models |
| Priority coverage | PASS | 20/20 executed, 20/20 with definitions |
| Revit stability | PASS | Full plan completed without crash |

**Source models:** Snowdon Towers Architectural, Electrical, HVAC, Plumbing, Structural

### Progressive Coverage Validation Roadmap

Queue mechanism validated through full plan (278 categories). Direct full-model extraction remains blocked.

**Completed:**
- [x] `max 10` — 10/10 (Phase 2)
- [x] `priority only` — 16/16 (Phase 2)
- [x] Full plan — 278/278 successful, 1 skipped unsupported (Phase 3)

**Next steps (broader coverage):**
1. Non-Snowdon models — broaden object/property coverage beyond the Snowdon Towers set
2. Family/library coverage — scan family parameters and shared parameter definitions
3. Resume validation — test resume on partially completed manifests from larger model sets

---

## PR #8: Registry Coverage Reporting (Superseded by PR #9)

**Branch:** `devin/1779537413-registry-coverage-reporting` (deleted)
**Base:** `main`
**Status:** Superseded — closed, branch deleted. All changes cherry-picked into PR #9.
**Scope:** Registry coverage reporting improvements (executed vs definitions vs zero-definitions vs not-executed)

PR #8 was created to fix misleading "missing coverage" terminology in registry summaries. Before it could be merged, the export path collision bug was discovered (BUG-018). PR #9 was created to fix both issues together — the collision fix plus the reporting improvements from PR #8 (via cherry-pick). PR #8 was closed and its branch deleted after PR #9 merged.

---

## PR #9: Export Path Collision Fix — Unique Filenames per Category + Duplicate Detection

**Branch:** `devin/1779605963-fix-export-path-collision`
**Base:** `main`
**Status:** Merged (2026-05-06)
**Scope:** C# export filename uniqueness, Python manifest duplicate detection, registry coverage reporting improvements

---

### Root Cause

`PersistInventoryJson` used `inv_YYYYMMDD_HHmmss.json` — second-level timestamp precision. When the full parameter schema plan processed multiple categories within the same second, they wrote to identical filenames, causing overwrites (278 exports → 26 unique files → 252 lost).

### Fix

1. **C# filename format:** `inv_YYYYMMDD_HHmmss_fff_NNN_category_slug.json`
   - `fff` = milliseconds
   - `NNN` = atomic sequence counter (`System.Threading.Interlocked.Increment`)
   - `category_slug` = sanitized category name
2. **Python import-batch:** Detects and warns on duplicate `export_path` values in manifests
3. **Registry coverage reporting:** Distinguishes executed vs with-definitions vs zero-definitions vs not-executed

### Live Validation

| Test | Result | Details |
|------|--------|---------|
| Full parameter schema plan | PASS | 278 successful exports, 0 duplicate paths |
| Manifest import | PASS | All 278 exports imported |
| Registry build | PASS | 6,444 unique definitions, 1,878 parameter names |
| Priority coverage | PASS | 20/20 executed, 20/20 with definitions |

### Test Results

| Suite | Count | Status |
|-------|-------|--------|
| pytest | 402 | All passing |
| ruff lint | 0 errors | Clean |

---

## PR #6: Axiom Local Runner v0 — Restricted Local Execution Harness

**Branch:** `feature/axiom-local-runner-v0`
**Base:** `main`
**Status:** Merged (2026-05-06)
**Scope:** Local task runner with allowlisted actions, workspace restriction, artifact capture

---

### Key Changes

1. **Allowlisted actions only:** 9 named actions (pytest, ruff, test_grids, test_levels, git_status, dotnet_build_revit_2027, deploy_revit_2027, collect_revit_journals, kill_revit). Arbitrary `command`/`shell`/`cmd` fields rejected.
2. **Workspace restriction:** `C:\Dev\Axiom` (Windows) / `~/repos` (Linux)
3. **Artifact capture:** stdout.txt, stderr.txt, run_log.json, failure_summary.md per run
4. **Timeout handling:** Process killed on expiry
5. **Command fix:** Changed from `python -m poetry run ...` to `poetry run ...` (Poetry is a CLI tool, not a venv module)

### Live Validation

| Task | Result |
|------|--------|
| git_status.task.json | PASS |
| test_grids.task.json | PASS |
| test_levels.task.json | PASS |
| ruff.task.json | PASS |
| Failure artifact capture | PASS |

### What Did NOT Change

- No InventoryModel, CreateGrids, CreateLevels behavior modified
- No Revit add-in code touched
- 2024 baseline unaffected

### Known Limitations

- `collect_revit_journals` and `kill_revit` are NOT_IMPLEMENTED placeholders
- No parallel task execution

### Test Results

| Suite | Count | Status |
|-------|-------|--------|
| Local runner tests | 22/22 | All passing |
| ruff lint | 0 errors | Clean |

---

## Post-Merge Registry Milestone (2026-05-06)

PRs #5, #6, and #9 are all merged to main. The parameter registry workflow is end-to-end validated on live Revit 2027.

### Milestone Summary

| Metric | Value |
|--------|-------|
| Unique parameter/property definitions | 6,444 |
| Unique parameter names | 1,878 |
| Source runs | 1,748 |
| Source models | 5 (Snowdon Towers: Architectural, Electrical, HVAC, Plumbing, Structural) |
| Full plan categories executed | 278 successful, 1 skipped unsupported, 0 failed |
| Export path duplicates | 0 (was 252 before PR #9 fix) |
| Priority categories executed | 20/20 |
| Priority categories with definitions | 20/20 |

### Safety Status

| Command | Status |
|---------|--------|
| Run full InventoryModel | BLOCKED |
| Run InventoryModel sample values (whole-model) | BLOCKED |
| Run InventoryModel parameter schema (whole-model) | BLOCKED |
| Plan queue category_parameter_schema | ALLOWED (validated) |
| CreateGrids / CreateLevels | Unchanged |
| Revit 2024 baseline | Protected |

### Validated Workflow

```
1. Run InventoryModel schema                          → object schema (45K elements)
2. axiom inventory-import --file <object_schema.json>  → import + object registry
3. axiom inventory-plan --mode parameter-schema        → plan (278 categories)
4. Run InventoryModel parameter schema plan            → 278 exports via structured dispatch
5. axiom inventory-import-batch --manifest <path>      → batch import
6. axiom parameter-registry-build --from-inventory ... --object-registry ...  → 6,444 definitions
```

### Artifact Locations

| Artifact | Path |
|----------|------|
| Registry JSONL | `artifacts/parameter_registry_candidates/<run_id>/revit_property_registry.jsonl` |
| Registry Parquet | `artifacts/parameter_registry_candidates/<run_id>/revit_property_registry.parquet` |
| Registry summary | `artifacts/parameter_registry_candidates/<run_id>/summary.md` |
| Run metadata | `artifacts/parameter_registry_candidates/<run_id>/run_metadata.json` |
| Inventory runs | `artifacts/model_inventory_runs/` |
| Object registry | `artifacts/object_registry_candidates/<run_id>/` |

### Known Next Gaps

1. **Broader model coverage:** Only Snowdon Towers validated. Need non-Snowdon models for wider parameter diversity.
2. **Family/library coverage:** Family-level and shared parameter definitions not yet scanned.
3. **Resume validation:** `plan resume` mode not yet tested on large partial manifests.
4. **Level scan / category+level scan:** Not yet live-validated on real models.
5. **Constrained sample values:** Not yet live-validated.

---

## PR #2: Vertical Slice — Prompt-to-Grid Pipeline with Agents, Pipe Bridge, and C# Capabilities

**Branch:** `devin/1778113509-vertical-slice`
**Base:** `main`
**Status:** Merge-ready (pending real Revit validation)
**Scope:** 84 files changed, +14,805 lines

---

### Feature Summary

| # | Feature | Key Files | Tests |
|---|---------|-----------|-------|
| 1 | **CreateGrids end-to-end** | `prompt_resolver.py`, `pipe_client.py`, `GridCapability.cs`, `GridCreationService.cs`, `GridParameters.cs` | 31/31 harness, 30+ pytest |
| 2 | **Variable grid spacing** | `prompt_resolver.py` (comma/table parsing), `GridParameters.cs` (`HorizontalSpacingsFeet`, `VerticalSpacingsFeet`) | 6 harness cases |
| 3 | **Clarification loop** | `_check_grid_clarification()`, `PromptDispatcher.CheckGridClarification()` | 7 pytest, 4 harness |
| 4 | **General Revit Prompt dialog** | `PromptCommand.cs` (text input, replaces grid-specific dialog) | Manual Revit test pending |
| 5 | **CreateLevels capability** | `LevelCapability.cs`, `LevelCreationService.cs`, `LevelParameters.cs`, resolver + mock | 18/18 harness, 26 pytest |
| 6 | **InventoryModel capability** | `InventoryModelCapability.cs`, `ModelInventoryService.cs`, `InventoryParameters.cs`, storage, reviewer | 58 pytest |
| 7 | **inventory-summary utility** | `src/axiom_core/inventory/review.py`, CLI `inventory-summary` command | 14 pytest |
| 8 | **Grid learning loop harness** | `src/axiom_core/testing/grid_harness.py`, `axiom test-grids` CLI | 31 test cases |
| 9 | **Level learning loop harness** | `src/axiom_core/testing/level_harness.py`, `axiom test-levels` CLI | 18 test cases |
| 10 | **Revit version compatibility metadata** | `supported_revit_versions.yaml`, `capability_compatibility.yaml`, `parameter_availability_examples.yaml` | Fixtures only |
| 11 | **Multi-platform architecture proposal** | `multi-platform-capability-intelligence.md` | Docs only |

### Infrastructure

| Component | Detail |
|-----------|--------|
| Capability registry | 3 capabilities: CreateGrids (validated), CreateLevels (validated), InventoryModel (validated) |
| Storage layers | JSONL (append-only), SQLite (queryable, WAL mode), Parquet (structured datasets) |
| CLI commands | `axiom prompt`, `axiom test-grids`, `axiom test-levels`, `axiom inventory-model`, `axiom inventory-summary` |
| C# solution | `Axiom.Core` + `Axiom.RevitAddin` targeting Revit 2024 (net48) |
| Pipe bridge | Named pipe (JSON protocol) for Python↔C# communication |

### Architecture Docs Added

| Document | Purpose |
|----------|---------|
| `capability-creation-checklist.md` | 13-step repeatable process for adding capabilities |
| `capability-design-pattern.md` | Template every capability follows |
| `create-levels-capability-plan.md` | CreateLevels pre-implementation plan |
| `revit-version-compatibility-strategy.md` | Shared capability + thin adapter approach for 2024–2027 |
| `revit-parameter-versioning-strategy.md` | One canonical ParameterAvailability registry |
| `multi-platform-capability-intelligence.md` | Platform vision: 9 concepts, Revit as Adapter 001 |
| `revit-multi-version-runbook.md` | Build/test procedures for multiple Revit versions |
| `model-inventory-runbook.md` | InventoryModel usage, schema reference, query examples |
| `grid-learning-loop-runbook.md` | Grid harness usage and regression workflow |

### Hardening Packet (Phase 4b+)

**Date:** 2026-05-06
**Focus:** Reliability, path handoff, docs, diagnostics, merge-readiness

Changes:
1. **Plan handoff path fix (BHV-019):** `inventory-plan` now writes plan JSON to both repo artifacts AND `%LOCALAPPDATA%\Axiom\inventory_plans\latest\` for Revit pickup.
2. **C# plan search order:** LocalAppData/latest → LocalAppData/flat → LocalAppData subdirs → repo artifacts subdirs. Dialog shows all searched paths on failure.
3. **Plan diagnostics:** `axiom inventory-plan-status` reports plan locations, existence, category/priority counts, next Revit prompts.
4. **Manifest hardening:** Per-category `prompt` field added. All required fields present: plan_id, source_model, started_at, completed_at, max_categories, priority_only, resume, per-category prompt/status/export_path/duration_ms/error_message.
5. **Import-batch reliability:** Failed/skipped manifest entries reported clearly. Missing export files counted and warned. All-failed manifest provides resume guidance.
6. **Registry coverage reporting:** Priority category coverage (covered/missing). Output paths in summary. Before/after dedup counts.
7. **Plan file usability:** Preferred execution path (plan queue) documented in plan markdown. Post-processing commands included. Manual prompt warning added.
8. **Deploy script polish:** `-ForceCloseRevit` flag added. DLL lock message improved. Default remains cancel.
9. **REVIEW.md:** Section 8 added with review agent instructions (safety blocks, testing policy, no code changes in review mode).
10. **Docs/logs updated:** pr-review-ledger, behavior-change-ledger (BHV-019), model-inventory-runbook.

### Phase 5: Structured dispatch fix (2026-05-06)

11. **Structured category dispatch (BHV-020):** Plan executor now calls `DispatchCategoryParameterSchema()` directly instead of round-tripping through NLP prompt parsing. Fixes 231 BLOCKED_UNSAFE failures caused by unrecognized categories (Grids, Materials, Project Information, etc.) falling through to the whole-model block.
12. **Non-executable category pre-filtering:** `(No Category)`, `<Unnamed>` skipped before execution with `skipped_unsupported` status. Python planner also filters these from plan generation.
13. **Manifest status distinctions:** `success`, `failed`, `skipped_unsupported`, `skipped_resume`, `skipped_no_elements`.

### Phase 6: Merge-readiness cleanup (2026-05-06)

14. **Environment.CurrentDirectory fallback removed from Revit plan search:** Only `%LOCALAPPDATA%` is the supported Revit plan source. Repo artifacts are CLI-only.
15. **Manifest write failure now reported in dialog** instead of silently showing path to nonexistent file.
16. **PersistInventoryJson catch-all now logs exception** via `Debug.WriteLine`.

### Review Findings Classification

| Finding | Classification | Disposition |
|---------|---------------|-------------|
| B-1: `Environment.CurrentDirectory` unreliable in Revit | Fixed | Removed repo artifact fallback from Revit; LocalAppData is sole supported path |
| B-2: Plan execution queue not live-validated | Resolved | Validated: max 10 (10/10), priority only (16/16) |
| R-2: Manifest write failure silent | Fixed | Dialog now shows WARNING when manifest write fails |
| R-3: Priority categories inconsistent Python/C# | Verified consistent | Both use same 20 categories |
| R-4: PersistInventoryJson catch-all | Improved | Now logs exception; returns null (caller checks) |
| R-5: knownCats duplication in PromptDispatcher | Deferred | Structured dispatch bypasses NLP entirely for plan execution; NLP resolver only used for ad-hoc prompts |

### Test Results

| Suite | Count | Status |
|-------|-------|--------|
| pytest | 373 (full checkpoint) | All passing |
| test-grids (simulate) | 35/35 | All passing |
| test-levels (simulate) | 18/18 | All passing |
| ruff lint | 0 errors | Clean |

---

## PR #1: SQLite Persistence (WAL Mode)

**Status:** Merged
**Scope:** Replace in-memory storage with SQLite persistence layer
