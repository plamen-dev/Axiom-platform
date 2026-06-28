# Architectural Principles

| Field | Value |
|-------|-------|
| **Title** | Architectural Principles |
| **Status** | Seeded (v1) — pointer + summary of existing doctrine; **not** a doctrine rewrite |
| **Owner / Responsible Program** | Program 6 — Knowledge, Constitution, and Doctrine (doctrine); Program 2 — Autonomous Engineering OS (engineering application) |
| **Last Updated** | 2026-06-23 |
| **Source / Provenance** | [`docs/architecture/axiom-doctrine.md`](../architecture/axiom-doctrine.md); Axiom knowledge base notes "Axiom architecture boundaries", "Axiom-platform project boundaries and repo rules". |
| **Purpose** | Point to the authoritative architectural doctrine and summarize the durable boundary rules, without duplicating doctrine text. |

## Authoritative doctrine location

The foundational architectural doctrine is **already repo-resident** at
[`docs/architecture/axiom-doctrine.md`](../architecture/axiom-doctrine.md). That
file remains authoritative for foundational principles. This file references and
summarizes it; it does **not** restate or fork it.

Doctrine, as stated there, covers: First-Principles Independence, Governance by
Default, Evidence Before Trust, Explicit Promotion Only, No State Mutation Without
Declaration, and Separation of Concerns.

## Architecture boundary rules (summary)

From the doctrine and the architecture-boundary knowledge:

- **Agents coordinate.**
- **Capabilities execute** deterministic work. They are registered executable
  units; agents route/coordinate them.
- **Product adapters** connect Axiom to external software (Revit = Adapter 001).
- **Services** contain low-level product/API implementation details.
- **Registries** hold capability metadata and governance policy.
- Product-specific concepts should not become universal core names unless
  genuinely generalized.
- Operational code contains **current behavior only**; historical behavior,
  failures, and before/after logic belong in `docs/logs/` and regression
  fixtures, not scattered through runtime code.
- Discovery and validation artifacts must **feed registries or promotion
  systems**, not remain isolated run outputs.

## Verification Factory ordering

The architecture prioritizes the verification factory loop:

1. Discover object/category/parameter/function behavior.
2. Validate primitives in controlled contexts.
3. Classify failures.
4. Retry known alternate strategies up to a bounded limit.
5. Produce evidence.
6. Assign promotion score.
7. Store trusted patterns for reuse.

## Standing constraints

- Do not add discipline agents unless explicitly instructed.
- Do not move capability ownership into `OrchestratorAgent` / `ExecutionAgent`.
- Do not duplicate capability logic across Revit versions unless the API forces
  it; prefer shared source with thin version-specific build/deploy adapters.
- Avoid broad conceptual expansion unless it directly supports the verification
  factory, trusted primitive library, evidence quality, failure/retry
  classification, promotion scoring, or a named workflow proof.

## Update rule

Substantive changes to architectural **doctrine** are made in
`docs/architecture/axiom-doctrine.md` under Program 6 review; this summary is then
updated to match. Do not let the summary drift from the doctrine source.
