# Validation Report — InventoryModel Parameter Discovery Enrichment (PR #21)

**Scope:** Devin-side validation with a synthetic/representative enriched export.
**Read-only:** export + discovery interpretation only. No mutation, no candidate
execution, no learning/promotion/scoring.

Live validation inside Revit 2027 (real model) is the AXIOM-01 step and is not
covered here.

## What was validated

1. The enriched InventoryModel parameter export (`parameters.parquet` +
   `parameters.csv` + `parameters.jsonl`) carries the full value contract,
   identity/join, ownership and provenance fields.
2. The stable join contract: `parameters.element_id == elements.element_id`.
3. DiscoveryHarness consumes the enriched export and reaches
   **Discovery complete: YES** with parameters and candidates > 0.
4. Value contract enforced: a writable `Double` is safely settable **only** with
   unit metadata; a bare `Double` is not.

## Inputs

Synthetic run of 3 elements (2 Walls instance/type, 1 Door), 6 parameters
spanning String / Double-with-units / Double-without-units / ElementId, instance
and type.

## Result

| Metric | Value |
| --- | --- |
| Object source | elements.jsonl |
| Parameter source | parameters.parquet |
| Parameter rows total | 6 |
| Parameter rows joined | 6 |
| Categories discovered | 2 |
| Parameters discovered | 6 |
| Writable parameters | 6 |
| Instance / Type parameters | 5 / 1 |
| Safely-settable parameters | 5 (bare Double excluded) |
| Candidate capabilities generated | 6 |
| **Discovery complete** | **YES** |

The bare Double ("Mystery Number", no spec/unit) is correctly **not**
safely-settable, while the unit-bearing Double ("Unconnected Height",
length/millimeters) is — demonstrating the value contract.

## Evidence files

- `validation_results.json` — full metrics + exported parameter schema columns.
- `discovery_parameters.csv` — per-parameter value contract (DiscoveryHarness output).
- `discovery_candidate_capabilities.csv` — generated SetParameterValue candidates.

## Reproduce

```bash
axiom discovery-run --adapter revit \
  --inventory-export-path artifacts/model_inventory_runs/<enriched_run> \
  --db-path discovery.db
```

Against a folder whose `parameters.parquet` was written by the enriched
`write_parameters_parquet` (PR #21), discovery reports parameters + candidates and
`Discovery complete: YES`.
