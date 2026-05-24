# Behavior Regression Runbook

## Philosophy

### Operational code = current behavior only

Capability source code (Python resolvers, C# capabilities, CLI commands) should represent the **current correct behavior**. Historical context — what used to happen, why it changed, what bug was fixed — does not belong in the operational code.

### Behavior history lives in ledgers and fixtures

Changes are recorded in:
- `docs/logs/behavior-change-ledger.md` — human-readable chronological record
- `tests/fixtures/behavior_regressions/` — machine-readable regression cases per capability

These files serve as durable evidence. They document the before/after of each behavior change with references to bugs, test cases, and artifacts.

### Old artifacts are evidence, not runtime logic

Previous test outputs, harness runs, and inventory JSON exports are learning data. They should be preserved in artifact directories but never imported into operational code paths. The artifact pipeline (`artifacts/model_inventory_runs/`) stores durable structured data. The `%LOCALAPPDATA%\Axiom\inventory_exports\` path is a temporary handoff location only.

### Regression tests prevent old bugs from returning

Each behavior change documented in the ledger should have at least one regression test that validates the **current** behavior. If the code is ever changed in a way that re-introduces the old behavior, the test fails.

### Repo artifacts are durable learning outputs

Parquet, SQLite, and JSONL files in `artifacts/` are persistent. They survive across sessions and can be queried, diffed, and compared across runs. They are the foundation for the capability learning loop.

---

## Structure

```
docs/logs/behavior-change-ledger.md              ← Chronological behavior history
tests/fixtures/behavior_regressions/
  create_grids_behavior_cases.yaml                ← Grid regression cases
  create_levels_behavior_cases.yaml               ← Level regression cases
  inventory_model_behavior_cases.yaml             ← Inventory regression cases
docs/logs/bug-validation-log.md                   ← Bug discovery/resolution log
```

---

## Behavior Change Ledger Format

Each entry in `behavior-change-ledger.md` includes:

| Field | Purpose |
|-------|---------|
| `behavior_id` | Unique ID (BHV-NNN) |
| `date` | When the behavior changed |
| `capability` | Which capability was affected |
| `observed_prompt` | The prompt that exposed the issue |
| `previous_behavior` | What happened before (the bug) |
| `expected_behavior` | What should happen |
| `current_behavior` | What happens now (the fix) |
| `status` | `pending` / `fixed` / `validated` |
| `related_bug_id` | Cross-reference to bug-validation-log.md |
| `related_test_case` | Harness and/or pytest test IDs |
| `related_artifact_path` | YAML fixtures, test outputs |
| `notes` | Implementation details |

---

## Regression Fixture Format

Each YAML file in `tests/fixtures/behavior_regressions/` contains a `cases` list:

```yaml
cases:
  - case_id: regression_example
    behavior_ref: BHV-001
    prompt: "the user prompt"
    previous_behavior: "what used to happen"
    expected_capability: CreateGrids
    expected_status: CLARIFICATION_NEEDED
    expected_success: false
    expected_message_contains:
      - "substring1"
      - "substring2"
    notes: "context"
```

These can be consumed by test harnesses or used for manual regression checks.

---

## When to Add a New Entry

Add a behavior-change-ledger entry when:
1. A prompt that previously resolved now returns CLARIFICATION_NEEDED (or vice versa)
2. A prompt that resolved to capability A now resolves to capability B
3. A capability's output format changes (e.g., dialog text, artifact structure)
4. A view restriction or execution context changes
5. A persistence or export behavior changes

Do **not** add entries for:
- Pure refactoring with no behavior change
- Documentation-only changes
- Build/deployment path changes (those go in the compatibility runbook)

---

## Validation Process

1. **Before changing prompt behavior:** Check the behavior-change-ledger for prior entries about the same prompt pattern. Understand why the current behavior was chosen.

2. **After changing prompt behavior:** Add a new BHV-NNN entry. Update or add regression fixture cases. Ensure at least one pytest or harness test covers the new behavior.

3. **Regression check:** Run the full test suite:
   ```bash
   python -m poetry run pytest
   python -m poetry run axiom test-grids --mode simulate
   python -m poetry run axiom test-levels --mode simulate
   ```

4. **Cross-reference:** If the behavior change fixes a bug, update `bug-validation-log.md` to reference the BHV-NNN entry.

---

## Related Documents

- `docs/logs/behavior-change-ledger.md` — The ledger itself
- `docs/logs/bug-validation-log.md` — Bug discovery and resolution log
- `docs/runbooks/model-inventory-runbook.md` — InventoryModel persistence pipeline
- `docs/runbooks/grid-learning-loop-runbook.md` — Grid capability evolution
- `docs/architecture/capability-design-pattern.md` — Capability architecture
