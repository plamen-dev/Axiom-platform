# Canonical Knowledge Base

| Field | Value |
|-------|-------|
| **Title** | Axiom Canonical Knowledge Base — Index and Source-of-Truth Rules |
| **Status** | Seeded (v1) — partial content; several sections marked "Source Needed" |
| **Owner / Responsible Program** | Program 6 — Knowledge, Constitution, and Doctrine (index custody); per-file owners listed below |
| **Last Updated** | 2026-06-23 |
| **Source / Provenance** | Seeded from repo evidence (`README.md`, `docs/architecture/axiom-doctrine.md`, `docs/logs/`, `docs/runbooks/`, `docs/architecture/integration/`) per PR #152 directive. |
| **Purpose** | Establish a stable, repo-resident, human-readable source of truth for current Axiom canonical organizational knowledge. |

## What this is

This directory is the **authoritative, repo-resident source of truth** for Axiom's
current canonical organizational knowledge — strategic context, organizational
state, architectural principles, open investigations, organizational
communications, and reasoning quality assurance.

It is repo-resident on purpose: the repository (not a chat thread) is the durable
authoritative location after this seed.

## What this is not

- It is **not** a doctrine rewrite. Foundational architectural doctrine already
  lives in [`docs/architecture/axiom-doctrine.md`](../architecture/axiom-doctrine.md);
  this base references it rather than duplicating it.
- It is **not** runtime code, configuration, or automation.
- It is **not** an artifact / evidence / recording / Devin-session store. Those
  remain under `artifacts/` and external systems.
- It is **not** a traceability ledger. Traceability records (PR/review/behavior
  ledgers under `docs/logs/`) stay separate from clean canonical source documents.

## Source-of-truth rules

1. The repo-resident files in this directory are the **authoritative source** of
   current Axiom canonical knowledge.
2. ChatGPT Library copies and chat summaries are **mirrors, references, or working
   context only** — not the durable source of truth after this seed.
3. Canonical updates happen through **PRs**, not silent chat-only edits.
4. **Stable filenames** — no `_v#` suffixes. Version, date, and status live inside
   each file's header, not in the filename.
5. Where exact canonical content is not yet available in the repo, files use a
   clearly marked **"Current Status / Source Needed"** placeholder rather than
   invented content. Missing content is routed as an open follow-up (see
   `40_Open_Investigations.md`).
6. **Canonical Impact Flags** may be logged and batched rather than forcing a
   standalone PR for every small flag.

## Mirror / reference rule

External mirrors (ChatGPT Library, chat exports) may copy from these files for
convenience, but must be treated as potentially stale. When a mirror and this
base disagree, **this base wins**.

## Traceability vs canonical-source distinction

- **Canonical source** (this directory): clean, current, durable statements of
  knowledge.
- **Traceability** (`docs/logs/behavior-change-ledger.md`, `pr-review-ledger.md`,
  `founders-evidence-log.md`, etc.): append-only historical records. Keep these
  out of the canonical source files; link to them where useful.

## Index

| File | Purpose | Owner / Responsible Program | Update Trigger |
|------|---------|-----------------------------|----------------|
| `00_Readme.md` | Index, source-of-truth rules, update policy | Program 6 | Structure or policy change |
| `10_Current_Strategic_Context.md` | Current strategic direction and boundaries | Program 0 — Vision and Strategy | Strategy change (Program 0) |
| `20_Current_Organizational_State.md` | Current state of programs, milestones, factory | Program 7 — Engineering Operations | Milestone / program-state change |
| `30_Architectural_Principles.md` | Pointer + summary of architectural doctrine | Program 6 (doctrine), Program 2 (engineering) | Doctrine change (Program 6) |
| `40_Open_Investigations.md` | Open investigations and routed follow-ups | Program 5 / Program 6 (by topic) | New/closed investigation |
| `50_Organizational_Communications.md` | Durable org communications and decisions | Program 0 / Program 7 | New durable comm/decision |
| `60_Reasoning_Quality_Assurance.md` | Reasoning QA: self-audit, reconciliation gates | Program 6 | QA-gate change |

## Update / review policy

Choose the lightest sufficient level:

- **Light update** — typo, link, header date/status. PR with trivial review.
- **Targeted review** — change to one file's substantive content. Reviewed by the
  responsible Program.
- **Full review** — change affecting strategy, doctrine, or cross-program
  boundaries. Reviewed by Program 0 and Program 6.
- **Batch-later canonical impact handling** — small Canonical Impact Flags may be
  recorded and batched into a periodic canonical-update PR rather than forcing a
  standalone PR per flag.

## Program ownership reference

Used throughout this base (override only with repo evidence):

- Program 0 — Vision and Strategy
- Program 1 — PR Execution Factory (owns PR execution and task-packet production, **not** the canonical knowledge base)
- Program 2 — Autonomous Engineering OS
- Program 3 — Operator Cockpit Design
- Program 4 — BIM Intelligence Platform
- Program 5 — Local Runner and Multi-Agent Infrastructure
- Program 6 — Knowledge, Constitution, and Doctrine
- Program 7 — Engineering Operations
