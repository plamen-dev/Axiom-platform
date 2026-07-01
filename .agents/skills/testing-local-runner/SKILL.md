---
name: testing-local-runner
description: Operate and verify the Local Runner — task.json format, allowlisted actions (git_status, ruff, execution_chain_run, capability_evidence_apply, emit_evidence_summary), Windows/WDAC invocation notes, and run artifact layout. Use when testing runner actions or changes under tools/local_runner/.
---

# Testing the Local Runner

## Domain

The Local Runner is a restricted execution harness with workspace sandboxing and an action allowlist as the security boundary. Source: `tools/local_runner/local_runner.py`; example tasks in `tools/local_runner/examples/`.

## Commands

- `poetry run python tools/local_runner/local_runner.py --task <task.json>`
- Task shape: `{"action": "<allowlisted action>", "prompt": "...", "timeout_seconds": <n>, "workspace": "<repo path>", "metadata": {...}}`
- Allowlisted loop actions include: `git_status`, `ruff`, `execution_chain_run`, `capability_evidence_apply`, `emit_evidence_summary` (see examples dir for current task files).

## Registry pointers

- The allowlist in the runner is the security boundary — tasks cannot supply arbitrary argv or evidence paths.
- Run artifacts: `artifacts/local_runner_runs/run_<timestamp>/` (gitignored scratch).
- Tracked proof objects: `emit_evidence_summary` writes `artifacts/validation_runs/<summary_id>/evidence_summary.{json,md}` — committable (attested → captured). It is read-only: resolves the newest chain bundle itself and mutates no capability/confidence/readiness/promotion state.

## Verification checklists

- Run an example task; assert `Status: success`, exit 0, artifacts dir printed.
- `emit_evidence_summary`: summary contains run_id, capability_id, chain id-flow status, quality verdict, promotion decision (or `not_applied`), current confidence/readiness, before→after, **relative** source paths, git commit, UTC timestamp. No raw stdout, no secrets, no absolute paths.
- Allowlist boundary: task-supplied evidence/summary paths are ignored; unknown actions are denied.
- Blocked-with-guidance when no evidence bundle exists.

## Tests

Targeted: `tests/test_local_runner.py`, `tests/test_evidence_summary.py`. Full pytest only at PR checkpoints.

## Notes / gotchas

- **Windows/WDAC:** bare `poetry`/`ruff`/`pytest` exe shims are blocked by Application Control (`WinError 4551`). The runner normalizes to `python -m` forms at execution time, Windows only; operators should use `python -m poetry run axiom ...` directly.
- `emit_evidence_summary` runs in-process (no subprocess), so it has no WDAC exe-shim exposure.
- Windows lane-2 validation status is owned by the operator run sheet (`docs/runbooks/`), not by this skill.
