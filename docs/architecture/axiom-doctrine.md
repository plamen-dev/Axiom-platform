# Axiom Doctrine

Foundational principles that govern how Axiom capabilities are designed,
built, and evolved.

## First-Principles Independence

Axiom must not depend on hidden prompts, private APIs, reverse engineering,
scraping, or proprietary implementation details of external AI systems.

Capabilities should be built from first principles and public software
engineering concepts.

## Governance by Default

Capabilities are governed by registries, not implicit assumptions. Every
capability has a known classification, safety level, and evidence requirement
before it is allowed to execute.

## Evidence Before Trust

No capability becomes trusted without durable evidence. Evidence bundles
are immutable artifacts that prove a capability behaves as declared.

## Explicit Promotion Only

Promotion from candidate to trusted is always an explicit human action.
No autonomous promotion. No implicit trust escalation.

## No State Mutation Without Declaration

Any operation that modifies external state (Revit models, files, databases)
must be declared as a mutation capability and governed accordingly.
Read-only operations are the default.

## Separation of Concerns

- Agents coordinate.
- Capabilities execute deterministic work.
- Product adapters connect to external software.
- Services contain low-level implementation details.
- Registries hold metadata and governance policy.
