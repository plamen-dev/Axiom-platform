"""Input Normalization Layer - Transforms raw inputs into NormalizedJob objects."""

from typing import Any, Optional
from uuid import uuid4

import openpyxl
from pydantic import BaseModel, Field

from axiom_core.schemas import (
    Job,
    JobStatus,
    JobType,
    NormalizedJob,
    ScopeBoxDef,
    ViewRequirement,
)


class NormalizationWarning(BaseModel):
    """A non-fatal warning during normalization."""

    field: str
    message: str
    original_value: Optional[str] = None


class NormalizationError(BaseModel):
    """A fatal error during normalization."""

    field: str
    message: str
    original_value: Optional[str] = None


class NormalizationReport(BaseModel):
    """Report from the normalization process."""

    success: bool
    job: Optional[Job] = None
    normalized_job: Optional[NormalizedJob] = None
    warnings: list[NormalizationWarning] = Field(default_factory=list)
    errors: list[NormalizationError] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class FirmMapping(BaseModel):
    """Firm-specific column mappings and defaults."""

    firm_id: str
    column_mappings: dict[str, list[str]] = Field(default_factory=dict)
    default_values: dict[str, Any] = Field(default_factory=dict)
    view_type_mappings: dict[str, list[str]] = Field(default_factory=dict)


DEFAULT_COLUMN_MAPPINGS = {
    "project_number": ["Project Number", "Proj #", "Project ID"],
    "project_name": ["Project Name/Recommended File Name", "Project Name", "Name"],
    "revit_version": ["Project Revit Version", "Revit Version", "Version"],
    "is_acc_project": ["Is this an ACC project?", "ACC Project", "Is ACC"],
    "scope_boxes": [
        "Will the footprint of the project be divided by areas",
        "Scope Boxes",
    ],
    "views_required": [
        "Indicate what views will be needed",
        "Views Required",
        "Views",
    ],
    "engineer_stamps": ["Which engineer's stamp", "Engineer Stamp", "Stamp"],
    "team_assignments": ["List the names of the Mech and Elec Engineers", "Team"],
    "bep_path": ["BIM Execution Plan", "BEP Path", "BEP"],
    "sheet_list_path": ["Sheets to be created", "Sheet List", "Sheet List Path"],
    "additional_comments": ["Additional comments", "Comments", "Notes"],
    "phase_scope": ["Phase related scope", "Has Phases", "Phase Scope"],
    "due_date": ["Due Date", "Due"],
}

VIEW_TYPE_CODES = [
    "E - General",
    "E - Lighting",
    "E - Lighting & Power",
    "E - Lighting & Power & Systems",
    "E - Power",
    "E - Power & Systems",
    "E - Systems",
    "M - HVAC",
    "M - HVAC Piping",
    "M - HVAC Zoning",
    "M - Fuel",
    "M - Misc Piping",
    "P - Hot & Cold Water",
    "P - Medical Gas",
    "P - Plumbing",
    "P - Sanitary Sewer & Storm Drainage",
]


