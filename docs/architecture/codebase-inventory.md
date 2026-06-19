# Codebase Inventory and Symbol Registry v1

## Purpose

Read-only registry of repo structure: files, modules, classes, functions,
CLI commands, tests, docs, and architecture docs. Axiom uses this to
understand its own codebase before planning code changes.

## Components

- **CodebaseInventory** — scans a local repo using `ast` + `pathlib`
- **CodeSymbolRegistry** — persists scan results in SQLite
- **CodeFileRecord** — a file in the codebase (path, category, module, lines)
- **CodeSymbol** — a symbol (class, function, CLI command, enum, constant)
- **CodeSurface** — summary of the codebase surface area
- **TestCoverageReference** — link between a test file and the module it tests

## File Categories

source, test, cli, architecture_doc, runbook, log_doc, config, artifact, other

## Symbol Kinds

class, function, cli_command, enum, constant, module

## CLI

```bash
axiom code-inventory --refresh          # rescan repo
axiom code-inventory --json             # list files as JSON
axiom code-symbols                      # list all symbols
axiom code-symbol --name <symbol>       # lookup by name
```

## Non-Goals

- No static analysis engine beyond basic symbol inventory
- No code generation
- No refactoring
- No execution
