"""Tests for the Capability Routing Framework v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.capability_routing import (
    CapabilityRoute,
    CapabilityRoutingDecision,
    CapabilityRoutingEngine,
    CapabilityRoutingEvidence,
    CapabilityRoutingReport,
    CapabilityRoutingRule,
)

from tests.conftest import make_symlink_or_skip


@pytest.fixture()
def engine(tmp_path: Path) -> CapabilityRoutingEngine:
    return CapabilityRoutingEngine(artifacts_root=str(tmp_path))


def _sample_routes() -> list[dict]:
    return [
        {
            "capability_id": "cap-grids",
            "work_type": "grids",
            "priority": 10,
            "created_at": "2026-01-02T00:00:00+00:00",
        },
        {
            "capability_id": "cap-levels",
            "work_type": "levels",
            "priority": 5,
            "created_at": "2026-01-01T00:00:00+00:00",
        },
    ]


def _sample_rules() -> list[dict]:
    return [
        {
            "work_pattern": "create *grid*",
            "capability_id": "cap-grids",
            "weight": 7,
            "created_at": "2026-01-02T00:00:00+00:00",
        },
        {
            "work_pattern": "create *level*",
            "capability_id": "cap-levels",
            "weight": 3,
            "created_at": "2026-01-01T00:00:00+00:00",
        },
    ]


def _sample_decisions() -> list[dict]:
    return [
        {
            "work_id": "w-3",
            "selected_capability_id": "cap-grids",
            "candidate_count": 2,
            "routing_score": 90,
            "rationale": "grid intent",
            "created_at": "2026-01-03T00:00:00+00:00",
        },
        {
            "work_id": "w-1",
            "selected_capability_id": "cap-levels",
            "candidate_count": 1,
            "routing_score": 80,
            "rationale": "level intent",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "work_id": "w-2",
            "selected_capability_id": "cap-grids",
            "candidate_count": 3,
            "routing_score": 70,
            "rationale": "grid intent",
            "created_at": "2026-01-02T00:00:00+00:00",
        },
    ]


def _sample_all() -> dict:
    return {
        "routes": _sample_routes(),
        "rules": _sample_rules(),
        "decisions": _sample_decisions(),
    }


# ---------------------------------------------------------------------------
# TestModels
# ---------------------------------------------------------------------------


class TestModels:
    def test_route_defaults(self) -> None:
        r = CapabilityRoute()
        assert r.route_id
        assert r.created_at
        assert r.priority == 0

    def test_rule_defaults(self) -> None:
        r = CapabilityRoutingRule()
        assert r.rule_id
        assert r.created_at
        assert r.weight == 0

    def test_decision_defaults(self) -> None:
        d = CapabilityRoutingDecision()
        assert d.decision_id
        assert d.created_at
        assert d.candidate_count == 0
        assert d.routing_score == 0

    def test_report_defaults(self) -> None:
        r = CapabilityRoutingReport()
        assert r.report_id
        assert r.created_at
        assert r.decision_count == 0
        assert r.capability_counts == {}

    def test_evidence_defaults(self) -> None:
        e = CapabilityRoutingEvidence()
        assert e.evidence_id
        assert e.created_at


# ---------------------------------------------------------------------------
# TestCreate
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_empty(self, engine: CapabilityRoutingEngine) -> None:
        result = engine.create()
        assert result["decision_count"] == 0
        assert result["routes"] == []
        assert result["rules"] == []
        assert result["decisions"] == []
        assert result["capability_counts"] == {}

    def test_create_with_all(self, engine: CapabilityRoutingEngine) -> None:
        result = engine.create(**_sample_all())
        assert result["decision_count"] == 3
        assert len(result["routes"]) == 2
        assert len(result["rules"]) == 2

    def test_report_id_present(self, engine: CapabilityRoutingEngine) -> None:
        result = engine.create(**_sample_all())
        assert result["report_id"]

    def test_create_decisions_only(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        result = engine.create(decisions=_sample_decisions())
        assert result["decision_count"] == 3
        assert result["routes"] == []


# ---------------------------------------------------------------------------
# TestCapabilityCounts
# ---------------------------------------------------------------------------


class TestCapabilityCounts:
    def test_capability_counts(self, engine: CapabilityRoutingEngine) -> None:
        result = engine.create(**_sample_all())
        counts = result["capability_counts"]
        assert counts["cap-grids"] == 2
        assert counts["cap-levels"] == 1

    def test_capability_counts_sorted_keys(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        result = engine.create(**_sample_all())
        keys = list(result["capability_counts"].keys())
        assert keys == sorted(keys)

    def test_unrouted_excluded_from_counts(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        result = engine.create(
            decisions=[
                {"work_id": "w-1", "selected_capability_id": ""},
                {"work_id": "w-2", "selected_capability_id": "cap-x"},
            ]
        )
        assert result["capability_counts"] == {"cap-x": 1}


# ---------------------------------------------------------------------------
# TestPersistenceOfFields
# ---------------------------------------------------------------------------


class TestPersistenceOfFields:
    def test_route_fields_persisted(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        result = engine.create(routes=_sample_routes())
        by_cap = {r["capability_id"]: r for r in result["routes"]}
        assert by_cap["cap-grids"]["work_type"] == "grids"
        assert by_cap["cap-grids"]["priority"] == 10

    def test_rule_fields_persisted(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        result = engine.create(rules=_sample_rules())
        by_cap = {r["capability_id"]: r for r in result["rules"]}
        assert by_cap["cap-grids"]["work_pattern"] == "create *grid*"
        assert by_cap["cap-grids"]["weight"] == 7

    def test_decision_fields_persisted(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        result = engine.create(decisions=_sample_decisions())
        by_work = {d["work_id"]: d for d in result["decisions"]}
        assert by_work["w-3"]["selected_capability_id"] == "cap-grids"
        assert by_work["w-3"]["routing_score"] == 90
        assert by_work["w-3"]["candidate_count"] == 2
        assert by_work["w-3"]["rationale"] == "grid intent"

    def test_work_id_reference_preserved(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        result = engine.create(decisions=_sample_decisions())
        work_ids = {d["work_id"] for d in result["decisions"]}
        assert work_ids == {"w-1", "w-2", "w-3"}


# ---------------------------------------------------------------------------
# TestDeterministicOrdering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_decisions_ordered(self, engine: CapabilityRoutingEngine) -> None:
        result = engine.create(decisions=_sample_decisions())
        created = [d["created_at"] for d in result["decisions"]]
        assert created == sorted(created)

    def test_routes_ordered(self, engine: CapabilityRoutingEngine) -> None:
        result = engine.create(routes=_sample_routes())
        created = [r["created_at"] for r in result["routes"]]
        assert created == sorted(created)

    def test_rules_ordered(self, engine: CapabilityRoutingEngine) -> None:
        result = engine.create(rules=_sample_rules())
        created = [r["created_at"] for r in result["rules"]]
        assert created == sorted(created)

    def test_order_independent(self, engine: CapabilityRoutingEngine) -> None:
        r1 = engine.create(decisions=_sample_decisions())
        r2 = engine.create(decisions=list(reversed(_sample_decisions())))
        keys1 = [(d["created_at"], d["work_id"]) for d in r1["decisions"]]
        keys2 = [(d["created_at"], d["work_id"]) for d in r2["decisions"]]
        assert keys1 == keys2


# ---------------------------------------------------------------------------
# TestValidation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_route_missing_capability_rejected(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        with pytest.raises(ValueError, match="capability_id is required"):
            engine.create(routes=[{"work_type": "grids"}])

    def test_rule_missing_capability_rejected(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        with pytest.raises(ValueError, match="capability_id is required"):
            engine.create(rules=[{"work_pattern": "create *grid*"}])

    def test_rule_missing_pattern_rejected(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        with pytest.raises(ValueError, match="work_pattern is required"):
            engine.create(rules=[{"capability_id": "cap-x"}])

    def test_rule_whitespace_pattern_rejected(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        with pytest.raises(ValueError, match="work_pattern is required"):
            engine.create(
                rules=[{"capability_id": "cap-x", "work_pattern": "   "}]
            )

    def test_decision_missing_work_id_rejected(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        with pytest.raises(ValueError, match="work_id is required"):
            engine.create(
                decisions=[{"selected_capability_id": "cap-x"}]
            )


# ---------------------------------------------------------------------------
# TestEvidenceGeneration
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_four_files_created(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        result = engine.create(**_sample_all())
        report_dir = Path(engine._report_dir) / result["report_id"]
        expected = {
            "capability_routing_request.json",
            "capability_routing_result.json",
            "capability_routing_summary.md",
            "pass_fail.json",
        }
        actual = {f.name for f in report_dir.iterdir() if f.is_file()}
        assert expected.issubset(actual)

    def test_request_valid_json(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        result = engine.create(**_sample_all())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads(
            (report_dir / "capability_routing_request.json").read_text()
        )
        assert len(data["decisions"]) == 3
        assert len(data["routes"]) == 2
        assert len(data["rules"]) == 2

    def test_result_valid_json(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        result = engine.create(**_sample_all())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads(
            (report_dir / "capability_routing_result.json").read_text()
        )
        assert data["report_id"] == result["report_id"]
        assert data["decision_count"] == 3

    def test_summary_has_sections(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        result = engine.create(**_sample_all())
        report_dir = Path(engine._report_dir) / result["report_id"]
        md = (report_dir / "capability_routing_summary.md").read_text()
        assert "# Capability Routing Report" in md
        assert "## Routing Summary" in md
        assert "## Capability Counts" in md
        assert "## Decisions" in md

    def test_pass_fail_passes_when_all_routed(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        result = engine.create(**_sample_all())
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True
        assert pf["status"] == "passed"
        assert pf["unrouted_count"] == 0

    def test_pass_fail_fails_on_unrouted(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        result = engine.create(
            decisions=[{"work_id": "w-1", "selected_capability_id": ""}]
        )
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is False
        assert pf["unrouted_count"] == 1

    def test_pass_fail_empty_report_passes(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        result = engine.create()
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, engine: CapabilityRoutingEngine) -> None:
        result = engine.create(**_sample_all())
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]
        assert loaded["decision_count"] == 3

    def test_list_reports_deterministic(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        engine.create(**_sample_all())
        engine.create()
        reports = engine.list_reports()
        assert len(reports) == 2
        assert reports[0]["created_at"] <= reports[1]["created_at"]


# ---------------------------------------------------------------------------
# TestExport
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_returns_markdown(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        result = engine.create(**_sample_all())
        md = engine.export_report(result["report_id"])
        assert "# Capability Routing Report" in md
        assert "cap-grids" in md

    def test_export_nonexistent_raises(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id-abc123")

    def test_export_marks_unrouted(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        result = engine.create(
            decisions=[{"work_id": "w-1", "selected_capability_id": ""}]
        )
        md = engine.export_report(result["report_id"])
        assert "(unrouted)" in md


# ---------------------------------------------------------------------------
# TestSafety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        with pytest.raises(ValueError):
            engine.get_report("../../etc/passwd")

    def test_empty_id_rejected(self, engine: CapabilityRoutingEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("")

    def test_whitespace_id_rejected(
        self, engine: CapabilityRoutingEngine
    ) -> None:
        with pytest.raises(ValueError):
            engine.get_report("   ")

    def test_symlink_escape_rejected(
        self, engine: CapabilityRoutingEngine, tmp_path: Path
    ) -> None:
        target = tmp_path / "outside"
        target.mkdir()
        link = Path(engine._report_dir) / "evil-link"
        make_symlink_or_skip(link, target)
        with pytest.raises(ValueError):
            engine.get_report("evil-link")

    def test_nonexistent_returns_none(
        self, engine: CapabilityRoutingEngine
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
            "capability-routing-create",
            "capability-routing-show",
            "capability-routing-export",
        }
        assert expected.issubset(set(names))


# ---------------------------------------------------------------------------
# TestSelectionMapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_capability_routing_mapped(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/capability_routing.py"]
            == "tests/test_capability_routing.py"
        )
