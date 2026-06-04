# Capability Validation Registry (PR #23)

## Objective

PR #19 established **execution**, PR #20 established **discovery**, PR #21
established **parameter discovery contracts**, and PR #22 established **command
governance**. The next missing component is **validation governance**.

Axiom can now discover candidate capabilities, but it has no standardized way to
*define, classify, and (eventually) execute* validation procedures. The
Capability Validation Registry is the source of truth that describes, for every
capability:

- **how** it is validated (the procedure),
- **what evidence** is required,
- **how pass/fail is determined**,
- **when retries are allowed**, and
- **when a capability becomes promotion-eligible**.

This is **governance/validation infrastructure only**. It does not execute,
schedule, score, promote, or learn. It is the policy layer that future
autonomous validation loops will consume.

## Architecture fit

```
Discovery (PR #20/#21)  →  candidate capabilities
                                  │
                                  ▼
        Capability Validation Registry (PR #23)  ← this layer
          "how is each capability validated?"
                                  │
                                  ▼
   future validation loop (out of scope)  →  execute → evidence → promote
```

The registry is a pure, read-only metadata layer (mirroring the Runner Command
Registry of PR #22). It introduces no new database technology — optional
persistence reuses the existing SQLite stack (`axiom_core.database` + the shared
SQLAlchemy `Base`).

- Module: `src/axiom_core/validation/validation_registry.py`
- Persistence: `src/axiom_core/validation/persistence.py`
- CLI: `axiom validation-registry` (`src/axiom_cli/main.py`)
- ORM row: `ValidationProcedureRow` (`src/axiom_core/models.py`,
  table `validation_procedures`)

**Unknown capabilities are denied by default**: `is_known(name)` returns `False`
for anything not explicitly cataloged, and the CLI exits `2` for an unknown
`--name`.

## Named types (glossary)

| Type | Role |
|------|------|
| `CapabilityValidationRegistry` | The governed catalog as an object: `list_procedures` / `get` / `is_known` / `by_capability_type` / `by_adapter` / `validate`. A `DEFAULT_REGISTRY` instance is built from the seed catalog; module-level functions delegate to it. |
| `ValidationProcedure` | The per-capability validation definition (identity + procedure + inputs + evidence + criteria + retry + promotion). |
| `ValidationEvidence` | The evidence contract: `required_artifacts`, `required_logs`, `required_checkpoints` (each a tuple of `EvidenceItem`). |
| `EvidenceItem` | A single required piece of evidence: `kind` (`EvidenceKind`), `name`, `required`. |
| `ValidationResult` | The record a future loop produces for one attempt (`status`, conditions met, failure condition, evidence refs, attempts). Defaults to `UNTESTED` — PR #23 ships no executor. |
| `RetryPolicy` | `max_retries`, `retry_delay_seconds`, `retry_conditions`; `should_retry(condition)` is a pure predicate. |
| `PromotionEligibility` | `minimum_successes`, `minimum_evidence_sets`, `required_confidence`; `is_eligible(...)` is a pure predicate that evaluates the contract — **not** a promotion engine. |

Supporting enums: `CapabilityType` (inventory / discovery / mutation / bridge /
creation), `EnvironmentRequirement` (`requires_revit`, `requires_model_open`,
`requires_test_model`, `requires_runner`, plus `poetry_env`,
`requires_inventory_export`, `requires_db_path`), `EvidenceKind`
(artifact / log / checkpoint / state), `PassCondition`, `FailureCondition`,
`ValidationStatus`.

## Validation definition model

Each capability supports the full contract requested for PR #23:

- **Identity** — `capability_name`, `capability_type`, `adapter`, `version`.
- **Validation procedure** — `validation_procedure_id`, `validation_name`,
  `validation_description`, `steps`.
- **Inputs** — `required_inputs`, `optional_inputs`,
  `environment_requirements` (e.g. `requires_revit`, `requires_model_open`,
  `requires_test_model`, `requires_runner`).
- **Evidence requirements** — `required_artifacts`, `required_logs`,
  `required_checkpoints` (e.g. `request.json`, `response.json`, `before_state`,
  `after_state`, `pass_fail.json`).
- **Pass criteria** — `pass_conditions` (e.g. `parameter_value_matches`,
  `element_created`, `element_count_matches`).
- **Failure criteria** — `failure_conditions` (e.g. `exception`, `timeout`,
  `incorrect_result`, `missing_evidence`).
- **Retry policy** — `max_retries`, `retry_delay`, `retry_conditions`.
- **Promotion eligibility** — `minimum_successes`, `minimum_evidence_sets`,
  `required_confidence`. **Contract only — promotion is not implemented.**

## Seed validation definitions

| Capability | Type | Pass conditions | Notes |
|-----------|------|-----------------|-------|
| `InventoryModel` | inventory | `artifacts_exist`, `row_counts_positive` | Summary-mode emits zero parameters by design; `row_counts_positive` requires a parameter-collecting scan. |
| `DiscoveryHarness` | discovery | `categories_discovered`, `parameters_discovered`, `candidates_generated`, `discovery_complete` | Read-only over an export; deterministic (no retries). |
| `SetParameterValue` | mutation | `parameter_value_matches` | **Definition only — not executed.** Requires a disposable/sample test model; higher promotion bar. |
| `BridgeExecute` | bridge | `result_received`, `checkpoints_present`, `evidence_bundle_present` | Requires runner + Revit; pipe-unavailable/timeout are the retryable transient failures. |

### Procedures

- **InventoryModel** — Execute → Export inventory → Verify artifacts exist →
  Verify row counts > 0 → Generate evidence.
- **DiscoveryHarness** — Run discovery → Verify categories discovered → Verify
  parameters discovered → Verify candidates generated → Verify
  `discovery_complete`.
- **SetParameterValue** *(definition only)* — Create test element → Read value →
  Write value → Read value → Compare → Generate evidence.
- **BridgeExecute** — Send request → Receive result → Verify checkpoints →
  Verify evidence bundle.

## CLI

```bash
axiom validation-registry                         # list all definitions
axiom validation-registry --type mutation         # filter by capability type
axiom validation-registry --name InventoryModel   # inspect one capability
axiom validation-registry --json                  # machine-readable catalog
axiom validation-registry --persist --db-path validation.db   # persist definitions
```

Unknown capabilities are denied by default (exit code `2`). The `--persist`
option writes the definitions into the `validation_procedures` SQLite table; it
persists **definitions only** and executes nothing.

## Persistence

The registry is fully usable in-memory. When persistence is requested, each
definition is upserted (keyed by `capability_name`) into the
`validation_procedures` table. List/enum/nested fields are stored as JSON text,
mirroring the existing JSON-column pattern used by the discovery and inventory
registries. No new database technology is introduced.

## How this becomes the execution policy layer

A future (out-of-scope) autonomous validation loop would:

1. Pull a candidate capability from discovery.
2. Look up its `ValidationProcedure` here (denied if unknown).
3. Check `environment_requirements` against the live context.
4. Execute the `steps`, collecting the declared `ValidationEvidence`.
5. Evaluate `pass_conditions` / `failure_conditions` to produce a
   `ValidationResult`.
6. Consult `RetryPolicy.should_retry(...)` on failure.
7. Accumulate successes/evidence and consult
   `PromotionEligibility.is_eligible(...)` — **the registry only states the
   contract; the loop and any promotion engine are future work.**

## Scope / non-goals (PR #23)

In scope: schema, seed catalog, classification, evidence/retry/promotion
*contracts*, SQLite persistence of definitions, a read-only CLI, docs, tests.

Explicitly **out of scope**: autonomous execution, scheduling, a promotion
engine, scoring logic, learning loops, and workflow generation. The 2024
baseline is unaffected; no live Revit validation is required for this PR (the
registry is pure metadata).
