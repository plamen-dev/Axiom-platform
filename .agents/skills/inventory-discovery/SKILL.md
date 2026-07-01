---
name: inventory-discovery
description: Operate and verify the inventory/discovery domain — code inventory, self-model build, and the InventoryModel-based discovery loop. Use when testing code-inventory, self-model-build, or discovery-engine changes.
---

# Inventory / discovery

**status: scaffold** — populate sections the first time verified operational knowledge exists for this domain (same PR as the change; see `.agents/skills/README.md`).

## Domain

Discovery feeds the verification factory: InventoryModel is the base for category/parameter discovery; the codebase inventory feeds the self-model. Source: `src/axiom_core/codebase_inventory.py`, `self_model.py`, `src/axiom_core/inventory/`, `src/axiom_core/discovery/`, `controlled_discovery_loop.py`.

## Commands

- `axiom code-inventory --refresh`
- `axiom self-model-build [--json-output]`

## Registry pointers

- Discovery/validation artifacts must feed registries or promotion systems, not remain isolated run outputs.

## Verification checklists

- `self-model-build --json-output` on a populated repo must report `module_count > 0` and `import_edge_count > 0`; zero counts on a populated inventory indicate a consumption bug, not empty inventory (see BUG-019).

## Tests

Targeted: inventory/self-model test files under `tests/`. Full pytest only at PR checkpoints.

## Notes / gotchas

- Windows path separators: inventory paths must be POSIX-normalized (`.as_posix()`); `str(Path.relative_to(...))` produces backslashes on Windows and silently zeroes the self-model (BUG-019, fixed in PR #53). Regression test uses `PureWindowsPath` so Linux CI catches it.
- Full InventoryModel against a live model must be blocked/guarded, not run by default.
