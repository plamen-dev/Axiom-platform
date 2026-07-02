"""Tests for the Capability Confidence Framework v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.capability_confidence import (
    CapabilityConfidence,
    CapabilityConfidenceEngine,
    CapabilityConfidenceEvidence,
    CapabilityConfidenceFactors,
    CapabilityConfidenceLevel,
    CapabilityConfidenceReport,
    _compute_score,
    _level_from_score,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine(tmp_path: Path) -> CapabilityConfidenceEngine:
    return CapabilityConfidenceEngine(artifacts_root=str(tmp_path))


# ---------------------------------------------------------------------------
# TestModels
# ---------------------------------------------------------------------------


class TestModels:
    def test_confidence_defaults(self) -> None:
        c = CapabilityConfidence()
        assert c.confidence_id
        assert c.created_at
        assert c.score == 0.0
        assert c.confidence_level == "very_low"
        assert c.factors is not None

    def test_factors_defaults(self) -> None:
        f = CapabilityConfidenceFactors()
        assert f.execution_count == 0
        assert f.success_count == 0
        assert f.failure_count == 0
        assert f.repair_count == 0
        assert f.recovery_count == 0

    def test_report_defaults(self) -> None:
        r = CapabilityConfidenceReport()
        assert r.report_id
        assert r.created_at
        assert r.score == 0.0

    def test_evidence_defaults(self) -> None:
        e = CapabilityConfidenceEvidence()
        assert e.evidence_id
        assert e.created_at


# ---------------------------------------------------------------------------
# TestScoring
# ---------------------------------------------------------------------------


class TestScoring:
    def test_zero_executions_gives_zero(self) -> None:
        f = CapabilityConfidenceFactors(execution_count=0)
        assert _compute_score(f) == 0.0

    def test_all_successes_is_damped_by_evidence_mass(self) -> None:
        f = CapabilityConfidenceFactors(execution_count=10, success_count=10)
        assert _compute_score(f) == 0.8333  # 1.0 * 10/12

    def test_half_successes(self) -> None:
        f = CapabilityConfidenceFactors(execution_count=10, success_count=5)
        assert _compute_score(f) == 0.4167  # 0.5 * 10/12

    def test_damping_curve_one_execution(self) -> None:
        f = CapabilityConfidenceFactors(execution_count=1, success_count=1)
        assert _compute_score(f) == 0.3333  # 1/1 is weak evidence -> low

    def test_damping_curve_five_executions(self) -> None:
        f = CapabilityConfidenceFactors(execution_count=5, success_count=5)
        assert _compute_score(f) == 0.7143  # 5/5 -> high

    def test_damping_curve_eighteen_executions(self) -> None:
        f = CapabilityConfidenceFactors(execution_count=18, success_count=18)
        assert _compute_score(f) == 0.9  # 18/18 -> very_high

    def test_damping_converges_to_ratio(self) -> None:
        f = CapabilityConfidenceFactors(execution_count=10_000, success_count=10_000)
        assert _compute_score(f) == 0.9998

    def test_recovery_bonus(self) -> None:
        f = CapabilityConfidenceFactors(
            execution_count=10,
            success_count=5,
            failure_count=5,
            recovery_count=5,
        )
        score = _compute_score(f)
        assert score > 0.4167  # above the no-bonus damped ratio
        assert score <= 0.5

    def test_partial_recovery_bonus(self) -> None:
        f = CapabilityConfidenceFactors(
            execution_count=10,
            success_count=5,
            failure_count=5,
            recovery_count=2,
        )
        score = _compute_score(f)
        assert score > 0.4167
        assert score < 0.5

    def test_score_capped_at_one(self) -> None:
        f = CapabilityConfidenceFactors(
            execution_count=10,
            success_count=10,
            failure_count=1,
            recovery_count=10,
        )
        assert _compute_score(f) <= 1.0


# ---------------------------------------------------------------------------
# TestLevelClassification
# ---------------------------------------------------------------------------


class TestLevelClassification:
    def test_very_high(self) -> None:
        assert _level_from_score(0.95) == "very_high"
        assert _level_from_score(0.9) == "very_high"

    def test_high(self) -> None:
        assert _level_from_score(0.8) == "high"
        assert _level_from_score(0.7) == "high"

    def test_medium(self) -> None:
        assert _level_from_score(0.6) == "medium"
        assert _level_from_score(0.5) == "medium"

    def test_low(self) -> None:
        assert _level_from_score(0.4) == "low"
        assert _level_from_score(0.3) == "low"

    def test_very_low(self) -> None:
        assert _level_from_score(0.2) == "very_low"
        assert _level_from_score(0.0) == "very_low"

    def test_all_levels_reachable(self) -> None:
        levels = {_level_from_score(s / 10) for s in range(11)}
        assert levels == {lv.value for lv in CapabilityConfidenceLevel}


# ---------------------------------------------------------------------------
# TestCreate
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_basic(self, engine: CapabilityConfidenceEngine) -> None:
        result = engine.create(
            capability_id="cap-001",
            execution_count=10,
            success_count=9,
        )
        assert result["capability_id"] == "cap-001"
        assert result["score"] == 0.75  # 0.9 * 10/12
        assert result["confidence_level"] == "high"

    def test_create_zero_executions(self, engine: CapabilityConfidenceEngine) -> None:
        result = engine.create(capability_id="cap-empty")
        assert result["score"] == 0.0
        assert result["confidence_level"] == "very_low"

    def test_create_with_all_factors(self, engine: CapabilityConfidenceEngine) -> None:
        result = engine.create(
            capability_id="cap-full",
            execution_count=100,
            success_count=80,
            failure_count=20,
            repair_count=10,
            recovery_count=15,
        )
        assert result["score"] > 0.0
        assert "confidence" in result
        factors = result["confidence"]["factors"]
        assert factors["execution_count"] == 100
        assert factors["success_count"] == 80
        assert factors["failure_count"] == 20
        assert factors["repair_count"] == 10
        assert factors["recovery_count"] == 15

    def test_create_level_override_persists(
        self, engine: CapabilityConfidenceEngine
    ) -> None:
        result = engine.create(
            capability_id="cap-clamped",
            execution_count=1,
            success_count=1,
            level_override="very_low",
        )
        # Score stays the score-doctrine value; only the published level differs.
        assert result["score"] == 0.3333
        assert result["confidence_level"] == "very_low"
        loaded = engine.get_report(result["report_id"])
        assert loaded["confidence_level"] == "very_low"

    def test_create_invalid_level_override_raises(
        self, engine: CapabilityConfidenceEngine
    ) -> None:
        with pytest.raises(ValueError, match="level_override"):
            engine.create(
                capability_id="cap-bad",
                execution_count=1,
                success_count=1,
                level_override="super_high",
            )


# ---------------------------------------------------------------------------
# TestPassFail
# ---------------------------------------------------------------------------


class TestPassFail:
    def test_high_confidence_passes(self, engine: CapabilityConfidenceEngine) -> None:
        result = engine.create(
            capability_id="cap-pass",
            execution_count=10,
            success_count=9,
        )
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True
        assert pf["status"] == "passed"

    def test_zero_score_fails(self, engine: CapabilityConfidenceEngine) -> None:
        result = engine.create(capability_id="cap-fail")
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is False
        assert pf["status"] == "failed"

    def test_borderline_passes(self, engine: CapabilityConfidenceEngine) -> None:
        result = engine.create(
            capability_id="cap-border",
            execution_count=10,
            success_count=4,  # 0.4 * 10/12 = 0.3333, just above the 0.3 gate
        )
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True

    def test_below_threshold_fails(self, engine: CapabilityConfidenceEngine) -> None:
        result = engine.create(
            capability_id="cap-low",
            execution_count=10,
            success_count=2,
        )
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is False


# ---------------------------------------------------------------------------
# TestDeterministicOrdering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_list_sorted_by_created_at(self, engine: CapabilityConfidenceEngine) -> None:
        engine.create(capability_id="cap-a", execution_count=10, success_count=5)
        engine.create(capability_id="cap-b", execution_count=10, success_count=9)
        reports = engine.list_reports()
        assert len(reports) == 2
        assert reports[0]["created_at"] <= reports[1]["created_at"]


# ---------------------------------------------------------------------------
# TestEvidenceGeneration
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_four_files_created(self, engine: CapabilityConfidenceEngine) -> None:
        result = engine.create(
            capability_id="cap-ev",
            execution_count=10,
            success_count=8,
        )
        report_dir = Path(engine._report_dir) / result["report_id"]
        expected = {
            "capability_confidence_request.json",
            "capability_confidence_result.json",
            "capability_confidence_summary.md",
            "pass_fail.json",
        }
        actual = {f.name for f in report_dir.iterdir() if f.is_file()}
        assert expected.issubset(actual)

    def test_request_valid_json(self, engine: CapabilityConfidenceEngine) -> None:
        result = engine.create(
            capability_id="cap-req",
            execution_count=5,
            success_count=3,
        )
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads((report_dir / "capability_confidence_request.json").read_text())
        assert data["capability_id"] == "cap-req"
        assert "factors" in data

    def test_result_valid_json(self, engine: CapabilityConfidenceEngine) -> None:
        result = engine.create(
            capability_id="cap-res",
            execution_count=10,
            success_count=7,
        )
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads((report_dir / "capability_confidence_result.json").read_text())
        assert data["score"] == result["score"]

    def test_summary_has_header(self, engine: CapabilityConfidenceEngine) -> None:
        result = engine.create(
            capability_id="cap-sum",
            execution_count=10,
            success_count=8,
        )
        report_dir = Path(engine._report_dir) / result["report_id"]
        md = (report_dir / "capability_confidence_summary.md").read_text()
        assert "# Capability Confidence Report" in md

    def test_factors_in_evidence(self, engine: CapabilityConfidenceEngine) -> None:
        result = engine.create(
            capability_id="cap-fac",
            execution_count=20,
            success_count=15,
            failure_count=5,
        )
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads((report_dir / "capability_confidence_result.json").read_text())
        factors = data["confidence"]["factors"]
        assert factors["execution_count"] == 20


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, engine: CapabilityConfidenceEngine) -> None:
        result = engine.create(
            capability_id="cap-get",
            execution_count=10,
            success_count=8,
        )
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]
        assert loaded["score"] == result["score"]

    def test_list_reports_deterministic(self, engine: CapabilityConfidenceEngine) -> None:
        engine.create(capability_id="a", execution_count=10, success_count=5)
        engine.create(capability_id="b", execution_count=10, success_count=9)
        reports = engine.list_reports()
        assert len(reports) == 2
        assert reports[0]["created_at"] <= reports[1]["created_at"]


# ---------------------------------------------------------------------------
# TestExport
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_returns_markdown(self, engine: CapabilityConfidenceEngine) -> None:
        result = engine.create(
            capability_id="cap-exp",
            execution_count=10,
            success_count=8,
        )
        md = engine.export_report(result["report_id"])
        assert "# Capability Confidence Report" in md
        assert "Factors" in md

    def test_export_nonexistent_raises(self, engine: CapabilityConfidenceEngine) -> None:
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id-abc123")


# ---------------------------------------------------------------------------
# TestSafety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(self, engine: CapabilityConfidenceEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("../../etc/passwd")

    def test_empty_id_rejected(self, engine: CapabilityConfidenceEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("")

    def test_whitespace_id_rejected(self, engine: CapabilityConfidenceEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("   ")

    def test_symlink_escape_rejected(
        self, engine: CapabilityConfidenceEngine, tmp_path: Path
    ) -> None:
        target = tmp_path / "outside"
        target.mkdir()
        link = Path(engine._report_dir) / "evil-link"
        link.symlink_to(target)
        with pytest.raises(ValueError):
            engine.get_report("evil-link")

    def test_nonexistent_returns_none(self, engine: CapabilityConfidenceEngine) -> None:
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
            "capability-confidence-create",
            "capability-confidences",
            "capability-confidence-show",
            "capability-confidence-export",
        }
        assert expected.issubset(set(names))


# ---------------------------------------------------------------------------
# TestSelectionMapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_capability_confidence_mapped(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/capability_confidence.py"]
            == "tests/test_capability_confidence.py"
        )
