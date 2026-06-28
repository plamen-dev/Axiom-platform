---
name: testing-axiom-cli
description: Run a recordable end-to-end walkthrough of the axiom CLI. Use when verifying axiom CLI subcommands (e.g. runner-commands, execution-chain-run, capability-evidence-apply) and needing visual evidence (screenshots/recording) for a PR. Also covers Devin PR execution guidance for architecture-sensitive Axiom PRs (compute mode, pre-review self-audit, Purpose-to-Workflow reconciliation).
---

# Testing the axiom CLI (with a recordable terminal)

The axiom CLI is a terminal app, so shell-tool output is not visible on screen. To produce a recording/screenshots of CLI behavior, drive a terminal that renders in the browser.

---

## Recommended Devin Compute Mode

Future Axiom PR task packets should include a compute-mode section. This is **operational guidance, not doctrine**.

### Template

```
Recommended Devin Compute Mode:
* Ultra / Normal / Fast
* Reason: <why this mode>
* Operator Action Required:
  - Keep current mode
  - Switch to Ultra before starting
  - Switch down after planning
  - Switch down after architecture-impacting work is complete
```

### When to use Ultra

Use Ultra when reasoning failure would be expensive:

- repo-wide reconciliation
- duplicate-concept detection
- architectural cleanup
- M4 vertical execution-chain reasoning
- M2 evidence-to-promotion mapping
- M3 purpose/layer/consumer mapping
- deciding whether code should be deleted, merged, preserved, or deferred
- resolving contradictions between implementation and canonical direction
- producing architecture-impacting PR scope

### When to use Normal/Fast

Use Normal/Fast when work is bounded, mechanical, already scoped, or primarily validation/refactor/docs work.

---

## Required Pre-Review Self-Audit

For architecture-sensitive PRs, before marking the PR review-ready, perform and post a self-audit in the PR body. This is **operational guidance, not doctrine**.

### Trigger conditions

Trigger the self-audit for PRs that touch:

- execution flow
- evidence
- capability state
- confidence/readiness
- promotion behavior
- persistent artifacts
- registries
- canonical doctrine
- source-of-truth boundaries
- CLI validation evidence
- architectural/program boundaries

### Self-audit checklist

Check each of these before posting the PR:

- [ ] overclaims (does the PR body claim more than the code delivers?)
- [ ] new object families (were any introduced without justification?)
- [ ] doctrine accidentally encoded in code (should it be routed to a Program instead?)
- [ ] idempotency / duplicate handling (can the same input be applied twice safely?)
- [ ] conflict handling (are contradictory signals handled explicitly, not silently?)
- [ ] invalid/stale/missing behavior (are edge cases covered?)
- [ ] source-of-truth boundaries (does the PR respect existing ownership?)
- [ ] unresolved questions routed rather than silently solved
- [ ] PR body accurately describes closure scope (no overclaiming EVID-* or gap closures)

---

## Purpose-to-Workflow Reconciliation Gate

For architecture-sensitive PRs, answer these questions in the PR body before implementing. This is **operational guidance, not doctrine**.

1. What existing PR/component/capability does this use?
2. What workflow does it participate in?
3. What consumes its output?
4. What evidence proves it works?
5. Is the result integrated, support-only, planning-only, superseded, duplicate candidate, deprecated, unresolved, or temporary?
6. What existing structure was checked before adding anything new?
7. What complexity, latency, indirection, or duplicate-engine risk does this introduce?
8. What should be deleted, merged, preserved, or left alone?

---

## Recordable terminal via ttyd

The exec/shell tool output is NOT captured by screen recording. To get a visible, recordable terminal:

1. Install ttyd if missing: `sudo apt-get install -y ttyd` (also `wmctrl` for maximizing).
2. Launch an interactive shell in the repo, served over HTTP:
   ```
   cd <repo> && (ttyd -p 7681 -t fontSize=18 -W bash -l >/tmp/ttyd.log 2>&1 &)
   ```
   Note: ttyd 1.6.x uses `-W` for writable mode; `--writable` is not supported.
3. Open `http://localhost:7681` in the browser tool, click to focus.
4. Maximize the window: `wmctrl -r :ACTIVE: -b add,maximized_vert,maximized_horz`.
5. `recording_start`, then type commands. NOTE: with xterm.js/ttyd, the browser `type` action must target the terminal element by its `devinid` (e.g. devinid 0); a plain `type` without devinid may silently fail. Press Enter with `press_key` Enter (also targeting the devinid). Wait ~2s after Enter before `view` for output to render.
6. For valid-JSON or exact-count assertions, ALSO verify in the shell tool (pipe to `python3 -m json.tool` / `json.load`), since the recording proves the human-facing path and the shell proves correctness.

