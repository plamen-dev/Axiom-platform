---
name: testing-cli-governance
description: Verify axiom CLI governance surfaces — runner-commands (command registry policy output) and the framework create/show/export CLI pattern with adversarial determinism fixtures. Use when testing command-registry coverage or any <framework>-create/-show/-export command family.
---

# Testing CLI governance

## Domain

Read-only governance surfaces of the axiom CLI: the command registry policy printout and the deterministic framework CLI pattern. Source: `src/axiom_core/runner/command_registry.py`, framework modules in `src/axiom_core/`.

## Commands

- `axiom runner-commands [--classification <c>] [--name <cmd>] [--json]`
- `axiom <framework>-create / -show / -export` (frameworks #112–#119 pattern)
- `axiom capability-graph-ingest [--artifacts-root <dir>] [--json-output]` — auto-ingest evidence intake reports, execution-chain run evidence, validation-run bundles, and GitHub PR imports into one capability-graph report (no manual `capability-graph-create`). Read-only artifact scan; node/edge ids are deterministic so re-runs over the same artifacts yield identical structure (only the report_id differs); malformed artifact files are skipped, never fatal.
- `axiom github-import-backfill --payload-dir <dir> [--ledger-out <path>] [--json-output]` — batch-import PR metadata payloads (fetched via `python scripts/fetch_github_pr_metadata.py --repo <owner/name> --out <dir>`) and regenerate `docs/logs/pr-sequence-ledger.md`. Re-runnable: duplicates are skipped, not fatal. Canonical numbers come from `PR #<n>` titles; PRs without one are listed as explicit gaps — never invent a number.

## Registry pointers

- The command registry is the source of truth for classification/safety/prerequisites/evidence outputs; governance test `tests/test_command_registry.py::test_all_builtin_axiom_commands_cataloged` enforces every CLI command is cataloged. New CLI commands must be added to the registry AND to `EXPECTED_AXIOM_COMMANDS` in that test.

## Verification checklists

### runner-commands

`axiom runner-commands` is read-only governance — it prints policy and never executes anything. Verify:

- `poetry run axiom runner-commands` -> footer shows total command count.
- `--classification mutation` -> only mutation/high_risk commands.
- `--name <cmd>` -> classification, safety, requires-revit / requires-model-open, prerequisites, evidence outputs, failure classification table.
- `--name <unknown>` -> "not allowed (unknown commands are denied by default)" and exit code 2 (check with `; echo "exit=$?"`).
- `--json` -> valid JSON list; per-entry typed fields: timeout {seconds,kill_on_expire,classification_on_expire}, evidence_outputs[] {location,description,required}, failure_modes[] {code,description,retryable}.

Exact counts may change as commands are added/removed — assert the shape and that the count matches the catalog, not a hardcoded number.

### Framework CLI (create/show/export)

Use an **adversarial fixture** to prove determinism — input order must differ from expected output order so a broken sort would look different.

Fixture design:
- Shuffle candidate/item `created_at` order so they are NOT in chronological order in the JSON file.
- Include a **tie case** (e.g. two candidates with equal `final_score` for the same work item) to prove stable tie-breaking. The winner must be deterministic (e.g. lexicographic by `capability_id`).
- Include a **negative case** (e.g. a work item with no candidates → `NO_CANDIDATE` reason, `passed: false`).
- Write the fixture from the shell tool (not ttyd) if it contains JSON with special chars — xterm.js/ttyd drops `|`, `{`, `}` characters typed via the `type` action.

Standard test flow (6 tests):
1. **T1 — create**: Run `poetry run axiom <fw>-create --selection-file <fixture>`. Assert counts, ordering, selection/routing decisions, and tie-break winner with reason.
2. **T2 — JSON correctness (shell authoritative)**: Run with `--json-output`, parse with `python3 -c "import json; ..."` in the shell tool. Assert valid JSON, exact counts, correct winner, specific reason types present.
3. **T3 — show round-trip**: Run `poetry run axiom <fw>-show <report_id>` for T1's id. Assert same report_id, identical counts, decisions, and ordering.
4. **T4 — export markdown**: Run `poetry run axiom <fw>-export <report_id>`. Assert all expected `##` headings present, bracketed tokens (e.g. `[w-alpha]`) render literally (not eaten by Rich markup), and tie-break/negative reasons appear.
5. **T5 — error paths**: `<fw>-show missing-xyz; echo "exit=$?"` → exit 2. `<fw>-show ../../etc; echo "exit=$?"` → exit 1 (path-safety).
6. **T6 — evidence bundle + pass/fail**: Check `artifacts/<fw>/<id>/` for 5 files (request/result/summary/pass_fail/report.json). Positive case: `passed: true`. Negative case (separate create): `passed: false`.

## Tests

Targeted: `tests/test_command_registry.py` plus the framework's own test file. Full pytest only at PR checkpoints.

## Notes / gotchas

- Adding a CLI command without cataloging it breaks the governance test on main — catalog in the same PR.
