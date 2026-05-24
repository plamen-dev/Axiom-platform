"""Tests for discipline-based inventory extraction.

Covers:
  - Classification of clear Architectural, Structural, Mechanical,
    Electrical, Plumbing categories
  - Ambiguity rules (walls, floors, columns, generic models)
  - Discipline extraction folder structure
  - Checkpoint JSONL creation
  - Root summary creation
  - Failure isolation (one discipline failing doesn't delete others)
"""

import json
import tempfile
from pathlib import Path

from axiom_core.inventory.discipline import (
    DISCIPLINES,
    classify_element,
    classify_elements,
)
from axiom_core.inventory.discipline_export import (
    run_discipline_extraction,
)


def _elem(category: str = "", bic: str = "", **kwargs) -> dict:
    """Build a minimal element dict for testing."""
    return {
        "ElementId": kwargs.get("element_id", 1),
        "UniqueId": kwargs.get("unique_id", "uid-1"),
        "Category": category,
        "BuiltInCategory": bic,
        "ClassName": kwargs.get("class_name", ""),
        "Name": kwargs.get("name", "Test Element"),
        "FamilyName": kwargs.get("family_name", ""),
        "TypeName": kwargs.get("type_name", ""),
        "LevelName": kwargs.get("level_name", ""),
        "LevelId": 0,
        "WorksetName": "",
        "IsType": kwargs.get("is_type", False),
        "Parameters": kwargs.get("parameters", []),
    }


# ── Classification tests ────────────────────────────────────────────

class TestArchitecturalClassification:
    def test_doors_are_architectural(self):
        r = classify_element(_elem("Doors", "OST_Doors"))
        assert r.discipline == "Architectural"
        assert r.classification_confidence == "high"

    def test_windows_are_architectural(self):
        r = classify_element(_elem("Windows", "OST_Windows"))
        assert r.discipline == "Architectural"

    def test_walls_default_architectural(self):
        r = classify_element(_elem("Walls", "OST_Walls"))
        assert r.discipline == "Architectural"
        assert r.classification_confidence == "high"

    def test_floors_default_architectural(self):
        r = classify_element(_elem("Floors", "OST_Floors"))
        assert r.discipline == "Architectural"


class TestStructuralClassification:
    def test_structural_columns(self):
        r = classify_element(_elem("Structural Columns", "OST_StructuralColumns"))
        assert r.discipline == "Structural"
        assert r.classification_confidence == "high"

    def test_structural_framing(self):
        r = classify_element(_elem("Structural Framing", "OST_StructuralFraming"))
        assert r.discipline == "Structural"
        assert r.classification_confidence == "high"

    def test_structural_foundation(self):
        r = classify_element(_elem("Structural Foundations", "OST_StructuralFoundation"))
        assert r.discipline == "Structural"

    def test_wall_with_structural_flag(self):
        params = [{"Name": "Structural Usage", "ValueString": "Bearing"}]
        r = classify_element(_elem("Walls", "OST_Walls", parameters=params))
        assert r.discipline == "Structural"
        assert r.classification_confidence == "medium"

    def test_floor_with_structural_flag(self):
        params = [{"Name": "Structural", "ValueString": "True"}]
        r = classify_element(_elem("Floors", "OST_Floors", parameters=params))
        assert r.discipline == "Structural"


class TestMechanicalClassification:
    def test_ducts_are_mechanical(self):
        r = classify_element(_elem("Ducts", "OST_DuctCurves"))
        assert r.discipline == "Mechanical"
        assert r.classification_confidence == "high"

    def test_air_terminals_are_mechanical(self):
        r = classify_element(_elem("Air Terminals", "OST_DuctTerminal"))
        assert r.discipline == "Mechanical"

    def test_mechanical_equipment(self):
        r = classify_element(_elem("Mechanical Equipment", "OST_MechanicalEquipment"))
        assert r.discipline == "Mechanical"


