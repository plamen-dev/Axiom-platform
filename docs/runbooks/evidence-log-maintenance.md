# Evidence Log Maintenance Runbook

## Purpose

The Founder's Evidence Log captures chronological proof of development effort on Axiom-platform. It serves as an auditable record for investors, partners, IP documentation, and internal retrospectives.

## Source Documents

Evidence is reconstructed from:

| Source | Location | Type |
|--------|----------|------|
| Git commit history | `git log --all --format=...` | Primary |
| PR review ledger | `docs/logs/pr-review-ledger.md` | Primary |
| Bug validation log | `docs/logs/bug-validation-log.md` | Primary |
| Behavior change ledger | `docs/logs/behavior-change-ledger.md` | Primary (on PR branches) |
| Test run artifacts | `artifacts/grid_test_runs/`, `artifacts/level_test_runs/`, `artifacts/model_inventory_runs/` | Secondary |
| Validation run artifacts | `artifacts/validation_runs/` | Secondary |
| PR descriptions | GitHub PR #1–#6 | Secondary |
| Architecture docs | `docs/architecture/` | Tertiary |
| Runbooks | `docs/runbooks/` | Tertiary |

## File Locations

| File | Purpose |
|------|---------|
| `docs/logs/founders-evidence-log.md` | Chronological work entries |
| `docs/logs/founders-evidence-source-index.md` | Maps evidence sources to log entries |
| `docs/runbooks/evidence-log-maintenance.md` | This file — maintenance process |

## Entry Format

Each evidence log entry follows this structure:

```markdown
### EVID-NNN: <Short description>

- **Date:** YYYY-MM-DD
- **Workstream:** <workstream name>
- **Work performed:** <description>
- **Evidence source:** <commit hash, PR number, artifact path>
- **Estimated hours:** <number or TBD>
- **Related PR/branch/commit:** <reference>
- **Validation artifact:** <path or N/A>
```

## Workstream Categories

| Code | Workstream |
|------|-----------|
| FOUNDATION | Core schemas, CLI, orchestrator, MCP layer |
| PERSISTENCE | SQLite, storage layers, WAL mode |
| VERTICAL-SLICE | Full prompt-to-capability pipeline |
| CAPABILITY | Individual capability implementation (CreateGrids, CreateLevels, InventoryModel) |
| REVIT-COMPAT | Revit version compatibility (2024/2027) |
| INVENTORY | Model inventory, schema discovery, registry building |
| SAFETY | Crash prevention, blocked commands, staged extraction |
| TESTING | Test harnesses, fixtures, validation runs |
| INFRA | Local runner, deploy scripts, tooling |
| DOCS | Architecture docs, runbooks, review guides |

## Maintenance Cadence

1. **Per PR:** Add entries for significant work items when a PR is created or merged.
2. **Per session:** At end of each Devin session, reconstruct entries from commits pushed.
3. **Weekly:** Review log for completeness and update source index.
4. **Before investor/partner meetings:** Verify log covers all recent work.

## How to Reconstruct Entries

```bash
# List all commits with dates
git log --all --format="%h|%ai|%an|%s" --reverse

# List commits in a specific date range
git log --after="2026-05-18" --before="2026-05-20" --format="%h|%ai|%s"

# List commits on a specific branch
git log main..revit-2027-compatibility --format="%h|%ai|%s" --reverse

# Find artifact directories created on a date
find artifacts/ -maxdepth 3 -name "*.json" -newer /tmp/dateref
```

## Rules

1. Do not invent exact hours. Mark uncertain estimates as TBD.
2. Do not modify runtime code in this process.
3. Each entry must have at least one evidence source (commit, PR, or artifact).
4. Group related commits into single entries when they form a logical unit of work.
5. Keep the source index current — every log entry must appear in the index.
