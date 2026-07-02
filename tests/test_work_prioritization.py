"""Tests for the Work Prioritization Framework v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.work_prioritization import (
    WorkPrioritizationEngine,
    WorkPrioritizationReport,
    WorkPriorityFactor,
    WorkPriorityFactorType,
    WorkPriorityResult,
    WorkPriorityRule,
)

from tests.conftest import make_symlink_or_skip


@pytest.fixture()
def engine(tmp_path: Path) -> WorkPrioritizationEngine:
    return WorkPrioritizationEngine(artifacts_root=str(tmp_path))


def _sample_factors() -> list[dict]:
    return [
        {"work_id": "w1", "factor_type": "user_priority", "score": 5.0},
        {"work_id": "w2", "factor_type": "user_priority", "score": 9.0},
        {"work_id": "w3", "factor_type": "blocker_count", "score": 2.0},
    ]


def _sample_rules() -> list[dict]:
    return [
        {"name": "user_priority", "description": "User set priority", "weight": 2.0},
        {"name": "blocker_count", "description": "Blocking work", "weight": 3.0},
    ]


# ---------------------------------------------------------------------------
# TestModels
# ---------------------------------------------------------------------------


class TestModels:
    def test_rule_defaults(self) -> None:
        r = WorkPriorityRule()
        assert r.rule_id
        assert r.created_at
        assert r.weight == 1.0

    def test_factor_defaults(self) -> None:
        f = WorkPriorityFactor()
        assert f.factor_id
        assert f.created_at
        assert f.factor_type == "user_priority"

    def test_result_defaults(self) -> None:
        r = WorkPriorityResult()
        assert r.result_id
        assert r.created_at
        assert r.execution_rank == 0

    def test_report_defaults(self) -> None:
        r = WorkPrioritizationReport()
        assert r.report_id
        assert r.created_at
        assert r.item_count == 0


# ---------------------------------------------------------------------------
# TestCreate
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_empty(self, engine: WorkPrioritizationEngine) -> None:
        result = engine.create()
        assert result["item_count"] == 0
        assert result["highest_priority_work_id"] == ""
        assert result["results"] == []

    def test_create_with_factors(self, engine: WorkPrioritizationEngine) -> None:
        result = engine.create(factors=_sample_factors())
        assert result["item_count"] == 3
        assert len(result["results"]) == 3

    def test_all_factor_types(self, engine: WorkPrioritizationEngine) -> None:
        factors = [
            {"work_id": f"w{t.value}", "factor_type": t.value, "score": 1.0}
            for t in WorkPriorityFactorType
        ]
        result = engine.create(factors=factors)
        assert result["item_count"] == len(WorkPriorityFactorType)

    def test_rules_persisted(self, engine: WorkPrioritizationEngine) -> None:
        result = engine.create(rules=_sample_rules(), factors=_sample_factors())
        assert len(result["rules"]) == 2
        names = {r["name"] for r in result["rules"]}
        assert names == {"user_priority", "blocker_count"}


# ---------------------------------------------------------------------------
# TestFactorPersistence
# ---------------------------------------------------------------------------


class TestFactorPersistence:
    def test_factors_persisted(self, engine: WorkPrioritizationEngine) -> None:
        result = engine.create(factors=_sample_factors())
        assert len(result["factors"]) == 3
        by_work = {f["work_id"]: f for f in result["factors"]}
        assert by_work["w2"]["score"] == 9.0
        assert by_work["w3"]["factor_type"] == "blocker_count"

    def test_score_aggregation(self, engine: WorkPrioritizationEngine) -> None:
        factors = [
            {"work_id": "w1", "factor_type": "user_priority", "score": 3.0},
            {"work_id": "w1", "factor_type": "age", "score": 4.0},
        ]
        result = engine.create(factors=factors)
        by_work = {r["work_id"]: r for r in result["results"]}
        assert by_work["w1"]["priority_score"] == 7.0


# ---------------------------------------------------------------------------
# TestWeighting
# ---------------------------------------------------------------------------


class TestWeighting:
    def test_rule_weight_applied(self, engine: WorkPrioritizationEngine) -> None:
        result = engine.create(rules=_sample_rules(), factors=_sample_factors())
        by_work = {r["work_id"]: r for r in result["results"]}
        # w1: user_priority 5 * 2.0 = 10
        assert by_work["w1"]["priority_score"] == 10.0
        # w2: user_priority 9 * 2.0 = 18
        assert by_work["w2"]["priority_score"] == 18.0
        # w3: blocker_count 2 * 3.0 = 6
        assert by_work["w3"]["priority_score"] == 6.0

    def test_default_weight_without_rule(
        self, engine: WorkPrioritizationEngine
    ) -> None:
        result = engine.create(factors=_sample_factors())
        by_work = {r["work_id"]: r for r in result["results"]}
        assert by_work["w1"]["priority_score"] == 5.0
        assert by_work["w2"]["priority_score"] == 9.0


# ---------------------------------------------------------------------------
# TestRanking
# ---------------------------------------------------------------------------


class TestRanking:
    def test_highest_first(self, engine: WorkPrioritizationEngine) -> None:
        result = engine.create(rules=_sample_rules(), factors=_sample_factors())
        # Highest weighted score is w2 (18).
        assert result["highest_priority_work_id"] == "w2"
        by_rank = {r["execution_rank"]: r["work_id"] for r in result["results"]}
        assert by_rank[1] == "w2"

    def test_ranks_contiguous(self, engine: WorkPrioritizationEngine) -> None:
        result = engine.create(factors=_sample_factors())
        ranks = sorted(r["execution_rank"] for r in result["results"])
        assert ranks == [1, 2, 3]

    def test_stable_tie_breaking(self, engine: WorkPrioritizationEngine) -> None:
        factors = [
            {"work_id": "wb", "factor_type": "user_priority", "score": 5.0},
            {"work_id": "wa", "factor_type": "user_priority", "score": 5.0},
            {"work_id": "wc", "factor_type": "user_priority", "score": 5.0},
        ]
        result = engine.create(factors=factors)
        # All tied; tie-break by work_id ascending.
        by_rank = {r["execution_rank"]: r["work_id"] for r in result["results"]}
        assert by_rank[1] == "wa"
        assert by_rank[2] == "wb"
        assert by_rank[3] == "wc"

    def test_deterministic_across_input_order(
        self, engine: WorkPrioritizationEngine
    ) -> None:
        r1 = engine.create(factors=_sample_factors())
        r2 = engine.create(factors=list(reversed(_sample_factors())))
        ranks1 = [(r["execution_rank"], r["work_id"]) for r in r1["results"]]
        ranks2 = [(r["execution_rank"], r["work_id"]) for r in r2["results"]]
        assert ranks1 == ranks2


# ---------------------------------------------------------------------------
# TestValidation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_factor_type_rejected(
        self, engine: WorkPrioritizationEngine
    ) -> None:
        with pytest.raises(ValueError, match="Invalid factor_type"):
            engine.create(
                factors=[{"work_id": "w1", "factor_type": "phase_of_moon", "score": 1.0}]
            )

    def test_missing_work_id_rejected(
        self, engine: WorkPrioritizationEngine
    ) -> None:
        with pytest.raises(ValueError, match="work_id is required"):
            engine.create(factors=[{"factor_type": "age", "score": 1.0}])


# ---------------------------------------------------------------------------
# TestDeterministicOrdering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_factors_ordered(self, engine: WorkPrioritizationEngine) -> None:
        result = engine.create(factors=_sample_factors())
        keys = [
            (f["work_id"], f["factor_type"]) for f in result["factors"]
        ]
        assert keys == sorted(keys)

    def test_rules_ordered(self, engine: WorkPrioritizationEngine) -> None:
        result = engine.create(rules=_sample_rules())
        names = [r["name"] for r in result["rules"]]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# TestEvidenceGeneration
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_four_files_created(self, engine: WorkPrioritizationEngine) -> None:
        result = engine.create(rules=_sample_rules(), factors=_sample_factors())
        report_dir = Path(engine._report_dir) / result["report_id"]
        expected = {
            "work_priority_request.json",
            "work_priority_result.json",
            "work_priority_summary.md",
            "pass_fail.json",
        }
        actual = {f.name for f in report_dir.iterdir() if f.is_file()}
        assert expected.issubset(actual)

    def test_request_valid_json(self, engine: WorkPrioritizationEngine) -> None:
        result = engine.create(rules=_sample_rules(), factors=_sample_factors())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads((report_dir / "work_priority_request.json").read_text())
        assert len(data["factors"]) == 3
        assert len(data["rules"]) == 2

    def test_summary_has_sections(self, engine: WorkPrioritizationEngine) -> None:
        result = engine.create(rules=_sample_rules(), factors=_sample_factors())
        report_dir = Path(engine._report_dir) / result["report_id"]
        md = (report_dir / "work_priority_summary.md").read_text()
        assert "# Work Prioritization Report" in md
        assert "## Ranking" in md
        assert "## Rules" in md

    def test_pass_fail_passes(self, engine: WorkPrioritizationEngine) -> None:
        result = engine.create(factors=_sample_factors())
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True
        assert pf["well_formed_ranking"] is True

    def test_pass_fail_empty_passes(self, engine: WorkPrioritizationEngine) -> None:
        result = engine.create()
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, engine: WorkPrioritizationEngine) -> None:
        result = engine.create(factors=_sample_factors())
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]
        assert loaded["item_count"] == 3

    def test_list_reports_deterministic(
        self, engine: WorkPrioritizationEngine
    ) -> None:
        engine.create(factors=_sample_factors())
        engine.create()
        reports = engine.list_reports()
        assert len(reports) == 2
        assert reports[0]["created_at"] <= reports[1]["created_at"]


# ---------------------------------------------------------------------------
# TestExport
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_returns_markdown(self, engine: WorkPrioritizationEngine) -> None:
        result = engine.create(factors=_sample_factors())
        md = engine.export_report(result["report_id"])
        assert "# Work Prioritization Report" in md
        assert "## Ranking" in md

    def test_export_nonexistent_raises(
        self, engine: WorkPrioritizationEngine
    ) -> None:
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id-abc123")


# ---------------------------------------------------------------------------
# TestSafety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(
        self, engine: WorkPrioritizationEngine
    ) -> None:
        with pytest.raises(ValueError):
            engine.get_report("../../etc/passwd")

    def test_empty_id_rejected(self, engine: WorkPrioritizationEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("")

    def test_whitespace_id_rejected(self, engine: WorkPrioritizationEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("   ")

    def test_symlink_escape_rejected(
        self, engine: WorkPrioritizationEngine, tmp_path: Path
    ) -> None:
        target = tmp_path / "outside"
        target.mkdir()
        link = Path(engine._report_dir) / "evil-link"
        make_symlink_or_skip(link, target)
        with pytest.raises(ValueError):
            engine.get_report("evil-link")

    def test_nonexistent_returns_none(
        self, engine: WorkPrioritizationEngine
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
            "work-priority-create",
            "work-priority-show",
            "work-priority-export",
        }
        assert expected.issubset(set(names))


# ---------------------------------------------------------------------------
# TestSelectionMapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_work_prioritization_mapped(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/work_prioritization.py"]
            == "tests/test_work_prioritization.py"
        )
