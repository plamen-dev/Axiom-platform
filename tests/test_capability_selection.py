"""Tests for the Capability Selection Framework v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.capability_selection import (
    CapabilitySelectionCandidate,
    CapabilitySelectionDecision,
    CapabilitySelectionEngine,
    CapabilitySelectionEvidence,
    CapabilitySelectionReason,
    CapabilitySelectionReport,
)

from tests.conftest import make_symlink_or_skip


@pytest.fixture()
def engine(tmp_path: Path) -> CapabilitySelectionEngine:
    return CapabilitySelectionEngine(artifacts_root=str(tmp_path))


def _sample_candidates() -> list[dict]:
    return [
        {
            "capability_id": "cap-grids",
            "work_id": "w-alpha",
            "routing_score": 50,
            "confidence_score": 30,
            "priority_score": 10,
            "final_score": 90,
            "created_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "capability_id": "cap-levels",
            "work_id": "w-alpha",
            "routing_score": 40,
            "confidence_score": 20,
            "priority_score": 10,
            "final_score": 70,
            "created_at": "2026-01-02T00:00:00+00:00",
        },
        {
            "capability_id": "cap-grids",
            "work_id": "w-bravo",
            "routing_score": 30,
            "confidence_score": 20,
            "priority_score": 5,
            "final_score": 55,
            "created_at": "2026-01-03T00:00:00+00:00",
        },
        {
            "capability_id": "cap-walls",
            "work_id": "w-charlie",
            "routing_score": 60,
            "confidence_score": 25,
            "priority_score": 15,
            "final_score": 100,
            "created_at": "2026-01-04T00:00:00+00:00",
        },
    ]


# ---------------------------------------------------------------------------
# TestModels
# ---------------------------------------------------------------------------


class TestModels:
    def test_candidate_defaults(self) -> None:
        c = CapabilitySelectionCandidate()
        assert c.candidate_id
        assert c.created_at
        assert c.final_score == 0

    def test_reason_defaults(self) -> None:
        r = CapabilitySelectionReason()
        assert r.reason_id
        assert r.created_at

    def test_decision_defaults(self) -> None:
        d = CapabilitySelectionDecision()
        assert d.decision_id
        assert d.created_at
        assert d.candidate_count == 0
        assert d.reasons == []

    def test_report_defaults(self) -> None:
        r = CapabilitySelectionReport()
        assert r.report_id
        assert r.created_at
        assert r.decision_count == 0
        assert r.capability_counts == {}

    def test_evidence_defaults(self) -> None:
        e = CapabilitySelectionEvidence()
        assert e.evidence_id
        assert e.created_at

    def test_decision_to_dict_serializes_reasons(self) -> None:
        d = CapabilitySelectionDecision(
            work_id="w-1",
            reasons=[CapabilitySelectionReason(reason_type="HIGHEST_SCORE")],
        )
        data = d.to_dict()
        assert data["reasons"][0]["reason_type"] == "HIGHEST_SCORE"


# ---------------------------------------------------------------------------
# TestCreate
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_empty(self, engine: CapabilitySelectionEngine) -> None:
        result = engine.create()
        assert result["decision_count"] == 0
        assert result["candidates"] == []
        assert result["decisions"] == []
        assert result["capability_counts"] == {}

    def test_create_with_candidates(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=_sample_candidates())
        assert len(result["candidates"]) == 4
        # 3 distinct work ids -> 3 decisions.
        assert result["decision_count"] == 3

    def test_report_id_present(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=_sample_candidates())
        assert result["report_id"]

    def test_final_score_derived_when_missing(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(
            candidates=[
                {
                    "capability_id": "cap-x",
                    "work_id": "w-1",
                    "routing_score": 10,
                    "confidence_score": 20,
                    "priority_score": 5,
                }
            ]
        )
        assert result["candidates"][0]["final_score"] == 35

    def test_decision_count_includes_declared_work_ids(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(
            candidates=_sample_candidates(),
            decisions=[{"work_id": "w-delta"}],
        )
        assert result["decision_count"] == 4


# ---------------------------------------------------------------------------
# TestSelection
# ---------------------------------------------------------------------------


class TestSelection:
    def test_highest_final_score_wins(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=_sample_candidates())
        by_work = {d["work_id"]: d for d in result["decisions"]}
        assert by_work["w-alpha"]["selected_capability_id"] == "cap-grids"
        assert by_work["w-alpha"]["final_score"] == 90

    def test_selected_candidate_id_recorded(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=_sample_candidates())
        by_work = {d["work_id"]: d for d in result["decisions"]}
        cand_by_id = {c["candidate_id"]: c for c in result["candidates"]}
        sel_id = by_work["w-alpha"]["selected_candidate_id"]
        assert cand_by_id[sel_id]["capability_id"] == "cap-grids"

    def test_candidate_count_per_decision(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=_sample_candidates())
        by_work = {d["work_id"]: d for d in result["decisions"]}
        assert by_work["w-alpha"]["candidate_count"] == 2
        assert by_work["w-bravo"]["candidate_count"] == 1

    def test_single_candidate_selected(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=_sample_candidates())
        by_work = {d["work_id"]: d for d in result["decisions"]}
        assert by_work["w-bravo"]["selected_capability_id"] == "cap-grids"

    def test_selected_count(self, engine: CapabilitySelectionEngine) -> None:
        result = engine.create(candidates=_sample_candidates())
        assert result["selected_count"] == 3
        assert result["no_candidate_count"] == 0


# ---------------------------------------------------------------------------
# TestTieBreaking
# ---------------------------------------------------------------------------


class TestTieBreaking:
    def _tied(self) -> list[dict]:
        return [
            {
                "capability_id": "cap-bravo",
                "work_id": "w-1",
                "final_score": 50,
                "confidence_score": 10,
                "priority_score": 10,
            },
            {
                "capability_id": "cap-alpha",
                "work_id": "w-1",
                "final_score": 50,
                "confidence_score": 10,
                "priority_score": 10,
            },
        ]

    def test_tie_broken_by_capability_id(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=self._tied())
        d = result["decisions"][0]
        assert d["selected_capability_id"] == "cap-alpha"

    def test_tie_breaker_reason_present(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=self._tied())
        reasons = {r["reason_type"] for r in result["decisions"][0]["reasons"]}
        assert "TIE_BREAKER" in reasons

    def test_tie_breaking_is_stable_across_input_order(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        r1 = engine.create(candidates=self._tied())
        r2 = engine.create(candidates=list(reversed(self._tied())))
        assert (
            r1["decisions"][0]["selected_capability_id"]
            == r2["decisions"][0]["selected_capability_id"]
        )

    def test_confidence_breaks_equal_final(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(
            candidates=[
                {
                    "capability_id": "cap-low",
                    "work_id": "w-1",
                    "final_score": 50,
                    "confidence_score": 10,
                },
                {
                    "capability_id": "cap-high",
                    "work_id": "w-1",
                    "final_score": 50,
                    "confidence_score": 40,
                },
            ]
        )
        assert result["decisions"][0]["selected_capability_id"] == "cap-high"


# ---------------------------------------------------------------------------
# TestReasons
# ---------------------------------------------------------------------------


class TestReasons:
    def test_highest_score_reason(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=_sample_candidates())
        by_work = {d["work_id"]: d for d in result["decisions"]}
        reasons = {r["reason_type"] for r in by_work["w-alpha"]["reasons"]}
        assert "HIGHEST_SCORE" in reasons

    def test_routing_match_reason(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=_sample_candidates())
        by_work = {d["work_id"]: d for d in result["decisions"]}
        reasons = {r["reason_type"] for r in by_work["w-alpha"]["reasons"]}
        assert "ROUTING_MATCH" in reasons

    def test_no_routing_match_when_zero(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(
            candidates=[
                {
                    "capability_id": "cap-x",
                    "work_id": "w-1",
                    "routing_score": 0,
                    "confidence_score": 5,
                    "final_score": 5,
                }
            ]
        )
        reasons = {r["reason_type"] for r in result["decisions"][0]["reasons"]}
        assert "ROUTING_MATCH" not in reasons

    def test_no_candidate_reason(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(decisions=[{"work_id": "w-empty"}])
        reasons = {r["reason_type"] for r in result["decisions"][0]["reasons"]}
        assert reasons == {"NO_CANDIDATE"}

    def test_reasons_in_canonical_order(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=_sample_candidates())
        by_work = {d["work_id"]: d for d in result["decisions"]}
        types = [r["reason_type"] for r in by_work["w-alpha"]["reasons"]]
        order = [
            "ROUTING_MATCH",
            "HIGHEST_SCORE",
            "HIGHEST_CONFIDENCE",
            "HIGHEST_PRIORITY",
            "TIE_BREAKER",
            "NO_CANDIDATE",
        ]
        ranks = [order.index(t) for t in types]
        assert ranks == sorted(ranks)

    def test_reason_persisted_with_summary(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=_sample_candidates())
        by_work = {d["work_id"]: d for d in result["decisions"]}
        for r in by_work["w-alpha"]["reasons"]:
            assert r["summary"]
            assert r["reason_id"]


# ---------------------------------------------------------------------------
# TestNoCandidate
# ---------------------------------------------------------------------------


class TestNoCandidate:
    def test_no_candidate_decision(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(decisions=[{"work_id": "w-empty"}])
        d = result["decisions"][0]
        assert d["selected_capability_id"] == ""
        assert d["candidate_count"] == 0

    def test_no_candidate_count(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(
            candidates=_sample_candidates(),
            decisions=[{"work_id": "w-empty"}],
        )
        assert result["no_candidate_count"] == 1
        assert result["selected_count"] == 3

    def test_no_candidate_excluded_from_counts(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(decisions=[{"work_id": "w-empty"}])
        assert result["capability_counts"] == {}


# ---------------------------------------------------------------------------
# TestCapabilityCounts
# ---------------------------------------------------------------------------


class TestCapabilityCounts:
    def test_capability_counts(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=_sample_candidates())
        counts = result["capability_counts"]
        assert counts["cap-grids"] == 2
        assert counts["cap-walls"] == 1

    def test_capability_counts_sorted_keys(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=_sample_candidates())
        keys = list(result["capability_counts"].keys())
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# TestDeterministicOrdering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_candidates_ordered(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=_sample_candidates())
        created = [c["created_at"] for c in result["candidates"]]
        assert created == sorted(created)

    def test_decisions_ordered_by_work_id(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=_sample_candidates())
        work_ids = [d["work_id"] for d in result["decisions"]]
        assert work_ids == sorted(work_ids)

    def test_order_independent(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        r1 = engine.create(candidates=_sample_candidates())
        r2 = engine.create(candidates=list(reversed(_sample_candidates())))
        keys1 = [d["work_id"] for d in r1["decisions"]]
        keys2 = [d["work_id"] for d in r2["decisions"]]
        assert keys1 == keys2
        sel1 = [d["selected_capability_id"] for d in r1["decisions"]]
        sel2 = [d["selected_capability_id"] for d in r2["decisions"]]
        assert sel1 == sel2


# ---------------------------------------------------------------------------
# TestValidation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_candidate_missing_capability_rejected(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        with pytest.raises(ValueError, match="capability_id is required"):
            engine.create(candidates=[{"work_id": "w-1"}])

    def test_candidate_missing_work_id_rejected(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        with pytest.raises(ValueError, match="work_id is required"):
            engine.create(candidates=[{"capability_id": "cap-x"}])

    def test_decision_missing_work_id_rejected(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        with pytest.raises(ValueError, match="work_id is required"):
            engine.create(decisions=[{"selected_capability_id": "cap-x"}])


# ---------------------------------------------------------------------------
# TestEvidenceGeneration
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_four_files_created(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=_sample_candidates())
        report_dir = Path(engine._report_dir) / result["report_id"]
        expected = {
            "capability_selection_request.json",
            "capability_selection_result.json",
            "capability_selection_summary.md",
            "pass_fail.json",
        }
        actual = {f.name for f in report_dir.iterdir() if f.is_file()}
        assert expected.issubset(actual)

    def test_request_valid_json(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=_sample_candidates())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads(
            (report_dir / "capability_selection_request.json").read_text()
        )
        assert len(data["candidates"]) == 4

    def test_result_valid_json(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=_sample_candidates())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads(
            (report_dir / "capability_selection_result.json").read_text()
        )
        assert data["report_id"] == result["report_id"]
        assert data["decision_count"] == 3

    def test_summary_has_sections(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=_sample_candidates())
        report_dir = Path(engine._report_dir) / result["report_id"]
        md = (report_dir / "capability_selection_summary.md").read_text()
        assert "# Capability Selection Report" in md
        assert "## Selection Summary" in md
        assert "## Capability Counts" in md
        assert "## Candidates" in md
        assert "## Decisions" in md

    def test_pass_fail_passes_when_all_selected(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=_sample_candidates())
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True
        assert pf["status"] == "passed"
        assert pf["no_candidate_count"] == 0

    def test_pass_fail_fails_on_no_candidate(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(decisions=[{"work_id": "w-empty"}])
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is False
        assert pf["no_candidate_count"] == 1

    def test_pass_fail_empty_report_passes(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create()
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, engine: CapabilitySelectionEngine) -> None:
        result = engine.create(candidates=_sample_candidates())
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]
        assert loaded["decision_count"] == 3

    def test_round_trip_identical(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=_sample_candidates())
        loaded = engine.get_report(result["report_id"])
        assert loaded == result

    def test_list_reports_deterministic(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        engine.create(candidates=_sample_candidates())
        engine.create()
        reports = engine.list_reports()
        assert len(reports) == 2
        assert reports[0]["created_at"] <= reports[1]["created_at"]


# ---------------------------------------------------------------------------
# TestExport
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_returns_markdown(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=_sample_candidates())
        md = engine.export_report(result["report_id"])
        assert "# Capability Selection Report" in md
        assert "cap-grids" in md

    def test_export_includes_reasons(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(candidates=_sample_candidates())
        md = engine.export_report(result["report_id"])
        assert "HIGHEST_SCORE" in md

    def test_export_nonexistent_raises(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id-abc123")

    def test_export_marks_no_candidate(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        result = engine.create(decisions=[{"work_id": "w-empty"}])
        md = engine.export_report(result["report_id"])
        assert "(no candidate)" in md


# ---------------------------------------------------------------------------
# TestSafety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        with pytest.raises(ValueError):
            engine.get_report("../../etc/passwd")

    def test_empty_id_rejected(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        with pytest.raises(ValueError):
            engine.get_report("")

    def test_whitespace_id_rejected(
        self, engine: CapabilitySelectionEngine
    ) -> None:
        with pytest.raises(ValueError):
            engine.get_report("   ")

    def test_symlink_escape_rejected(
        self, engine: CapabilitySelectionEngine, tmp_path: Path
    ) -> None:
        target = tmp_path / "outside"
        target.mkdir()
        link = Path(engine._report_dir) / "evil-link"
        make_symlink_or_skip(link, target)
        with pytest.raises(ValueError):
            engine.get_report("evil-link")

    def test_nonexistent_returns_none(
        self, engine: CapabilitySelectionEngine
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
            "capability-selection-create",
            "capability-selection-show",
            "capability-selection-export",
        }
        assert expected.issubset(set(names))


# ---------------------------------------------------------------------------
# TestSelectionMapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_capability_selection_mapped(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/capability_selection.py"]
            == "tests/test_capability_selection.py"
        )