### Recording / ttyd reliability guidance

Lessons from PR #146, #147, #148 CLI walkthroughs:

- **Browser typing into ttyd/xterm can drop characters.** The `|`, `{`, `}` characters typed via the computer `type` action are unreliable. Write helper scripts from the shell tool instead of typing long commands directly.
- **Use short helper scripts for long walkthroughs.** Write per-test `.sh` scripts to `/tmp/` (not the repo), each echoing a clear section banner and running one logical step. Type only `bash /tmp/scripts/tN.sh` + Enter in ttyd.
- **Avoid fragile pipe/brace-heavy one-liners in recorded terminal tests.** Move piped commands, JSON construction, and inline Python to helper scripts or the shell tool.
- **Ensure helper files are not committed.** Keep walkthrough scripts in `/tmp/` or `$HOME/` — never in the repo working tree. Delete any stray files after recording.
- **Clean working tree after recording.** Run `git status --porcelain` to verify no untracked/modified files before reporting results.
- **Attach reports and recording evidence separately from runtime code.** Test reports, screenshots, and recordings go to the PR comment and user message attachments, not to the repo.
- **Convert mp4 recordings to animated webp for PR comment embedding:** `ffmpeg -y -i recording.mp4 -vf "fps=8,scale=900:-1:flags=lanczos" -loop 0 -q:v 60 walkthrough.webp`.

---

## M4 execution-chain-run CLI verification checklist

