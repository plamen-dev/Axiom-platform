# Runner Command Registry — Automation Command Catalog (PR #22)

> Status: **IMPLEMENTED** (governance/infrastructure only). This PR ships the
> declarative catalog + a read-only CLI. It does **not** add autonomous
> execution, scheduling, model mutation, or a promotion loop.

## 1. Objective

Give Axiom a **governed catalog of commands the AXIOM-01 runner is allowed to
execute**, so that automation does not just know *what it can discover* but
*which local commands it may run, under what conditions, and how the outputs
are validated*.

This is the **execution policy layer**. Future automation loops (the
Verification Factory's outer loop) consult this registry *before* dispatching
any command. It is the bridge between "we know a command exists" and "we are
allowed to run it, and here is how we judge the result".

## 2. Where it sits

```
Automation loop / runner
        │  (asks: "may I run X? what does success look like?")
        ▼
Runner Command Registry   ← THIS PR (pure metadata, no execution)
        │  (policy: classification, prerequisites, evidence, timeout, failure modes)
        ▼
Local Runner (tools/local_runner)   ← existing execution harness
        │  (named allowlisted actions, workspace policy, timeout, artifact capture)
        ▼
Subprocess
```

- The registry is **pure governance metadata** — no `subprocess`, no I/O, no
  Revit. It lives in `src/axiom_core/runner/command_registry.py`.
- The **Local Runner** remains the execution harness. The registry is the
  policy it (and future loops) consult. The two are complementary: the Local
  Runner answers "*can this be executed safely in this workspace?*"; the
  registry answers "*is this command governed, and how is its result judged?*".
- **Unknown commands are denied by default**: `is_allowed(name)` returns
  `False` for anything not explicitly cataloged.

## 3. Named types (governance vocabulary)

PR #22 defines these first-class types in
`src/axiom_core/runner/command_registry.py` (re-exported from
`axiom_core.runner`):

| Type | Role |
|------|------|
| `CommandRegistry` | The governed catalog as an object: `list_commands`, `get`, `is_allowed`, `by_classification`, `runnable_in(context)`, `validate`. The module ships a `DEFAULT_REGISTRY`. **Unknown ⇒ denied.** |
| `AllowedCommand` | A single governed command entry (the per-command policy record). `CommandSpec` is a back-compat alias. |
| `ExecutionContext` | The runtime conditions a runner reports (revit_running, model_open, poetry_env, dotnet_sdk, branch_checked_out, workspace_clean, db_path_available, inventory_export_available). Consulted to decide whether a command may run — never executes. |
| `SafetyLevel` | `safe` / `guarded` / `high_risk`. |
| `CommandClass` | Primary effect: `read_only` / `test` / `build` / `mutation` / `live_revit_required`. |
| `EvidenceOutput` | A typed evidence expectation: `location`, `description`, `required`. |
| `Timeout` | A typed timeout: `seconds`, `kill_on_expire`, and `classification_on_expire` (→ `FailureClassification.TIMEOUT`). |
| `FailureClassification` | The stable failure taxonomy enum (alias of `FailureClass`). |
| `FailureMode` | A classified failure on a command: `code` (`FailureClassification`) + `description` + `retryable`. |
| `Prerequisite` | A condition that must hold before dispatch. |

### `AllowedCommand` fields & derived predicates

| Field | Type | Meaning |
|-------|------|---------|
| `name` | str | Canonical registry id (e.g. `pytest`, `discovery-run`). |
| `command` | str | The governed invocation string. |
| `description` | str | What the command does. |
| `classification` | `CommandClass` | Primary effect (see below). |
| `safety_level` | `SafetyLevel` | `safe` / `guarded` / `high_risk`. |
| `prerequisites` | `tuple[Prerequisite]` | Conditions that must hold first. |
| `evidence_outputs` | `tuple[EvidenceOutput]` | Where to look to validate the result (strings are coerced to `EvidenceOutput`). |
| `timeout_seconds` | int | Hard ceiling for the command (also exposed as the typed `timeout`). |
| `failure_modes` | `tuple[FailureMode]` | Classified failures + retry guidance. |
| `notes` | str | Free-form caveats. |

Derived predicates (explicit, first-class):

- `requires_revit` (**RequiresRevit**) — class is `live_revit_required` or
  `revit_running` is a prerequisite (`requires_live_revit` is a back-compat alias).
- `requires_model_open` (**RequiresModelOpen**) — `model_open` is a prerequisite.
- `is_read_only` / `is_mutation` (**ReadOnly/Mutation**).
- `timeout` — the typed `Timeout`.
- `unmet_prerequisites(context)` / `can_run(context)` — gate against an
  `ExecutionContext`.

### Classification (`CommandClass`)

- `read_only` — produces artifacts/console output only; no model/repo mutation
  (`ruff`, `discovery-run`, `inventory-*` readers, `stats`, `jobs`, `plans`…).
- `test` — verification gate (`pytest`, `validation-run`, `test-grids`,
  `test-levels`).
- `build` — compiles/produces binaries (`dotnet build`).
- `mutation` — mutates the model or repository state. Cataloged commands:
  `prompt`, `execute`, `set-parameter-value`, `local-runner` — all `high_risk`.
  PR #22 only *governs* these; it does **not** execute them.
- `live_revit_required` — talks to a running Revit add-in (`bridge-execute`,
  `inventory-model`).

### Safety level (`SafetyLevel`)

- `safe` — no side effects beyond artifacts; runnable anytime.
- `guarded` — has prerequisites / environment constraints (build tools, a
  checked-out branch, a running Revit, a docs-mutating `--apply` form).
- `high_risk` — mutates model/state; must be explicitly gated.

### Prerequisites (`Prerequisite`)

`poetry_env`, `dotnet_sdk`, `revit_running`, `model_open`,
`branch_checked_out`, `workspace_clean`, `db_path_available`,
`inventory_export_available` (and `none`). Each maps to a boolean on
`ExecutionContext`; `none` is always satisfied.

### Failure classification (`FailureClassification`)

A stable taxonomy automation loops use to decide **retry vs. escalate**:
`nonzero_exit`, `timeout`, `missing_prerequisite`, `environment_error`,
`pipe_unavailable`, `malformed_input`, `build_error`, `test_failure`,
`lint_violation`, `incomplete_discovery`, `missing_evidence`.

Each command lists the specific `FailureMode`s it can exhibit, each carrying a
`retryable` flag (e.g. a `timeout` or `pipe_unavailable` is retryable; a
`test_failure` or `build_error` is not).

## 4. Cataloged commands (full — 33)

Covers **every built-in `axiom` CLI command** plus the toolchain commands
`pytest`, `ruff`, and `dotnet-build`. Full evidence outputs, failure modes, and
notes are in the catalog and via `axiom runner-commands --name <name>`.

| Name | Class | Safety | Prerequisites | Timeout |
|------|-------|--------|---------------|---------|
| `bridge-execute` | live_revit_required | guarded | poetry_env, revit_running, model_open | 600s |
| `demo` | read_only | safe | poetry_env | 600s |
| `discovery-run` | read_only | safe | poetry_env, inventory_export_available, db_path_available | 600s |
| `dotnet-build` | build | guarded | dotnet_sdk | 1200s |
| `evidence-run` | read_only | safe | poetry_env | 600s |
| `evidence-update` | read_only | guarded | poetry_env | 120s |
| `execute` | mutation | high_risk | poetry_env, revit_running, model_open | 600s |
| `inventory-combine` | read_only | safe | poetry_env, inventory_export_available | 600s |
| `inventory-export` | read_only | safe | poetry_env, inventory_export_available | 600s |
| `inventory-import` | read_only | safe | poetry_env, inventory_export_available | 600s |
| `inventory-import-batch` | read_only | safe | poetry_env, inventory_export_available | 900s |
| `inventory-model` | live_revit_required | guarded | poetry_env, revit_running, model_open | 900s |
| `inventory-plan` | read_only | safe | poetry_env, inventory_export_available | 300s |
| `inventory-plan-status` | read_only | safe | poetry_env | 60s |
| `inventory-summary` | read_only | safe | poetry_env, inventory_export_available | 120s |
| `jobs` | read_only | safe | poetry_env | 60s |
| `local-runner` | mutation | high_risk | poetry_env, workspace_clean | 1800s |
| `parameter-registry-build` | read_only | safe | poetry_env, inventory_export_available | 600s |
| `plan` | read_only | safe | poetry_env | 120s |
| `plans` | read_only | safe | poetry_env | 60s |
| `pr-snapshot` | read_only | safe | poetry_env | 120s |
| `prompt` | mutation | high_risk | poetry_env, revit_running, model_open | 600s |
| `pytest` | test | safe | poetry_env | 1800s |
| `ruff` | read_only | safe | poetry_env | 300s |
| `runner-commands` | read_only | safe | poetry_env | 60s |
| `set-parameter-value` | mutation | high_risk | poetry_env, revit_running, model_open | 600s |
| `stats` | read_only | safe | poetry_env | 60s |
| `submit` | read_only | safe | poetry_env | 120s |
| `test-grids` | test | guarded | poetry_env | 600s |
| `test-levels` | test | guarded | poetry_env | 600s |
| `tools` | read_only | safe | poetry_env | 60s |
| `validation-registry` | read_only | safe | poetry_env | 60s |
| `validation-run` | test | guarded | poetry_env, branch_checked_out | 1800s |

Notes on classification of the mutating/live commands:

- `prompt` / `execute` default to live execution — classified `mutation` /
  `high_risk`. `test-grids` / `test-levels` are `test` in simulate mode; their
  `--mode real` form is live-Revit + mutation (called out in their notes).
- `inventory-model` is summary-only by default (per InventoryModel safety
  rules); full/parameter scans stay guarded.
- `local-runner` is the meta-executor; classified at its worst case (`mutation`
  / `high_risk`) and bounded by the local_runner allowlist + workspace policy.
- `evidence-update` is read-only by default; its `--apply` form mutates
  docs/logs ledgers, hence `guarded`.

## 5. CLI

```
axiom runner-commands                          # list all allowed commands
axiom runner-commands --classification test    # filter by classification
axiom runner-commands --name pytest            # inspect one command in detail
axiom runner-commands --name <unknown>         # denied (exit 2) by default
axiom runner-commands --json                   # machine-readable catalog
```

The CLI is **read-only**: it prints policy, it never executes a cataloged
command. Inspecting an uncataloged name exits non-zero with an explicit
"unknown commands are denied by default" message.

## 6. How this becomes the execution policy layer

A future automation loop (out of scope here — no autonomous execution in PR
#22) will, for each step:

1. Resolve the step to a cataloged `name`; if `DEFAULT_REGISTRY.is_allowed(name)`
   is `False`, **refuse** (unknown ⇒ denied).
2. Build an `ExecutionContext` from the live environment and call
   `command.unmet_prerequisites(context)` (or `DEFAULT_REGISTRY.runnable_in`);
   if any prerequisite is unmet, record `missing_prerequisite` and skip/escalate.
3. Dispatch via the Local Runner with the spec's `timeout` (kill on expiry →
   `FailureClassification.TIMEOUT`).
4. Locate the declared `evidence_outputs` to validate success; a missing
   `required` output is a `missing_evidence` failure.
5. On failure, map to one of the spec's `failure_modes` and use `retryable`
   to decide bounded retry vs. escalation — feeding the existing
   FailureClassifier / retry direction.

This keeps the policy declarative and auditable, and keeps execution,
scheduling, retry, and promotion as separate, later layers.

## 7. Scope / non-goals

In scope: schema, catalog, classification, prerequisites, evidence
expectations, timeout, failure classification, list/inspect CLI, unknown-by
default denial, tests, docs.

Explicitly **not** in this PR: autonomous command execution, scheduling,
model mutation, promotion/scoring loops. The 2024 baseline is unaffected
(no runtime capability behavior changes).
