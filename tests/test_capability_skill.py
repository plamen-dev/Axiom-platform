"""Tests for the Capability Skill Framework v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.capability_skill import (
    CapabilitySkill,
    CapabilitySkillEngine,
    CapabilitySkillEvidence,
    CapabilitySkillObservation,
    CapabilitySkillReport,
    CapabilitySkillType,
)

from tests.conftest import make_symlink_or_skip

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine(tmp_path: Path) -> CapabilitySkillEngine:
    return CapabilitySkillEngine(artifacts_root=str(tmp_path))


def _sample_skills() -> list[dict]:
    return [
        {
            "name": "retry-on-timeout",
            "description": "Retry the capability when a timeout occurs",
            "skill_type": "recovery_pattern",
            "confidence_score": 0.8,
            "observations": [
                {
                    "source_id": "repair-001",
                    "summary": "Recovered after timeout",
                    "created_at": "2026-01-02T00:00:00+00:00",
                },
                {
                    "source_id": "repair-000",
                    "summary": "First recovery",
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
            ],
        },
        {
            "name": "grid-creation",
            "description": "Reliable grid creation pattern",
            "skill_type": "execution_pattern",
            "confidence_score": 0.9,
            "observations": [
                {
                    "source_id": "exec-001",
                    "summary": "Grids created",
                    "created_at": "2026-01-03T00:00:00+00:00",
                },
            ],
        },
    ]


# ---------------------------------------------------------------------------
# TestModels
# ---------------------------------------------------------------------------


class TestModels:
    def test_skill_defaults(self) -> None:
        s = CapabilitySkill()
        assert s.skill_id
        assert s.created_at
        assert s.skill_type == "execution_pattern"
        assert s.confidence_score == 0.0
        assert s.observations == []

    def test_observation_defaults(self) -> None:
        o = CapabilitySkillObservation()
        assert o.observation_id
        assert o.created_at

    def test_report_defaults(self) -> None:
        r = CapabilitySkillReport()
        assert r.report_id
        assert r.created_at
        assert r.skill_count == 0

    def test_evidence_defaults(self) -> None:
        ev = CapabilitySkillEvidence()
        assert ev.evidence_id
        assert ev.created_at


# ---------------------------------------------------------------------------
# TestCreate
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_empty(self, engine: CapabilitySkillEngine) -> None:
        result = engine.create(capability_id="cap-empty", skills=[])
        assert result["skill_count"] == 0
        assert result["capability_id"] == "cap-empty"

    def test_create_with_skills(self, engine: CapabilitySkillEngine) -> None:
        result = engine.create(capability_id="cap-001", skills=_sample_skills())
        assert result["skill_count"] == 2
        assert len(result["skills"]) == 2

    def test_create_all_skill_types(self, engine: CapabilitySkillEngine) -> None:
        skills = [
            {"name": t.value, "skill_type": t.value, "confidence_score": 0.6}
            for t in CapabilitySkillType
        ]
        result = engine.create(capability_id="cap-all", skills=skills)
        assert result["skill_count"] == len(CapabilitySkillType)

    def test_observations_created(self, engine: CapabilitySkillEngine) -> None:
        result = engine.create(capability_id="cap-obs", skills=_sample_skills())
        recovery = [s for s in result["skills"] if s["skill_type"] == "recovery_pattern"][0]
        assert len(recovery["observations"]) == 2


# ---------------------------------------------------------------------------
# TestValidation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_valid_skill_types(self, engine: CapabilitySkillEngine) -> None:
        for t in CapabilitySkillType:
            result = engine.create(
                capability_id="cap-v",
                skills=[{"name": "x", "skill_type": t.value, "confidence_score": 0.5}],
            )
            assert result["skill_count"] == 1

    def test_invalid_skill_type_rejected(self, engine: CapabilitySkillEngine) -> None:
        with pytest.raises(ValueError, match="Invalid skill_type"):
            engine.create(
                capability_id="cap-bad",
                skills=[{"name": "x", "skill_type": "telepathy"}],
            )

    def test_confidence_out_of_range_rejected(self, engine: CapabilitySkillEngine) -> None:
        with pytest.raises(ValueError, match="within"):
            engine.create(
                capability_id="cap-bad",
                skills=[{"name": "x", "skill_type": "success_pattern", "confidence_score": 1.5}],
            )

    def test_confidence_bool_rejected(self, engine: CapabilitySkillEngine) -> None:
        with pytest.raises(ValueError, match="number"):
            engine.create(
                capability_id="cap-bad",
                skills=[{"name": "x", "skill_type": "success_pattern", "confidence_score": True}],
            )


# ---------------------------------------------------------------------------
# TestConfidencePersistence
# ---------------------------------------------------------------------------


class TestConfidencePersistence:
    def test_confidence_persisted(self, engine: CapabilitySkillEngine) -> None:
        result = engine.create(capability_id="cap-c", skills=_sample_skills())
        scores = {s["name"]: s["confidence_score"] for s in result["skills"]}
        assert scores["retry-on-timeout"] == 0.8
        assert scores["grid-creation"] == 0.9


# ---------------------------------------------------------------------------
# TestDeterministicOrdering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_skills_ordered(self, engine: CapabilitySkillEngine) -> None:
        result = engine.create(capability_id="cap-order", skills=_sample_skills())
        types = [s["skill_type"] for s in result["skills"]]
        assert types == sorted(types)
        # execution_pattern sorts before recovery_pattern
        assert types == ["execution_pattern", "recovery_pattern"]

    def test_observations_ordered_chronologically(self, engine: CapabilitySkillEngine) -> None:
        result = engine.create(capability_id="cap-obs-order", skills=_sample_skills())
        recovery = [s for s in result["skills"] if s["skill_type"] == "recovery_pattern"][0]
        timestamps = [o["created_at"] for o in recovery["observations"]]
        assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# TestSourceReferences
# ---------------------------------------------------------------------------


class TestSourceReferences:
    def test_observation_source_ids_preserved(self, engine: CapabilitySkillEngine) -> None:
        result = engine.create(capability_id="cap-src", skills=_sample_skills())
        recovery = [s for s in result["skills"] if s["skill_type"] == "recovery_pattern"][0]
        sources = [o["source_id"] for o in recovery["observations"]]
        assert sources == ["repair-000", "repair-001"]

    def test_observation_skill_id_linked(self, engine: CapabilitySkillEngine) -> None:
        result = engine.create(capability_id="cap-link", skills=_sample_skills())
        for s in result["skills"]:
            for o in s["observations"]:
                assert o["skill_id"] == s["skill_id"]


# ---------------------------------------------------------------------------
# TestEvidenceGeneration
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_four_files_created(self, engine: CapabilitySkillEngine) -> None:
        result = engine.create(capability_id="cap-ev", skills=_sample_skills())
        report_dir = Path(engine._report_dir) / result["report_id"]
        expected = {
            "capability_skill_request.json",
            "capability_skill_result.json",
            "capability_skill_summary.md",
            "pass_fail.json",
        }
        actual = {f.name for f in report_dir.iterdir() if f.is_file()}
        assert expected.issubset(actual)

    def test_request_valid_json(self, engine: CapabilitySkillEngine) -> None:
        result = engine.create(capability_id="cap-req", skills=_sample_skills())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads((report_dir / "capability_skill_request.json").read_text())
        assert data["capability_id"] == "cap-req"
        assert len(data["skills"]) == 2

    def test_result_valid_json(self, engine: CapabilitySkillEngine) -> None:
        result = engine.create(capability_id="cap-res", skills=_sample_skills())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads((report_dir / "capability_skill_result.json").read_text())
        assert data["skill_count"] == 2

    def test_summary_has_header(self, engine: CapabilitySkillEngine) -> None:
        result = engine.create(capability_id="cap-sum", skills=_sample_skills())
        report_dir = Path(engine._report_dir) / result["report_id"]
        md = (report_dir / "capability_skill_summary.md").read_text()
        assert "# Capability Skill Report" in md
        assert "## Skills" in md

    def test_pass_fail_passes_for_confident_skills(self, engine: CapabilitySkillEngine) -> None:
        result = engine.create(capability_id="cap-pf", skills=_sample_skills())
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True
        assert pf["skill_count"] == 2

    def test_pass_fail_fails_for_low_confidence(self, engine: CapabilitySkillEngine) -> None:
        result = engine.create(
            capability_id="cap-low",
            skills=[{"name": "weak", "skill_type": "failure_pattern", "confidence_score": 0.1}],
        )
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is False

    def test_pass_fail_empty_passes(self, engine: CapabilitySkillEngine) -> None:
        result = engine.create(capability_id="cap-empty", skills=[])
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, engine: CapabilitySkillEngine) -> None:
        result = engine.create(capability_id="cap-get", skills=_sample_skills())
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]
        assert loaded["skill_count"] == 2

    def test_list_reports_deterministic(self, engine: CapabilitySkillEngine) -> None:
        engine.create(capability_id="a", skills=_sample_skills())
        engine.create(capability_id="b", skills=[])
        reports = engine.list_reports()
        assert len(reports) == 2
        assert reports[0]["created_at"] <= reports[1]["created_at"]


# ---------------------------------------------------------------------------
# TestExport
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_returns_markdown(self, engine: CapabilitySkillEngine) -> None:
        result = engine.create(capability_id="cap-exp", skills=_sample_skills())
        md = engine.export_report(result["report_id"])
        assert "# Capability Skill Report" in md
        assert "EXECUTION_PATTERN" in md

    def test_export_nonexistent_raises(self, engine: CapabilitySkillEngine) -> None:
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id-abc123")


# ---------------------------------------------------------------------------
# TestSafety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(self, engine: CapabilitySkillEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("../../etc/passwd")

    def test_empty_id_rejected(self, engine: CapabilitySkillEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("")

    def test_whitespace_id_rejected(self, engine: CapabilitySkillEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("   ")

    def test_symlink_escape_rejected(
        self, engine: CapabilitySkillEngine, tmp_path: Path
    ) -> None:
        target = tmp_path / "outside"
        target.mkdir()
        link = Path(engine._report_dir) / "evil-link"
        make_symlink_or_skip(link, target)
        with pytest.raises(ValueError):
            engine.get_report("evil-link")

    def test_nonexistent_returns_none(self, engine: CapabilitySkillEngine) -> None:
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
            "capability-skill-create",
            "capability-skill-show",
            "capability-skill-export",
        }
        assert expected.issubset(set(names))


# ---------------------------------------------------------------------------
# TestSelectionMapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_capability_skill_mapped(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/capability_skill.py"]
            == "tests/test_capability_skill.py"
        )
