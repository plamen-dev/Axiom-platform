# Integration Validation Packets — Index (PR #145)

Status: Planning deliverable (v1)
Owner routing: Program 0 (sequencing) · Program 2 (architecture) · Program 7 (reasoning QA)
Prior evidence: Integration PR #143 (Self-Model Population, merged), Integration PR #144 (Self-Model Gap Analysis, merge-ready, PR #34)

## Purpose

These three packets convert PR #144's **negative discovery** (what is disconnected, unwired,
or unexplained) into **narrow, implementation-ready validation targets** for the next
executable PRs. They are validation packets, not implementations and not a new architecture
cycle. Each packet is judged by a single test:

> PR #146+ can begin from the packet without redoing discovery.

They define *what to inspect, what to wire, and exactly how to validate* — not new frameworks.
All re-architecture questions (full Execution Graph Synthesizer, Organizational State schema,
promotion doctrine, semantic architecture) are routed to open investigations / owner programs,
**not designed here** (per `30_Architectural_Principles.md` P6-AP-01 evidence-gating and
`60_Reasoning_Quality_Assurance.md` P7-RQA-05 integration-before-proliferation).

## Packets

| Packet | Milestone | Open investigation | Next executable PR (proposed) | Role |
|---|---|---|---|---|
| [M4 — Execution Chain Validation](./M4_Execution_Chain_Validation_Packet.md) | M4 — One capability through full execution chain | INV-03 | Integration PR #146 — Execution Chain Orchestrator v1 | **Next executable target** |
| [M2 — Evidence→Promotion Validation](./M2_Evidence_Promotion_Validation_Packet.md) | M2 — Evidence to promotion loop | INV-04 | Integration PR — Evidence-to-State Loop v1 | Hooks + test matrix |
| [M3 — Purpose & Layer Validation](./M3_Purpose_Layer_Validation_Packet.md) | M3 — Purpose and layer index | INV-05 | Integration PR — Purpose & Layer Index v1 | Hooks + test matrix |

## Priority guardrail

**M4 remains the next executable implementation target.** M2 and M3 are represented as hooks
and test matrices, not as reasons to delay M4. PR #144 evidence makes the M4 case stronger,
not weaker: all five execution-chain transitions exist as modules yet carry **zero import
edges** — the chain is nominal, not executable. Nothing in PR #144 shows M4 cannot be
validated without M2/M3 first, so M4 proceeds first.

## PR #144 evidence used by these packets

Re-run of PR #144's gap analyzer against **current `main`** (which includes PR #142,
`execution_report.py`, merged as `dc99c70`):

| Metric | Value |
|---|---|
| Modules in self-model | 158 |
| Import edges | 275 |
| Isolated modules | 9 |
| Total gaps | 16 across all 9 categories |
| `declared_but_unwired_chains` | 5 (all execution-chain transitions, "no import edge in either direction") |
| `artifact_or_evidence_producers_without_consumers` | EVID-001 (`model_health`) → M2 |
| `missing_purpose_or_layer_candidates` | PURP-001 (all 158 modules) → M3 |
| `recommended_integration_candidates` | REC-002 (wire execution chain) ranks the M4 target |

Note on CHAIN-005 / `ExecutionArtifact → ExecutionReport`: PR #144's original run (branch cut
before PR #142 merged) flagged this transition as *"stage module not present"*. Re-run on
current `main` (with `execution_report.py` present) flags it as *"no import edge in either
direction"* — identical in kind to the other four. This branch-timing artifact is resolved:
M4 treats `ExecutionReport` as the real terminal stage.

## Canonical source status (reference rule only — no migration in PR #145)

Per the Canonical Filename and Versioning addendum, these packets cross-reference canonical
documents by their **stable** filenames:

- `00_Readme.md`
- `10_Current_Strategic_Context.md`
- `20_Current_Organizational_State.md`
- `30_Architectural_Principles.md`
- `40_Open_Investigations.md`
- `50_Organizational_Communications.md`
- `60_Reasoning_Quality_Assurance.md`

Source-structure observations (reported, **not** acted on in PR #145):

1. These canonical documents are **not yet committed to this repo**. They exist in the
   Canonical Knowledge Base supplied to this task. Cross-references use stable filenames so
   they resolve once the canonical set is committed.
2. The supplied copies carry **version suffixes** (`10_..._v2.md`, `20_..._v3.md`,
   `30_..._v3.md`, `40_..._v1.md`, `60_..._v2.md`) plus `_review_traceability.md` mirrors.
   Per the addendum, versioned filenames are acceptable only for review/draft/traceability
   artifacts; repo-native canonical sources should use stable names with version info in the
   header.

Canonical filename migration is **explicitly out of scope for PR #145** (reference rule only).
No "Unresolved Source Reference" remains — all referenced canonical documents were supplied.
