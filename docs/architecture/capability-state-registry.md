# Capability State Registry v1 (PR #27)

The Capability State Registry is Axiom's **durable lifecycle-state memory** for
capabilities. Axiom can already discover, validate, govern, execute, and produce
evidence; this layer answers — from one queryable place — *which capabilities
exist, which are executable, which have validation definitions, which passed or
failed, which are blocked/refused/unsupported, which have evidence, and which are
candidates for future promotion*.

It is **state/governance infrastructure only**. It **summarizes** existing
sources; it does **not** execute capabilities, retry, classify failures, promote,
score, schedule, learn, generate workflows, mutate models, run
`SetParameterValue`, or integrate MCP/external systems. This is the state layer
that future retry, promotion, and controlled discovery loops will *consume* so
they no longer re-infer status from raw artifacts each time.

## Sources summarized

| Source | PR | Contributes |
| --- | --- | --- |
| Command Registry | #22 | Known command, classification/safety, `executable` seed for capabilities with a safe executor |
| Validation Registry | #24 | `validation_defined` seed, capability type/adapter, evidence expectations |
| Capability Runner bundles | #26 | Execution events from `artifacts/capability_runs/<cap>/<run_id>/{capability_result.json,pass_fail.json}` |
| Validation Evidence bundles | #25 | Validation events from `artifacts/validation_evidence/<name>/<run_id>/{validation_result.json,pass_fail.json}` |
| DiscoveryHarness candidates | #20 | `discovered` seed + candidate counts (from the SQLite `candidate_capabilities` table, when a db is supplied) |

A validation bundle whose `capability_name` is null (an *infrastructure*
validation such as `CommandRegistry`) is **not** a capability lifecycle event and
is skipped. Scanning raw `artifacts/discovery_runs/` CSVs directly is a
documented **future source** (kept out of scope).

## Data structures

- **`CapabilityStatus`** — lifecycle taxonomy: `discovered`, `defined`,
  `validation_defined`, `validation_passed`, `validation_failed`, `executable`,
  `execution_passed`, `execution_failed`, `blocked`, `refused`, `unsupported`,
  `denied`, `deprecated`.
- **`CapabilityHistoryEvent`** / **`CapabilityHistory`** — the ordered, observed
  events (execution + validation) for one capability, derived from evidence
  bundles.
- **`CapabilityState`** — the durable per-capability record (all required
  fields: identity, `current_status`, source, first/last seen, last
  validation/execution run ids, last evidence path, pass/fail/refused/blocked/
  unsupported counts, last error summary, `promotion_candidate`, metadata JSON).
- **`CapabilitySnapshot`** — a point-in-time view of all capability states with
  `names()`, `get()`, `status_counts()`, `to_dict()`.
- **`CapabilityStateRegistry`** — builds (`build_snapshot`, pure read),
  persists (`refresh`), and queries (`snapshot`, `load_snapshot`, `get_state`,
  `load_history`).

## Status derivation (deterministic)

For each capability the current status is chosen in strict priority order:

1. The **newest execution** event's outcome (`passed`→`execution_passed`,
   `failed`→`execution_failed`, `refused`/`blocked`/`unsupported`/`denied`→same).
2. Else the **newest validation** event's outcome
   (`passed`→`validation_passed`, `failed`→`validation_failed`, …).
3. Else the **definitional** seed: `executable` > `validation_defined` >
   `discovered` > `defined`.

`promotion_candidate` is a **non-binding** derived flag — true only when a
capability is validation-defined, is currently passing (`execution_passed` or
`validation_passed`), has ≥1 pass across the execution **or** validation
dimension, and has 0 failures in either dimension. (Counting both dimensions
keeps the `validation_passed` case reachable for capabilities with a passing
validation but no execution evidence yet.) It triggers no action; it exists for
a future promotion engine.

## Persistence

Reuses the existing SQLite/SQLAlchemy stack (no new database technology):

- `capability_states` — one upserted row per capability (keyed by
  `capability_name`); `first_seen_at` is preserved across refreshes.
- `capability_state_events` — the append-derived event history, rebuilt
  deterministically on each refresh (idempotent; never duplicated).

## CLI

```bash
axiom capability-state                        # list all capability states
axiom capability-state --name InventoryModel  # inspect one capability
axiom capability-state --json                 # machine-readable snapshot
axiom capability-state --refresh              # rebuild + persist into SQLite
```

Optional: `--db-path`, `--capability-runs-dir`, `--validation-evidence-dir`.

The command is **read-only** unless `--refresh` is given. In read-only mode it
loads persisted state when the db already contains it and otherwise builds an
in-memory snapshot — it never creates a database file. Unknown capability lookup
(`--name <unknown>`) prints a clear message and exits non-zero (`2`).

## Explicit non-goals

No retry execution, failure-classification engine, promotion engine, scoring,
autonomous loops, scheduling, learning, workflow generation, mutation allowance,
`SetParameterValue` execution, MCP, or Autodesk Assistant integration.
