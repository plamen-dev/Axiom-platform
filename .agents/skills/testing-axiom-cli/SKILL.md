---
name: testing-axiom-cli
description: Run a recordable end-to-end walkthrough of the axiom CLI. Use when verifying axiom CLI subcommands (e.g. runner-commands, execution-chain-run, capability-evidence-apply) and needing visual evidence (screenshots/recording) for a PR.
---

# Testing the axiom CLI (with a recordable terminal)

The axiom CLI is a terminal app, so shell-tool output is not visible on screen. To produce a recording/screenshots of CLI behavior, drive a terminal that renders in the browser.

## Recordable terminal via ttyd

The exec/shell tool output is NOT captured by screen recording. To get a visible, recordable terminal:

1. Install ttyd if missing: `sudo apt-get install -y ttyd` (also `wmctrl` for maximizing).
2. Launch an interactive shell in the repo, served over HTTP:
   ```
   cd <repo> && (ttyd -p 7681 -t fontSize=18 --writable bash -l >/tmp/ttyd.log 2>&1 &)
   ```
3. Open `http://localhost:7681` in the browser tool, click to focus.
4. Maximize the window: `wmctrl -r :ACTIVE: -b add,maximized_vert,maximized_horz`.
5. `recording_start`, then type commands. NOTE: with xterm.js/ttyd, the browser `type` action must target the terminal element by its `devinid` (e.g. devinid 0); a plain `type` without devinid may silently fail. Press Enter with `press_key` Enter (also targeting the devinid). Wait ~2s after Enter before `view` for output to render.
6. For valid-JSON or exact-count assertions, ALSO verify in the shell tool (pipe to `python3 -m json.tool` / `json.load`), since the recording proves the human-facing path and the shell proves correctness.

## Long CLI walkthrough scripts

For complex multi-step walkthroughs (e.g. 12+ steps with JSON output), write a shell script from the shell tool and run it in ttyd with `bash /path/to/walkthrough.sh`. This avoids pipe/brace/quote issues in ttyd's xterm.js and produces a clean scrolling recording. Key rules:
- Write the script from the shell tool (NOT ttyd) to avoid dropped characters.
- Write synthetic test fixtures from the shell tool too (JSON with braces/pipes).
- Do NOT pipe the walkthrough script to `head` or `less` — it breaks `set -e` scripts with SIGPIPE. Let the full output scroll naturally.
- Verify the script works in the shell tool first, then re-prep artifacts and run it in ttyd for recording.
- Use the shell tool for authoritative JSON verification after the recording (parse with `python3 -c "import json; ..."`).

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

### Pipe character workaround
The `|` character is dropped when typed into ttyd via the computer `type` action. Workarounds:
- For JSON validation, run the piped command in the shell tool (not ttyd) — this is authoritative anyway.
- For display in ttyd, use `grep -E 'pattern1pattern2'` (grep's `-E` with no pipe) or write helper scripts from the shell tool.

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

## runner-commands (Command Registry, PR #22) verification checklist

`axiom runner-commands` is read-only governance — it prints policy and never executes anything. Verify:

- `poetry run axiom runner-commands` -> footer shows total command count (was 31).
- `--classification mutation` -> only mutation/high_risk commands (was 4: execute, local-runner, prompt, set-parameter-value).
- `--name <cmd>` -> classification, safety, requires-revit / requires-model-open, prerequisites, evidence outputs, failure classification table.
- `--name <unknown>` -> "not allowed (unknown commands are denied by default)" and exit code 2 (check with `; echo "exit=$?"`).
- `--json` -> valid JSON list; per-entry typed fields: timeout {seconds,kill_on_expire,classification_on_expire}, evidence_outputs[] {location,description,required}, failure_modes[] {code,description,retryable}.

Exact counts may change as commands are added/removed — assert the shape and that the count matches the catalog, not a hardcoded number.

## Test tiering (per repo policy)

Code + tests changes: run targeted tests then full `poetry run pytest` + `poetry run ruff check` at the PR checkpoint. Docs/log-only changes: do not run full pytest.

## Reporting

Post ONE PR comment with collapsed <details> sections (pre-expand the main evidence), inline screenshots, the recording, and a link to the Devin session.

## Devin Secrets Needed

None for CLI governance testing — runner-commands is local, read-only, and needs no Revit/credentials. Live Revit validation (not required for governance PRs) would run on AXIOM-01.
