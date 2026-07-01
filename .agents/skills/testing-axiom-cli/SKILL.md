---
name: testing-axiom-cli
description: Base skill for recordable axiom CLI testing — the ttyd recordable terminal setup, recording reliability rules, and reporting/secrets conventions. Use when any axiom CLI verification needs visual evidence (screenshots/recording). Domain-specific checklists live in sibling skills (testing-execution-chain, testing-evidence-promotion, testing-cli-governance, testing-atlas-ui, testing-local-runner); PR guidance lives in axiom-pr-workflow.
---

# Testing the axiom CLI (with a recordable terminal)

## Domain

The axiom CLI is a terminal app, so shell-tool output is not visible on screen. To produce a recording/screenshots of CLI behavior, drive a terminal that renders in the browser. This skill covers only the shared mechanics; domain checklists are in sibling skills under `.agents/skills/`:

- `testing-execution-chain` — M4 execution-chain-run
- `testing-evidence-promotion` — M2 capability-evidence-apply + cli-validation-record
- `testing-cli-governance` — runner-commands + framework create/show/export pattern
- `testing-atlas-ui` — the Atlas browser UI
- `testing-local-runner` — Local Runner actions incl. emit_evidence_summary
- `axiom-pr-workflow` — compute mode, self-audit, reconciliation gate, tiering, reporting

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

## Recording / ttyd reliability guidance

Lessons from PR #146, #147, #148 CLI walkthroughs:

- **Browser typing into ttyd/xterm can drop characters.** The `|`, `{`, `}` characters typed via the computer `type` action are unreliable. Write helper scripts from the shell tool instead of typing long commands directly.
- **Use short helper scripts for long walkthroughs.** Write per-test `.sh` scripts to `/tmp/` (not the repo), each echoing a clear section banner and running one logical step. Type only `bash /tmp/scripts/tN.sh` + Enter in ttyd.
- **Avoid fragile pipe/brace-heavy one-liners in recorded terminal tests.** Move piped commands, JSON construction, and inline Python to helper scripts or the shell tool.
- **Ensure helper files are not committed.** Keep walkthrough scripts in `/tmp/` or `$HOME/` — never in the repo working tree. Delete any stray files after recording.
- **Clean working tree after recording.** Run `git status --porcelain` to verify no untracked/modified files before reporting results.
- **Attach reports and recording evidence separately from runtime code.** Test reports, screenshots, and recordings go to the PR comment and user message attachments, not to the repo.
- **Convert mp4 recordings to animated webp for PR comment embedding:** `ffmpeg -y -i recording.mp4 -vf "fps=8,scale=900:-1:flags=lanczos" -loop 0 -q:v 60 walkthrough.webp`.

## Reporting

Post ONE PR comment with collapsed <details> sections (pre-expand the main evidence), inline screenshots, the recording, and a link to the Devin session.

## Devin Secrets Needed

None for CLI governance testing — runner-commands is local, read-only, and needs no Revit/credentials. Live Revit validation (not required for governance PRs) would run on AXIOM-01.
