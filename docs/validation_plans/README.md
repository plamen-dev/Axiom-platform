# Validation Plans

Example plans for the **CLI Validation Evidence Recorder**
(`axiom cli-validation-record`). A plan is a small, explicit JSON list of
allowlisted Axiom CLI commands. The recorder runs the plan and writes a durable
evidence bundle under `<artifacts-root>/validation_evidence/<run_id>/` capturing
each command's inputs, stdout/stderr, exit code, timing, environment metadata,
an artifact manifest, and a human-readable `report.md`.

These are **plans**, not generated evidence. The generated bundles live under
`artifacts/validation_evidence/` and are git-ignored.

## Governance

Every command is authorized against the Runner Command Registry
(`src/axiom_core/runner/command_registry.py`). Only commands cataloged as
`safe` and not requiring live Revit run by default. Unknown / guarded /
high-risk / mutation / live-Revit commands are refused. Commands are executed
without a shell (explicit `argv`), so there is no shell-injection surface.

## Plan format

```json
{
  "plan_id": "string (required)",
  "title": "string (required)",
  "purpose": "string (required)",
  "commands": [
    {
      "id": "unique-id (required)",
      "command": "registry command name (required, e.g. execution-chain-run)",
      "args": ["--flag", "value", "${artifacts_root}"],
      "timeout_seconds": 120,
      "expected_exit_code": 0,
      "expect_stdout_contains": ["substring"],
      "expect_stderr_contains": ["substring"],
      "expect_artifact_exists": ["relative/or/absolute/path"],
      "continue_on_failure": false
    }
  ]
}
```

### Variable substitution

`args` support `${...}` substitution. Built-in variables:

- `${artifacts_root}` — resolved artifacts root.
- `${run_dir}` — this run's bundle directory (so a step can write sub-artifacts
  inside the bundle).
- `${repo_root}` — repository root (recorder working directory).

Additional variables can be supplied with repeatable `--set KEY=VALUE`.

### Run policy

Commands run in order. If a command fails (assertion failure, non-expected exit
code, timeout) or is blocked by governance and `continue_on_failure` is `false`
(the default), the remaining commands are marked `skipped` and the run stops.
The run status is `passed` only if every command passed.

## Example plans

### `m4_execution_chain.json`

Captures M4 proof: `execution-chain-run --capability self-model-build` writes
its chain objects/evidence under `${run_dir}/chain` and the recorder asserts a
zero exit code and expected output. Self-contained — no external inputs.

```bash
axiom cli-validation-record --plan docs/validation_plans/m4_execution_chain.json
```

### `m2_evidence_promotion.json`

Captures a narrow M2 proof: `capability-evidence-apply` consumes an evidence
bundle (e.g. the `evidence.json` produced by an execution-chain run) and routes
it into capability state, then `capability-evidence-history` shows the intake is
queryable. Supply the evidence path with `--set`:

```bash
axiom cli-validation-record \
  --plan docs/validation_plans/m2_evidence_promotion.json \
  --set evidence=artifacts/.../execution_chain/<run_id>/evidence.json
```

This plan is intentionally narrow; it does not recreate the full
evidence-promotion test suite.
