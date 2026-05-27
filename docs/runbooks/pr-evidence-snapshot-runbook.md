# PR Evidence Snapshot Runbook

Capture durable PR review/evidence snapshots as repo-native artifacts.

## Why

GitHub PR pages and Devin session summaries are not durable records. This workflow captures PR metadata, validation results, and review evidence into versioned artifacts under `artifacts/pr_reviews/`.

## Quick Start

```bash
# 1. Save PR description to a local file
#    (copy-paste from GitHub PR page or Devin session summary)
cat > /tmp/pr9_summary.md << 'EOF'
## Summary
Fixed export path collision bug.

## Root Cause
Second-level timestamp precision caused overwrites.

## Changes
Added milliseconds + atomic counter to filename.

## Validation Results
278 exports, 0 duplicates, 6,444 definitions.

## Safety Notes
Direct full-model extraction remains blocked.
EOF

# 2. Create snapshot (with verification method)
axiom pr-snapshot \
  --pr 9 \
  --title "Export path collision fix" \
  --branch "devin/fix-export-collision" \
  --status merged \
  --merge-status "merged to main 2026-05-06" \
  --verification-method github_ui_manual \
  --status-source "Plamen verified GitHub PR #9 page" \
  --summary-file /tmp/pr9_summary.md \
  --source-url "https://github.com/plamen-hristov/Axiom-platform/pull/9"

# 3. Generate ledger entries
axiom evidence-update --from-pr-snapshot artifacts/pr_reviews/pr_0009
```

## Commands

### axiom pr-snapshot

Creates JSON + Markdown snapshot files.

**Required flags:**
- `--pr <number>` — PR number
- `--title <text>` — PR title
- `--branch <name>` — Branch name
- `--status <open|merged|closed|superseded>` — PR status

**Optional flags:**
- `--merge-status <text>` — Merge details (default: same as status)
- `--verification-method <method>` — How the status was verified (see below; default: `unverified`)
- `--status-source <text>` — Description of how status was determined
- `--summary-file <path>` — Markdown file with PR description
- `--validation-file <path>` — Validation results file (overrides parsed validation from summary)
- `--changed-files <path>` — Text file listing changed files
- `--commits-file <path>` — Text file listing commits
- `--source-url <url>` — GitHub/GitLab PR URL
- `--out <dir>` — Output directory (default: `artifacts/pr_reviews/pr_NNNN/`)

**Output:**
```
artifacts/pr_reviews/pr_0009/
  review_snapshot.json     # Machine-readable snapshot
  review_snapshot.md       # Human-readable snapshot
  changed_files.txt        # If --changed-files provided
  commits.txt              # If --commits-file provided
```

**Snapshot fields:**
pr_number, title, branch, status, merge_status, verification_method, status_source, summary, review_checklist, notes, root_cause, changes, what_did_not_change, validation_commands, validation_results, safety_notes, known_limitations, follow_up_tasks, artifact_paths, source_url, created_at.

### axiom evidence-update

Generates proposed ledger entries from a snapshot.

**Required:**
- `--from-pr-snapshot <dir>` — Path to snapshot directory

**Optional:**
- `--out <file>` — Write to file instead of stdout + snapshot dir
- `--apply` — Auto-append to ledger files (use with caution)

**Target ledger files:**
- `docs/logs/pr-review-ledger.md` — always generated
- `docs/logs/founders-evidence-log.md` — always generated
- `docs/logs/bug-validation-log.md` — only if root_cause present
- `docs/logs/behavior-change-ledger.md` — only if changes present

**Output:**
```
artifacts/pr_reviews/pr_0009/
  proposed_ledger_entries.md   # Copy-paste ready entries
```

## Status Verification

Every snapshot records how the PR status was verified. The `evidence-update` command qualifies status labels based on the verification method — it will **not** present "Merged" as a verified fact unless the method is authoritative.

### Verification Methods

