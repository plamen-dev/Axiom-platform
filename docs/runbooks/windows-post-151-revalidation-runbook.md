# Windows Post-#151 Revalidation Runbook

## Purpose

Convert Windows-local evidence from **attested** to **captured** for the
execution-chain and evidence-promotion paths, on the real target machine, after
PR #151 (Windows Artifact Path Compatibility Fix).

This is the **lane-2** gate. It does *not* touch Revit — it proves the
deterministic substrate loop (chain → evidence → promotion) runs on Windows and
that the `Resolved path escapes artifacts root: '<uuid>'` bug found pre-#151 is
gone. Revit-live mutation is a separate, later lane.

### Evidence lanes (do not conflate)

| Lane | Meaning | This runbook |
|------|---------|--------------|
| 1 — Devin/Ubuntu | repo proof | already green (not sufficient alone) |
| 2 — Plamen Windows-local | **required target-environment proof** | **this runbook** |
| 3 — Revit-live | real model mutation | out of scope here |

## Background: what #151 fixed

Pre-#151, on `C:\Dev\Axiom\Code\Axiom-platform`, the execution-chain /
evidence-promotion paths failed with `Resolved path escapes artifacts root:
'<uuid>'` (targeted pytest: 38 failed / 77 passed / 1 skipped, concentrated in
`tests/test_execution_chain_orchestrator.py` and `tests/test_evidence_promotion.py`).
`capability-evidence-apply` could not proceed because no chain evidence was
created. PR #151 addressed the Windows artifact-path containment bug. This
runbook confirms the fix on the real machine.

## Prerequisites

- Windows 10/11, repo at `C:\Dev\Axiom\Code\Axiom-platform` (the real path — **not**
  the `C:\Dev\Axiom\Axiom-platform` placeholder).
- `main` synced **at or past both PR #151 and PR #50** (the Local Runner loop
  actions `execution_chain_run` / `capability_evidence_apply` are required for
  steps 3–4). Confirm with `poetry run axiom local-runner --help` and that the
  two actions appear in `tools/local_runner/local_runner.py`.
- `poetry install` completed; `poetry run axiom --help` lists `execution-chain-run`
  and `capability-evidence-apply`.
- No tracked source files modified before starting (`git status --short` clean).

See `docs/runbooks/windows-revit-build-test-runbook.md` and
`docs/runbooks/local-runner-runbook.md` for environment/build detail — not repeated here.

## The 8-point revalidation gate

Run in order. All eight must pass before Windows is treated as ready for
Local-Runner loop integration, implementation-worker work, or Revit-adjacent
execution. Capture the console output and the artifact folders for each step.

### 1. Local Runner `git_status`

```
poetry run axiom local-runner --task tools/local_runner/examples/git_status.task.json
```
Pass: `status: success`, exit code 0, `artifacts/local_runner_runs/<run>/` written.

### 2. Local Runner `ruff`

```
poetry run axiom local-runner --task tools/local_runner/examples/ruff.task.json
```
Pass: `status: success`, no lint violations.

### 3. `execution-chain-run` (via the runner — PR #50 action)

```
poetry run axiom local-runner --task tools/local_runner/examples/execution_chain_run.task.json
```
Pass: `status: success`; a bundle exists at
`artifacts\execution_chain\<run_id>\evidence.json`. This is the step that failed
pre-#151 with `Resolved path escapes artifacts root`.

> Direct-CLI equivalent (if running without the runner):
> `poetry run axiom execution-chain-run --json-output`

### 4. `capability-evidence-apply` (via the runner — PR #50 action)

```
poetry run axiom local-runner --task tools/local_runner/examples/capability_evidence_apply.task.json
```
Pass: `status: success`; the runner resolves the newest
`artifacts\execution_chain\<run_id>\evidence.json` itself (sandbox-validated path,
no task-supplied path) and applies it. A confidence/intake record is written under
`artifacts\capability_confidence\` and `artifacts\capability_evidence_intake\`.

If this step reports `blocked` with "run the 'execution_chain_run' action first",
step 3 did not produce a bundle — fix step 3 before continuing.

### 5. Targeted tests

```
poetry run pytest tests/test_local_runner.py tests/test_command_registry.py tests/test_execution_chain_orchestrator.py tests/test_evidence_promotion.py -q
```
Pass: 0 failed. (Pre-#151 this set produced the 38-failure cluster.)

### 6. CLI Validation Evidence Recorder (if relevant)

If exercised, run it on Windows and confirm it records the run without error. Skip
only if not part of the current validation scope; note the skip in the report.

### 7. No tracked source files modified

```
git status --short
```
Pass: no ` M ` / ` D ` on tracked files — only untracked artifact folders.

### 8. Only gitignored artifact folders produced

```
git status --short --ignored | findstr /R "artifacts"
```
Pass: `artifacts\execution_chain\`, `artifacts\capability_confidence\`,
`artifacts\capability_evidence_intake\`, and `artifacts\local_runner_runs\` appear
as **ignored** (`!!`), not untracked (`??`). (These are gitignored as of PR #50.)

## Recording the result

After all eight pass, record the outcome so it becomes captured evidence, not a
chat note:

- Append a dated entry to `docs/logs/behavior-change-ledger.md` (observed command,
  previous behavior = pre-#151 path-escape failure, current behavior = pass, related
  PRs #151/#50, artifact paths).
- Preserve the `execution_chain\<run_id>\evidence.json` and the
  `capability_confidence\` / `capability_evidence_intake\` records as the captured
  lane-2 bundle.

### Required status line on success

> "Post-#151 Windows revalidation passed on `C:\Dev\Axiom\Code\Axiom-platform`:
> Local Runner `git_status`/`ruff`, `execution-chain-run`, and
> `capability-evidence-apply` all succeeded via the runner; the targeted
> execution-chain/evidence-promotion tests are green; no tracked source files were
> modified; only gitignored artifact folders were produced. The pre-#151
> `Resolved path escapes artifacts root` bug is resolved. Windows substrate loop is
> now captured, not just attested. Revit-live mutation remains a separate,
> pending lane."

### If any step fails

Do not mark Windows ready. Capture the failing step's `failure_summary.md`, the
`stderr.txt`, and the `git status`, and route the failure into a bug/evidence entry
(`docs/logs/bug-validation-log.md`) — not just a chat note.
