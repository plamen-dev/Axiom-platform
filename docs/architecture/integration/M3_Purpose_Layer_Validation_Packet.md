# M3 Validation Packet — Purpose & Layer Index (Semantic Self-Knowledge)

Milestone: M3 (`40_Open_Investigations.md` INV-05) · Role: **hooks + test matrix** (does not delay M4)
Prior evidence: PR #144 Self-Model Gap Analysis — PURP-001
Source hierarchy: Program 0 directive (PR #144) → Operational Integration Plan / Integration
Dependency Graph → `10_Current_Strategic_Context.md`, `30_Architectural_Principles.md`,
`40_Open_Investigations.md` → current repository evidence.

## 1. Likely next PR title

**Integration PR — Purpose & Layer Index v1** (after M4)

## 2. The finding this packet preserves (structural ≠ semantic)

PR #144 gap **PURP-001** (`missing_purpose_or_layer_candidates`): **all 158 modules** are
flagged. Axiom has strong **structural** self-knowledge (imports, dependency graph from M1) but
weak **semantic** self-knowledge — for almost every module, *purpose, layer, intended use, and
consumer meaning are unresolved.* This is the "semantic weakness behind structural
self-knowledge" failure in `60_Reasoning_Quality_Assurance.md` (Observed Basis #9) and
`30_Architectural_Principles.md`'s tension between structural and semantic knowledge.

## 3. Three relationship types — must NOT be collapsed

Per the Semantic Discipline directive, M3 keeps these distinct (`30_Architectural_Principles.md`
P6-AP-02 do-not-collapse-graphs):

| Relationship | Definition | Source today | Owned by milestone |
|---|---|---|---|
| **Structural** | imports, dependency graph, module references | M1 self-model (`capability_knowledge_graph`, 275 edges) | M1 (done) |
| **Semantic** | purpose, layer, intended use, conceptual overlap | `capability_summary` fields (today mostly empty) | **M3 (this packet)** |
| **Executable** | producer/consumer flow that changes platform behavior | execution chain id flow | M4 |

M3 validates that **structural and semantic relationships are independently queryable** — e.g.
two modules can share a layer (semantic) with **no** import edge (structural), and vice versa.

## 4. Files / modules to inspect

| Module | Existing structure to reuse |
|---|---|
| `src/axiom_core/capability_summary.py` | `CapabilitySummary` fields **already exist**: `capability_id`, `capability_name`, `purpose`, `summary`, `architectural_significance` — only need population + a `layer` field/enum |
| `src/axiom_core/codebase_inventory.py` | M1 module inventory + docstrings = the population source |
| `src/axiom_core/capability_knowledge_graph.py` | structural graph to contrast against the semantic index |

## 5. Smallest implementation that validates the milestone

Populate `CapabilitySummary.purpose` / `summary` from each module's **docstring** for every
module in the self-model, and add a small `layer` enum reflecting the existing architecture
boundary (Agents coordinate · Capabilities execute · Product adapters connect · Services
implement · plus registry / execution-stage / infrastructure). **No new semantic framework** —
reuse `CapabilitySummary`; add one enum field.

## 6. Exact pass/fail criteria

| # | Criterion | Pass | Fail |
|---|---|---|---|
| P1 | Coverage | Every module in the self-model has a `CapabilitySummary` with **non-empty `purpose`** | Any module missing a summary (PURP-001 persists) |
| P2 | Layer queryable | `layer` is set per module and validates against the enum | Layer absent or free-text/unbounded |
| P3 | Structural vs semantic distinguishable | A query returns ≥1 module pair sharing a `layer` (semantic) with **no import edge** (structural) | The two relationship types cannot be separated |
| P4 | Semantic ≠ executable | Purpose/layer index does **not** assert producer/consumer flow (that remains M4's executable relationship) | Semantic index conflated with execution wiring |
| P5 | Determinism | Same repo → same purpose/layer index | Non-deterministic output |

## 7. Validation evidence expected from the implementation PR

- A count assertion: modules with non-empty `purpose` == module count in the self-model (158),
  i.e. PURP-001 cleared.
- A query test demonstrating P3 (same-layer, no-import pair) — proving structural and semantic
  relationships are separable.
- Full `pytest -q` green; `ruff` clean.

## 8. Relationship to M4 (why this does not block M4)

M4 proves **executable** relationships (id flow); M3 populates **semantic** relationships.
M4's import-edge proofs do not depend on purpose/layer being populated. No PR #144 evidence
shows M4 requires M3 first, so M4 proceeds first.

## 9. Unresolved questions (routed — NOT designed here)

| Question | Route |
|---|---|
| Full purpose/layer architecture & semantic schema | INV-05 / **Program 2** + **Program 6** |
| Canonical layer taxonomy (final enum membership) | **Program 6** (doctrine) |
| Conceptual-overlap / duplicate-concept detection | INV-06 (M5) / **Program 2** |
| Measuring semantic vs executable relationship density | INV-07 / **Program 7** |
