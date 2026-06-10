# MCP-Compatible Server Surface

## Purpose

Exposes Axiom capabilities through a local tool surface whose schemas and names
map cleanly to a future MCP server. The surface is usable today as plain Python
function calls; network/JSON-RPC transport can be added later without changing
the tool contracts.

## Tool inventory

### Server diagnostics

| Tool                        | Description                        |
|-----------------------------|------------------------------------|
| `axiom_server_diagnose`     | Server health, version, counts     |
| `axiom_server_get_log_path` | Audit log path and existence       |
| `axiom_server_get_version`  | Axiom + API version                |

### Capability management

| Tool                          | Description                          |
|-------------------------------|--------------------------------------|
| `axiom_capabilities_list`     | List all registered capabilities     |
| `axiom_capabilities_describe` | Full metadata for one capability     |

### Run operations

| Tool                        | Description                              |
|-----------------------------|------------------------------------------|
| `axiom_runs_create_dry_run` | Launch dry-run via run spine (PR #31)    |
| `axiom_runs_list_history`   | Recent runs from artifact store          |
| `axiom_runs_get_artifacts`  | Manifest + file list for a run ID        |

### Optional (depend on PR #32)

| Tool                             | Description                         |
|----------------------------------|-------------------------------------|
| `axiom_model_health_get_latest`  | Latest model health report          |
| `axiom_capability_readiness_get` | Readiness assessment for capability |

## Contract details

### `axiom_server_diagnose`

```json
{
  "status": "healthy",
  "axiom_version": "0.1.0",
  "artifact_root": "artifacts",
  "audit_log_path": "artifacts/audit/axiom_command_log.jsonl",
  "registered_capability_count": 1,
  "external_calls_made": false
}
```

### `axiom_capabilities_describe`

Success:
```json
{
  "error": false,
  "capability": { /* EnhancedCapabilityMeta.to_dict() */ }
}
```

Error (unknown capability):
```json
{
  "error": true,
  "error_type": "CapabilityNotFound",
  "error_message": "Unknown capability: 'foo'",
  "available_capabilities": ["grid_creation"]
}
```

### `axiom_runs_create_dry_run`

Success:
```json
{
  "error": false,
  "run_id": "20260607_120000_grid_creation_dry_run_a1b2c3d4",
  "status": "completed",
  "artifact_path": "artifacts/Runs/...",
  "capability_id": "grid_creation",
  "mode": "dry_run"
}
```

### Error convention

All tool functions return ``dict``. Error responses include:

```json
{
  "error": true,
  "error_type": "CapabilityNotFound",
  "error_message": "..."
}
```

Non-error responses include `"error": false`.

## Future MCP mapping

The tool names follow a `<domain>_<resource>_<action>` pattern that maps
directly to MCP tool definitions:

```
axiom_server_diagnose      → tools/axiom.server.diagnose
axiom_capabilities_list    → tools/axiom.capabilities.list
axiom_runs_create_dry_run  → tools/axiom.runs.createDryRun
```

To add JSON-RPC transport:

1. Wrap each tool function in a JSON-RPC handler.
2. Map tool names to MCP tool definitions.
3. Add input/output schema declarations from the registry metadata.
4. Expose on `localhost` (default — no external network exposure).

## Non-goals

- Production OAuth
- Network service exposure outside localhost
- Cloud dependencies
- Full MCP feature completeness
- Multiple new Revit capabilities
- UI
