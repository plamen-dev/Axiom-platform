"""Axiom Local Audit, Evidence, and Run Spine v1.

Every Axiom action gets a run ID, a standard artifact folder, structured audit
logs, and machine-readable result files. This module is the backbone that all
future capabilities must use.

Artifact folder pattern::

    <artifacts_root>/Runs/<run_id>/
        run_metadata.json
        command_input.json
        parsed_intent.json      (optional)
        execution_result.json
        validation_result.json  (optional)
        error_result.json       (written only on failure)
        external_calls.json
        artifact_manifest.json
        run_summary.md

Command audit log (JSONL)::

    <artifacts_root>/audit/axiom_command_log.jsonl

The output path is configurable via the ``AXIOM_ARTIFACTS_ROOT`` env var.
Default: ``artifacts`` (relative to repo root). Windows canonical path:
``C:\\Dev\\Axiom\\Artifacts``
"""

from __future__ import annotations

import getpass
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_ARTIFACTS_ROOT = "artifacts"


def artifacts_root() -> Path:
    """Return the root directory for all Axiom artifacts."""
    return Path(os.environ.get("AXIOM_ARTIFACTS_ROOT", _DEFAULT_ARTIFACTS_ROOT))


def runs_root() -> Path:
    """Return the directory containing all run artifact folders."""
    return artifacts_root() / "Runs"


def _audit_dir() -> Path:
    return artifacts_root() / "audit"


def audit_log_path() -> Path:
    """Return the path to the JSONL command audit log."""
    return _audit_dir() / "axiom_command_log.jsonl"


# ---------------------------------------------------------------------------
# Run ID generation
# ---------------------------------------------------------------------------