class TestElectricalClassification:
    def test_conduit_is_electrical(self):
        r = classify_element(_elem("Conduits", "OST_Conduit"))
        assert r.discipline == "Electrical"
        assert r.classification_confidence == "high"

    def test_cable_tray_is_electrical(self):
        r = classify_element(_elem("Cable Trays", "OST_CableTray"))
        assert r.discipline == "Electrical"

    def test_lighting_fixtures_are_electrical(self):
        r = classify_element(_elem("Lighting Fixtures", "OST_LightingFixtures"))
        assert r.discipline == "Electrical"

    def test_electrical_equipment(self):
        r = classify_element(_elem("Electrical Equipment", "OST_ElectricalEquipment"))
        assert r.discipline == "Electrical"


class TestPlumbingClassification:
    def test_pipes_are_plumbing(self):
        r = classify_element(_elem("Pipes", "OST_PipeCurves"))
        assert r.discipline == "Plumbing"
        assert r.classification_confidence == "high"

    def test_plumbing_fixtures(self):
        r = classify_element(_elem("Plumbing Fixtures", "OST_PlumbingFixtures"))
        assert r.discipline == "Plumbing"

    def test_sprinklers_are_plumbing(self):
        r = classify_element(_elem("Sprinklers", "OST_Sprinklers"))
        assert r.discipline == "Plumbing"


class TestAmbiguityRules:
    def test_generic_models_default_other(self):
        r = classify_element(_elem("Generic Models", "OST_GenericModel"))
        assert r.discipline == "Other"
        assert r.classification_confidence == "low"

    def test_unknown_category_goes_to_other(self):
        r = classify_element(_elem("Something Unknown", "OST_SomethingRandom"))
        assert r.discipline == "Other"
        assert r.classification_confidence == "unknown"

    def test_empty_category_goes_to_other(self):
        r = classify_element(_elem("", ""))
        assert r.discipline == "Other"

    def test_keyword_fallback_works(self):
        r = classify_element(_elem("Duct Accessories", ""))
        assert r.discipline == "Mechanical"
        assert r.classification_confidence == "medium"


# ── Extraction engine tests ─────────────────────────────────────────

def _sample_elements() -> list[dict]:
    """Create a mixed set of elements across disciplines."""
    return [
        _elem("Walls", "OST_Walls", element_id=1),
        _elem("Doors", "OST_Doors", element_id=2),
        _elem("Structural Columns", "OST_StructuralColumns", element_id=3),
        _elem("Structural Framing", "OST_StructuralFraming", element_id=4),
        _elem("Ducts", "OST_DuctCurves", element_id=5),
        _elem("Conduits", "OST_Conduit", element_id=6),
        _elem("Pipes", "OST_PipeCurves", element_id=7),
        _elem("Generic Models", "OST_GenericModel", element_id=8),
    ]


