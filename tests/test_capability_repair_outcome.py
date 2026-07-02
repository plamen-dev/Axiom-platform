"""Tests for the Capability Repair Outcome Framework v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.capability_repair_outcome import (
    CapabilityRepairOutcome,
    CapabilityRepairOutcomeEngine,
    CapabilityRepairOutcomeEvidence,
    CapabilityRepairOutcomeReport,
    CapabilityRepairOutcomeType,
)

from tests.conftest import make_symlink_or_skip

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine(tmp_path: Path) -> CapabilityRepairOutcomeEngine:
    return CapabilityRepairOutcomeEngine(artifacts_root=str(tmp_path))


def _sample_outcomes() -> list[dict]:
    return [
        {
            "retry_id": "retry-001",
            "outcome_type": "full_recovery",
            "status": "succeeded",
            "summary": "Fully recovered after retry",
        },
        {
            "retry_id": "retry-002",
            "outcome_type": "regression",
            "status": "failed",
            "summary": "Retry made things worse",
        },
    ]


# ---------------------------------------------------------------------------
# TestModels
# ---------------------------------------------------------------------------


class TestModels:
    def test_outcome_defaults(self) -> None:
        o = CapabilityRepairOutcome()
        assert o.outcome_id
        assert o.created_at
        assert o.outcome_type == "no_recovery"
        assert o.status == "failed"

    def test_report_defaults(self) -> None:
        r = CapabilityRepairOutcomeReport()
        assert r.report_id
        assert r.created_at
        assert r.outcome_count == 0

    def test_evidence_defaults(self) -> None:
        e = CapabilityRepairOutcomeEvidence()
        assert e.evidence_id
        assert e.created_at


# ---------------------------------------------------------------------------
# TestCreate
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_empty(self, engine: CapabilityRepairOutcomeEngine) -> None:
        result = engine.create(outcomes=[])
        assert result["outcome_count"] == 0
        assert result["recovery_count"] == 0
        assert result["regression_count"] == 0

    def test_create_with_outcomes(self, engine: CapabilityRepairOutcomeEngine) -> None:
        result = engine.create(outcomes=_sample_outcomes())
        assert result["outcome_count"] == 2
        assert result["recovery_count"] == 1
        assert result["regression_count"] == 1

    def test_create_with_all_types(self, engine: CapabilityRepairOutcomeEngine) -> None:
        outcomes = [
            {"outcome_type": "full_recovery", "status": "succeeded", "summary": "a"},
            {"outcome_type": "partial_recovery", "status": "partial_success", "summary": "b"},
            {"outcome_type": "no_recovery", "status": "failed", "summary": "c"},
            {"outcome_type": "regression", "status": "failed", "summary": "d"},
        ]
        result = engine.create(outcomes=outcomes)
        assert result["outcome_count"] == 4
        assert result["recovery_count"] == 2
        assert result["regression_count"] == 1


# ---------------------------------------------------------------------------
# TestValidation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_valid_outcome_types(self, engine: CapabilityRepairOutcomeEngine) -> None:
        for ot in CapabilityRepairOutcomeType:
            result = engine.create(
                outcomes=[{"outcome_type": ot.value, "status": "failed", "summary": "x"}]
            )
            assert result["outcome_count"] == 1

    def test_invalid_outcome_type_rejected(self, engine: CapabilityRepairOutcomeEngine) -> None:
        with pytest.raises(ValueError, match="Invalid outcome_type"):
            engine.create(
                outcomes=[{"outcome_type": "magic_fix", "status": "failed", "summary": "x"}]
            )

    def test_invalid_status_rejected(self, engine: CapabilityRepairOutcomeEngine) -> None:
        with pytest.raises(ValueError, match="Invalid status"):
            engine.create(
                outcomes=[{"outcome_type": "full_recovery", "status": "unknown", "summary": "x"}]
            )


# ---------------------------------------------------------------------------
# TestPassFail
# ---------------------------------------------------------------------------


class TestPassFail:
    def test_no_regressions_passes(self, engine: CapabilityRepairOutcomeEngine) -> None:
        result = engine.create(
            outcomes=[
                {"outcome_type": "full_recovery", "status": "succeeded", "summary": "ok"},
            ]
        )
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True
        assert pf["status"] == "passed"

    def test_no_outcomes_passes(self, engine: CapabilityRepairOutcomeEngine) -> None:
        result = engine.create(outcomes=[])
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True

    def test_regression_fails(self, engine: CapabilityRepairOutcomeEngine) -> None:
        result = engine.create(
            outcomes=[
                {"outcome_type": "regression", "status": "failed", "summary": "worse"},
            ]
        )
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is False
        assert pf["status"] == "failed"

    def test_no_recovery_without_regression_passes(
        self, engine: CapabilityRepairOutcomeEngine
    ) -> None:
        result = engine.create(
            outcomes=[
                {"outcome_type": "no_recovery", "status": "failed", "summary": "nothing"},
            ]
        )
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True

    def test_partial_recovery_passes(self, engine: CapabilityRepairOutcomeEngine) -> None:
        result = engine.create(
            outcomes=[
                {
                    "outcome_type": "partial_recovery",
                    "status": "partial_success",
                    "summary": "some",
                },
            ]
        )
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True


# ---------------------------------------------------------------------------
# TestDeterministicOrdering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_outcomes_ordered_by_type_then_summary(
        self, engine: CapabilityRepairOutcomeEngine
    ) -> None:
        outcomes = [
            {"outcome_type": "full_recovery", "status": "succeeded", "summary": "z"},
            {"outcome_type": "regression", "status": "failed", "summary": "a"},
            {"outcome_type": "partial_recovery", "status": "partial_success", "summary": "b"},
            {"outcome_type": "no_recovery", "status": "failed", "summary": "c"},
        ]
        result = engine.create(outcomes=outcomes)
        types = [o["outcome_type"] for o in result["outcomes"]]
        assert types == [
            "regression",
            "no_recovery",
            "partial_recovery",
            "full_recovery",
        ]


# ---------------------------------------------------------------------------
# TestEvidenceGeneration
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_four_files_created(self, engine: CapabilityRepairOutcomeEngine) -> None:
        result = engine.create(outcomes=_sample_outcomes())
        report_dir = Path(engine._report_dir) / result["report_id"]
        expected = {
            "capability_repair_outcome_request.json",
            "capability_repair_outcome_result.json",
            "capability_repair_outcome_summary.md",
            "pass_fail.json",
        }
        actual = {f.name for f in report_dir.iterdir() if f.is_file()}
        assert expected.issubset(actual)

    def test_request_valid_json(self, engine: CapabilityRepairOutcomeEngine) -> None:
        result = engine.create(outcomes=_sample_outcomes())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads((report_dir / "capability_repair_outcome_request.json").read_text())
        assert "outcomes" in data

    def test_result_valid_json(self, engine: CapabilityRepairOutcomeEngine) -> None:
        result = engine.create(outcomes=_sample_outcomes())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads((report_dir / "capability_repair_outcome_result.json").read_text())
        assert data["outcome_count"] == 2

    def test_summary_has_header(self, engine: CapabilityRepairOutcomeEngine) -> None:
        result = engine.create(outcomes=_sample_outcomes())
        report_dir = Path(engine._report_dir) / result["report_id"]
        md = (report_dir / "capability_repair_outcome_summary.md").read_text()
        assert "# Capability Repair Outcome Report" in md

    def test_regression_in_evidence(self, engine: CapabilityRepairOutcomeEngine) -> None:
        result = engine.create(outcomes=_sample_outcomes())
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["regression_count"] == 1


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, engine: CapabilityRepairOutcomeEngine) -> None:
        result = engine.create(outcomes=_sample_outcomes())
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]
        assert loaded["outcome_count"] == 2

    def test_list_reports_deterministic(self, engine: CapabilityRepairOutcomeEngine) -> None:
        engine.create(outcomes=_sample_outcomes())
        engine.create(outcomes=[])
        reports = engine.list_reports()
        assert len(reports) == 2
        assert reports[0]["created_at"] <= reports[1]["created_at"]


# ---------------------------------------------------------------------------
# TestExport
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_returns_markdown(self, engine: CapabilityRepairOutcomeEngine) -> None:
        result = engine.create(outcomes=_sample_outcomes())
        md = engine.export_report(result["report_id"])
        assert "# Capability Repair Outcome Report" in md
        assert "REGRESSION" in md

    def test_export_nonexistent_raises(self, engine: CapabilityRepairOutcomeEngine) -> None:
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id-abc123")


# ---------------------------------------------------------------------------
# TestSafety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(self, engine: CapabilityRepairOutcomeEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("../../etc/passwd")

    def test_empty_id_rejected(self, engine: CapabilityRepairOutcomeEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("")

    def test_whitespace_id_rejected(self, engine: CapabilityRepairOutcomeEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("   ")

    def test_symlink_escape_rejected(
        self, engine: CapabilityRepairOutcomeEngine, tmp_path: Path
    ) -> None:
        target = tmp_path / "outside"
        target.mkdir()
        link = Path(engine._report_dir) / "evil-link"
        make_symlink_or_skip(link, target)
        with pytest.raises(ValueError):
            engine.get_report("evil-link")

    def test_nonexistent_returns_none(self, engine: CapabilityRepairOutcomeEngine) -> None:
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
            "capability-repair-outcome-create",
            "capability-repair-outcomes",
            "capability-repair-outcome-show",
            "capability-repair-outcome-export",
        }
        assert expected.issubset(set(names))


# ---------------------------------------------------------------------------
# TestSelectionMapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_capability_repair_outcome_mapped(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/capability_repair_outcome.py"]
            == "tests/test_capability_repair_outcome.py"
        )