def generate_run_id(capability: str, mode: str = "dry_run") -> str:
    """Generate a timestamped run ID with a unique suffix.

    Format: ``YYYYMMDD_HHMMSS_<capability_snake>_<mode>_<hex8>``

    The 8-char hex suffix (from uuid4) prevents collisions when two runs
    for the same capability/mode occur within the same UTC second.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    cap_slug = capability.lower().replace(" ", "_").replace("-", "_")
    suffix = uuid4().hex[:8]
    return f"{ts}_{cap_slug}_{mode}_{suffix}"


# ---------------------------------------------------------------------------
# Artifact folder creation
# ---------------------------------------------------------------------------


def create_run_folder(run_id: str) -> Path:
    """Create the standard run artifact folder and return its path."""
    folder = runs_root() / run_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class RunMetadata:
    """Per-run metadata record."""

    run_id: str
    created_at_utc: str
    capability: str
    capability_version: str = "1.0.0"
    mode: str = "dry_run"
    source: str = "cli"
    status: str = "started"
    artifact_path: str = ""
    axiom_version: str = "0.1.0"
    revit_version: str | None = None
    model_path: str | None = None
    active_view: str | None = None
    active_view_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at_utc": self.created_at_utc,
            "capability": self.capability,
            "capability_version": self.capability_version,
            "mode": self.mode,
            "source": self.source,
            "status": self.status,
            "artifact_path": self.artifact_path,
            "axiom_version": self.axiom_version,
            "revit_version": self.revit_version,
            "model_path": self.model_path,
            "active_view": self.active_view,
            "active_view_type": self.active_view_type,
        }


@dataclass
class AuditEntry:
    """One entry in the command audit JSONL log."""

    timestamp_utc: str
    run_id: str
    source: str = "cli"
    capability: str = ""
    mode: str = "dry_run"
    risk_level: str = "low"
    model_path: str | None = None
    model_path_redacted: str | None = None
    user: str = ""
    input_summary: str = ""
    artifact_path: str = ""
    status: str = "started"
    external_calls_made: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp_utc": self.timestamp_utc,
            "run_id": self.run_id,
            "source": self.source,
            "capability": self.capability,
            "mode": self.mode,
            "risk_level": self.risk_level,
            "model_path": self.model_path,
            "model_path_redacted": self.model_path_redacted,
            "user": self.user,
            "input_summary": self.input_summary,
            "artifact_path": self.artifact_path,
            "status": self.status,
            "external_calls_made": self.external_calls_made,
        }


@dataclass
class ExternalCallDeclaration:
    """External call declaration for a run."""

    external_calls_made: bool = False
    services: list[str] = field(default_factory=list)
    notes: str = "Local-only run. No external calls were made."

    def to_dict(self) -> dict[str, Any]:
        return {
            "external_calls_made": self.external_calls_made,
            "services": self.services,
            "notes": self.notes,
        }


@dataclass
class ArtifactManifest:
    """Manifest of all files in a run folder."""

    run_id: str
    artifact_path: str
    files: list[str] = field(default_factory=list)
    created_at_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "artifact_path": self.artifact_path,
            "files": self.files,
            "created_at_utc": self.created_at_utc,
        }


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")


def write_run_metadata(folder: Path, metadata: RunMetadata) -> Path:
    """Write run_metadata.json."""
    p = folder / "run_metadata.json"
    _write_json(p, metadata.to_dict())
    return p


def write_command_input(folder: Path, input_data: dict[str, Any]) -> Path:
    """Write command_input.json."""
    p = folder / "command_input.json"
    _write_json(p, input_data)
    return p


def write_parsed_intent(folder: Path, intent_data: dict[str, Any]) -> Path:
    """Write parsed_intent.json (optional)."""
    p = folder / "parsed_intent.json"
    _write_json(p, intent_data)
    return p


def write_execution_result(folder: Path, result_data: dict[str, Any]) -> Path:
    """Write execution_result.json."""
    p = folder / "execution_result.json"
    _write_json(p, result_data)
    return p


def write_validation_result(folder: Path, result_data: dict[str, Any]) -> Path:
    """Write validation_result.json (optional)."""
    p = folder / "validation_result.json"
    _write_json(p, result_data)
    return p


def write_error_result(folder: Path, error_data: dict[str, Any]) -> Path:
    """Write error_result.json."""
    p = folder / "error_result.json"
    _write_json(p, error_data)
    return p


def write_external_calls(
    folder: Path,
    declaration: ExternalCallDeclaration | None = None,
) -> Path:
    """Write external_calls.json (defaults to no external calls)."""
    if declaration is None:
        declaration = ExternalCallDeclaration()
    p = folder / "external_calls.json"
    _write_json(p, declaration.to_dict())
    return p


def write_artifact_manifest(folder: Path, run_id: str) -> Path:
    """Write artifact_manifest.json listing all files in the run folder."""
    files = sorted(
        str(f.relative_to(folder))
        for f in folder.rglob("*")
        if f.is_file() and f.name != "artifact_manifest.json"
    )
    manifest = ArtifactManifest(
        run_id=run_id,
        artifact_path=str(folder),
        files=files,
        created_at_utc=datetime.now(timezone.utc).isoformat(),
    )
    p = folder / "artifact_manifest.json"
    _write_json(p, manifest.to_dict())
    return p


def write_run_summary(folder: Path, run_id: str, metadata: RunMetadata, status: str) -> Path:
    """Write run_summary.md — human-readable summary."""
    lines = [
        f"# Run Summary: {run_id}",
        "",
        f"- **Capability**: {metadata.capability}",
        f"- **Mode**: {metadata.mode}",
        f"- **Source**: {metadata.source}",
        f"- **Status**: {status}",
        f"- **Created**: {metadata.created_at_utc}",
        f"- **Axiom Version**: {metadata.axiom_version}",
    ]
    if metadata.model_path:
        lines.append(f"- **Model**: {redact_path(metadata.model_path)}")
    if metadata.revit_version:
        lines.append(f"- **Revit Version**: {metadata.revit_version}")
    lines.append("")
    p = folder / "run_summary.md"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Audit log (JSONL)
# ---------------------------------------------------------------------------


def append_audit_entry(entry: AuditEntry) -> Path:
    """Append an entry to the command audit JSONL log."""
    log_path = audit_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry.to_dict(), default=str) + "\n")
    return log_path


# ---------------------------------------------------------------------------
# Run history query
# ---------------------------------------------------------------------------


def list_runs(limit: int = 50) -> list[dict[str, Any]]:
    """List completed runs by reading run_metadata.json from each run folder.

    Returns most-recent-first, up to ``limit`` entries.
    """
    runs_dir = runs_root()
    if not runs_dir.is_dir():
        return []

    results: list[dict[str, Any]] = []
    for folder in sorted(runs_dir.iterdir(), reverse=True):
        if not folder.is_dir():
            continue
        meta_file = folder / "run_metadata.json"
        if meta_file.is_file():
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                results.append(data)
            except (json.JSONDecodeError, OSError):
                continue
        if len(results) >= limit:
            break
    return results


# ---------------------------------------------------------------------------
# Orchestrated run execution
# ---------------------------------------------------------------------------


def _get_user() -> str:
    """Best-effort current user identity."""
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


def redact_path(path: str | None) -> str | None:
    """Redact user-specific portions of a file path.

    Replaces the username segment following ``Users`` or ``home`` directory
    components with ``***``.  This is a core audit/trust behaviour — all
    modules that write audit entries or summary artifacts should use this
    single implementation to keep redaction consistent.
    """
    if path is None:
        return None
    parts = path.replace("\\", "/").split("/")
    redacted = []
    for part in parts:
        if part.lower() in ("users", "home"):
            redacted.append(part)
        elif redacted and redacted[-1].lower() in ("users", "home"):
            redacted.append("***")
        else:
            redacted.append(part)
    return "/".join(redacted)


@dataclass
class RunContext:
    """Input context for a spine-governed run."""

    capability: str
    mode: str = "dry_run"
    source: str = "cli"
    risk_level: str = "low"
    model_path: str | None = None
    revit_version: str | None = None
    active_view: str | None = None
    active_view_type: str | None = None
    input_data: dict[str, Any] = field(default_factory=dict)
    parsed_intent: dict[str, Any] | None = None


@dataclass
class RunResult:
    """Outcome of a spine-governed run."""

    run_id: str
    artifact_path: str
    status: str  # completed | failed
    result_data: dict[str, Any] = field(default_factory=dict)
    error_data: dict[str, Any] | None = None
    external_calls: ExternalCallDeclaration = field(
        default_factory=ExternalCallDeclaration
    )


def execute_run(
    context: RunContext,
    executor: Any | None = None,
) -> RunResult:
    """Execute a full spine-governed run.

    1. Generate run ID.
    2. Create artifact folder.
    3. Write audit entry (started).
    4. Write metadata + input.
    5. Call executor (if provided) to get result/error.
    6. Write result or error files.
    7. Write external calls.
    8. Write manifest + summary.
    9. Update audit entry (completed/failed).
    10. Return RunResult with artifact path.

    If ``executor`` is None, a dry-run stub that returns success is used.
    If execution raises, artifacts are still produced with error capture.
    """
    run_id = generate_run_id(context.capability, context.mode)
    folder = create_run_folder(run_id)
    now_utc = datetime.now(timezone.utc).isoformat()
    user = _get_user()

    # --- Metadata ---
    metadata = RunMetadata(
        run_id=run_id,
        created_at_utc=now_utc,
        capability=context.capability,
        mode=context.mode,
        source=context.source,
        status="started",
        artifact_path=str(folder),
        revit_version=context.revit_version,
        model_path=context.model_path,
        active_view=context.active_view,
        active_view_type=context.active_view_type,
    )
    write_run_metadata(folder, metadata)

    # --- Input ---
    write_command_input(folder, context.input_data)

    # --- Parsed intent (optional) ---
    if context.parsed_intent is not None:
        write_parsed_intent(folder, context.parsed_intent)

    # --- Audit entry (started) ---
    _audit_common = dict(
        run_id=run_id,
        source=context.source,
        capability=context.capability,
        mode=context.mode,
        risk_level=context.risk_level,
        model_path=context.model_path,
        model_path_redacted=redact_path(context.model_path),
        user=user,
        input_summary=json.dumps(context.input_data, default=str)[:200],
        artifact_path=str(folder),
    )
    append_audit_entry(
        AuditEntry(timestamp_utc=now_utc, status="started", external_calls_made=False, **_audit_common)
    )

    # --- Execute ---
    result_data: dict[str, Any] = {}
    error_data: dict[str, Any] | None = None
    status = "completed"

    try:
        if executor is not None:
            result_data = executor(context)
        else:
            result_data = {
                "outcome": "success",
                "mode": context.mode,
                "capability": context.capability,
                "note": "Dry-run completed. No model mutation.",
            }
    except Exception as exc:
        status = "failed"
        error_data = {
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "run_id": run_id,
            "capability": context.capability,
            "mode": context.mode,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

    # --- Write result / error ---
    write_execution_result(folder, result_data)
    if error_data is not None:
        write_error_result(folder, error_data)

    # --- External calls ---
    ext_calls = ExternalCallDeclaration()
    write_external_calls(folder, ext_calls)

    # --- Update metadata status ---
    metadata.status = status
    write_run_metadata(folder, metadata)

    # --- Manifest + summary ---
    write_run_summary(folder, run_id, metadata, status)
    write_artifact_manifest(folder, run_id)

    # --- Audit entry (final) ---
    append_audit_entry(
        AuditEntry(
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            status=status,
            external_calls_made=ext_calls.external_calls_made,
            **_audit_common,
        )
    )

    return RunResult(
        run_id=run_id,
        artifact_path=str(folder),
        status=status,
        result_data=result_data,
        error_data=error_data,
        external_calls=ext_calls,
    )
