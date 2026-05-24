"""Discipline classifier for Revit inventory elements.

Classifies elements into discipline groups (Architectural, Structural,
Mechanical, Electrical, Plumbing, Other) using BuiltInCategory first,
then category name keyword fallback.  Includes ambiguity rules for
walls, floors, columns, generic models, and MEP crossovers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DISCIPLINES = [
    "Architectural",
    "Structural",
    "Mechanical",
    "Electrical",
    "Plumbing",
    "Other",
]

_MAPPING_PATH = Path(__file__).parent / "discipline_mapping.json"


@dataclass
class DisciplineClassification:
    """Result of classifying an element into a discipline."""

    discipline: str
    discipline_reason: str
    source_category: str
    source_built_in_category: str
    classification_confidence: str  # high, medium, low, unknown


def _load_mapping() -> dict:
    """Load the discipline category mapping from the JSON file."""
    with open(_MAPPING_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


_mapping_cache: Optional[dict] = None


def _get_mapping() -> dict:
    global _mapping_cache
    if _mapping_cache is None:
        _mapping_cache = _load_mapping()
    return _mapping_cache


def _build_bic_lookup(mapping: dict) -> dict[str, str]:
    """Build a BuiltInCategory -> discipline lookup from the mapping."""
    lookup: dict[str, str] = {}
    for discipline, info in mapping.get("disciplines", {}).items():
        for bic in info.get("high_confidence_categories", []):
            lookup[bic] = discipline
        for bic in info.get("default_categories", []):
            lookup[bic] = discipline
    return lookup


def _build_keyword_lookup(mapping: dict) -> list[tuple[str, str]]:
    """Build a (keyword, discipline) list sorted by keyword length desc."""
    pairs: list[tuple[str, str]] = []
    for discipline, info in mapping.get("disciplines", {}).items():
        for kw in info.get("category_name_keywords", []):
            pairs.append((kw, discipline))
    pairs.sort(key=lambda x: len(x[0]), reverse=True)
    return pairs


_bic_lookup_cache: Optional[dict[str, str]] = None
_keyword_lookup_cache: Optional[list[tuple[str, str]]] = None


def _get_bic_lookup() -> dict[str, str]:
    global _bic_lookup_cache
    if _bic_lookup_cache is None:
        _bic_lookup_cache = _build_bic_lookup(_get_mapping())
    return _bic_lookup_cache


def _get_keyword_lookup() -> list[tuple[str, str]]:
    global _keyword_lookup_cache
    if _keyword_lookup_cache is None:
        _keyword_lookup_cache = _build_keyword_lookup(_get_mapping())
    return _keyword_lookup_cache


def _is_structural_wall_or_floor(element: dict) -> bool:
    """Check if a wall/floor element has structural usage indicators."""
    for param in element.get("Parameters", []):
        name_lower = (param.get("Name") or "").lower()
        val_lower = (param.get("ValueString") or "").lower()
        if "structural" in name_lower and val_lower in (
            "true", "yes", "1", "structural",
        ):
            return True
        if name_lower == "structural usage" and val_lower:
            return True
    return False


def classify_element(element: dict) -> DisciplineClassification:
    """Classify a single inventory element into a discipline.

    Priority:
      1. Ambiguity rules (walls, floors, columns, generic models, MEP)
      2. BuiltInCategory lookup (high confidence)
      3. Category name keyword fallback (medium/low confidence)
      4. Default to Other (unknown confidence)
    """
    category = element.get("Category", "") or ""
    bic = element.get("BuiltInCategory", "") or ""

    # ── Ambiguity rules ──────────────────────────────────────────────

    # 1. Structural Columns vs Architectural Columns
    if bic == "OST_StructuralColumns" or "Structural Column" in category:
        return DisciplineClassification(
            discipline="Structural",
            discipline_reason="Structural column category",
            source_category=category,
            source_built_in_category=bic,
            classification_confidence="high",
        )

    # 2. Walls — check structural flags
    if bic == "OST_Walls" or category.startswith("Wall"):
        if _is_structural_wall_or_floor(element):
            return DisciplineClassification(
                discipline="Structural",
                discipline_reason="Wall with structural usage flag",
                source_category=category,
                source_built_in_category=bic,
                classification_confidence="medium",
            )
        return DisciplineClassification(
            discipline="Architectural",
            discipline_reason="Wall defaults to Architectural",
            source_category=category,
            source_built_in_category=bic,
            classification_confidence="high",
        )

    # 3. Floors — check structural flags
    if bic == "OST_Floors" or category.startswith("Floor"):
        if _is_structural_wall_or_floor(element):
            return DisciplineClassification(
                discipline="Structural",
                discipline_reason="Floor with structural usage flag",
                source_category=category,
                source_built_in_category=bic,
                classification_confidence="medium",
            )
        return DisciplineClassification(
            discipline="Architectural",
            discipline_reason="Floor defaults to Architectural",
            source_category=category,
            source_built_in_category=bic,
            classification_confidence="high",
        )

    # 4. Generic Models — default to Other
    if bic == "OST_GenericModel" or category == "Generic Models":
        return DisciplineClassification(
            discipline="Other",
            discipline_reason="Generic model defaults to Other",
            source_category=category,
            source_built_in_category=bic,
            classification_confidence="low",
        )

    # ── BuiltInCategory lookup ───────────────────────────────────────

    if bic:
        bic_lookup = _get_bic_lookup()
        disc = bic_lookup.get(bic)
        if disc:
            return DisciplineClassification(
                discipline=disc,
                discipline_reason=f"BuiltInCategory {bic}",
                source_category=category,
                source_built_in_category=bic,
                classification_confidence="high",
            )

    # ── Category name keyword fallback ───────────────────────────────

    if category:
        cat_lower = category.lower()
        for keyword, disc in _get_keyword_lookup():
            if keyword.lower() in cat_lower:
                return DisciplineClassification(
                    discipline=disc,
                    discipline_reason=f"Category name contains '{keyword}'",
                    source_category=category,
                    source_built_in_category=bic,
                    classification_confidence="medium",
                )

    # ── Default to Other ─────────────────────────────────────────────

    return DisciplineClassification(
        discipline="Other",
        discipline_reason="No matching category or keyword",
        source_category=category,
        source_built_in_category=bic,
        classification_confidence="unknown",
    )


def classify_elements(
    elements: list[dict],
) -> dict[str, list[dict]]:
    """Classify a list of elements into discipline buckets.

    Returns a dict mapping discipline name to list of elements.
    Each element gets discipline classification fields added.
    """
    buckets: dict[str, list[dict]] = {d: [] for d in DISCIPLINES}

    for elem in elements:
        result = classify_element(elem)
        elem["discipline"] = result.discipline
        elem["discipline_reason"] = result.discipline_reason
        elem["source_category"] = result.source_category
        elem["source_built_in_category"] = result.source_built_in_category
        elem["classification_confidence"] = result.classification_confidence
        buckets[result.discipline].append(elem)

    return buckets


def get_categories_for_discipline(discipline: str) -> list[str]:
    """Return the list of BuiltInCategories mapped to a discipline."""
    mapping = _get_mapping()
    info = mapping.get("disciplines", {}).get(discipline, {})
    cats = list(info.get("high_confidence_categories", []))
    cats.extend(info.get("default_categories", []))
    return cats
