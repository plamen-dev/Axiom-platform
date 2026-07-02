"""Tests for the Skill Composition Framework v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.skill_composition import (
    SkillComposition,
    SkillCompositionElement,
    SkillCompositionEngine,
    SkillCompositionEvidence,
    SkillCompositionReport,
    SkillCompositionType,
)

from tests.conftest import make_symlink_or_skip


@pytest.fixture()
def engine(tmp_path: Path) -> SkillCompositionEngine:
    return SkillCompositionEngine(artifacts_root=str(tmp_path))


def _sample_compositions() -> list[dict]:
    return [
        {
            "name": "alpha",
            "composition_type": "execution_sequence",
            "created_at": "2026-01-01T00:00:00+00:00",
            "elements": [
                {"skill_id": "s2", "order_index": 1},
                {"skill_id": "s1", "order_index": 0},
            ],
        },
        {
            "name": "bravo",
            "composition_type": "validation_sequence",
            "created_at": "2026-01-02T00:00:00+00:00",
            "elements": [
                {"skill_id": "s3", "order_index": 0},
            ],
        },
        {
            "name": "charlie",
            "composition_type": "execution_sequence",
            "created_at": "2026-01-03T00:00:00+00:00",
            "elements": [
                {"skill_id": "s4", "order_index": 0},
            ],
        },
    ]


# ---------------------------------------------------------------------------
# TestModels
# ---------------------------------------------------------------------------


class TestModels:
    def test_element_defaults(self) -> None:
        el = SkillCompositionElement()
        assert el.element_id
        assert el.created_at
        assert el.order_index == 0

    def test_composition_defaults(self) -> None:
        c = SkillComposition()
        assert c.composition_id
        assert c.created_at
        assert c.composition_type == "custom_sequence"
        assert c.elements == []

    def test_report_defaults(self) -> None:
        r = SkillCompositionReport()
        assert r.report_id
        assert r.created_at
        assert r.composition_count == 0
        assert r.composition_type_counts == {}

    def test_evidence_defaults(self) -> None:
        e = SkillCompositionEvidence()
        assert e.evidence_id
        assert e.created_at


# ---------------------------------------------------------------------------
# TestCreate
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_empty(self, engine: SkillCompositionEngine) -> None:
        result = engine.create()
        assert result["composition_count"] == 0
        assert result["compositions"] == []
        assert result["composition_type_counts"] == {}

    def test_create_with_compositions(
        self, engine: SkillCompositionEngine
    ) -> None:
        result = engine.create(compositions=_sample_compositions())
        assert result["composition_count"] == 3

    def test_report_id_present(self, engine: SkillCompositionEngine) -> None:
        result = engine.create(compositions=_sample_compositions())
        assert result["report_id"]

    def test_all_types(self, engine: SkillCompositionEngine) -> None:
        compositions = [
            {
                "name": f"comp-{t.value}",
                "composition_type": t.value,
                "elements": [{"skill_id": "s1", "order_index": 0}],
            }
            for t in SkillCompositionType
        ]
        result = engine.create(compositions=compositions)
        assert result["composition_count"] == len(SkillCompositionType)


# ---------------------------------------------------------------------------
# TestTypeCounts
# ---------------------------------------------------------------------------


class TestTypeCounts:
    def test_type_counts(self, engine: SkillCompositionEngine) -> None:
        result = engine.create(compositions=_sample_compositions())
        counts = result["composition_type_counts"]
        assert counts["execution_sequence"] == 2
        assert counts["validation_sequence"] == 1

    def test_type_counts_sorted_keys(
        self, engine: SkillCompositionEngine
    ) -> None:
        result = engine.create(compositions=_sample_compositions())
        keys = list(result["composition_type_counts"].keys())
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# TestTypePersistence
# ---------------------------------------------------------------------------


class TestTypePersistence:
    def test_composition_type_persisted(
        self, engine: SkillCompositionEngine
    ) -> None:
        result = engine.create(compositions=_sample_compositions())
        by_name = {c["name"]: c for c in result["compositions"]}
        assert by_name["alpha"]["composition_type"] == "execution_sequence"
        assert by_name["bravo"]["composition_type"] == "validation_sequence"

    def test_name_persisted(self, engine: SkillCompositionEngine) -> None:
        result = engine.create(compositions=_sample_compositions())
        names = {c["name"] for c in result["compositions"]}
        assert names == {"alpha", "bravo", "charlie"}


# ---------------------------------------------------------------------------
# TestElementOrdering
# ---------------------------------------------------------------------------


class TestElementOrdering:
    def test_elements_ordered_by_index(
        self, engine: SkillCompositionEngine
    ) -> None:
        result = engine.create(compositions=_sample_compositions())
        by_name = {c["name"]: c for c in result["compositions"]}
        order = [el["order_index"] for el in by_name["alpha"]["elements"]]
        assert order == [0, 1]

    def test_elements_order_independent(
        self, engine: SkillCompositionEngine
    ) -> None:
        c1 = {
            "name": "alpha",
            "composition_type": "execution_sequence",
            "elements": [
                {"skill_id": "s1", "order_index": 0},
                {"skill_id": "s2", "order_index": 1},
            ],
        }
        c2 = {
            "name": "alpha",
            "composition_type": "execution_sequence",
            "elements": [
                {"skill_id": "s2", "order_index": 1},
                {"skill_id": "s1", "order_index": 0},
            ],
        }
        r1 = engine.create(compositions=[c1])
        r2 = engine.create(compositions=[c2])
        ids1 = [el["skill_id"] for el in r1["compositions"][0]["elements"]]
        ids2 = [el["skill_id"] for el in r2["compositions"][0]["elements"]]
        assert ids1 == ids2 == ["s1", "s2"]

    def test_skill_ids_preserved(self, engine: SkillCompositionEngine) -> None:
        result = engine.create(compositions=_sample_compositions())
        by_name = {c["name"]: c for c in result["compositions"]}
        skills = {el["skill_id"] for el in by_name["alpha"]["elements"]}
        assert skills == {"s1", "s2"}


# ---------------------------------------------------------------------------
# TestValidation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_type_rejected(
        self, engine: SkillCompositionEngine
    ) -> None:
        with pytest.raises(ValueError, match="Invalid composition_type"):
            engine.create(
                compositions=[{"name": "x", "composition_type": "boom"}]
            )

    def test_missing_name_rejected(
        self, engine: SkillCompositionEngine
    ) -> None:
        with pytest.raises(ValueError, match="name is required"):
            engine.create(
                compositions=[{"composition_type": "custom_sequence"}]
            )

    def test_whitespace_name_rejected(
        self, engine: SkillCompositionEngine
    ) -> None:
        with pytest.raises(ValueError, match="name is required"):
            engine.create(
                compositions=[
                    {"name": "   ", "composition_type": "custom_sequence"}
                ]
            )

    def test_missing_skill_id_rejected(
        self, engine: SkillCompositionEngine
    ) -> None:
        with pytest.raises(ValueError, match="skill_id is required"):
            engine.create(
                compositions=[
                    {
                        "name": "x",
                        "composition_type": "custom_sequence",
                        "elements": [{"order_index": 0}],
                    }
                ]
            )


# ---------------------------------------------------------------------------
# TestDeterministicOrdering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_compositions_ordered(
        self, engine: SkillCompositionEngine
    ) -> None:
        result = engine.create(compositions=_sample_compositions())
        created = [c["created_at"] for c in result["compositions"]]
        assert created == sorted(created)

    def test_order_independent(self, engine: SkillCompositionEngine) -> None:
        r1 = engine.create(compositions=_sample_compositions())
        r2 = engine.create(
            compositions=list(reversed(_sample_compositions()))
        )
        keys1 = [(c["created_at"], c["name"]) for c in r1["compositions"]]
        keys2 = [(c["created_at"], c["name"]) for c in r2["compositions"]]
        assert keys1 == keys2


# ---------------------------------------------------------------------------
# TestEvidenceGeneration
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_four_files_created(self, engine: SkillCompositionEngine) -> None:
        result = engine.create(compositions=_sample_compositions())
        report_dir = Path(engine._report_dir) / result["report_id"]
        expected = {
            "skill_composition_request.json",
            "skill_composition_result.json",
            "skill_composition_summary.md",
            "pass_fail.json",
        }
        actual = {f.name for f in report_dir.iterdir() if f.is_file()}
        assert expected.issubset(actual)

    def test_request_valid_json(self, engine: SkillCompositionEngine) -> None:
        result = engine.create(compositions=_sample_compositions())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads(
            (report_dir / "skill_composition_request.json").read_text()
        )
        assert len(data["compositions"]) == 3

    def test_result_valid_json(self, engine: SkillCompositionEngine) -> None:
        result = engine.create(compositions=_sample_compositions())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads(
            (report_dir / "skill_composition_result.json").read_text()
        )
        assert data["report_id"] == result["report_id"]
        assert data["composition_count"] == 3

    def test_summary_has_sections(
        self, engine: SkillCompositionEngine
    ) -> None:
        result = engine.create(compositions=_sample_compositions())
        report_dir = Path(engine._report_dir) / result["report_id"]
        md = (report_dir / "skill_composition_summary.md").read_text()
        assert "# Skill Composition Report" in md
        assert "## Composition Summary" in md
        assert "## Type Counts" in md
        assert "## Compositions" in md

    def test_pass_fail_passes_with_elements(
        self, engine: SkillCompositionEngine
    ) -> None:
        result = engine.create(compositions=_sample_compositions())
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True
        assert pf["status"] == "passed"

    def test_pass_fail_fails_on_empty_composition(
        self, engine: SkillCompositionEngine
    ) -> None:
        result = engine.create(
            compositions=[
                {
                    "name": "empty",
                    "composition_type": "custom_sequence",
                    "elements": [],
                }
            ]
        )
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is False
        assert pf["empty_count"] == 1

    def test_pass_fail_empty_report_passes(
        self, engine: SkillCompositionEngine
    ) -> None:
        result = engine.create()
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, engine: SkillCompositionEngine) -> None:
        result = engine.create(compositions=_sample_compositions())
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]
        assert loaded["composition_count"] == 3

    def test_list_reports_deterministic(
        self, engine: SkillCompositionEngine
    ) -> None:
        engine.create(compositions=_sample_compositions())
        engine.create()
        reports = engine.list_reports()
        assert len(reports) == 2
        assert reports[0]["created_at"] <= reports[1]["created_at"]


# ---------------------------------------------------------------------------
# TestExport
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_returns_markdown(
        self, engine: SkillCompositionEngine
    ) -> None:
        result = engine.create(compositions=_sample_compositions())
        md = engine.export_report(result["report_id"])
        assert "# Skill Composition Report" in md
        assert "EXECUTION_SEQUENCE" in md

    def test_export_nonexistent_raises(
        self, engine: SkillCompositionEngine
    ) -> None:
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id-abc123")


# ---------------------------------------------------------------------------
# TestSafety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(
        self, engine: SkillCompositionEngine
    ) -> None:
        with pytest.raises(ValueError):
            engine.get_report("../../etc/passwd")

    def test_empty_id_rejected(self, engine: SkillCompositionEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("")

    def test_whitespace_id_rejected(
        self, engine: SkillCompositionEngine
    ) -> None:
        with pytest.raises(ValueError):
            engine.get_report("   ")

    def test_symlink_escape_rejected(
        self, engine: SkillCompositionEngine, tmp_path: Path
    ) -> None:
        target = tmp_path / "outside"
        target.mkdir()
        link = Path(engine._report_dir) / "evil-link"
        make_symlink_or_skip(link, target)
        with pytest.raises(ValueError):
            engine.get_report("evil-link")

    def test_nonexistent_returns_none(
        self, engine: SkillCompositionEngine
    ) -> None:
        result = engine.get_report("valid-but-missing-id")
        assert result is None


# ---------------------------------------------------------------------------
# TestCommandRegistryIntegration
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_commands_registered(self) -> None:
        from axiom_core.runner.command_registry import command_names

        names = command_names()
        expected = {
            "skill-composition-create",
            "skill-composition-show",
            "skill-composition-export",
        }
        assert expected.issubset(set(names))


# ---------------------------------------------------------------------------
# TestSelectionMapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_skill_composition_mapped(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/skill_composition.py"]
            == "tests/test_skill_composition.py"
        )
