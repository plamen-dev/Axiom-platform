"""Comprehensive tests for Capability Chain Framework v1."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest
from axiom_core.capability_chain import (
    CapabilityChain,
    CapabilityChainEngine,
    CapabilityChainEvidence,
    CapabilityChainReport,
    CapabilityChainStep,
    CapabilityChainType,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tmp_engine() -> CapabilityChainEngine:
    tmp = tempfile.mkdtemp()
    return CapabilityChainEngine(artifacts_root=tmp)


def _basic_chains() -> list[dict]:
    return [
        {
            "work_id": "w-alpha",
            "chain_type": "linear",
            "steps": [
                {"order_index": 1, "capability_id": "cap-grids", "selection_id": "sel-1", "description": "create grids"},
                {"order_index": 0, "capability_id": "cap-levels", "selection_id": "sel-2", "description": "create levels"},
            ],
            "created_at": "2026-03-01T00:00:00+00:00",
        },
        {
            "work_id": "w-bravo",
            "chain_type": "validation_chain",
            "steps": [
                {"order_index": 0, "capability_id": "cap-validate", "selection_id": "sel-3"},
            ],
            "created_at": "2026-03-02T00:00:00+00:00",
        },
    ]


# ---------------------------------------------------------------------------
# TestModels
# ---------------------------------------------------------------------------


class TestModels:
    def test_chain_step_defaults(self):
        step = CapabilityChainStep()
        assert step.step_id
        assert step.order_index == 0
        assert step.capability_id == ""
        assert step.selection_id == ""
        assert step.description == ""

    def test_chain_step_serialization(self):
        step = CapabilityChainStep(
            order_index=2, capability_id="cap-x", selection_id="sel-x", description="do x"
        )
        d = step.to_dict()
        assert d["order_index"] == 2
        assert d["capability_id"] == "cap-x"
        assert d["selection_id"] == "sel-x"
        assert d["description"] == "do x"
        assert "step_id" in d

    def test_chain_defaults(self):
        chain = CapabilityChain()
        assert chain.chain_id
        assert chain.work_id == ""
        assert chain.chain_type == "linear"
        assert chain.steps == []
        assert chain.created_at

    def test_chain_serialization(self):
        chain = CapabilityChain(work_id="w-1", chain_type="repair_chain")
        d = chain.to_dict()
        assert d["work_id"] == "w-1"
        assert d["chain_type"] == "repair_chain"
        assert d["steps"] == []

    def test_report_defaults(self):
        report = CapabilityChainReport()
        assert report.report_id
        assert report.chain_count == 0
        assert report.step_count == 0
        assert report.chain_type_counts == {}
        assert report.empty_step_count == 0
        assert report.created_at

    def test_evidence_defaults(self):
        ev = CapabilityChainEvidence(report_id="r-1", summary="test")
        assert ev.evidence_id
        assert ev.report_id == "r-1"
        assert ev.summary == "test"
        assert ev.created_at

    def test_chain_type_enum_values(self):
        assert CapabilityChainType.LINEAR.value == "linear"
        assert CapabilityChainType.VALIDATION_CHAIN.value == "validation_chain"
        assert CapabilityChainType.REPAIR_CHAIN.value == "repair_chain"
        assert CapabilityChainType.REVIEW_CHAIN.value == "review_chain"
        assert CapabilityChainType.CUSTOM_CHAIN.value == "custom_chain"


# ---------------------------------------------------------------------------
# TestCreate
# ---------------------------------------------------------------------------


class TestCreate:
    def test_empty_create(self):
        engine = _tmp_engine()
        report = engine.create()
        assert report["chain_count"] == 0
        assert report["step_count"] == 0
        assert report["empty_step_count"] == 0
        assert report["chain_type_counts"] == {}
        assert report["chains"] == []

    def test_create_with_chains(self):
        engine = _tmp_engine()
        report = engine.create(chains=_basic_chains())
        assert report["chain_count"] == 2
        assert report["step_count"] == 3
        assert report["empty_step_count"] == 0

    def test_report_id_generated(self):
        engine = _tmp_engine()
        r1 = engine.create()
        r2 = engine.create()
        assert r1["report_id"] != r2["report_id"]

    def test_chain_type_counts_sorted(self):
        engine = _tmp_engine()
        report = engine.create(chains=_basic_chains())
        keys = list(report["chain_type_counts"].keys())
        assert keys == sorted(keys)
        assert report["chain_type_counts"]["linear"] == 1
        assert report["chain_type_counts"]["validation_chain"] == 1

    def test_step_count_correct(self):
        engine = _tmp_engine()
        chains = [
            {"work_id": "w-1", "chain_type": "linear", "steps": [
                {"order_index": 0, "capability_id": "cap-a"},
                {"order_index": 1, "capability_id": "cap-b"},
                {"order_index": 2, "capability_id": "cap-c"},
            ]},
        ]
        report = engine.create(chains=chains)
        assert report["step_count"] == 3


# ---------------------------------------------------------------------------
# TestStepOrdering
# ---------------------------------------------------------------------------


class TestStepOrdering:
    def test_steps_sorted_by_order_index(self):
        engine = _tmp_engine()
        chains = [
            {"work_id": "w-1", "chain_type": "linear", "steps": [
                {"order_index": 2, "capability_id": "cap-c"},
                {"order_index": 0, "capability_id": "cap-a"},
                {"order_index": 1, "capability_id": "cap-b"},
            ]},
        ]
        report = engine.create(chains=chains)
        steps = report["chains"][0]["steps"]
        assert [s["order_index"] for s in steps] == [0, 1, 2]
        assert [s["capability_id"] for s in steps] == ["cap-a", "cap-b", "cap-c"]

    def test_equal_order_index_breaks_by_capability_id(self):
        engine = _tmp_engine()
        chains = [
            {"work_id": "w-1", "chain_type": "linear", "steps": [
                {"order_index": 0, "capability_id": "cap-zeta"},
                {"order_index": 0, "capability_id": "cap-alpha"},
            ]},
        ]
        report = engine.create(chains=chains)
        steps = report["chains"][0]["steps"]
        assert steps[0]["capability_id"] == "cap-alpha"
        assert steps[1]["capability_id"] == "cap-zeta"


# ---------------------------------------------------------------------------
# TestChainOrdering
# ---------------------------------------------------------------------------


class TestChainOrdering:
    def test_chains_sorted_by_created_at(self):
        engine = _tmp_engine()
        chains = [
            {"work_id": "w-late", "chain_type": "linear", "steps": [
                {"order_index": 0, "capability_id": "cap-a"}
            ], "created_at": "2026-03-10T00:00:00+00:00"},
            {"work_id": "w-early", "chain_type": "linear", "steps": [
                {"order_index": 0, "capability_id": "cap-b"}
            ], "created_at": "2026-03-01T00:00:00+00:00"},
        ]
        report = engine.create(chains=chains)
        work_ids = [c["work_id"] for c in report["chains"]]
        assert work_ids == ["w-early", "w-late"]

    def test_same_created_at_breaks_by_work_id(self):
        engine = _tmp_engine()
        chains = [
            {"work_id": "w-zeta", "chain_type": "linear", "steps": [
                {"order_index": 0, "capability_id": "cap-a"}
            ], "created_at": "2026-03-01T00:00:00+00:00"},
            {"work_id": "w-alpha", "chain_type": "linear", "steps": [
                {"order_index": 0, "capability_id": "cap-b"}
            ], "created_at": "2026-03-01T00:00:00+00:00"},
        ]
        report = engine.create(chains=chains)
        work_ids = [c["work_id"] for c in report["chains"]]
        assert work_ids == ["w-alpha", "w-zeta"]

    def test_order_independent_results(self):
        engine = _tmp_engine()
        chains_a = [
            {"work_id": "w-2", "chain_type": "linear", "steps": [
                {"order_index": 0, "capability_id": "cap-a"}
            ], "created_at": "2026-03-02T00:00:00+00:00"},
            {"work_id": "w-1", "chain_type": "linear", "steps": [
                {"order_index": 0, "capability_id": "cap-b"}
            ], "created_at": "2026-03-01T00:00:00+00:00"},
        ]
        chains_b = list(reversed(chains_a))
        r1 = engine.create(chains=chains_a)
        r2 = engine.create(chains=chains_b)
        # Same ordering regardless of input order
        assert [c["work_id"] for c in r1["chains"]] == [c["work_id"] for c in r2["chains"]]


# ---------------------------------------------------------------------------
# TestEmptyChains
# ---------------------------------------------------------------------------


class TestEmptyChains:
    def test_empty_chain_counted(self):
        engine = _tmp_engine()
        chains = [
            {"work_id": "w-empty", "chain_type": "linear", "steps": []},
            {"work_id": "w-full", "chain_type": "linear", "steps": [
                {"order_index": 0, "capability_id": "cap-a"}
            ]},
        ]
        report = engine.create(chains=chains)
        assert report["empty_step_count"] == 1
        assert report["chain_count"] == 2
        assert report["step_count"] == 1

    def test_all_empty_chains(self):
        engine = _tmp_engine()
        chains = [
            {"work_id": "w-1", "chain_type": "linear", "steps": []},
            {"work_id": "w-2", "chain_type": "repair_chain", "steps": []},
        ]
        report = engine.create(chains=chains)
        assert report["empty_step_count"] == 2
        assert report["step_count"] == 0

    def test_empty_chain_renders_as_empty_in_export(self):
        engine = _tmp_engine()
        chains = [
            {"work_id": "w-empty", "chain_type": "linear", "steps": []},
        ]
        report = engine.create(chains=chains)
        md = engine.export_report(report["report_id"])
        assert "(empty)" in md


# ---------------------------------------------------------------------------
# TestChainTypes
# ---------------------------------------------------------------------------


class TestChainTypes:
    def test_all_valid_types(self):
        engine = _tmp_engine()
        for ct in CapabilityChainType:
            chains = [
                {"work_id": f"w-{ct.value}", "chain_type": ct.value, "steps": [
                    {"order_index": 0, "capability_id": "cap-a"}
                ]},
            ]
            report = engine.create(chains=chains)
            assert report["chain_count"] == 1

    def test_invalid_type_rejected(self):
        engine = _tmp_engine()
        with pytest.raises(ValueError, match="Invalid chain_type"):
            engine.create(chains=[
                {"work_id": "w-1", "chain_type": "invalid_type", "steps": []}
            ])

    def test_type_counts_correct(self):
        engine = _tmp_engine()
        chains = [
            {"work_id": "w-1", "chain_type": "linear", "steps": [
                {"order_index": 0, "capability_id": "cap-a"}
            ]},
            {"work_id": "w-2", "chain_type": "linear", "steps": [
                {"order_index": 0, "capability_id": "cap-b"}
            ]},
            {"work_id": "w-3", "chain_type": "review_chain", "steps": [
                {"order_index": 0, "capability_id": "cap-c"}
            ]},
        ]
        report = engine.create(chains=chains)
        assert report["chain_type_counts"]["linear"] == 2
        assert report["chain_type_counts"]["review_chain"] == 1


# ---------------------------------------------------------------------------
# TestValidation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_missing_work_id_rejected(self):
        engine = _tmp_engine()
        with pytest.raises(ValueError, match="work_id is required"):
            engine.create(chains=[
                {"work_id": "", "chain_type": "linear", "steps": []}
            ])

    def test_whitespace_work_id_rejected(self):
        engine = _tmp_engine()
        with pytest.raises(ValueError, match="work_id is required"):
            engine.create(chains=[
                {"work_id": "   ", "chain_type": "linear", "steps": []}
            ])

    def test_missing_capability_id_rejected(self):
        engine = _tmp_engine()
        with pytest.raises(ValueError, match="capability_id is required"):
            engine.create(chains=[
                {"work_id": "w-1", "chain_type": "linear", "steps": [
                    {"order_index": 0, "capability_id": ""}
                ]}
            ])


# ---------------------------------------------------------------------------
# TestEvidenceGeneration
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_four_files_created(self):
        engine = _tmp_engine()
        report = engine.create(chains=_basic_chains())
        report_dir = Path(engine._report_dir) / report["report_id"]
        expected = {
            "capability_chain_request.json",
            "capability_chain_result.json",
            "capability_chain_summary.md",
            "pass_fail.json",
            "report.json",
        }
        assert expected == set(os.listdir(report_dir))

    def test_request_json_valid(self):
        engine = _tmp_engine()
        report = engine.create(chains=_basic_chains())
        report_dir = Path(engine._report_dir) / report["report_id"]
        data = json.loads((report_dir / "capability_chain_request.json").read_text())
        assert "chains" in data
        assert len(data["chains"]) == 2

    def test_result_json_valid(self):
        engine = _tmp_engine()
        report = engine.create(chains=_basic_chains())
        report_dir = Path(engine._report_dir) / report["report_id"]
        data = json.loads((report_dir / "capability_chain_result.json").read_text())
        assert data["chain_count"] == 2
        assert data["step_count"] == 3

    def test_summary_md_has_sections(self):
        engine = _tmp_engine()
        report = engine.create(chains=_basic_chains())
        report_dir = Path(engine._report_dir) / report["report_id"]
        md = (report_dir / "capability_chain_summary.md").read_text()
        assert "# Capability Chain Report" in md
        assert "## Chain Summary" in md
        assert "## Type Counts" in md
        assert "## Chains" in md

    def test_pass_fail_passed_when_no_empty(self):
        engine = _tmp_engine()
        report = engine.create(chains=_basic_chains())
        report_dir = Path(engine._report_dir) / report["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True
        assert pf["status"] == "passed"
        assert pf["empty_step_count"] == 0

    def test_pass_fail_failed_when_empty_chain(self):
        engine = _tmp_engine()
        chains = [
            {"work_id": "w-empty", "chain_type": "linear", "steps": []},
        ]
        report = engine.create(chains=chains)
        report_dir = Path(engine._report_dir) / report["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is False
        assert pf["status"] == "failed"
        assert pf["empty_step_count"] == 1


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self):
        engine = _tmp_engine()
        report = engine.create(chains=_basic_chains())
        loaded = engine.get_report(report["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == report["report_id"]
        assert loaded["chain_count"] == 2

    def test_round_trip_identical(self):
        engine = _tmp_engine()
        report = engine.create(chains=_basic_chains())
        loaded = engine.get_report(report["report_id"])
        assert loaded == report

    def test_list_reports_deterministic(self):
        engine = _tmp_engine()
        r1 = engine.create(chains=[
            {"work_id": "w-1", "chain_type": "linear", "steps": [
                {"order_index": 0, "capability_id": "cap-a"}
            ]},
        ])
        r2 = engine.create(chains=[
            {"work_id": "w-2", "chain_type": "linear", "steps": [
                {"order_index": 0, "capability_id": "cap-b"}
            ]},
        ])
        reports = engine.list_reports()
        assert len(reports) >= 2
        ids = [r["report_id"] for r in reports]
        assert r1["report_id"] in ids
        assert r2["report_id"] in ids

    def test_nonexistent_report_returns_none(self):
        engine = _tmp_engine()
        assert engine.get_report("nonexistent-id") is None


# ---------------------------------------------------------------------------
# TestExport
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_has_markdown_sections(self):
        engine = _tmp_engine()
        report = engine.create(chains=_basic_chains())
        md = engine.export_report(report["report_id"])
        assert "# Capability Chain Report" in md
        assert "## Chain Summary" in md
        assert "## Type Counts" in md
        assert "## Chains" in md

    def test_export_includes_step_descriptions(self):
        engine = _tmp_engine()
        report = engine.create(chains=_basic_chains())
        md = engine.export_report(report["report_id"])
        assert "create levels" in md
        assert "create grids" in md

    def test_export_nonexistent_raises(self):
        engine = _tmp_engine()
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id")

    def test_export_empty_chain_shows_empty_marker(self):
        engine = _tmp_engine()
        chains = [
            {"work_id": "w-empty", "chain_type": "linear", "steps": []},
        ]
        report = engine.create(chains=chains)
        md = engine.export_report(report["report_id"])
        assert "(empty)" in md

    def test_export_shows_work_id_brackets(self):
        engine = _tmp_engine()
        report = engine.create(chains=_basic_chains())
        md = engine.export_report(report["report_id"])
        assert "[w-alpha]" in md
        assert "[w-bravo]" in md


# ---------------------------------------------------------------------------
# TestSafety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(self):
        engine = _tmp_engine()
        with pytest.raises(ValueError):
            engine.get_report("../../etc")

    def test_empty_report_id_rejected(self):
        engine = _tmp_engine()
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("")

    def test_whitespace_report_id_rejected(self):
        engine = _tmp_engine()
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("   ")

    def test_slash_in_id_rejected(self):
        engine = _tmp_engine()
        with pytest.raises(ValueError):
            engine.get_report("foo/bar")

    def test_backslash_in_id_rejected(self):
        engine = _tmp_engine()
        with pytest.raises(ValueError):
            engine.get_report("foo\\bar")


# ---------------------------------------------------------------------------
# TestCommandRegistryIntegration
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_capability_chain_commands_registered(self):
        from axiom_core.runner.command_registry import command_names

        names = command_names()
        assert "capability-chain-create" in names
        assert "capability-chain-show" in names
        assert "capability-chain-export" in names


# ---------------------------------------------------------------------------
# TestSelectionMapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_capability_chain_mapping_exists(self):
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/capability_chain.py"]
            == "tests/test_capability_chain.py"
        )
