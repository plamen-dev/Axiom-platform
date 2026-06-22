"""Configuration Merge Framework v1.

Provides deterministic merge capabilities on top of configuration diffs.
Combines compatible configuration states while preserving traceability,
reviewability, and evidence.

Non-goals: no automatic conflict resolution, no schedulers, no workflow
engines, no external merge tools, no uncontrolled mutation.
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

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ConfigurationMergeStrategy(str, Enum):
    LEFT_WINS = "left_wins"
    RIGHT_WINS = "right_wins"
    KEEP_IDENTICAL_ONLY = "keep_identical_only"
    FAIL_ON_CONFLICT = "fail_on_conflict"


class ConfigurationMergeStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL_SUCCESS = "partial_success"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ConfigurationMergeRequest:
    """A request to merge two configuration states."""

    request_id: str = ""
    left_config_id: str = ""
    right_config_id: str = ""
    merge_strategy: str = ""
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
            "merge_strategy": self.merge_strategy,
            "created_at": self.created_at,
        }


@dataclass
class ConfigurationMergeEntry:
    """A single merge entry for a configuration key."""

    key: str = ""
    left_value: str = ""
    right_value: str = ""
    merged_value: str = ""
    conflict_detected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "left_value": self.left_value,
            "right_value": self.right_value,
            "merged_value": self.merged_value,
            "conflict_detected": self.conflict_detected,
        }


@dataclass
class ConfigurationMergeResult:
    """Result of merging two configuration states."""

    result_id: str = ""
    request_id: str = ""
    merged_entries: list[ConfigurationMergeEntry] = field(default_factory=list)
    conflict_count: int = 0
    merged_count: int = 0
    status: str = ""
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
            "merged_entries": [e.to_dict() for e in self.merged_entries],
            "conflict_count": self.conflict_count,
            "merged_count": self.merged_count,
            "status": self.status,
            "created_at": self.created_at,
        }


@dataclass
class ConfigurationMergeReport:
    """Report summarizing a configuration merge."""

    report_id: str = ""
    request_id: str = ""
    merge_summary: str = ""
    request: ConfigurationMergeRequest | None = None
    result: ConfigurationMergeResult | None = None
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
            "merge_summary": self.merge_summary,
            "request": self.request.to_dict() if self.request else None,
            "result": self.result.to_dict() if self.result else None,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Merge engine
# ---------------------------------------------------------------------------


class ConfigurationMergeEngine:
    """Merges two configuration states deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._merge_dir = self._artifacts_root / "config_merge"
        self._merge_dir.mkdir(parents=True, exist_ok=True)

    def _safe_merge_path(self, report_id: str) -> Path:
        target = (self._merge_dir / report_id).resolve()
        sandbox = self._merge_dir.resolve()
        if not str(target).startswith(str(sandbox) + "/") and target != sandbox:
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

    def merge(
        self,
        left_config: dict[str, Any] | None = None,
        right_config: dict[str, Any] | None = None,
        strategy: str = "left_wins",
    ) -> dict[str, Any]:
        """Merge two configuration states using the given strategy."""
        left_config = left_config or {}
        right_config = right_config or {}

        left_id = left_config.get("config_id", "")
        right_id = right_config.get("config_id", "")

        request = ConfigurationMergeRequest(
            left_config_id=left_id,
            right_config_id=right_id,
            merge_strategy=strategy,
        )

        left_entries = self._extract_entries(left_config)
        right_entries = self._extract_entries(right_config)

        merged_entries, conflict_count = self._compute_merge(
            left_entries, right_entries, strategy
        )

        merged_count = len(merged_entries)
        status = self._determine_status(strategy, conflict_count)

        result = ConfigurationMergeResult(
            request_id=request.request_id,
            merged_entries=merged_entries,
            conflict_count=conflict_count,
            merged_count=merged_count,
            status=status,
        )

        merge_summary = (
            f"Merge complete ({strategy}): {merged_count} entries merged, "
            f"{conflict_count} conflicts."
        )

        report = ConfigurationMergeReport(
            request_id=request.request_id,
            merge_summary=merge_summary,
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
    def _determine_status(strategy: str, conflict_count: int) -> str:
        if strategy == ConfigurationMergeStrategy.FAIL_ON_CONFLICT.value:
            if conflict_count > 0:
                return ConfigurationMergeStatus.FAILED.value
        if strategy == ConfigurationMergeStrategy.KEEP_IDENTICAL_ONLY.value:
            if conflict_count > 0:
                return ConfigurationMergeStatus.PARTIAL_SUCCESS.value
        return ConfigurationMergeStatus.SUCCEEDED.value

    @staticmethod
    def _compute_merge(
        left: dict[str, str],
        right: dict[str, str],
        strategy: str,
    ) -> tuple[list[ConfigurationMergeEntry], int]:
        all_keys = sorted(set(list(left.keys()) + list(right.keys())))
        entries: list[ConfigurationMergeEntry] = []
        conflict_count = 0

        for key in all_keys:
            in_left = key in left
            in_right = key in right
            left_val = left.get(key, "")
            right_val = right.get(key, "")

            if in_left and in_right and left_val != right_val:
                conflict_count += 1
                merged_value = _resolve_conflict(
                    strategy, left_val, right_val
                )
                entries.append(ConfigurationMergeEntry(
                    key=key,
                    left_value=left_val,
                    right_value=right_val,
                    merged_value=merged_value,
                    conflict_detected=True,
                ))
            elif in_left and in_right:
                entries.append(ConfigurationMergeEntry(
                    key=key,
                    left_value=left_val,
                    right_value=right_val,
                    merged_value=left_val,
                    conflict_detected=False,
                ))
            elif in_left and not in_right:
                is_conflict = strategy == ConfigurationMergeStrategy.KEEP_IDENTICAL_ONLY.value
                if is_conflict:
                    conflict_count += 1
                merged_value = "" if is_conflict else left_val
                entries.append(ConfigurationMergeEntry(
                    key=key,
                    left_value=left_val,
                    right_value="",
                    merged_value=merged_value,
                    conflict_detected=is_conflict,
                ))
            else:
                is_conflict = strategy == ConfigurationMergeStrategy.KEEP_IDENTICAL_ONLY.value
                if is_conflict:
                    conflict_count += 1
                merged_value = "" if is_conflict else right_val
                entries.append(ConfigurationMergeEntry(
                    key=key,
                    left_value="",
                    right_value=right_val,
                    merged_value=merged_value,
                    conflict_detected=is_conflict,
                ))

        return entries, conflict_count

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        self._validate_id_segment(report_id, "report_id")
        return self._load_report(report_id)

    def list_reports(self) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        if not self._merge_dir.exists():
            return reports

        sandbox = self._merge_dir.resolve()
        for entry in self._merge_dir.iterdir():
            if not entry.is_dir():
                continue
            resolved = entry.resolve()
            if not str(resolved).startswith(str(sandbox) + "/") and resolved != sandbox:
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
            raise ValueError(f"Merge report not found: {report_id}")
        return self._generate_summary(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_report(self, report: ConfigurationMergeReport) -> None:
        report_dir = self._safe_merge_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def _load_report(self, report_id: str) -> dict[str, Any] | None:
        report_dir = self._safe_merge_path(report_id)
        report_file = report_dir / "report.json"
        if not report_file.exists():
            return None
        return json.loads(report_file.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def _write_evidence(self, report: ConfigurationMergeReport) -> None:
        evidence_dir = self._safe_merge_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = report.request.to_dict() if report.request else {}
        (evidence_dir / "config_merge_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        result_data = report.result.to_dict() if report.result else {}
        (evidence_dir / "config_merge_result.json").write_text(
            json.dumps(result_data, indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_summary(report.to_dict())
        (evidence_dir / "config_merge_summary.md").write_text(
            md, encoding="utf-8",
        )

        passed = report.result.status != ConfigurationMergeStatus.FAILED.value if report.result else True
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "status": report.result.status if report.result else "",
            "conflict_count": report.result.conflict_count if report.result else 0,
            "merged_count": report.result.merged_count if report.result else 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _generate_summary(data: dict[str, Any]) -> str:
        lines: list[str] = []

        lines.append("# Configuration Merge Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Summary: {data.get('merge_summary', '')}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        result = data.get("result")
        if result:
            lines.append("## Counts")
            lines.append("")
            lines.append(f"- Merged entries: {result.get('merged_count', 0)}")
            lines.append(f"- Conflicts: {result.get('conflict_count', 0)}")
            lines.append(f"- Status: {result.get('status', '')}")
            lines.append("")

            entries = result.get("merged_entries", [])
            if entries:
                lines.append("## Entries")
                lines.append("")
                for entry in entries:
                    conflict = " [CONFLICT]" if entry.get("conflict_detected") else ""
                    lines.append(
                        f"- {entry.get('key', '')}: "
                        f"merged='{entry.get('merged_value', '')}'{conflict}"
                    )
                lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _resolve_conflict(strategy: str, left_val: str, right_val: str) -> str:
    if strategy == ConfigurationMergeStrategy.LEFT_WINS.value:
        return left_val
    if strategy == ConfigurationMergeStrategy.RIGHT_WINS.value:
        return right_val
    if strategy == ConfigurationMergeStrategy.KEEP_IDENTICAL_ONLY.value:
        return ""
    if strategy == ConfigurationMergeStrategy.FAIL_ON_CONFLICT.value:
        return ""
    return left_val
