# Current Strategic Context

| Field | Value |
|-------|-------|
| **Title** | Current Strategic Context |
| **Status** | Seeded (v1) — supported by repo evidence and Axiom knowledge base; strategic narrative beyond what is below is **Source Needed** from Program 0 |
| **Owner / Responsible Program** | Program 0 — Vision and Strategy |
| **Last Updated** | 2026-06-23 |
| **Source / Provenance** | `README.md`; Axiom knowledge base notes "Axiom long-term capability intelligence direction", "Axiom-platform project boundaries and repo rules", "Axiom PR review and validation expectations". |
| **Purpose** | State the current strategic anchor so PRs and programs can be judged against a single, durable direction. |

## Strategic anchor

Axiom is **not** a generic Revit AI assistant, chatbot, or saved-prompt system.
Axiom is a **self-improving BIM workflow generation and validation engine**.

- The value is not generic workflows by themselves. The value is the machine that
  industrializes workflow **discovery, primitive validation, retry, evidence,
  promotion, and trust generation**.
- Generic workflows (Excel-to-rooms, device placement, parameter editing, view/
  schedule creation, exports) are workflow **content**, not the moat.
- The moat is the **discovery and validation factory** (the "Verification
  Factory") that generates, tests, scores, and promotes trusted BIM workflow
  primitives faster than manual coding, Dynamo, consultants, or generic
  assistants.

## Beachhead and adapters

- **Revit is Adapter 001** and the first proving ground — not the end state.
- The current baseline is `baseline-001-revit-2024-capability-platform`.
- Other product adapters are **not** implemented unless explicitly instructed.
- Product-agnostic layers should avoid Revit-only naming where a generalized
  concept is clearly intended.

## Immediate bottleneck

Autonomous **verification throughput**, not workflow ideation. Axiom has enough
workflow ideas; the priority is making the discovery/validation loop spin
repeatedly with minimal human intervention.

## First strategic loop

Category / Parameter / Primitive **Discovery and Validation**.

- `InventoryModel` is the foundation of this loop and is expanding into the
  Discovery Engine (not a one-off reporting tool).
- `SetParameterValue` is the first Primitive Action Validation candidate.

## How PRs are judged against this direction

Preferred PR types (per "Axiom PR review and validation expectations"):

1. Discovery loop improvements
2. Primitive validation improvements
3. Failure classifier / retry improvements
4. Evidence artifact improvements
5. Promotion score / trusted pattern registry improvements
6. Named workflow proof tied to the factory
7. Revit live validation of a trusted primitive

Avoid PRs that only add generic demo workflows unless they explicitly strengthen
the verification factory or validate a reusable primitive.

## Boundaries

- Axiom-platform is **separate** from Capital Engineering. Do not use
  Capital-specific terminology, branding, paths, or business context in this repo.
- Keep Axiom independent / local-first for now. Do not start Autodesk Assistant /
  MCP integration unless explicitly requested.

## Current Status / Source Needed

The detailed Program 0 strategic statement (market framing, sequencing of
programs, success metrics, time horizons) is **not fully repo-resident**. This
file captures the durable anchor supportable from current repo evidence and the
knowledge base. The fuller strategic narrative should be supplied by Program 0
and added here via PR. Tracked in `40_Open_Investigations.md`.
