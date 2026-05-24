# Axiom PR Review Guide

How AI and human reviewers should evaluate pull requests against this repository.

---

## 1. Project Context

Axiom is a **capability-learning platform** — not a Revit-only automation tool.

- **Revit is Adapter 001** — the first product integration proving the platform architecture.
- **Current baseline:** `baseline-001-revit-2024-capability-platform`.
- **Revit 2027 compatibility work must not break the 2024 baseline.**
- Capabilities are product-agnostic in design; adapters connect them to specific software.

Key architecture docs:

- `docs/architecture/multi-platform-capability-intelligence.md`
- `docs/architecture/capability-design-pattern.md`
- `docs/architecture/revit-version-compatibility-strategy.md`

---

## 2. Review Priorities

Do not focus only on syntax. Prioritize these architectural checks:

### Architecture Boundaries

| Layer | Responsibility | Violation Example |
|-------|---------------|-------------------|
| **Agents** | Coordinate workflows | Agent directly calling Revit API |
| **Capabilities** | Execute discrete operations | Capability orchestrating other capabilities |
| **Adapters** | Connect to external software | Adapter containing business logic |
| **Core** | Product-agnostic orchestration | Core code importing `Autodesk.Revit` |

### Code Reuse

- Shared code must not be unnecessarily duplicated across version-specific projects.
- Version-specific build files (`.csproj`, `.sln`) should link to shared source, not copy it.
- If a change applies to all Revit versions, it belongs in the shared source tree (`Axiom.Core/`, `Axiom.RevitAddin/`), not in a version-specific project.

### Baseline Protection

- Version-specific build files must not mutate the Revit 2024 baseline project files.
- Changes to shared source must be validated against all supported versions.

---

## 3. Revit Compatibility Review Rules

### Version Matrix

| Revit Version | Runtime | Generation | Status |
|--------------|---------|------------|--------|
| **2024** | .NET Framework 4.8 | Baseline | Current target |
| **2025** | .NET 8 | Gen 2 | Planned |
| **2026** | .NET 8 | Gen 2 | Planned |
| **2027** | .NET 10 | Gen 3 | Adapter created |

### Architecture Rule

Separate thin adapters/build projects are preferred over duplicated capability logic. One shared source tree, multiple build targets.

### Version PR Checklist

For any Revit version compatibility PR, verify:

- [ ] `.addin` manifest points to correct `Addins\<version>\` folder
- [ ] Output path is separate from other versions
- [ ] `RevitAPI.dll` / `RevitAPIUI.dll` references point to the correct Revit version install path
- [ ] Dependencies (e.g., `Newtonsoft.Json.dll`) are copied to output or addins folder
- [ ] Deployment script targets the correct version folder
- [ ] No changes to the 2024 `.csproj`, `.sln`, or `.addin` files

---

## 4. Required Validation Categories

### Automated (must pass on every PR)

| Check | Command | Expected |
|-------|---------|----------|
| **pytest** | `python -m poetry run pytest --tb=no -q` | All tests pass |
| **test-grids** | `python -m poetry run axiom test-grids --mode simulate` | 31/31 |
| **test-levels** | `python -m poetry run axiom test-levels --mode simulate` | 18/18 |
| **inventory mock tests** | Included in pytest | All pass |
| **ruff** | `python -m poetry run ruff check src/ tests/` | 0 errors |

### Manual (where applicable)

| Check | When Required |
|-------|--------------|
| Revit startup validation | Any C# change or new `.addin` manifest |
| Prompt dialog opens | Any change to `PromptCommand.cs` or `AxiomPromptDialog.cs` |
| InventoryModel smoke test | Any change to `InventoryModelCapability.cs` or `ModelInventoryService.cs` |
| CreateGrids smoke test | Any change to `GridCapability.cs` or `GridCreationService.cs` |
| CreateLevels smoke test | Any change to `LevelCapability.cs` or `LevelCreationService.cs` |

---

## 5. Things Reviewers Should Flag

### Blocking Issues

- Silent behavior changes to CreateGrids, CreateLevels, or InventoryModel
- Duplicate capability logic across version-specific projects
- Wrong `.addin` manifest path (e.g., deploying to `Addins\2024\` instead of `Addins\2027\`)
- Wrong `RevitAPI.dll` version referenced in a `.csproj`
- Missing dependency copy-local behavior (DLLs not reaching the addins folder)
- C# code executing Revit API outside a valid Revit context or transaction
- Read-only capabilities (InventoryModel) accidentally modifying the model
- Prompt resolver keyword collisions between capabilities

### Non-Blocking Risks

- Missing telemetry/logging for new code paths
- New generated artifacts (Parquet, JSONL, SQLite) committed unintentionally
- Test coverage gaps for edge cases
- Documentation not updated to reflect code changes

---

## 6. PR Classification

Classify each PR to set review expectations:

| Type | Scope | Review Focus |
|------|-------|-------------|
| **Feature PR** | New capability, new CLI command, new infrastructure | Architecture boundaries, test coverage, baseline protection |
| **Compatibility PR** | New Revit version support, runtime migration | Version isolation, shared source linking, deployment paths |
| **Docs-only PR** | Architecture docs, runbooks, strategy docs | Accuracy, cross-references, no stale information |
| **Test/Harness PR** | New test cases, harness improvements, fixtures | Coverage gaps, no false positives, fixture schema alignment |
| **Bugfix PR** | Fixing confirmed bugs | Root cause analysis, regression test added, no side effects |

---

## 7. Review Output

Reviewers should produce a structured assessment:

### Required Outputs

| Category | Description |
|----------|-------------|
| **Blocking issues** | Must be fixed before merge. Cite specific file and line. |
| **Non-blocking risks** | Worth noting but not merge-blocking. Suggest follow-up. |
| **Validation gaps** | Tests or checks that should exist but don't. |
| **Recommended local tests** | Specific manual tests the author should run before merge. |
| **Merge recommendation** | One of: `Ready to merge`, `Merge after fixes`, `Needs rework`, `Needs discussion`. |

### Example Format

```
## Review: PR #N — <title>

### Blocking Issues
- None / [list with file:line references]

### Non-Blocking Risks
- None / [list]

### Validation Gaps
- None / [list]

### Recommended Local Tests
- [specific commands or manual steps]

### Merge Recommendation
Ready to merge / Merge after fixes / Needs rework / Needs discussion
```

---

## 8. Review Agent Instructions

Review agents (AI or human) evaluating Axiom PRs must:

1. **Read the PR review ledger** (`docs/logs/pr-review-ledger.md`) before reviewing.
2. **Respect Axiom Knowledge rules** — safety blocks, architecture boundaries, testing policy.
3. **Verify safety blocks** — whole-model InventoryModel, sample values, and full values must remain blocked.
4. **Check Revit 2024 baseline protection** — no changes to 2024 `.csproj`, `.sln`, or `.addin` files.
5. **Do not require full pytest after every small change** — use tiered testing per Axiom testing/capacity policy.
6. **Report blockers vs non-blockers clearly** — blocking issues must cite specific file and line.
7. **Do not make code changes in review-only mode** — review agents produce assessments, not commits.