class InputNormalizer:
    """Normalizes raw inputs into validated NormalizedJob objects."""

    def __init__(self, firm_mapping: Optional[FirmMapping] = None):
        self.firm_mapping = firm_mapping
        self.column_mappings = DEFAULT_COLUMN_MAPPINGS.copy()
        if firm_mapping and firm_mapping.column_mappings:
            for key, values in firm_mapping.column_mappings.items():
                if key in self.column_mappings:
                    self.column_mappings[key] = values + self.column_mappings[key]
                else:
                    self.column_mappings[key] = values

    def normalize_excel(self, file_path: str, firm_id: str) -> NormalizationReport:
        """Normalize an Excel file into a NormalizedJob."""
        report = NormalizationReport(success=False)

        try:
            wb = openpyxl.load_workbook(file_path)
            sheet = wb.active

            if sheet is None:
                report.errors.append(
                    NormalizationError(field="file", message="Excel file has no active sheet")
                )
                return report

            headers = [cell.value for cell in sheet[1]]
            header_map = self._build_header_map(headers)

            if sheet.max_row < 2:
                report.errors.append(
                    NormalizationError(field="file", message="Excel file has no data rows")
                )
                return report

            data_row = list(sheet[2])
            raw_data = {
                headers[i]: cell.value for i, cell in enumerate(data_row) if i < len(headers)
            }

            return self._normalize_row(raw_data, header_map, firm_id, report)

        except FileNotFoundError:
            report.errors.append(
                NormalizationError(
                    field="file", message=f"File not found: {file_path}", original_value=file_path
                )
            )
            return report
        except Exception as e:
            report.errors.append(
                NormalizationError(field="file", message=f"Error reading Excel file: {str(e)}")
            )
            return report

    def normalize_dict(self, data: dict[str, Any], firm_id: str) -> NormalizationReport:
        """Normalize a dictionary into a NormalizedJob."""
        report = NormalizationReport(success=False)
        header_map = self._build_header_map(list(data.keys()))
        return self._normalize_row(data, header_map, firm_id, report)

    def _build_header_map(self, headers: list[Optional[str]]) -> dict[str, str]:
        """Map canonical field names to actual column headers."""
        header_map: dict[str, str] = {}
        headers_lower = {h.lower(): h for h in headers if h}

        for field, possible_names in self.column_mappings.items():
            for name in possible_names:
                name_lower = name.lower()
                for header_lower, header in headers_lower.items():
                    if name_lower in header_lower or header_lower in name_lower:
                        header_map[field] = header
                        break
                if field in header_map:
                    break

        return header_map

    def _get_value(
        self, data: dict[str, Any], header_map: dict[str, str], field: str
    ) -> Optional[Any]:
        """Get a value from the data using the header map."""
        if field in header_map:
            return data.get(header_map[field])
        return data.get(field)

    def _normalize_row(
        self,
        data: dict[str, Any],
        header_map: dict[str, str],
        firm_id: str,
        report: NormalizationReport,
    ) -> NormalizationReport:
        """Normalize a single row of data."""
        project_number = self._get_value(data, header_map, "project_number")
        if not project_number:
            report.errors.append(
                NormalizationError(field="project_number", message="Project number is required")
            )

        project_name = self._get_value(data, header_map, "project_name")
        if not project_name:
            report.errors.append(
                NormalizationError(field="project_name", message="Project name is required")
            )

        revit_version_raw = self._get_value(data, header_map, "revit_version")
        revit_version = self._parse_revit_version(revit_version_raw, report)

        is_acc_raw = self._get_value(data, header_map, "is_acc_project")
        is_acc_project = self._parse_boolean(is_acc_raw, "is_acc_project", report)

        views_raw = self._get_value(data, header_map, "views_required")
        views_required = self._parse_views(views_raw, report)

        if not views_required:
            report.errors.append(
                NormalizationError(
                    field="views_required", message="At least one view type is required"
                )
            )

        scope_boxes_raw = self._get_value(data, header_map, "scope_boxes")
        scope_boxes = self._parse_scope_boxes(scope_boxes_raw, report)

        phase_scope_raw = self._get_value(data, header_map, "phase_scope")
        phase_scope = self._parse_boolean(phase_scope_raw, "phase_scope", report)

        engineer_stamps_raw = self._get_value(data, header_map, "engineer_stamps")
        engineer_stamps = self._parse_list(engineer_stamps_raw) if engineer_stamps_raw else []

        if report.errors:
            return report

        job_id = uuid4()

        job = Job(
            job_id=job_id,
            job_type=JobType.PROJECT_SETUP,
            firm_id=firm_id,
            source="EXCEL",
            raw_inputs=data,
            status=JobStatus.NORMALIZING,
        )

        normalized_job = NormalizedJob(
            job_id=job_id,
            job_type=JobType.PROJECT_SETUP,
            firm_id=firm_id,
            source="EXCEL",
            project_number=str(project_number),
            project_name=str(project_name),
            revit_version=revit_version,
            is_acc_project=is_acc_project,
            scope_boxes=scope_boxes,
            views_required=views_required,
            engineer_stamps=engineer_stamps,
            team_assignments=self._get_value(data, header_map, "team_assignments"),
            bep_path=self._get_value(data, header_map, "bep_path"),
            sheet_list_path=self._get_value(data, header_map, "sheet_list_path"),
            additional_comments=self._get_value(data, header_map, "additional_comments"),
            phase_scope=phase_scope,
        )

        report.success = True
        report.job = job
        report.normalized_job = normalized_job
        return report

    def _parse_revit_version(
        self, value: Any, report: NormalizationReport
    ) -> int:
        """Parse Revit version from various formats."""
        if value is None:
            report.errors.append(
                NormalizationError(field="revit_version", message="Revit version is required")
            )
            return 2023

        try:
            version = int(value)
            if version < 2020 or version > 2030:
                report.warnings.append(
                    NormalizationWarning(
                        field="revit_version",
                        message=f"Unusual Revit version: {version}",
                        original_value=str(value),
                    )
                )
            return version
        except (ValueError, TypeError):
            report.errors.append(
                NormalizationError(
                    field="revit_version",
                    message=f"Invalid Revit version: {value}",
                    original_value=str(value),
                )
            )
            return 2023

    def _parse_boolean(
        self, value: Any, field: str, report: NormalizationReport
    ) -> bool:
        """Parse boolean from various formats."""
        if value is None:
            return False

        if isinstance(value, bool):
            return value

        str_value = str(value).lower().strip()
        if str_value in ("yes", "true", "1", "y"):
            return True
        if str_value in ("no", "false", "0", "n", ""):
            return False

        report.warnings.append(
            NormalizationWarning(
                field=field,
                message="Could not parse boolean, defaulting to False",
                original_value=str(value),
            )
        )
        return False

    def _parse_views(
        self, value: Any, report: NormalizationReport
    ) -> list[ViewRequirement]:
        """Parse view requirements from semicolon-separated string."""
        if not value:
            return []

        views = []
        raw_views = str(value).split(";")

        for raw_view in raw_views:
            view_code = raw_view.strip()
            if not view_code:
                continue

            matched = False
            for valid_code in VIEW_TYPE_CODES:
                if view_code.lower() == valid_code.lower() or valid_code.lower() in view_code.lower():
                    views.append(ViewRequirement(view_type_code=valid_code))
                    matched = True
                    break

            if not matched:
                report.warnings.append(
                    NormalizationWarning(
                        field="views_required",
                        message=f"Unknown view type: {view_code}",
                        original_value=view_code,
                    )
                )

        return views

    def _parse_scope_boxes(
        self, value: Any, report: NormalizationReport
    ) -> list[ScopeBoxDef]:
        """Parse scope box definitions from description string."""
        if not value:
            return []

        scope_boxes = []
        str_value = str(value)

        import re

        count_match = re.search(r"(\d+)\s*(?:scope\s*box|area)", str_value.lower())
        if count_match:
            count = int(count_match.group(1))

            names = re.findall(r"(?:for|:)\s*([^,;]+(?:,\s*[^,;]+)*)", str_value, re.IGNORECASE)
            if names:
                name_list = [n.strip() for n in names[0].split(",")]
                for name in name_list[:count]:
                    scope_boxes.append(ScopeBoxDef(name=name.strip(), copy_from_arch=True))

            while len(scope_boxes) < count:
                scope_boxes.append(
                    ScopeBoxDef(name=f"Scope Box {len(scope_boxes) + 1}", copy_from_arch=True)
                )

            report.assumptions.append(
                f"Parsed {count} scope boxes from description: {str_value}"
            )

        return scope_boxes

    def _parse_list(self, value: Any) -> list[str]:
        """Parse a list from various formats."""
        if not value:
            return []

        if isinstance(value, list):
            return [str(v) for v in value]

        str_value = str(value)
        if ";" in str_value:
            return [v.strip() for v in str_value.split(";") if v.strip()]
        if "," in str_value:
            return [v.strip() for v in str_value.split(",") if v.strip()]

        return [str_value]