Use when verifying the execution-chain orchestrator (PR #146+). Run in the recordable terminal with shell-authoritative JSON checks alongside.

1. **Run deterministic capability:** `poetry run axiom execution-chain-run --capability self-model-build --artifacts-root <art> --json-output > chain.json`
2. **Confirm all 7 IDs present:** ExecutionPlan, ExecutionStep, ExecutionAttempt, ExecutionResult, ExecutionArtifact, Evidence, ExecutionReport.
3. **Confirm ID-flow PASS:** `ID-flow status: PASS` in console output, `7/7` transitions `[OK]`.
4. **Confirm each downstream reference_value equals upstream ID:** Shell-authoritative: parse JSON, assert `downstream.reference_value == upstream.id` for all 7 transitions. Assert `ids_distinct: True`.
5. **Confirm terminal report resolves back through artifact/result/attempt/step/plan:** Read persisted disk records and verify the resolution chain from report back to plan.
6. **Confirm persisted disk records, not response-only records:** Load `report.json` from the artifacts directory and resolve IDs from persisted files, not just the in-memory orchestrator response.
7. **Distinguish runtime relationship proof from static import metrics:** The static analyzer's `declared_but_unwired_chains` may remain unchanged. The M4 proof is the runtime executable ID flow + disk resolution, not static import edges. Do NOT add direct `execution_*` imports merely to improve the static analyzer.

---

## M2 capability-evidence-apply CLI verification checklist

Use when verifying evidence-to-promotion behavior (PR #147+, hardened in PR #148). Run in the recordable terminal with shell-authoritative JSON checks alongside.

1. **Show baseline confidence/readiness:** Before applying evidence, confirm the capability starts at `very_low (0.0) / blocked`.
2. **Apply passing evidence:** `poetry run axiom capability-evidence-apply --evidence <path> --artifacts-root <art>`. Assert: decision `accepted`, confidence raised (e.g. `very_low → very_high`), readiness `blocked → ready`, `Signals:` line present.
3. **Show after state:** Confirm updated confidence/readiness, factors (successes/executions), linkage fields (capability, result, artifact, report).
4. **Apply failing evidence:** Assert: decision `accepted`, confidence reduced, readiness may drop to `provisional` or `blocked`, factors show failure increment.
5. **Apply duplicate evidence (PR #148+):** Re-apply the exact same evidence file. Assert: decision `duplicate`, `state_changed: false`, confidence/readiness unchanged, `duplicate_of` references the prior accepted intake, execution/success counts do NOT inflate.
6. **Apply conflicting evidence (PR #148+):** Create evidence where `evidence.json` has `passed: true` but sibling `trace.json` has `status: FAIL`. Assert: outcome `conflict`, decision `quarantined`, `state_changed: false`, `Signals:` shows both disagreeing signals, reason mentions "rather than resolved by source priority".
7. **Apply invalid/no-identity evidence:** Evidence without `capability_id` in references. Assert: decision `quarantined`, `state_changed: false`.
8. **Apply stale evidence:** Use `--max-age-seconds 3600` with old evidence. Assert: decision `quarantined`, reason mentions staleness, `state_changed: false`.
9. **Show capability-evidence-history:** `poetry run axiom capability-evidence-history --capability-id <id> --artifacts-root <art>`. Assert: all intake records listed with timestamps, decisions, confidence transitions.
10. **Show capability-evidence-show:** `poetry run axiom capability-evidence-show <intake_id> --artifacts-root <art>`. Assert: full intake detail including decision, reason, signals, fingerprint, linkage.
11. **Confirm rejected/quarantined/duplicate records do not mutate confidence:** Count confidence reports in artifacts — accepted intakes produce confidence reports; rejected/quarantined/duplicate intakes do not.
12. **Confirm audit artifacts are not a new registry:** Intake directory contains only `report.json` + `pass_fail.json` per record (standard evidence convention). No promotion registry, no doctrine layer, no independent durable state separate from `CapabilityConfidenceEngine`.

---

## Framework CLI (create/show/export) verification checklist

The deterministic chain frameworks (#112–#119) each follow the same CLI pattern: `axiom <framework>-create`, `<framework>-show`, `<framework>-export`. Use an **adversarial fixture** to prove determinism — input order must differ from expected output order so a broken sort would look different.

### Fixture design
- Shuffle candidate/item `created_at` order so they are NOT in chronological order in the JSON file.
- Include a **tie case** (e.g. two candidates with equal `final_score` for the same work item) to prove stable tie-breaking. The winner must be deterministic (e.g. lexicographic by `capability_id`).
- Include a **negative case** (e.g. a work item with no candidates → `NO_CANDIDATE` reason, `passed: false`).
- Write the fixture from the shell tool (not ttyd) if it contains JSON with special chars — xterm.js/ttyd drops `|`, `{`, `}` characters typed via the `type` action.

### Standard test flow (6 tests)
1. **T1 — create**: Run `poetry run axiom <fw>-create --selection-file <fixture>`. Assert counts, ordering, selection/routing decisions, and tie-break winner with reason.
2. **T2 — JSON correctness (shell authoritative)**: Run with `--json-output`, parse with `python3 -c "import json; ..."` in the shell tool. Assert valid JSON, exact counts, correct winner, specific reason types present.
3. **T3 — show round-trip**: Run `poetry run axiom <fw>-show <report_id>` for T1's id. Assert same report_id, identical counts, decisions, and ordering.
4. **T4 — export markdown**: Run `poetry run axiom <fw>-export <report_id>`. Assert all expected `##` headings present, bracketed tokens (e.g. `[w-alpha]`) render literally (not eaten by Rich markup), and tie-break/negative reasons appear.
5. **T5 — error paths**: `<fw>-show missing-xyz; echo "exit=$?"` → exit 2. `<fw>-show ../../etc; echo "exit=$?"` → exit 1 (path-safety).
6. **T6 — evidence bundle + pass/fail**: Check `artifacts/<fw>/<id>/` for 5 files (request/result/summary/pass_fail/report.json). Positive case: `passed: true`. Negative case (separate create): `passed: false`.

---

## execution-chain-run verification checklist

`axiom execution-chain-run --capability <id> [--artifacts-root <p>] [--json-output]` runs one deterministic capability through the full execution stack (Plan→Step→Attempt→Result→Artifact→Evidence→Report). Verify:

- All 7 chain IDs present in output (plan, step, attempt, result, artifact, evidence, report).
- `status: "PASS"` and `id_flow_status: "PASS"`.
- `transitions` array shows 7/7 `[OK]` with `reference_value == upstream_id` at each stage.
- `ids_distinct: true` (all 7 IDs are unique).
- Use `--artifacts-root /tmp/testdir/artifacts` for isolated test runs.
- Evidence file persisted at `artifacts/execution_chain/<run_id>/evidence.json` with `capability_id`, `result_id`, `artifact_id` in `references`.
- Trace file at `artifacts/execution_chain/<run_id>/trace.json` with `status`, `report_id`, `created_at`.

## capability-evidence-apply verification checklist

`axiom capability-evidence-apply --evidence <path> [--capability-id <id>] [--max-age-seconds <n>] [--artifacts-root <p>] [--json-output]` routes evidence into existing capability confidence/readiness. Verify:

### Passing evidence
- `decision: "accepted"`, `evidence_outcome: "pass"`.
- `prior_state` shows baseline (e.g. `very_low / 0.0 / blocked` for first application).
- `updated_state` shows raised confidence (e.g. `very_high / 1.0 / ready` after first pass).
- `state_changed: true`.

### Failing evidence
- Create synthetic evidence: write `evidence.json` with `capability_id` in `references` + `trace.json` with `status: "FAIL"`.
- `decision: "accepted"`, `evidence_outcome: "fail"`.
- Score drops (e.g. 2 pass + 1 fail = score 0.6667), confidence drops, readiness may drop to `provisional`.

### Invalid/quarantined evidence
- Evidence with empty `references` (no `capability_id`): `decision: "quarantined"`, `state_changed: false`.
- Stale evidence with `--max-age-seconds 3600` and old `created_at`: `decision: "quarantined"`, reason includes "stale".

### Cumulative behavior
- Apply the same evidence twice: `execution_count` increments, `success_count` increments.

### Queryability
- `axiom capability-evidence-history --capability-id <id>`: shows all intakes with confidence transitions.
- `axiom capability-evidence-show <intake_id>`: shows one full record.

### Audit structure
- Intake records persisted at `artifacts/capability_evidence_intake/<intake_id>/report.json` + `pass_fail.json`.
- Exactly 2 files per intake (standard evidence convention).
- Quarantined/rejected evidence produces NO new confidence reports (`accepted_count == confidence_report_count`).

## cli-validation-record verification checklist

`axiom cli-validation-record --plan <path> [--artifacts-root <p>] [--name <run-name>] [--set KEY=VALUE] [--dry-run] [--json-output]` runs an explicit plan of allowlisted CLI commands and writes a durable evidence bundle. Verify:

- **Dry run governance:** `--dry-run` on `docs/validation_plans/m4_execution_chain.json` resolves the argv and shows each command `[OK]` (safe) without executing; an unknown/unsafe command shows `[XX]` and the run exits non-zero.
- **M4 plan:** `--plan docs/validation_plans/m4_execution_chain.json` -> `Status: PASSED`, `1/1 passed`, bundle under `artifacts/validation_evidence/<run_id>/`.
- **M2 plan:** `--plan docs/validation_plans/m2_evidence_promotion.json --set evidence=<chain_evidence.json>` -> `Status: PASSED`, `2/2 passed`.
- **Bundle shape:** `validation_run.json`, `commands.json`, `environment.json`, `artifact_manifest.json` (sha256 per file), `assertion_results.json`, `plan_snapshot.json`, `report.md`, and per-command `commands/NN_<id>.stdout.txt`/`.stderr.txt`.
- **Failures first-class:** a failing command with `continue_on_failure=false` marks later commands `skipped`, sets run status `failed`, and exits 1; stdout/stderr/exit are still preserved.
- Generated bundles stay under git-ignored `artifacts/validation_evidence/`.

## runner-commands (Command Registry, PR #22) verification checklist

`axiom runner-commands` is read-only governance — it prints policy and never executes anything. Verify:

- `poetry run axiom runner-commands` -> footer shows total command count (was 31).
- `--classification mutation` -> only mutation/high_risk commands (was 4: execute, local-runner, prompt, set-parameter-value).
- `--name <cmd>` -> classification, safety, requires-revit / requires-model-open, prerequisites, evidence outputs, failure classification table.
- `--name <unknown>` -> "not allowed (unknown commands are denied by default)" and exit code 2 (check with `; echo "exit=$?"`).
- `--json` -> valid JSON list; per-entry typed fields: timeout {seconds,kill_on_expire,classification_on_expire}, evidence_outputs[] {location,description,required}, failure_modes[] {code,description,retryable}.

Exact counts may change as commands are added/removed — assert the shape and that the count matches the catalog, not a hardcoded number.

---

## Test tiering (per repo policy)

Code + tests changes: run targeted tests then full `poetry run pytest` + `poetry run ruff check` at the PR checkpoint. Docs/log-only changes: do not run full pytest.

## Reporting

Post ONE PR comment with collapsed <details> sections (pre-expand the main evidence), inline screenshots, the recording, and a link to the Devin session.

## Devin Secrets Needed

None for CLI governance testing — runner-commands is local, read-only, and needs no Revit/credentials. Live Revit validation (not required for governance PRs) would run on AXIOM-01.
