"""Capability Input Framework v1.

Provides deterministic capability input handling on top of capability
definitions. Represents structured inputs required to run capabilities.

Non-goals: no capability execution, no autonomous planning, no workflow
engines, no schedulers.
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


class CapabilityInputType(str, Enum):
    TEXT = "text"
    JSON = "json"
    FILE_PATH = "file_path"
    CONFIGURATION = "configuration"
    LIST = "list"
    DICTIONARY = "dictionary"
    BOOLEAN = "boolean"
    NUMBER = "number"


class CapabilityInputStatus(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    MISSING = "missing"
    UNSUPPORTED = "unsupported"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CapabilityInput:
    """A structured input for a capability."""

    input_id: str = ""
    capability_id: str = ""
    name: str = ""
    input_type: str = "text"
    value: Any = None
    required: bool = True
    status: str = "valid"
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.input_id:
            self.input_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_id": self.input_id,
            "capability_id": self.capability_id,
            "name": self.name,
            "input_type": self.input_type,
            "value": self.value,
            "required": self.required,
            "status": self.status,
            "created_at": self.created_at,
        }


@dataclass
class CapabilityInputValidationResult:
    """Validation result for a capability input."""

    result_id: str = ""
    input_id: str = ""
    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.result_id:
            self.result_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "input_id": self.input_id,
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "created_at": self.created_at,
        }


@dataclass
class CapabilityInputReport:
    """Report summarizing capability inputs."""

    report_id: str = ""
    capability_id: str = ""
    input_count: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    missing_count: int = 0
    unsupported_count: int = 0
    inputs: list[CapabilityInput] = field(default_factory=list)
    validation_results: list[CapabilityInputValidationResult] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.report_id:
            self.report_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "capability_id": self.capability_id,
            "input_count": self.input_count,
            "valid_count": self.valid_count,
            "invalid_count": self.invalid_count,
            "missing_count": self.missing_count,
            "unsupported_count": self.unsupported_count,
            "inputs": [i.to_dict() for i in self.inputs],
            "validation_results": [v.to_dict() for v in self.validation_results],
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Capability input engine
# ---------------------------------------------------------------------------

_SUPPORTED_TYPES = {t.value for t in CapabilityInputType}


class CapabilityInputEngine:
    """Manages capability inputs deterministically."""

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._input_dir = self._artifacts_root / "capability_inputs"
        self._input_dir.mkdir(parents=True, exist_ok=True)

    def _safe_input_path(self, report_id: str) -> Path:
        target = (self._input_dir / report_id).resolve()
        sandbox = self._input_dir.resolve()
        if not str(target).startswith(str(sandbox) + "/") and target != sandbox:
            raise ValueError(f"Resolved path escapes artifacts root: {report_id!r}")
        return target

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"{name} must not be empty or whitespace")
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(f"{name} must not contain '..', '/', or '\\': {value!r}")

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(
        self,
        capability_id: str = "",
        inputs: list[dict[str, Any]] | None = None,
        known_capability_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create capability inputs and validate them."""
        inputs = inputs or []

        input_objects: list[CapabilityInput] = []
        validation_results: list[CapabilityInputValidationResult] = []

        for inp_data in sorted(inputs, key=lambda i: i.get("name", "")):
            inp = CapabilityInput(
                capability_id=capability_id,
                name=inp_data.get("name", ""),
                input_type=inp_data.get("input_type", "text"),
                value=inp_data.get("value"),
                required=inp_data.get("required", True),
                status=inp_data.get("status", "valid"),
            )

            errors: list[str] = []
            warnings: list[str] = []

            # Validate input type
            if inp.input_type not in _SUPPORTED_TYPES:
                inp.status = CapabilityInputStatus.UNSUPPORTED.value
                errors.append(f"Unsupported input type: {inp.input_type}")

            # Validate required inputs
            if inp.required and inp.value is None:
                inp.status = CapabilityInputStatus.MISSING.value
                errors.append(f"Required input '{inp.name}' has no value")

            # Validate capability reference
            if known_capability_ids is not None:
                if capability_id and capability_id not in known_capability_ids:
                    inp.status = CapabilityInputStatus.INVALID.value
                    errors.append(f"Unknown capability_id: {capability_id}")

            # Type-specific validation
            if inp.status == CapabilityInputStatus.VALID.value and inp.value is not None:
                type_error = self._validate_type(inp.input_type, inp.value)
                if type_error:
                    inp.status = CapabilityInputStatus.INVALID.value
                    errors.append(type_error)

            valid = len(errors) == 0
            vr = CapabilityInputValidationResult(
                input_id=inp.input_id,
                valid=valid,
                errors=errors,
                warnings=warnings,
            )

            input_objects.append(inp)
            validation_results.append(vr)

        valid_count = sum(1 for i in input_objects if i.status == CapabilityInputStatus.VALID.value)
        invalid_count = sum(
            1 for i in input_objects if i.status == CapabilityInputStatus.INVALID.value
        )
        missing_count = sum(
            1 for i in input_objects if i.status == CapabilityInputStatus.MISSING.value
        )
        unsupported_count = sum(
            1 for i in input_objects if i.status == CapabilityInputStatus.UNSUPPORTED.value
        )

        report = CapabilityInputReport(
            capability_id=capability_id,
            input_count=len(input_objects),
            valid_count=valid_count,
            invalid_count=invalid_count,
            missing_count=missing_count,
            unsupported_count=unsupported_count,
            inputs=input_objects,
            validation_results=validation_results,
        )

        self._persist_report(report)
        self._write_evidence(report)

        return report.to_dict()

    @staticmethod
    def _validate_type(input_type: str, value: Any) -> str | None:
        """Type-specific validation. Returns error message or None."""
        if input_type == CapabilityInputType.BOOLEAN.value:
            if not isinstance(value, bool):
                return f"Expected boolean, got {type(value).__name__}"
        elif input_type == CapabilityInputType.NUMBER.value:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return f"Expected number, got {type(value).__name__}"
        elif input_type == CapabilityInputType.LIST.value:
            if not isinstance(value, list):
                return f"Expected list, got {type(value).__name__}"
        elif input_type == CapabilityInputType.DICTIONARY.value:
            if not isinstance(value, dict):
                return f"Expected dictionary, got {type(value).__name__}"
        return None

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        self._validate_id_segment(report_id, "report_id")
        return self._load_report(report_id)

    def list_reports(self) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        if not self._input_dir.exists():
            return reports

        sandbox = self._input_dir.resolve()
        for entry in self._input_dir.iterdir():
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
            raise ValueError(f"Capability input report not found: {report_id}")
        return self._generate_summary(data)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_report(self, report: CapabilityInputReport) -> None:
        report_dir = self._safe_input_path(report.report_id)
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def _load_report(self, report_id: str) -> dict[str, Any] | None:
        report_dir = self._safe_input_path(report_id)
        report_file = report_dir / "report.json"
        if not report_file.exists():
            return None
        return json.loads(report_file.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def _write_evidence(self, report: CapabilityInputReport) -> None:
        evidence_dir = self._safe_input_path(report.report_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "capability_id": report.capability_id,
            "inputs": [i.to_dict() for i in report.inputs],
        }
        (evidence_dir / "capability_input_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
            encoding="utf-8",
        )

        result_data = report.to_dict()
        (evidence_dir / "capability_input_result.json").write_text(
            json.dumps(result_data, indent=2, default=str),
            encoding="utf-8",
        )

        md = self._generate_summary(report.to_dict())
        (evidence_dir / "capability_input_summary.md").write_text(
            md,
            encoding="utf-8",
        )

        passed = report.invalid_count == 0 and report.missing_count == 0 and report.unsupported_count == 0
        pass_fail = {
            "passed": passed,
            "report_id": report.report_id,
            "capability_id": report.capability_id,
            "valid_count": report.valid_count,
            "invalid_count": report.invalid_count,
            "missing_count": report.missing_count,
            "unsupported_count": report.unsupported_count,
            "status": "passed" if passed else "failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _generate_summary(data: dict[str, Any]) -> str:
        lines: list[str] = []

        lines.append("# Capability Input Report")
        lines.append("")
        lines.append(f"- Report ID: {data.get('report_id', '')}")
        lines.append(f"- Capability ID: {data.get('capability_id', '')}")
        lines.append(f"- Input Count: {data.get('input_count', 0)}")
        lines.append(f"- Valid: {data.get('valid_count', 0)}")
        lines.append(f"- Invalid: {data.get('invalid_count', 0)}")
        lines.append(f"- Missing: {data.get('missing_count', 0)}")
        lines.append(f"- Unsupported: {data.get('unsupported_count', 0)}")
        lines.append(f"- Created: {data.get('created_at', '')}")
        lines.append("")

        inputs = data.get("inputs", [])
        if inputs:
            lines.append("## Inputs")
            lines.append("")
            for inp in inputs:
                status = inp.get("status", "").upper()
                itype = inp.get("input_type", "")
                req = "required" if inp.get("required") else "optional"
                lines.append(f"- [{status}] {inp.get('name', '')} " f"(type: {itype}, {req})")
            lines.append("")

        vrs = data.get("validation_results", [])
        errors_found = [vr for vr in vrs if vr.get("errors")]
        if errors_found:
            lines.append("## Validation Errors")
            lines.append("")
            for vr in errors_found:
                for err in vr.get("errors", []):
                    lines.append(f"- {err}")
            lines.append("")

        return "\n".join(lines)
