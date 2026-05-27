# Founder's Evidence Source Index

Maps each evidence log entry to its primary and secondary sources.

**Maintenance:** See `docs/runbooks/evidence-log-maintenance.md`

---

## Source Types

| Code | Description |
|------|------------|
| COMMIT | Git commit hash |
| PR | GitHub Pull Request |
| ARTIFACT | File/directory in artifacts/ |
| DOC | Document in docs/ |
| BUG | Bug entry in bug-validation-log.md |
| BHV | Behavior change in behavior-change-ledger.md |

---

## Index

| Entry | Date | Primary Source | Secondary Sources |
|-------|------|---------------|-------------------|
| EVID-001 | 2025-12-13 | COMMIT `84799c0` | — |
| EVID-002 | 2026-05-06 | PR #1, COMMIT `76cf496`, `282ff5e` | Merge `3423d58` |
| EVID-003 | 2026-05-07 | PR #2, COMMIT `8efc206`, `8efa0e9` | — |
| EVID-004 | 2026-05-08 | COMMIT `a91cc8b`, `35e86fb`, `6d302d7`, `53ada46` | PR #2 |
| EVID-005 | 2026-05-08 | PR #3, COMMIT `5464461` | — |
| EVID-006 | 2026-05-09 | COMMIT `bbc9b57` | PR #2 |
| EVID-007 | 2026-05-10–11 | COMMIT `7097226`–`ab9b255` (10 commits) | PR #2 |
| EVID-008 | 2026-05-11–12 | COMMIT `18a033c`, `6b21bd3`, `7368e42` | PR #2 |
| EVID-009 | 2026-05-12 | COMMIT `8efa572` | PR #2 |
| EVID-010 | 2026-05-17 | COMMIT `503162b`, `37e25e2`, `782333a` | PR #2, BUG-001, BUG-002, ARTIFACT `artifacts/grid_test_runs/` |
| EVID-011 | 2026-05-18 | COMMIT `270baf6`, `1ae38c6` | PR #2, ARTIFACT `artifacts/level_test_runs/` |
| EVID-012 | 2026-05-18 | COMMIT `2704183`, `2aae0d4`, `ddedee6`, `6a68432` | PR #2, ARTIFACT `artifacts/model_inventory_runs/` |
| EVID-013 | 2026-05-18–19 | COMMIT `05f34ea`–`f327469` (6 commits) | PR #2, DOC `docs/architecture/` |
| EVID-014 | 2026-05-19 | PR #2 merge `1c79cc7` | DOC `docs/logs/pr-review-ledger.md` |
| EVID-015 | 2026-05-19 | PR #5, COMMIT `3a4c8dd`, `4c74669`, `4bb642c` | DOC `docs/runbooks/revit-2027-compatibility-runbook.md` |
| EVID-016 | 2026-05-19 | COMMIT `40e4f3d`–`4cf8841` (7 commits) | PR #5, BUG-008 |
| EVID-017 | 2026-05-19 | COMMIT `9a4c5bf`, `16e9344`, `51837aa` | PR #5, BUG-012, BHV series |
| EVID-018 | 2026-05-19 | COMMIT `02d288f`, `2c56f3e` | PR #5 |
| EVID-019 | 2026-05-20 | COMMIT `b78e391`, `c46f281`, `bf07c35`, `5969fc1` | PR #5 |
| EVID-020 | 2026-05-20–21 | COMMIT `c6a1de2`–`b96767b` (5 commits) | PR #5, ARTIFACT `artifacts/validation_runs/safe_inventory_modes/` |
| EVID-021 | 2026-05-23 | COMMIT `b33f6ca`–`ae51abc` (4 commits) | PR #5, BUG-016, BUG-017, BHV-015, BHV-016 |
| EVID-022 | 2026-05-24 | COMMIT `90b7f74`, `1fe2a21`, `f260a17` | PR #5 |
| EVID-023 | 2026-05-24 | COMMIT `c3d0749` | PR #5 |
| EVID-024 | 2026-05-24 | COMMIT `839ca60` | PR #5 |
| EVID-025 | 2026-05-24 | COMMIT `24067f0` | PR #5 |
| EVID-026 | 2026-05-24 | COMMIT `d16258f` | PR #5 |
| EVID-027 | 2026-05-24 | COMMIT `2178f20` | PR #5, BHV-019 |
| EVID-028 | 2026-05-24 | PR #6, COMMIT `d450287` | — |
| EVID-029 | 2026-05-06 | PR #5 merge `c5df9df` | DOC `docs/logs/pr-review-ledger.md` |
| EVID-030 | 2026-05-06 | PR #6 merge `45680ed` | DOC `docs/runbooks/local-runner-runbook.md` |
| EVID-031 | 2026-05-06 | PR #8 (closed) | PR #9 (superseded) |
| EVID-032 | 2026-05-06 | PR #9 merge `0121777` | BUG-018 |
| EVID-033 | 2026-05-06 | PR #10 | ARTIFACT `artifacts/parameter_registry_candidates/` |

