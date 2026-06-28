"""Configuration Diff Framework v1.

Provides deterministic configuration diff capabilities on top of configuration
history. Compares configuration states in a structured, reviewable, and
evidence-backed way.

Non-goals: no automatic merging, no conflict resolution, no schedulers,
no workflow engines, no external diff tools, no uncontrolled mutation.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from axiom_core.artifact_paths import is_within_sandbox

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ConfigurationDiffType(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ConfigurationDiffRequest:
    """A request to diff two configuration states."""

    request_id: str = ""
    left_config_id: str = ""
    right_config_id: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.request_id:
            self.request_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "left_config_id": self.left_config_id,
            "right_config_id": self.right_config_id,
            "created_at": self.created_at,
        }


@dataclass
class ConfigurationDiffEntry:
    """A single diff entry for a configuration key."""

    key: str = ""
    diff_type: str = ""
    left_value: str = ""
    right_value: str = ""
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "diff_type": self.diff_type,
            "left_value": self.left_value,
            "right_value": self.right_value,
            "summary": self.summary,
        }


@dataclass
class ConfigurationDiffResult:
    """Result of comparing two configuration states."""

    result_id: str = ""
    request_id: str = ""
    entries: list[ConfigurationDiffEntry] = field(default_factory=list)
    added_count: int = 0
    removed_count: int = 0
    changed_count: int = 0
    unchanged_count: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.result_id:
            self.result_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "request_id": self.request_id,
            "entries": [e.to_dict() for e in self.entries],
            "added_count": self.added_count,
            "removed_count": self.removed_count,
            "changed_count": self.changed_count,
            "unchanged_count": self.unchanged_count,
            "created_at": self.created_at,
        }


@dataclass
class ConfigurationDiffReport:
    """Report summarizing a configuration diff."""

    report_id: str = ""
    request_id: str = ""
    diff_summary: str = ""
    request: ConfigurationDiffRequest | None = None
    result: ConfigurationDiffResult | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "request_id": self.request_id,
            "diff_summary": self.diff_summary,
            "request": self.request.to_dict() if self.request else None,
            "result": self.result.to_dict() if self.result else None,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Diff engine
# ---------------------------------------------------------------------------


class ConfigurationDiffEngine:
    """Compares two configuration states deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._diff_dir = self._artifacts_root / "config_diff"
        self._diff_dir.mkdir(parents=True, exist_ok=True)

    def _safe_diff_path(self, report_id: str) -> Path:
        target = (self._diff_dir / report_id).resolve()
        sandbox = self._diff_dir.resolve()
        if not is_within_sandbox(target, sandbox):
            raise ValueError(
                f"Resolved path escapes artifacts root: {report_id!r}"
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

    def diff(
        self,
        left_config: dict[str, Any] | None = None,
        right_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Diff two configuration states deterministically."""
        left_config = left_config or {}
        right_config = right_config or {}

        left_id = left_config.get("config_id", "")
        right_id = right_config.get("config_id", "")

        request = ConfigurationDiffRequest(
            left_config_id=left_id,
            right_config_id=right_id,
        )

        left_entries = self._extract_entries(left_config)
        right_entries = self._extract_entries(right_config)

        diff_entries = self._compute_diff(left_entries, right_entries)

        added = sum(1 for e in diff_entries if e.diff_type == ConfigurationDiffType.ADDED.value)
        removed = sum(1 for e in diff_entries if e.diff_type == ConfigurationDiffType.REMOVED.value)
        changed = sum(1 for e in diff_entries if e.diff_type == ConfigurationDiffType.CHANGED.value)
        unchanged = sum(1 for e in diff_entries if e.diff_type == ConfigurationDiffType.UNCHANGED.value)

        result = ConfigurationDiffResult(
            request_id=request.request_id,
            entries=diff_entries,
            added_count=added,
            removed_count=removed,
            changed_count=changed,
            unchanged_count=unchanged,
        )

        diff_summary = (
            f"Diff complete: {added} added, {removed} removed, "
            f"{changed} changed, {unchanged} unchanged."
        )

        report = ConfigurationDiffReport(
            request_id=request.request_id,
            diff_summary=diff_summary,
            request=request,
            result=result,
        )

        self._persist_report(report)
        self._write_evidence(report)

        return report.to_dict()

    @staticmethod
    def _extract_entries(config: dict[str, Any]) -> dict[str, str]:
        entries: dict[str, str] = {}
        for entry in config.get("entries", []):
            key = entry.get("key", "")
            value = entry.get("value", "")
            if key:
                entries[key] = value
        return entries

    @staticmethod
    def _compute_diff(
        left: dict[str, str],
        right: dict[str, str],
    ) -> list[ConfigurationDiffEntry]:
        all_keys = sorted(set(list(left.keys()) + list(right.keys())))
        entries: list[ConfigurationDiffEntry] = []

        for key in all_keys:
            in_left = key in left
            in_right = key in right

            if in_left and not in_right:
                entries.append(ConfigurationDiffEntry(
                    key=key,
                    diff_type=ConfigurationDiffType.REMOVED.value,
                    left_value=left[key],
                    right_value="",
                    summary=f"Key '{key}' removed (was: '{left[key]}')",
                ))
            elif not in_left and in_right:
                entries.append(ConfigurationDiffEntry(
                    key=key,
                    diff_type=ConfigurationDiffType.ADDED.value,
                    left_value="",
                    right_value=right[key],
                    summary=f"Key '{key}' added (value: '{right[key]}')",
                ))
            elif left[key] != right[key]:
                entries.append(ConfigurationDiffEntry(
                    key=key,
                    diff_type=ConfigurationDiffType.CHANGED.value,
                    left_value=left[key],
                    right_value=right[key],
                    summary=f"Key '{key}' changed: '{left[key]}' -> '{right[key]}'",
                ))
            else:
                entries.append(ConfigurationDiffEntry(
                    key=key,
                    diff_type=ConfigurationDiffType.UNCHANGED.value,
                    left_value=left[key],
                    right_value=right[key],
                    summary=f"Key '{key}' unchanged (value: '{left[key]}')",
                ))

        return entries

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        self._validate_id_segment(report_id, "report_id")
        return self._load_report(report_id)

    def list_reports(self) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        if not self._diff_dir.exists():
            return reports

        sandbox = self._diff_dir.resolve()
        for entry in self._diff_dir.iterdir():
            if not entry.is_dir():
                continue
            resolved = entry.resolve()
            if not is_within_sandbox(resolved, sandbox):
                continue
            report_file = entry / "report.json"
            if not report_file.exists():
                continue
            try:
                data = json.loads(report_file.read_text(encoding="utf-8"))
                reports.append(data)
            except (json.JSONDecodeError, OSError):
                continue

        reports.sort(key=lambda r: r.get("created_at", ""))
        return reports

    def export_report(self, report_id: str) -> str:
        self._validate_id_segment(report_id, "report_id")
        data = self._load_report(report_id)
        if data is None:
            raise ValueError(f"Diff report not found: {report_id}")
        return self._generate_summary(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_report(self, report: ConfigurationDiffReport) -> None:
        report_dir = self._safe_diff_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def _load_report(self, report_id: str) -> dict[str, Any] | None:
        report_dir = self._safe_diff_path(report_id)
        report_file = report_dir / "report.json"
        if not report_file.exists():
            return None
        return json.loads(report_file.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def _write_evidence(self, report: ConfigurationDiffReport) -> None:
        evidence_dir = self._safe_diff_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = report.request.to_dict() if report.request else {}
        (evidence_dir / "config_diff_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        result_data = report.result.to_dict() if report.result else {}
        (evidence_dir / "config_diff_result.json").write_text(
            json.dumps(result_data, indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_summary(report.to_dict())
        (evidence_dir / "config_diff_summary.md").write_text(
            md, encoding="utf-8",
        )

        has_diff = (
            report.result is not None
            and (report.result.added_count + report.result.removed_count + report.result.changed_count) > 0
        ) if report.result else False

        pass_fail = {
            "passed": True,
            "report_id": report.report_id,
            "has_differences": has_diff,
            "added_count": report.result.added_count if report.result else 0,
            "removed_count": report.result.removed_count if report.result else 0,
            "changed_count": report.result.changed_count if report.result else 0,
            "unchanged_count": report.result.unchanged_count if report.result else 0,
            "status": "succeeded",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _generate_summary(data: dict[str, Any]) -> str:
        lines: list[str] = []

        lines.append("# Configuration Diff Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Summary: {data.get('diff_summary', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        result = data.get("result")
        if result:
            lines.append("## Counts")
            lines.append("")
            lines.append(f"- Added: {result.get('added_count', 0)}")
            lines.append(f"- Removed: {result.get('removed_count', 0)}")
            lines.append(f"- Changed: {result.get('changed_count', 0)}")
            lines.append(f"- Unchanged: {result.get('unchanged_count', 0)}")
            lines.append("")

            entries = result.get("entries", [])
            if entries:
                lines.append("## Entries")
                lines.append("")
                for entry in entries:
                    dt = entry.get("diff_type", "").upper()
                    lines.append(f"- [{dt}] {entry.get('summary', '')}")
                lines.append("")

        return "\n".join(lines)
