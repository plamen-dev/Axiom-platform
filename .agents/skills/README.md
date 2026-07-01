# Axiom skills policy

`.agents/skills/` is the single discoverable root for **operational skills**: knowledge for an agent (Devin or otherwise) working *on* Axiom — how to test, build, deploy, record evidence, and run each domain. One directory per domain/engine, each containing a `SKILL.md` with YAML frontmatter (`name`, `description`). The frontmatter descriptions are the index; there is no separate catalog to maintain.

## What belongs where (data flows where it belongs)

| Data | Home |
|------|------|
| How to operate/test/verify a domain (commands, checklists, gotchas) | that domain's `SKILL.md` here |
| What a capability can do, its trust/confidence/readiness | registries (`command_registry`, capability confidence, knowledge graph) — never duplicated into skills |
| Historical behavior, bugs, before/after | `docs/logs/` ledgers and regression fixtures |
| Run outputs and proof objects | `artifacts/` (evidence bundles, validation runs) |

Skills **reference** registries as the source of truth; they never hardcode counts or state (assert shape, not numbers).

## Structure conventions

Every `SKILL.md` uses these standard sections so the content is scannable by tooling (e.g. a future Atlas per-domain view showing skills, parameters, checklists, and tests for each bubble):

1. frontmatter: `name`, `description` (when to invoke)
2. `## Domain` — what this skill covers, key source paths
3. `## Commands` — the CLI/actions this domain exposes
4. `## Registry pointers` — where the authoritative state lives
5. `## Verification checklists` — how to prove the domain works
6. `## Tests` — targeted test files + tiering notes
7. `## Notes / gotchas` — verified operational lessons only

Scaffolded skills (domains without operational content yet) keep the same sections with a `status: scaffold` marker in the body; populate them the first time real operational knowledge is verified.

## Lifecycle rule (same-PR skill updates)

**Any PR that changes how a domain is operated, tested, or verified must update that domain's `SKILL.md` in the same PR, populated at the end of the work (after verification, before marking the PR ready for review).** Do not ship operational changes and file a separate one-off skill PR afterwards. A new domain gets its skill directory in the PR that introduces it.

Only write verified knowledge: commands actually run, behaviors actually observed. No speculative instructions.
