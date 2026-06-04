# Capability Execution Runner v1 (PR #26)

The Capability Execution Runner is the first step from *validation evidence*
(PR #25) to *governed capability execution*. It executes explicitly allowed,
safe/read-only capabilities through the existing governance stack and produces a
durable evidence bundle for every run.

It is **governance-first execution**: it consumes the **Runner Command Registry**
(PR #22) for policy, maps a capability to its **Capability Validation Registry**
(PR #24) contract, and drives execution through the existing **Automation
Bridge** (PR #19). It does **not** schedule, execute discovered candidates,
execute `SetParameterValue`, allow mutation, retry, promote, score, learn,
generate workflows, or integrate external systems / MCP.

## How a run is decided

For `axiom capability-run --capability <name>`:

1. **Resolve against the supported-capability set.**
   - Unknown name → **denied by default** (`denied`, exit `2`).
   - Known **mutation/high-risk** capability (e.g. `SetParameterValue`) →
     **refused** (`refused`, exit `3`). Mutation allowance is deliberately not
     implemented.
   - Known capability with no safe executor wired here yet (e.g. `BridgeExecute`)
     → **unsupported** (`unsupported`, exit `4`).
2. **Gate the command it drives against the command registry (PR #22).**
   The command must be allowed and must not be mutation/high-risk.
3. **Apply capability-level safety.** For `InventoryModel`, an unsafe scan shape
   is **refused** before any bridge call. Refused shapes are:
   - an explicit full/whole-model flag (`FullScan`/`WholeModel`/… truthy);
   - a `mode`/`scan`/`scanmode`/`scan_type` key whose value requests a
     full/unbounded scan (`full`, `all`, `everything`, `whole`, …) — refused
     regardless of `SummaryOnly`, so a raw `full` value can never reach the bridge;
   - an oversized or non-numeric numeric limit (`max`/`limit`/`top`/`take`/
     `sample_size`/…) — a limit must be a positive integer `<= 10000`; a huge
     limit is effectively unbounded and is refused outright;
   - `SummaryOnly=false` without a valid bound (category/level/sample or a modest
     numeric limit). A categorical key only bounds the scan when its value is a
     real, narrowing subset — an empty/whitespace/null value, a boolean, or a
     full-scan alias (`all`/`everything`/`full`/…) is **not** a bound, so it
     cannot be used to slip an unbounded `SummaryOnly=false` scan past the gate.

   Full/unbounded scans are blocked/high-risk — they crashed Revit 2027. Key
   matching is case-insensitive and alias-aware.
4. **Check prerequisites** against the runner's `ExecutionContext`. Unmet
   prerequisites → **blocked** (`blocked`, exit `5`). In `--simulate` mode the
   bridge uses the mock path, so live-Revit prerequisites are considered
   satisfied; in live mode an off-Windows / no-Revit run is correctly blocked
   unless the caller supplies a context proving Revit is up.
5. **Execute the capability** through the Automation Bridge and judge the checks
   → `passed` (exit `0`) or `failed` (exit `1`). An unhandled exception during
   gating/execution is caught and classified `failed` (exit `1`) so the durable
   evidence bundle is still written rather than lost.

A **bundle is written every time**, including for denied / refused / blocked
outcomes and for runs that raise an unhandled exception.

## Outcome taxonomy and exit codes

| Outcome | Exit | Meaning |
|---------|------|---------|
| `passed` | 0 | Executed and met every pass check |
| `failed` | 1 | Executed but at least one check failed |
| `denied` | 2 | Unknown capability — denied by default |
| `refused` | 3 | Mutation/high-risk capability or unbounded InventoryModel scan |
| `unsupported` | 4 | Known capability, no safe executor wired here yet |
| `blocked` | 5 | Command prerequisites not met |

## Supported capabilities (v1)

| Capability | Drives command | Validation contract | Allowed modes |
|------------|----------------|---------------------|---------------|
| `InventoryModel` | `bridge-execute` | `InventoryModel` | summary (default) and bounded category/level/sample scans; full/unbounded scans refused |

`InventoryModel` defaults to safe summary mode (`SummaryOnly: true`) when no
args are supplied.

## CLI

```bash
axiom capability-run --capability <name>
axiom capability-run --capability InventoryModel --simulate
axiom capability-run --capability InventoryModel --args-json '{"Category": "Walls"}' --simulate
```

Optional flags: `--args-json <json>` (capability arguments; must be a JSON
object), `--run-id <id>`, `--output-dir <path>`, `--simulate`. No mutation flags
are exposed.

## Evidence bundle

Written under `artifacts/capability_runs/<capability>/<run_id>/`:

```text
capability_request.json     # capability, args, simulate, run id, timestamp
capability_result.json      # full machine-readable result + validation_contract
capability_summary.md       # human-readable summary
pass_fail.json              # compact, machine-readable verdict
command_outputs/            # bridge_result.json + bridge evidence sub-bundle
```

`capability_result.json` records the mapped validation contract
(`validation_procedure_id`, declared `pass_conditions`, required artifacts /
checkpoints) so governed execution traces back to the validation registry's
declared expectations.

## Scope guardrails (PR #26)

- Safe/read-only capabilities only; the only initial capability is
  `InventoryModel` in summary/bounded mode.
- No `SetParameterValue` execution, no mutation allowance.
- No autonomous scheduling, discovered-candidate execution, retry engine,
  promotion engine, scoring, learning loop, workflow generation, or external /
  MCP integration.
- Live bridge execution is optional; simulate/mocked execution is always
  available for off-Windows testing.
- The Revit 2024 baseline is unaffected.
