# Validation Evidence Runner v1 (PR #25)

The Validation Evidence Runner connects the **Runner Command Registry** (PR #22)
and the **Capability Validation Registry** (PR #24) into a repeatable,
read-only evidence generator. It is the first step toward Axiom validating
Axiom — producing validation evidence bundles itself instead of relying on a
human manually recording walkthroughs.

It is **governance + read-only execution only**: it consumes registry
definitions, runs only explicitly allowed safe/read-only procedures, and writes
a durable evidence bundle. It does **not** schedule, promote, learn, score,
generate workflows, mutate models, or execute `SetParameterValue`.

## How a run is decided

For `axiom evidence-run --validation <name>`:

1. **Resolve against the validation registry.**
   - Unknown name → **denied by default** (`denied`, exit `2`).
   - Known **mutation/high-risk** capability (e.g. `SetParameterValue`) →
     **refused** (`refused`, exit `3`). Mutation allowance is deliberately not
     implemented.
   - Known capability with no safe read-only executor here (e.g. `BridgeExecute`,
     `InventoryModel` — require live Revit) → **unsupported** (`unsupported`,
     exit `4`).
2. **Gate the command it drives against the command registry (PR #22).**
   The validation's command must be allowed, must not be mutation/high-risk, and
   its prerequisites must be satisfiable by the runner's `ExecutionContext`.
   Unmet prerequisites → **blocked** (`blocked`, exit `5`).
3. **Run the read-only procedure** and judge the checks → `passed` (exit `0`) or
   `failed` (exit `1`).

A **bundle is written every time**, including for denied / refused / blocked
outcomes.

## Supported validations (v1)

| Validation | Drives command | Consumes registry capability | What it checks |
|------------|----------------|------------------------------|----------------|
| `DiscoveryHarness` | `discovery-run` | `DiscoveryHarness` | categories / parameters / candidates discovered and `discovery_complete` (checks derived from the registry's declared `pass_conditions`) |
| `CommandRegistry` | `runner-commands` | — | catalog non-empty, entries well-formed, unknown command denied by default |
| `ValidationRegistry` | `validation-registry` | — | catalog non-empty, structurally valid, unknown capability denied by default |

`DiscoveryHarness` uses the supplied `--inventory-export-path` when given,
otherwise the built-in deterministic export (so it is runnable in CI and
reaches `discovery_complete = yes`). Per the InventoryModel safety rules, this
runner never triggers a full live-Revit parameter scan.

## Evidence bundle

```text
artifacts/validation_evidence/<validation>/<evr_id>/
    validation_request.json     # what was asked (validation, inputs, timestamp)
    validation_result.json      # full machine-readable result + checks
    validation_summary.md       # human-readable summary table
    command_outputs/            # captured outputs of the checks performed
    pass_fail.json              # compact machine-readable verdict
```

`pass_fail.json` is the stable machine-readable contract:

```json
{
  "validation_name": "CommandRegistry",
  "outcome": "passed",
  "passed": true,
  "exit_code": 0,
  "checks_passed": 3,
  "checks_total": 3,
  "checks": [{"name": "catalog_non_empty", "passed": true, "detail": "33 commands cataloged"}]
}
```

## Outcomes and exit codes

| Outcome | Exit | Meaning |
|---------|------|---------|
| `passed` | 0 | ran and met every check |
| `failed` | 1 | ran but at least one check failed |
| `denied` | 2 | unknown validation — denied by default |
| `refused` | 3 | known mutation/high-risk — not allowed (no mutation allowance) |
| `unsupported` | 4 | known capability, no safe read-only executor here |
| `blocked` | 5 | command prerequisites not met |

## CLI

```bash
axiom evidence-run --validation CommandRegistry
axiom evidence-run --validation ValidationRegistry
axiom evidence-run --validation DiscoveryHarness
axiom evidence-run --validation DiscoveryHarness --inventory-export-path <folder>
```

The CLI prints the outcome, the per-check table, the bundle location, and the
exit code.

## Boundaries

- Read-only. No model mutation, no `SetParameterValue` execution.
- No autonomous scheduling, no promotion engine, no learning loop, no scoring,
  no workflow generation.
- Mutation/high-risk validations are refused; the allowance path is intentionally
  not implemented in v1.
- The runner is pure Python over the existing registries + discovery harness; it
  imports no CLI and starts no background process. Future autonomous validation
  loops will consume this runner.
