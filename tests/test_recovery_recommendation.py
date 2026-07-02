"""Tests for the Recovery Recommendation Framework v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.recovery_recommendation import (
    RecoveryPriority,
    RecoveryRecommendation,
    RecoveryRecommendationEngine,
    RecoveryRecommendationEvidence,
    RecoveryRecommendationReport,
    RecoveryRecommendationType,
)

from tests.conftest import make_symlink_or_skip


@pytest.fixture()
def engine(tmp_path: Path) -> RecoveryRecommendationEngine:
    return RecoveryRecommendationEngine(artifacts_root=str(tmp_path))


def _sample_recommendations() -> list[dict]:
    return [
        {
            "classification_id": "c1",
            "recommendation_type": "retry",
            "priority": "normal",
            "summary": "transient failure",
            "rationale": "retrying may succeed",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "classification_id": "c2",
            "recommendation_type": "repair",
            "priority": "high",
            "created_at": "2026-01-02T00:00:00+00:00",
        },
        {
            "classification_id": "c3",
            "recommendation_type": "escalate",
            "priority": "critical",
            "created_at": "2026-01-03T00:00:00+00:00",
        },
    ]


# ---------------------------------------------------------------------------
# TestModels
# ---------------------------------------------------------------------------


class TestModels:
    def test_recommendation_defaults(self) -> None:
        r = RecoveryRecommendation()
        assert r.recommendation_id
        assert r.created_at
        assert r.recommendation_type == "investigate"
        assert r.priority == "normal"

    def test_report_defaults(self) -> None:
        r = RecoveryRecommendationReport()
        assert r.report_id
        assert r.created_at
        assert r.recommendation_count == 0

    def test_evidence_defaults(self) -> None:
        e = RecoveryRecommendationEvidence()
        assert e.evidence_id
        assert e.created_at


# ---------------------------------------------------------------------------
# TestCreate
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_empty(self, engine: RecoveryRecommendationEngine) -> None:
        result = engine.create()
        assert result["recommendation_count"] == 0
        assert result["recommendations"] == []

    def test_create_with_recommendations(
        self, engine: RecoveryRecommendationEngine
    ) -> None:
        result = engine.create(recommendations=_sample_recommendations())
        assert result["recommendation_count"] == 3

    def test_all_types(self, engine: RecoveryRecommendationEngine) -> None:
        recommendations = [
            {"classification_id": f"c{t.value}", "recommendation_type": t.value}
            for t in RecoveryRecommendationType
        ]
        result = engine.create(recommendations=recommendations)
        assert result["recommendation_count"] == len(RecoveryRecommendationType)

    def test_all_priorities(self, engine: RecoveryRecommendationEngine) -> None:
        recommendations = [
            {"classification_id": f"c{p.value}", "priority": p.value}
            for p in RecoveryPriority
        ]
        result = engine.create(recommendations=recommendations)
        assert result["recommendation_count"] == len(RecoveryPriority)


# ---------------------------------------------------------------------------
# TestPriorityCounts
# ---------------------------------------------------------------------------


class TestPriorityCounts:
    def test_priority_counts(self, engine: RecoveryRecommendationEngine) -> None:
        result = engine.create(recommendations=_sample_recommendations())
        assert result["low_count"] == 0
        assert result["normal_count"] == 1
        assert result["high_count"] == 1
        assert result["critical_count"] == 1

    def test_low_counted(self, engine: RecoveryRecommendationEngine) -> None:
        recommendations = [
            {"classification_id": "c1", "priority": "low"},
            {"classification_id": "c2", "priority": "low"},
        ]
        result = engine.create(recommendations=recommendations)
        assert result["low_count"] == 2


# ---------------------------------------------------------------------------
# TestPriorityPersistence
# ---------------------------------------------------------------------------


class TestPriorityPersistence:
    def test_priority_persisted(
        self, engine: RecoveryRecommendationEngine
    ) -> None:
        result = engine.create(recommendations=_sample_recommendations())
        by_classification = {
            r["classification_id"]: r for r in result["recommendations"]
        }
        assert by_classification["c2"]["priority"] == "high"
        assert by_classification["c3"]["priority"] == "critical"

    def test_type_summary_rationale_persisted(
        self, engine: RecoveryRecommendationEngine
    ) -> None:
        result = engine.create(recommendations=_sample_recommendations())
        by_classification = {
            r["classification_id"]: r for r in result["recommendations"]
        }
        assert by_classification["c1"]["recommendation_type"] == "retry"
        assert by_classification["c1"]["summary"] == "transient failure"
        assert by_classification["c1"]["rationale"] == "retrying may succeed"


# ---------------------------------------------------------------------------
# TestValidation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_type_rejected(
        self, engine: RecoveryRecommendationEngine
    ) -> None:
        with pytest.raises(ValueError, match="Invalid recommendation_type"):
            engine.create(
                recommendations=[
                    {"classification_id": "c1", "recommendation_type": "boom"}
                ]
            )

    def test_invalid_priority_rejected(
        self, engine: RecoveryRecommendationEngine
    ) -> None:
        with pytest.raises(ValueError, match="Invalid priority"):
            engine.create(
                recommendations=[
                    {"classification_id": "c1", "priority": "urgent"}
                ]
            )

    def test_missing_classification_id_rejected(
        self, engine: RecoveryRecommendationEngine
    ) -> None:
        with pytest.raises(ValueError, match="classification_id is required"):
            engine.create(recommendations=[{"recommendation_type": "retry"}])


# ---------------------------------------------------------------------------
# TestDeterministicOrdering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_recommendations_ordered(
        self, engine: RecoveryRecommendationEngine
    ) -> None:
        result = engine.create(recommendations=_sample_recommendations())
        created = [r["created_at"] for r in result["recommendations"]]
        assert created == sorted(created)

    def test_order_independent(
        self, engine: RecoveryRecommendationEngine
    ) -> None:
        r1 = engine.create(recommendations=_sample_recommendations())
        r2 = engine.create(
            recommendations=list(reversed(_sample_recommendations()))
        )
        keys1 = [
            (r["created_at"], r["classification_id"])
            for r in r1["recommendations"]
        ]
        keys2 = [
            (r["created_at"], r["classification_id"])
            for r in r2["recommendations"]
        ]
        assert keys1 == keys2


# ---------------------------------------------------------------------------
# TestEvidenceGeneration
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_four_files_created(
        self, engine: RecoveryRecommendationEngine
    ) -> None:
        result = engine.create(recommendations=_sample_recommendations())
        report_dir = Path(engine._report_dir) / result["report_id"]
        expected = {
            "recovery_recommendation_request.json",
            "recovery_recommendation_result.json",
            "recovery_recommendation_summary.md",
            "pass_fail.json",
        }
        actual = {f.name for f in report_dir.iterdir() if f.is_file()}
        assert expected.issubset(actual)

    def test_request_valid_json(
        self, engine: RecoveryRecommendationEngine
    ) -> None:
        result = engine.create(recommendations=_sample_recommendations())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads(
            (report_dir / "recovery_recommendation_request.json").read_text()
        )
        assert len(data["recommendations"]) == 3

    def test_result_valid_json(
        self, engine: RecoveryRecommendationEngine
    ) -> None:
        result = engine.create(recommendations=_sample_recommendations())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads(
            (report_dir / "recovery_recommendation_result.json").read_text()
        )
        assert data["report_id"] == result["report_id"]
        assert data["recommendation_count"] == 3

    def test_summary_has_sections(
        self, engine: RecoveryRecommendationEngine
    ) -> None:
        result = engine.create(recommendations=_sample_recommendations())
        report_dir = Path(engine._report_dir) / result["report_id"]
        md = (report_dir / "recovery_recommendation_summary.md").read_text()
        assert "# Recovery Recommendation Report" in md
        assert "## Priority Counts" in md
        assert "## Type Counts" in md
        assert "## Recommendations" in md

    def test_pass_fail_passes_no_critical(
        self, engine: RecoveryRecommendationEngine
    ) -> None:
        recommendations = [
            {"classification_id": "c1", "priority": "low"},
            {"classification_id": "c2", "priority": "high"},
        ]
        result = engine.create(recommendations=recommendations)
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True
        assert pf["status"] == "passed"

    def test_pass_fail_fails_on_critical(
        self, engine: RecoveryRecommendationEngine
    ) -> None:
        result = engine.create(recommendations=_sample_recommendations())
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is False
        assert pf["critical_count"] == 1

    def test_pass_fail_empty_passes(
        self, engine: RecoveryRecommendationEngine
    ) -> None:
        result = engine.create()
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, engine: RecoveryRecommendationEngine) -> None:
        result = engine.create(recommendations=_sample_recommendations())
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]
        assert loaded["recommendation_count"] == 3

    def test_list_reports_deterministic(
        self, engine: RecoveryRecommendationEngine
    ) -> None:
        engine.create(recommendations=_sample_recommendations())
        engine.create()
        reports = engine.list_reports()
        assert len(reports) == 2
        assert reports[0]["created_at"] <= reports[1]["created_at"]


# ---------------------------------------------------------------------------
# TestExport
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_returns_markdown(
        self, engine: RecoveryRecommendationEngine
    ) -> None:
        result = engine.create(recommendations=_sample_recommendations())
        md = engine.export_report(result["report_id"])
        assert "# Recovery Recommendation Report" in md
        assert "RETRY" in md

    def test_export_nonexistent_raises(
        self, engine: RecoveryRecommendationEngine
    ) -> None:
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id-abc123")


# ---------------------------------------------------------------------------
# TestSafety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(
        self, engine: RecoveryRecommendationEngine
    ) -> None:
        with pytest.raises(ValueError):
            engine.get_report("../../etc/passwd")

    def test_empty_id_rejected(
        self, engine: RecoveryRecommendationEngine
    ) -> None:
        with pytest.raises(ValueError):
            engine.get_report("")

    def test_whitespace_id_rejected(
        self, engine: RecoveryRecommendationEngine
    ) -> None:
        with pytest.raises(ValueError):
            engine.get_report("   ")

    def test_symlink_escape_rejected(
        self, engine: RecoveryRecommendationEngine, tmp_path: Path
    ) -> None:
        target = tmp_path / "outside"
        target.mkdir()
        link = Path(engine._report_dir) / "evil-link"
        make_symlink_or_skip(link, target)
        with pytest.raises(ValueError):
            engine.get_report("evil-link")

    def test_nonexistent_returns_none(
        self, engine: RecoveryRecommendationEngine
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
            "recovery-recommendation-create",
            "recovery-recommendation-show",
            "recovery-recommendation-export",
        }
        assert expected.issubset(set(names))


# ---------------------------------------------------------------------------
# TestSelectionMapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_recovery_recommendation_mapped(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/recovery_recommendation.py"]
            == "tests/test_recovery_recommendation.py"
        )
