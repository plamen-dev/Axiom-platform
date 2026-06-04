---
name: testing-axiom-cli
description: Run a recordable end-to-end walkthrough of the axiom CLI. Use when verifying axiom CLI subcommands (e.g. runner-commands) and needing visual evidence (screenshots/recording) for a PR.
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
