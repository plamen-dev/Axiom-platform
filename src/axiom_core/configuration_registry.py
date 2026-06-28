"""Structured Configuration Framework v1.

Provides durable configuration file loading, validation, persistence,
export, and evidence generation built on top of parse_key_value_lines.

Non-goals: no generalized settings systems, no environment variable
management, no workflow engines, no schedulers.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from axiom_core.artifact_paths import is_within_sandbox
from axiom_core.text_utils import parse_key_value_lines

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ConfigurationEntry:
    """A single key-value configuration entry."""

    key: str = ""
    value: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key, "value": self.value}


@dataclass
class ConfigurationValidationResult:
    """Result of validating a configuration file."""

    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


@dataclass
class ConfigurationFile:
    """A parsed and validated configuration file."""

    config_id: str = ""
    file_name: str = ""
    entries: list[ConfigurationEntry] = field(default_factory=list)
    entry_count: int = 0
    validation: ConfigurationValidationResult = field(
        default_factory=ConfigurationValidationResult,
    )
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.config_id:
            self.config_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_id": self.config_id,
            "file_name": self.file_name,
            "entries": [e.to_dict() for e in self.entries],
            "entry_count": self.entry_count,
            "validation": self.validation.to_dict(),
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ConfigurationRegistry:
    """Durable registry for structured configuration artifacts."""

    def __init__(
        self,
        artifacts_root: str | None = None,
    ) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._configs_dir = self._artifacts_root / "configurations"
        self._configs_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Path safety
    # ------------------------------------------------------------------

    def _safe_config_path(self, config_id: str) -> Path:
        """Resolve and validate the config directory stays inside sandbox."""
        target = (self._configs_dir / config_id).resolve()
        sandbox = self._configs_dir.resolve()
        if not is_within_sandbox(target, sandbox):
            raise ValueError(
                f"Resolved path escapes artifacts root: {config_id!r}"
            )
        return target

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"{name} must not be empty or whitespace")
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(
                f"{name} must not contain '..', '/', or '\\': {value!r}"
            )

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def load_config(
        self,
        text: str,
        file_name: str = "",
    ) -> dict[str, Any]:
        """Load and validate a configuration from key=value text."""
        validation = ConfigurationValidationResult()

        if not text or not text.strip():
            validation.warnings.append("Configuration text is empty")
            config = ConfigurationFile(
                file_name=file_name,
                entries=[],
                entry_count=0,
                validation=validation,
            )
            self._persist_config(config)
            return config.to_dict()

        entries: list[ConfigurationEntry] = []
        try:
            parsed = parse_key_value_lines(text)
            for k, v in parsed.items():
                entries.append(ConfigurationEntry(key=k, value=v))
        except ValueError as exc:
            error_msg = str(exc)
            validation.valid = False
            if "Duplicate key" in error_msg:
                validation.errors.append(f"Duplicate detected: {error_msg}")
            elif "Malformed" in error_msg:
                validation.errors.append(f"Malformed line: {error_msg}")
            else:
                validation.errors.append(error_msg)

        config = ConfigurationFile(
            file_name=file_name,
            entries=entries,
            entry_count=len(entries),
            validation=validation,
        )
        self._persist_config(config)
        return config.to_dict()

    def get_config(self, config_id: str) -> dict[str, Any] | None:
        """Get a configuration by ID."""
        self._validate_id_segment(config_id, "config_id")
        return self._load_config(config_id)

    def list_configs(self) -> list[dict[str, Any]]:
        """List all configurations with deterministic ordering."""
        configs: list[dict[str, Any]] = []
        if not self._configs_dir.exists():
            return configs

        sandbox = self._configs_dir.resolve()
        for entry in self._configs_dir.iterdir():
            if not entry.is_dir():
                continue
            resolved = entry.resolve()
            if not is_within_sandbox(resolved, sandbox):
                continue
            config_file = entry / "config.json"
            if not config_file.exists():
                continue
            try:
                data = json.loads(config_file.read_text(encoding="utf-8"))
                configs.append(data)
            except (json.JSONDecodeError, OSError):
                continue

        configs.sort(key=lambda c: c.get("created_at", ""))
        return configs

    def export_config(self, config_id: str) -> str:
        """Export a configuration as markdown."""
        self._validate_id_segment(config_id, "config_id")
        data = self._load_config(config_id)
        if data is None:
            raise ValueError(f"Configuration not found: {config_id}")

        lines: list[str] = []
        lines.append(f"# Configuration: {data.get('file_name') or config_id}")
        lines.append("")
        lines.append(f"- Config ID: {data['config_id']}")
        if data.get("file_name"):
            lines.append(f"- File: {data['file_name']}")
        lines.append(f"- Entries: {data['entry_count']}")
        lines.append(f"- Created: {data['created_at']}")
        lines.append("")

        validation = data.get("validation", {})
        valid = validation.get("valid", True)
        lines.append(f"## Validation: {'PASSED' if valid else 'FAILED'}")
        lines.append("")
        if validation.get("errors"):
            for err in validation["errors"]:
                lines.append(f"- ERROR: {err}")
            lines.append("")
        if validation.get("warnings"):
            for warn in validation["warnings"]:
                lines.append(f"- WARNING: {warn}")
            lines.append("")

        entries = data.get("entries", [])
        if entries:
            lines.append("## Entries")
            lines.append("")
            for e in entries:
                lines.append(f"- `{e['key']}` = `{e['value']}`")
            lines.append("")

        return "\n".join(lines)

    def write_evidence(self, config_id: str) -> str:
        """Write evidence bundle for a configuration."""
        self._validate_id_segment(config_id, "config_id")
        data = self._load_config(config_id)
        if data is None:
            raise ValueError(f"Configuration not found: {config_id}")

        evidence_dir = self._safe_config_path(config_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        # configuration_request.json
        request_data = {
            "config_id": data["config_id"],
            "file_name": data.get("file_name", ""),
            "entry_count": data["entry_count"],
        }
        (evidence_dir / "configuration_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        # configuration_result.json
        (evidence_dir / "configuration_result.json").write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )

        # configuration_summary.md
        md = self.export_config(config_id)
        (evidence_dir / "configuration_summary.md").write_text(
            md, encoding="utf-8",
        )

        # pass_fail.json
        validation = data.get("validation", {})
        pass_fail = {
            "passed": validation.get("valid", True),
            "config_id": config_id,
            "file_name": data.get("file_name", ""),
            "entry_count": data["entry_count"],
            "error_count": len(validation.get("errors", [])),
            "warning_count": len(validation.get("warnings", [])),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

        return str(evidence_dir)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _persist_config(self, config: ConfigurationFile) -> None:
        config_dir = self._safe_config_path(config.config_id)
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text(
            json.dumps(config.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def _load_config(self, config_id: str) -> dict[str, Any] | None:
        config_dir = self._safe_config_path(config_id)
        config_file = config_dir / "config.json"
        if not config_file.exists():
            return None
        return json.loads(config_file.read_text(encoding="utf-8"))
