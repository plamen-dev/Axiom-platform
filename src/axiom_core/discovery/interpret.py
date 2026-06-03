"""Pure interpretation of InventoryModel exports into discovery facts.

DiscoveryHarness v1 sits ABOVE InventoryModel and never extracts/scans. This
module contains only pure functions that transform an already-produced
InventoryModel export (the JSON handoff artifact, same shape persisted by
``axiom_core.inventory.storage``) into interpreted facts:

  - discovered categories      -> ProductObjectRegistry
  - discovered properties      -> ProductPropertyRegistry (with value contract)
  - candidate capabilities     -> CandidateCapabilityGenerator output
  - discovery evidence records
  - run metrics

No I/O, no Revit, no database here - that lives in ``registries`` / ``reports``
/ ``harness``. This keeps interpretation deterministic and unit-testable.

Value contract (PR #20):
StorageType alone is NOT sufficient. A ``Double`` may represent length, area,
volume, angle, airflow, slope, temperature, electrical load, etc., so a Double
parameter is only ``safely_settable_by_axiom`` when semantic/unit metadata
(spec_type_id / unit_type_id / display_unit) is present in the export.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Storage types for which a writable parameter yields a SetParameterValue
# candidate. Confirmed scope (PR #20): String, Integer, Double, ElementId.
SUPPORTED_STORAGE_TYPES = ("String", "Integer", "Double", "ElementId")

# Storage types that require semantic/unit metadata before they can be set
# safely (a bare Double is ambiguous).
UNIT_DEPENDENT_STORAGE_TYPES = ("Double",)

ADAPTER = "revit"
MAX_SAMPLE_VALUES = 5


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug(value: str) -> str:
    """Lowercase, non-alphanumeric -> single underscore (for stable ids)."""
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")


@dataclass
class DiscoveredCategory:
    category_name: str
    built_in_category: str = ""
    category_id: int | None = None
    element_count: int = 0  # instance count only (excludes type definitions)
    type_count: int = 0
    adapter: str = ADAPTER


@dataclass
class DiscoveredProperty:
    category: str
    parameter_name: str
    storage_type: str
    read_only: bool
    instance_parameter: bool
    built_in_parameter_id: str = ""
    # ---- value contract metadata (captured where available) ----
    spec_type_id: str = ""
    unit_type_id: str = ""
    display_unit: str = ""
    format_options: str = ""
    has_value: bool = False
    sample_values: list[str] = field(default_factory=list)
    expected_input_format: str = ""
    safely_settable_by_axiom: bool = False
    adapter: str = ADAPTER

    @property
    def parameter_kind(self) -> str:
        return "instance" if self.instance_parameter else "type"


@dataclass
class CandidateCapability:
    candidate_id: str
    capability: str
    category: str
    parameter_name: str
    storage_type: str
    instance_parameter: bool
    spec_type_id: str = ""
    unit_type_id: str = ""
    expected_input_format: str = ""
    safely_settable_by_axiom: bool = False
    status: str = "candidate"
    adapter: str = ADAPTER

    @property
    def parameter_kind(self) -> str:
        return "instance" if self.instance_parameter else "type"


@dataclass
class DiscoveryEvidenceRecord:
    run_id: str
    discovery_type: str  # "category" | "parameter" | "candidate"
    object: str
    result: str
    property: str | None = None
    adapter: str = ADAPTER
    timestamp: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "discovery_type": self.discovery_type,
            "adapter": self.adapter,
            "object": self.object,
            "property": self.property,
            "result": self.result,
            "timestamp": self.timestamp,
        }


@dataclass
class DiscoveryMetrics:
    categories_discovered: int = 0
    parameters_discovered: int = 0
    writable_parameters: int = 0
    read_only_parameters: int = 0
    instance_parameters: int = 0
    type_parameters: int = 0
    safely_settable_parameters: int = 0
    candidate_capabilities_generated: int = 0

    def to_dict(self) -> dict:
        return {
            "categories_discovered": self.categories_discovered,
            "parameters_discovered": self.parameters_discovered,
            "writable_parameters": self.writable_parameters,
            "read_only_parameters": self.read_only_parameters,
            "instance_parameters": self.instance_parameters,
            "type_parameters": self.type_parameters,
            "safely_settable_parameters": self.safely_settable_parameters,
            "candidate_capabilities_generated": self.candidate_capabilities_generated,
        }


@dataclass
class Interpretation:
    categories: list[DiscoveredCategory]
    properties: list[DiscoveredProperty]
    candidates: list[CandidateCapability]
    evidence: list[DiscoveryEvidenceRecord]
    metrics: DiscoveryMetrics
    source_model: str
    scan_mode: str
    object_source: str = ""
    parameter_source: str = ""
    # Diagnostics from the parameter source join (None when no source detected).
    parameter_rows_total: int | None = None
    parameter_rows_joined: int | None = None

    @property
    def parameter_source_present(self) -> bool:
        return bool(self.parameter_source)

    @property
    def discovery_complete(self) -> bool:
        """Complete only when parameters were actually discovered.

        A detected-but-empty/unusable parameter source (0 parameters) is NOT
        complete, and neither is category-only discovery (no source at all).
        """
        return self.metrics.parameters_discovered > 0

    @property
    def warnings(self) -> list[str]:
        msgs: list[str] = []
        if self.metrics.parameters_discovered > 0:
            return msgs
        if not self.parameter_source_present:
            msgs.append(
                "Parameter source missing/not provided: discovered categories "
                "only (no parameters/candidates). Point --inventory-export-path "
                "at an InventoryModel run folder containing parameters.parquet "
                "for full parameter discovery."
            )
        elif self.parameter_rows_total == 0:
            msgs.append(
                f"Parameter source '{self.parameter_source}' contained no "
                "usable parameter rows (empty or schema-only) - category-only "
                "discovery. Re-run InventoryModel in a full-detail (non-summary) "
                "mode that dumps parameters."
            )
        elif self.parameter_rows_joined == 0:
            msgs.append(
                f"Parameter source '{self.parameter_source}' had "
                f"{self.parameter_rows_total} rows but none matched elements by "
                "element_id (join key mismatch) - category-only discovery."
            )
        else:
            msgs.append(
                f"Parameter source '{self.parameter_source}' produced no "
                "discoverable parameters - category-only discovery."
            )
        return msgs


def _coerce_category_id(elem: dict) -> int | None:
    raw = elem.get("CategoryId")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def interpret_categories(elements: list[dict]) -> list[DiscoveredCategory]:
    """Group elements by category; element_count = instances, type_count = types."""
    by_name: dict[str, DiscoveredCategory] = {}
    for elem in elements:
        name = elem.get("Category") or "(No Category)"
        cat = by_name.get(name)
        if cat is None:
            cat = DiscoveredCategory(
                category_name=name,
                built_in_category=elem.get("BuiltInCategory", ""),
                category_id=_coerce_category_id(elem),
            )
            by_name[name] = cat
        if elem.get("IsType", False):
            cat.type_count += 1
        else:
            cat.element_count += 1
        if not cat.built_in_category:
            cat.built_in_category = elem.get("BuiltInCategory", "")
        if cat.category_id is None:
            cat.category_id = _coerce_category_id(elem)
    return [by_name[k] for k in sorted(by_name)]


def _param_spec_type(param: dict) -> str:
    # Accept both raw element-export naming and InventoryModel schema naming.
    return (
        param.get("SpecTypeId")
        or param.get("ForgeTypeId")
        or param.get("DataTypeId")
        or ""
    )


def _param_unit_type(param: dict) -> str:
    return param.get("UnitTypeId") or ""


def _param_display_unit(param: dict) -> str:
    return param.get("DisplayUnit") or param.get("UnitLabel") or ""


def _param_format_options(param: dict) -> str:
    fmt = param.get("FormatOptions")
    if fmt is None:
        return ""
    if isinstance(fmt, (dict, list)):
        return json.dumps(fmt, default=str, sort_keys=True)
    return str(fmt)


def _param_value_string(param: dict) -> str:
    val = param.get("ValueString")
    return "" if val is None else str(val)


def _param_has_value(param: dict) -> bool:
    if _param_value_string(param):
        return True
    return param.get("ValueDouble") is not None or param.get("ValueInt") is not None


def _expected_input_format(storage_type: str, unit_hint: str) -> str:
    if storage_type == "String":
        return "text"
    if storage_type == "Integer":
        return "integer"
    if storage_type == "ElementId":
        return "element_id (integer)"
    if storage_type == "Double":
        return f"double ({unit_hint})" if unit_hint else "double (unit unknown)"
    return storage_type.lower() if storage_type else "unknown"


def _is_safely_settable(
    storage_type: str, read_only: bool, unit_hint: str
) -> bool:
    """Encode the value contract safety rule.

    StorageType alone is insufficient: a unit-dependent type (Double) needs
    semantic/unit metadata before Axiom may set it.
    """
    if read_only:
        return False
    if storage_type not in SUPPORTED_STORAGE_TYPES:
        return False
    if storage_type in UNIT_DEPENDENT_STORAGE_TYPES and not unit_hint:
        return False
    return True


def interpret_properties(elements: list[dict]) -> list[DiscoveredProperty]:
    """Derive distinct parameters per (category, name, instance/type).

    Instance vs type is derived exactly as InventoryModel does:
    ``is_instance_param = not element.IsType``. A parameter observed as both an
    instance and a type parameter is recorded as two correctly-labeled rows.
    Value-contract metadata and sample values are accumulated across elements.
    """
    acc: dict[tuple, DiscoveredProperty] = {}
    for elem in elements:
        category = elem.get("Category") or "(No Category)"
        is_instance = not elem.get("IsType", False)
        for param in elem.get("Parameters", []) or []:
            pname = param.get("Name", "")
            if not pname:
                continue
            key = (category, pname, is_instance)
            spec_type = _param_spec_type(param)
            unit_type = _param_unit_type(param)
            display_unit = _param_display_unit(param)
            unit_hint = display_unit or unit_type or spec_type
            storage_type = param.get("StorageType", "")
            read_only = bool(param.get("IsReadOnly", False))

            prop = acc.get(key)
            if prop is None:
                prop = DiscoveredProperty(
                    category=category,
                    parameter_name=pname,
                    storage_type=storage_type,
                    read_only=read_only,
                    instance_parameter=is_instance,
                    built_in_parameter_id=param.get("BuiltInParameterId", ""),
                    spec_type_id=spec_type,
                    unit_type_id=unit_type,
                    display_unit=display_unit,
                    format_options=_param_format_options(param),
                    expected_input_format=_expected_input_format(storage_type, unit_hint),
                    safely_settable_by_axiom=_is_safely_settable(
                        storage_type, read_only, unit_hint
                    ),
                )
                acc[key] = prop
            else:
                # Enrich missing metadata from later observations.
                prop.spec_type_id = prop.spec_type_id or spec_type
                prop.unit_type_id = prop.unit_type_id or unit_type
                prop.display_unit = prop.display_unit or display_unit
                if not prop.format_options:
                    prop.format_options = _param_format_options(param)
                new_unit_hint = prop.display_unit or prop.unit_type_id or prop.spec_type_id
                prop.expected_input_format = _expected_input_format(
                    prop.storage_type, new_unit_hint
                )
                prop.safely_settable_by_axiom = _is_safely_settable(
                    prop.storage_type, prop.read_only, new_unit_hint
                )

            if _param_has_value(param):
                prop.has_value = True
            sample = _param_value_string(param)
            if (
                sample
                and sample not in prop.sample_values
                and len(prop.sample_values) < MAX_SAMPLE_VALUES
            ):
                prop.sample_values.append(sample)

    return [
        acc[k]
        for k in sorted(acc, key=lambda t: (t[0], t[1], not t[2]))
    ]


def generate_candidates(
    properties: list[DiscoveredProperty],
) -> list[CandidateCapability]:
    """One SetParameterValue candidate per writable supported-type parameter.

    Includes BOTH instance and type parameters, each labeled correctly, and
    each carries the value contract (incl. ``safely_settable_by_axiom``) so a
    future validation loop can gate on it. Nothing is executed/validated/promoted.
    """
    candidates: list[CandidateCapability] = []
    for prop in properties:
        if prop.read_only:
            continue
        if prop.storage_type not in SUPPORTED_STORAGE_TYPES:
            continue
        kind = prop.parameter_kind
        candidate_id = (
            f"cand_{ADAPTER}_{_slug(prop.category)}_"
            f"{_slug(prop.parameter_name)}_{kind}_setparametervalue"
        )
        candidates.append(
            CandidateCapability(
                candidate_id=candidate_id,
                capability="SetParameterValue",
                category=prop.category,
                parameter_name=prop.parameter_name,
                storage_type=prop.storage_type,
                instance_parameter=prop.instance_parameter,
                spec_type_id=prop.spec_type_id,
                unit_type_id=prop.unit_type_id,
                expected_input_format=prop.expected_input_format,
                safely_settable_by_axiom=prop.safely_settable_by_axiom,
            )
        )
    return candidates


def compute_metrics(
    categories: list[DiscoveredCategory],
    properties: list[DiscoveredProperty],
    candidates: list[CandidateCapability],
) -> DiscoveryMetrics:
    return DiscoveryMetrics(
        categories_discovered=len(categories),
        parameters_discovered=len(properties),
        writable_parameters=sum(1 for p in properties if not p.read_only),
        read_only_parameters=sum(1 for p in properties if p.read_only),
        instance_parameters=sum(1 for p in properties if p.instance_parameter),
        type_parameters=sum(1 for p in properties if not p.instance_parameter),
        safely_settable_parameters=sum(
            1 for p in properties if p.safely_settable_by_axiom
        ),
        candidate_capabilities_generated=len(candidates),
    )


def interpret_export(export: dict, run_id: str) -> Interpretation:
    """Transform a loaded InventoryModel export into discovery facts.

    ``export`` is the parsed JSON handoff (keys: ``document_title``,
    ``scan_mode``, ``elements``). Summary-only exports with no elements yield
    zero properties/candidates but are still valid (per InventoryModel rules,
    zero parameters in summary mode does not mean no data).
    """
    elements = export.get("elements", []) or []
    source_model = export.get("document_title", "") or ""
    scan_mode = export.get("scan_mode", "") or ""

    object_source = export.get("object_source", "") or ""
    if not object_source and elements:
        object_source = "export"
    # parameter_source is set explicitly by the loader (e.g. parameters.parquet);
    # otherwise infer "embedded" when elements already carry Parameters.
    parameter_source = export.get("parameter_source", "") or ""
    if not parameter_source and any(
        (e.get("Parameters") for e in elements)
    ):
        parameter_source = "embedded"

    categories = interpret_categories(elements)
    properties = interpret_properties(elements)
    candidates = generate_candidates(properties)
    metrics = compute_metrics(categories, properties, candidates)

    evidence: list[DiscoveryEvidenceRecord] = []
    for cat in categories:
        evidence.append(
            DiscoveryEvidenceRecord(
                run_id=run_id,
                discovery_type="category",
                object=cat.category_name,
                result="discovered",
            )
        )
    for prop in properties:
        evidence.append(
            DiscoveryEvidenceRecord(
                run_id=run_id,
                discovery_type="parameter",
                object=prop.category,
                property=prop.parameter_name,
                result=f"discovered:{prop.parameter_kind}",
            )
        )
    for cand in candidates:
        evidence.append(
            DiscoveryEvidenceRecord(
                run_id=run_id,
                discovery_type="candidate",
                object=cand.category,
                property=cand.parameter_name,
                result=f"candidate:{cand.parameter_kind}",
            )
        )

    return Interpretation(
        categories=categories,
        properties=properties,
        candidates=candidates,
        evidence=evidence,
        metrics=metrics,
        source_model=source_model,
        scan_mode=scan_mode,
        object_source=object_source,
        parameter_source=parameter_source,
        parameter_rows_total=export.get("parameter_rows_total"),
        parameter_rows_joined=export.get("parameter_rows_joined"),
    )