| Method | Authoritative? | When to use |
|--------|---------------|-------------|
| `gh_cli` | Yes | Status confirmed via `gh pr view --json state,mergedAt` |
| `github_pr_api` | Yes | Status confirmed via GitHub PR API (e.g. `git_view_pr`) |
| `github_ui_manual` | Yes | Human manually verified from GitHub PR page |
| `git_inferred` | **No** | Git log/diff evidence only — branch present on main, but PR state not confirmed |
| `unverified` | **No** | Default — no verification performed |

### How Status Appears in Ledger Entries

| Method | Status = merged | Status = open |
|--------|-----------------|---------------|
| `gh_cli` | Merged (verified: gh_cli) | Open (verified: gh_cli) |
| `github_ui_manual` | Merged (verified: github_ui_manual) | Open (verified: github_ui_manual) |
| `git_inferred` | Code present on main (git-inferred; PR merge not verified) | Open (git-inferred; not verified from GitHub) |
| `unverified` | Merged (UNVERIFIED — status not confirmed from GitHub) | Open (unverified) |

### Why Git-Only Evidence Cannot Prove PR Merge State

Git evidence (`git log`, `git diff`, branch presence on `main`) can confirm that **code is present** on a branch. It **cannot** confirm:

- Whether a GitHub PR was merged, closed, or squash-merged
- Whether the merge was performed via the PR (vs. direct push to `main`)
- The actual PR state on GitHub (especially after squash merges, where the original branch commits may not appear in `main`'s history)
- Whether the PR was reverted after merge

Always use `gh pr view` or the GitHub PR API to verify PR state when possible. When not possible, use `--verification-method git_inferred` and the snapshot/evidence will be clearly labeled as unverified.

## Summary Section Parsing

When `--summary-file` is provided, the parser recognizes these Markdown headings:

| Heading | Maps to field |
|---------|---------------|
| `## Summary` | summary |
| `## Review` / `## Checklist` | review_checklist |
| `## Root Cause` | root_cause |
| `## Changes` | changes |
| `## What Did NOT Change` | what_did_not_change |
| `## Validation Results` / `## Live Validation` | validation_results |
| `## Validation Commands` / `## To Validate` | validation_commands |
| `## Safety` / `## Safety Notes` | safety_notes |
| `## Known Limitations` / `## Known Gaps` | known_limitations |
| `## Follow Up` / `## Next Steps` | follow_up_tasks |
| `## Artifacts` / `## Artifact Paths` | artifact_paths |
| `### Notes` | notes |

Unrecognized headings are ignored. Content under recognized headings is captured as-is.

## Workflow: Capture a Merged PR

```bash
# 1. Copy PR description from GitHub into a file
pbpaste > /tmp/pr_summary.md  # macOS
# or: xclip -o > /tmp/pr_summary.md  # Linux

# 2. Optionally capture changed files
git diff --name-only main...devin/fix-branch > /tmp/changed.txt

# 3. Optionally capture commits
git log --oneline main...devin/fix-branch > /tmp/commits.txt

# 4. Create snapshot (verified from GitHub)
axiom pr-snapshot \
  --pr 9 \
  --title "Export path collision fix" \
  --branch "devin/fix-export-collision" \
  --status merged \
  --verification-method github_ui_manual \
  --status-source "Verified from GitHub PR #9 page" \
  --summary-file /tmp/pr_summary.md \
  --changed-files /tmp/changed.txt \
  --commits-file /tmp/commits.txt \
  --source-url "https://github.com/plamen-hristov/Axiom-platform/pull/9"

# 5. Review proposed ledger entries
axiom evidence-update --from-pr-snapshot artifacts/pr_reviews/pr_0009

# 6. Edit proposed entries (assign EVID-NNN, BUG-NNN, BHV-NNN numbers)
# 7. Copy into the appropriate ledger files
# 8. Commit
```

## What This Is NOT

- Not a GitHub API integration (yet)
- Not an automated PR watcher
- Not a replacement for the ledger files themselves
- Does not modify extraction behavior or runtime code

## Future

- GitHub API integration to auto-fetch PR metadata
- Auto-assign EVID/BUG/BHV numbers from existing ledger state
- Pre-commit hook to remind about snapshot for merged PRs