---

## PR Cross-Reference

All PR statuses verified via GitHub PR API (`git_view_pr`) on 2026-05-06.

| PR | Title | Status | Verification | Evidence Entries |
|----|-------|--------|-------------|-----------------|
| #1 | SQLite persistence (WAL mode) | Merged | GitHub PR API verified | EVID-002 |
| #2 | Vertical slice — prompt-to-grid pipeline | Merged | GitHub PR API verified | EVID-003–014 |
| #3 | Development process documentation | Open (not merged) | GitHub PR API verified | EVID-005 |
| #5 | Revit 2027 compatibility adapter | Merged | GitHub PR API verified | EVID-015–027, EVID-029 |
| #6 | Axiom Local Runner v0 | Merged | GitHub PR API verified | EVID-028, EVID-030 |
| #7 | Founder's Evidence Log reconstruction | Open | GitHub PR API verified | — (this document) |
| #8 | Registry coverage reporting | Closed (superseded by #9) | GitHub PR API verified | EVID-031 |
| #9 | Export path collision fix | Merged | GitHub PR API verified | EVID-032 |
| #10 | Post-merge registry milestone report | Merged | GitHub PR API verified | EVID-033 |
| #11 | PR evidence snapshot workflow | Open | GitHub PR API verified | — |

**Verification methods:**
- **GitHub PR API verified** — Status confirmed via `git_view_pr` (reads GitHub PR state directly)
- **GitHub UI manually verified by Plamen** — Human-verified from GitHub web interface
- **Git-only inferred** — Branch/merge evidence from `git log` only; does not confirm GitHub PR state
- **Unverified** — Status not confirmed from any source; treat as provisional

---

## Artifact Directory Index

| Path | Type | Created By | Evidence |
|------|------|-----------|----------|
| `artifacts/grid_test_runs/` | Test results | `axiom test-grids` | EVID-010 |
| `artifacts/level_test_runs/` | Test results | `axiom test-levels` | EVID-011 |
| `artifacts/model_inventory_runs/` | Inventory exports | `axiom inventory-import` | EVID-012 |
| `artifacts/validation_runs/safe_inventory_modes/` | Validation run | `validate_safe_inventory_modes.py` | EVID-020 |
| `artifacts/object_registry_candidates/` | Object registry | `axiom inventory-import` (object_schema) | EVID-025 |
| `artifacts/parameter_registry_candidates/` | Property registry | `axiom parameter-registry-build` | EVID-025 |
| `artifacts/inventory_plans/` | Extraction plans | `axiom inventory-plan` | EVID-025 |
| `artifacts/local_runner_runs/` | Local runner output | `axiom local-runner` | EVID-028 |
| `artifacts/pr_reviews/` | PR evidence snapshots | `axiom pr-snapshot` | — (PR #11) |

---

## Assumptions

1. All commits attributed to "Devin AI" represent directed developer work sessions.
2. Hours marked TBD — exact session durations not reconstructed from commit timestamps alone (commits may cluster within sessions).
3. PR #4 does not appear in the repo; it may have been a draft or deleted PR. Not verified via GitHub API (returns 404 or was never created).
4. Behavior change ledger entries (BHV-001 through BHV-019) exist on the `revit-2027-compatibility` branch, now merged to main via PR #5.
5. Bug entries (BUG-001 through BUG-018) exist in `docs/logs/bug-validation-log.md` on main (merged via PR #5, #9, #10).
6. All PR statuses in the Cross-Reference table were verified via GitHub PR API on 2026-05-06. PR statuses should be re-verified before any future evidence log update.
