# Axiom Local Runner Runbook

## Purpose

The Axiom Local Runner provides a restricted local execution harness so agents and developers can request controlled local actions, capture logs/artifacts, and inspect results without arbitrary shell access.

This is **infrastructure tooling**, not Revit product functionality. It does not modify CreateGrids, CreateLevels, or InventoryModel behavior.

## Security Model

- **No arbitrary shell commands.** Only named allowlisted actions are permitted.
- **No shell strings from task.json.** The `command`, `shell`, and `cmd` fields are explicitly rejected.
- **Workspace restricted (trusted-root policy).** The runner only operates inside explicitly trusted roots, assembled (and canonicalized) from: built-in defaults (`C:\Dev\Axiom` on Windows; `~/repos`, `~/Dev/Axiom`, `/home` on Linux); the config file `tools/local_runner/workspace_policy.json`; the GitHub Actions checkout (`$GITHUB_WORKSPACE`, set during workflow runs); and `$AXIOM_LOCAL_RUNNER_WORKSPACE_ROOTS` (os.pathsep-separated). The Axiom-01 self-hosted runner work dir (`C:\actions-runner-axiom\actions-runner\_work\Axiom-platform\Axiom-platform`) is trusted automatically during workflow runs via `$GITHUB_WORKSPACE`, and is also listed explicitly in `workspace_policy.json` for manual invocations. There is **no** path-name heuristic (e.g. matching `actions-runner/_work`) — a directory is trusted only if it is, or is under, an explicitly approved root, so a forged path like `C:\evil\actions-runner\_work\...` is rejected. Add future approved roots in the config file (or the env var) rather than in code; comparison is case-insensitive on Windows. All other paths are rejected.
- **No file deletion** outside `artifacts/local_runner_runs/`.
- **No secret reading.** The runner does not access secrets or credentials.
- **No external uploads.** All output stays local in artifact directories.
- **Timeout handling.** Processes are killed after the configured timeout.

## Allowed Actions

| Action | Command | Description |
|--------|---------|-------------|
| `git_status` | `git status --short`, `git branch --show-current`, `git log -1 --oneline` | Repository state |
| `pytest` | `poetry run pytest` | Full pytest suite |
| `ruff` | `poetry run ruff check .` | Lint check |
| `test_grids` | `poetry run axiom test-grids --mode simulate` | Grid harness |
| `test_levels` | `poetry run axiom test-levels --mode simulate` | Level harness |
| `dotnet_build_revit_2027` | `dotnet build src/axiom_revit/Axiom.Revit.2027.sln -c Release -p:Platform=x64` | Build only |
| `deploy_revit_2027` | `.\scripts\deploy-revit-2027.ps1` | Build and deploy |
| `test_pr_snapshot` | `poetry run pytest tests/test_pr_snapshot.py` | PR evidence snapshot tests |
| `test_set_parameter_value` | `poetry run pytest tests/test_set_parameter_value.py` | SetParameterValue v0 tests |
| `test_validation_loop` | `poetry run pytest tests/test_validation_loop.py` | Validation Automation Loop v0 tests |
| `collect_revit_journals` | *placeholder* | NOT_IMPLEMENTED — planned journal collection |
| `kill_revit` | *placeholder* | NOT_IMPLEMENTED — requires `allow_kill_revit=true` |

## How to Run

### Via Axiom CLI (preferred)

```bash
poetry run axiom local-runner --task tools/local_runner/examples/test_grids.task.json
```

### Via direct Python invocation

```bash
python tools/local_runner/local_runner.py --task tools/local_runner/examples/git_status.task.json
```

## task.json Format

```json
{
  "action": "test_grids",
  "prompt": "Validate grid simulation harness after changes.",
  "timeout_seconds": 300,
  "workspace": "C:\\Dev\\Axiom\\Code\\Axiom-platform",
  "metadata": {
    "requested_by": "human",
    "purpose": "validate grid harness"
  }
}
```

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `action` | string | Must be one of the allowed actions |
| `workspace` | string | Absolute path within allowed workspace bases |

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `prompt` | string | `""` | Human or agent request that caused this task. Falls back to `metadata.purpose` if missing |
| `timeout_seconds` | integer | 300 | Max execution time in seconds |
| `metadata` | object | `{}` | Arbitrary metadata (requested_by, purpose, etc.) |

## Inspecting Artifacts

Each run creates:

```
artifacts/local_runner_runs/<run_id>/
├── task.json                  # Copy of the input task (includes prompt)
├── run_log.json               # Execution metadata (includes prompt, resolved_action, command_executed)
├── result_summary.md          # Human-readable summary (every run)
├── stdout.txt                 # Captured standard output
├── stderr.txt                 # Captured standard error
├── environment_summary.json   # Platform/env info
└── failure_summary.md         # Only on failure — diagnostics
```

### run_log.json Fields

| Field | Description |
|-------|-------------|
| `run_id` | Timestamped identifier |
| `action` | Executed action name |
| `workspace` | Working directory |
| `started_at` / `completed_at` | ISO timestamps |
| `duration_ms` | Wall-clock duration |
| `exit_code` | Process exit code |
| `timed_out` | Whether timeout was hit |
| `status` | `success` / `failed` / `timed_out` / `blocked` / `not_implemented` |
| `prompt` | Original request text (falls back to metadata.purpose, then "N/A") |
| `resolved_action` | The allowlisted action name |
| `command_executed` | Actual allowlisted command(s) as human-readable string |
| `result_summary_path` | Path to result_summary.md |
| `stdout_path` / `stderr_path` | Paths to output files |
| `failure_summary_path` | Path to failure_summary.md (if failed) |

### failure_summary.md

Generated on any non-success status. Includes:
- Action and status
- Exit code and timeout status
- Likely failure reason (heuristic detection)
- Last 50 lines of stderr and stdout
- Suggested next action

## What Is Intentionally Not Supported

- **Arbitrary shell commands.** Not allowed — use named actions only.
- **Commands outside the workspace.** Workspace path validation enforced.
- **File deletion** outside artifact directories.
- **Secret access** or credential handling.
- **Network uploads** or external communication.
- **Interactive prompts** — all actions run non-interactively.
- **Multiple actions in one task.** Each task.json runs exactly one action.

## Sample Tasks

Located in `tools/local_runner/examples/`:

- `git_status.task.json` — check repo state
- `test_grids.task.json` — run grid simulation harness
- `test_levels.task.json` — run level simulation harness
- `ruff.task.json` — lint check
- `deploy_revit_2027.task.json` — build and deploy to Revit 2027
- `test_pr_snapshot.task.json` — run PR evidence snapshot tests
- `test_set_parameter_value.task.json` — run SetParameterValue v0 tests
- `test_validation_loop.task.json` — run Validation Automation Loop v0 tests

## Encoding Notes

The task file parser uses `utf-8-sig` encoding, which transparently handles UTF-8 files with or without a Byte Order Mark (BOM). This is important on Windows where `Set-Content -Encoding UTF8` (PowerShell) prepends a BOM (`EF BB BF`) to the file. Without `utf-8-sig`, the BOM appears as the first character of the JSON and causes a parse error.

## Future Roadmap

- **Revit journal collection:** Scrape journal files from `%LOCALAPPDATA%\Autodesk\Revit\` for post-mortem analysis.
- **Chained actions:** Execute multiple actions in sequence with dependency checking.
- **Agent integration:** Allow Axiom agents to request local runner actions programmatically.
- **Result parsing:** Structured parsing of test results, build errors, lint output.
- **Kill Revit with safety:** Safe Revit process termination for DLL unlock during deploy.