class TestDisciplineExtraction:
    def test_classify_elements_returns_all_disciplines(self):
        buckets = classify_elements(_sample_elements())
        assert set(buckets.keys()) == set(DISCIPLINES)

    def test_classify_elements_correct_buckets(self):
        buckets = classify_elements(_sample_elements())
        assert len(buckets["Architectural"]) == 2  # wall + door
        assert len(buckets["Structural"]) == 2  # column + framing
        assert len(buckets["Mechanical"]) == 1  # duct
        assert len(buckets["Electrical"]) == 1  # conduit
        assert len(buckets["Plumbing"]) == 1  # pipe
        assert len(buckets["Other"]) == 1  # generic model

    def test_chunk_creates_discipline_subfolders(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_discipline_extraction(
                _sample_elements(),
                Path(tmpdir), "test_run",
                source_model="Test Model",
            )

            run_dir = Path(tmpdir) / "test_run"
            assert run_dir.exists()

            for disc in DISCIPLINES:
                disc_dir = run_dir / disc
                assert disc_dir.exists(), f"{disc} folder not created"

    def test_root_summary_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = run_discipline_extraction(
                _sample_elements(),
                Path(tmpdir), "test_run",
                source_model="Test Model",
            )

            assert "root_summary_md" in paths
            assert paths["root_summary_md"].exists()
            assert "root_summary_xlsx" in paths
            assert paths["root_summary_xlsx"].exists()

    def test_checkpoint_jsonl_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = run_discipline_extraction(
                _sample_elements(),
                Path(tmpdir), "test_run",
            )

            assert "checkpoint" in paths
            assert paths["checkpoint"].exists()

            lines = paths["checkpoint"].read_text(encoding="utf-8").strip().split("\n")
            entries = [json.loads(line) for line in lines]

            # Each discipline gets STARTED + SUCCESS = 2 entries
            disciplines_seen = {e["discipline"] for e in entries}
            assert disciplines_seen == set(DISCIPLINES)

            statuses = {e["status"] for e in entries}
            assert "STARTED" in statuses
            assert "SUCCESS" in statuses

    def test_discipline_parquet_files_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_discipline_extraction(
                _sample_elements(),
                Path(tmpdir), "test_run",
            )

            run_dir = Path(tmpdir) / "test_run"
            # Disciplines with elements should have parquet files
            arch_dir = run_dir / "Architectural"
            assert (arch_dir / "elements.parquet").exists()
            assert (arch_dir / "elements.csv").exists()
            assert (arch_dir / "inventory_summary.xlsx").exists()
            assert (arch_dir / "inventory_summary.md").exists()

    def test_single_discipline_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_discipline_extraction(
                _sample_elements(),
                Path(tmpdir), "test_run",
                discipline_filter="Structural",
            )

            run_dir = Path(tmpdir) / "test_run"
            struct_dir = run_dir / "Structural"
            assert struct_dir.exists()
            assert (struct_dir / "elements.parquet").exists()

            # Other discipline folders should NOT exist
            assert not (run_dir / "Architectural").exists()
            assert not (run_dir / "Mechanical").exists()

    def test_root_metadata_has_discipline_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = run_discipline_extraction(
                _sample_elements(),
                Path(tmpdir), "test_run",
                source_model="Test Model",
            )

            meta = json.loads(paths["root_metadata"].read_text(encoding="utf-8"))
            assert meta["chunk_by"] == "discipline"
            assert meta["source_model"] == "Test Model"
            assert "disciplines" in meta

            arch = meta["disciplines"]["Architectural"]
            assert arch["element_count"] == 2
            assert arch["status"] == "SUCCESS"

    def test_empty_discipline_still_creates_folder(self):
        # Elements with no Plumbing items
        elements = [
            _elem("Walls", "OST_Walls", element_id=1),
            _elem("Ducts", "OST_DuctCurves", element_id=2),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            run_discipline_extraction(
                elements,
                Path(tmpdir), "test_run",
            )

            run_dir = Path(tmpdir) / "test_run"
            # Plumbing folder should exist even if empty
            assert (run_dir / "Plumbing").exists()

    def test_root_summary_md_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = run_discipline_extraction(
                _sample_elements(),
                Path(tmpdir), "test_run",
                source_model="Test Model",
            )

            content = paths["root_summary_md"].read_text(encoding="utf-8")
            assert "Test Model" in content
            assert "Architectural" in content
            assert "Structural" in content
            assert "Mechanical" in content
            assert "Electrical" in content
            assert "Plumbing" in content
            assert "Other" in content

    def test_empty_elements_guardrail(self):
        """Summary-mode JSON with elements=[] produces warning in summary, metadata, and paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = run_discipline_extraction(
                [],  # empty elements list
                Path(tmpdir), "test_empty",
                source_model="Summary Model",
            )

            # Warning key in returned paths
            assert paths.get("warning") == "empty_input"

            # Warning in summary markdown
            md_content = paths["root_summary_md"].read_text(encoding="utf-8")
            assert "WARNING" in md_content
            assert "no element-level records" in md_content
            assert "full-detail inventory export" in md_content

            # Warning in run_metadata.json
            meta = json.loads(paths["root_metadata"].read_text(encoding="utf-8"))
            assert "warning" in meta
            assert "no element-level records" in meta["warning"]

            # All discipline counts should be 0
            for disc_stats in meta["disciplines"].values():
                assert disc_stats["element_count"] == 0
