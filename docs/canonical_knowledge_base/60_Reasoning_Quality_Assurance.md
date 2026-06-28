# Reasoning Quality Assurance

| Field | Value |
|-------|-------|
| **Title** | Reasoning Quality Assurance |
| **Status** | Seeded (v1) — supported by existing repo skill/process evidence |
| **Owner / Responsible Program** | Program 6 — Knowledge, Constitution, and Doctrine |
| **Last Updated** | 2026-06-23 |
| **Source / Provenance** | `.agents/skills/testing-axiom-cli/SKILL.md` (PR #149/#150 gates); Axiom knowledge base notes "Axiom PR review and validation expectations", "Axiom testing and capacity policy". |
| **Purpose** | State the durable reasoning-quality gates that PRs and investigations must satisfy, so quality is enforced consistently rather than ad hoc. |

## Pre-review self-audit gate

Substantial PRs answer a pre-review self-audit before being marked review-ready.
The canonical, maintained checklist lives in
`.agents/skills/testing-axiom-cli/SKILL.md` (operational location). At minimum a
self-audit confirms: scope preserved, no unintended behavior change, safety
invariants intact, tests run, validation pending stated honestly, and risks named.

## Purpose-to-Workflow reconciliation gate

Before implementation, substantial PRs answer:

1. What existing PR/component/capability does this use?
2. What workflow does it participate in?
3. What consumes its output?
4. What evidence proves it works?
5. Disposition (integrated / support-only / validation hardening / compatibility
   hardening / canonical-source / unresolved / temporary)?
6. What existing structure was checked before adding anything new?
7. What complexity, indirection, duplicate-engine, or safety risk does this add?
8. What should be deleted, merged, preserved, or left alone?

The intent is to prevent duplicate engines, duplicate doctrine, and orphaned work.

## PR review expectations

Every substantial Axiom PR should identify: what changed; what behavior changed;
what did not change; tests run; validation still pending; known risks; whether
Revit live validation is required; whether the 2024 baseline is affected; and
whether the PR strengthens the verification factory, trusted primitive library,
evidence quality, failure/retry classification, promotion scoring, or a named
workflow proof.

## Testing / capacity policy (tiered)

Match validation to change scope (per "Axiom testing and capacity policy"):

- **Docs/log-only:** do not run full pytest; report "tests not run — docs/logs only".
- **Python module-only:** run targeted tests + ruff on changed files.
- **C# add-in:** prefer dotnet build/deploy validation.
- **Cross-cutting / pre-merge checkpoint:** run full pytest + ruff (+ grid/level
  validation where relevant).

After each session, report: tests run, tests intentionally skipped, reason, and
remaining validation required.

## Anti-fabrication rule

Do not fabricate canonical content from memory. Use repo evidence or explicitly
provided source context; where exact content is unavailable, use a clearly marked
placeholder and route the gap as a follow-up (see `40_Open_Investigations.md`).

## Update rule

Changes to these gates are Program 6 decisions. The operational checklists in
`.agents/skills/` remain the executable copy; this file is the canonical statement
of intent and must not drift from them.
