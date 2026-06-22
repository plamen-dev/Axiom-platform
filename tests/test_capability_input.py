"""Tests for Capability Input Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.capability_input import (
    CapabilityInput,
    CapabilityInputEngine,
    CapabilityInputReport,
    CapabilityInputValidationResult,
)

# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestModels:
    def test_input_auto_id(self):
        inp = CapabilityInput(name="test-input")
        assert inp.input_id
        assert inp.name == "test-input"
        assert inp.created_at

    def test_validation_result_auto_id(self):
        vr = CapabilityInputValidationResult(input_id="i1")
        assert vr.result_id
        assert vr.input_id == "i1"

    def test_report_auto_id(self):
        rpt = CapabilityInputReport(capability_id="c1")
        assert rpt.report_id
        assert rpt.capability_id == "c1"

    def test_input_to_dict(self):
        inp = CapabilityInput(
            name="config-path",
            capability_id="cap1",
            input_type="file_path",
            value="/path/to/config",
            required=True,
            status="valid",
        )
        d = inp.to_dict()
        assert d["name"] == "config-path"
        assert d["value"] == "/path/to/config"
        assert d["required"] is True

    def test_validation_result_to_dict(self):
        vr = CapabilityInputValidationResult(input_id="i1", valid=False, errors=["Missing value"])
        d = vr.to_dict()
        assert d["valid"] is False
        assert "Missing value" in d["errors"]

    def test_report_to_dict(self):
        rpt = CapabilityInputReport(
            capability_id="cap1", input_count=3, valid_count=2, invalid_count=1
        )
        d = rpt.to_dict()
        assert d["input_count"] == 3
        assert d["valid_count"] == 2


# ---------------------------------------------------------------------------
# Engine - basic creation
# ---------------------------------------------------------------------------


class TestCreate:
    def test_empty_inputs(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        report = engine.create(capability_id="cap1", inputs=[])
        assert report["input_count"] == 0
        assert report["valid_count"] == 0

    def test_single_valid_input(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        inputs = [{"name": "config", "input_type": "text", "value": "hello"}]
        report = engine.create(capability_id="cap1", inputs=inputs)
        assert report["input_count"] == 1
        assert report["valid_count"] == 1

    def test_all_input_types(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        inputs = [
            {"name": f"inp-{t}", "input_type": t, "value": "x"}
            for t in ["text", "json", "file_path", "configuration"]
        ]
        inputs.extend(
            [
                {"name": "inp-list", "input_type": "list", "value": [1, 2]},
                {"name": "inp-dict", "input_type": "dictionary", "value": {"k": "v"}},
                {"name": "inp-bool", "input_type": "boolean", "value": True},
                {"name": "inp-num", "input_type": "number", "value": 42},
            ]
        )
        report = engine.create(capability_id="cap1", inputs=inputs)
        assert report["valid_count"] == 8


# ---------------------------------------------------------------------------
# Engine - input status handling
# ---------------------------------------------------------------------------


class TestInputStatus:
    def test_missing_required_input(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        inputs = [{"name": "req-input", "required": True, "value": None}]
        report = engine.create(capability_id="cap1", inputs=inputs)
        assert report["missing_count"] == 1

    def test_optional_input_without_value(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        inputs = [{"name": "opt-input", "required": False, "value": None}]
        report = engine.create(capability_id="cap1", inputs=inputs)
        assert report["valid_count"] == 1
        assert report["missing_count"] == 0

    def test_unsupported_input_type(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        inputs = [{"name": "weird", "input_type": "quantum", "value": "x"}]
        report = engine.create(capability_id="cap1", inputs=inputs)
        assert report["unsupported_count"] == 1

    def test_type_mismatch_boolean(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        inputs = [{"name": "flag", "input_type": "boolean", "value": "yes"}]
        report = engine.create(capability_id="cap1", inputs=inputs)
        assert report["invalid_count"] == 1

    def test_type_mismatch_number(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        inputs = [{"name": "count", "input_type": "number", "value": "five"}]
        report = engine.create(capability_id="cap1", inputs=inputs)
        assert report["invalid_count"] == 1

    def test_type_mismatch_list(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        inputs = [{"name": "items", "input_type": "list", "value": "not-a-list"}]
        report = engine.create(capability_id="cap1", inputs=inputs)
        assert report["invalid_count"] == 1

    def test_type_mismatch_dictionary(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        inputs = [{"name": "data", "input_type": "dictionary", "value": [1, 2]}]
        report = engine.create(capability_id="cap1", inputs=inputs)
        assert report["invalid_count"] == 1

    def test_boolean_not_accepted_as_number(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        inputs = [{"name": "count", "input_type": "number", "value": True}]
        report = engine.create(capability_id="cap1", inputs=inputs)
        assert report["invalid_count"] == 1


# ---------------------------------------------------------------------------
# Engine - unknown capability ID handling
# ---------------------------------------------------------------------------


class TestUnknownCapabilityId:
    def test_unknown_capability_marks_invalid(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        inputs = [{"name": "inp1", "value": "hello"}]
        report = engine.create(
            capability_id="unknown-cap",
            inputs=inputs,
            known_capability_ids=["cap1", "cap2"],
        )
        assert report["invalid_count"] == 1

    def test_known_capability_stays_valid(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        inputs = [{"name": "inp1", "value": "hello"}]
        report = engine.create(
            capability_id="cap1",
            inputs=inputs,
            known_capability_ids=["cap1", "cap2"],
        )
        assert report["valid_count"] == 1

    def test_no_known_ids_skips_validation(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        inputs = [{"name": "inp1", "value": "hello"}]
        report = engine.create(
            capability_id="anything",
            inputs=inputs,
            known_capability_ids=None,
        )
        assert report["valid_count"] == 1


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_inputs_sorted_by_name(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        inputs = [
            {"name": "zeta", "value": "z"},
            {"name": "alpha", "value": "a"},
            {"name": "middle", "value": "m"},
        ]
        report = engine.create(capability_id="cap1", inputs=inputs)
        names = [i["name"] for i in report["inputs"]]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# Evidence generation
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_evidence_files_created(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        report = engine.create(
            capability_id="cap1",
            inputs=[{"name": "inp1", "value": "v1"}],
        )
        report_id = report["report_id"]

        evidence_dir = tmp_path / "capability_inputs" / report_id
        assert (evidence_dir / "capability_input_request.json").exists()
        assert (evidence_dir / "capability_input_result.json").exists()
        assert (evidence_dir / "capability_input_summary.md").exists()
        assert (evidence_dir / "pass_fail.json").exists()

    def test_pass_fail_true_when_all_valid(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        report = engine.create(
            capability_id="cap1",
            inputs=[{"name": "inp1", "value": "hello"}],
        )
        report_id = report["report_id"]

        pf = json.loads((tmp_path / "capability_inputs" / report_id / "pass_fail.json").read_text())
        assert pf["passed"] is True

    def test_pass_fail_false_when_invalid(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        report = engine.create(
            capability_id="cap1",
            inputs=[{"name": "flag", "input_type": "boolean", "value": "wrong"}],
        )
        report_id = report["report_id"]

        pf = json.loads((tmp_path / "capability_inputs" / report_id / "pass_fail.json").read_text())
        assert pf["passed"] is False

    def test_pass_fail_false_when_missing(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        report = engine.create(
            capability_id="cap1",
            inputs=[{"name": "req", "required": True, "value": None}],
        )
        report_id = report["report_id"]

        pf = json.loads((tmp_path / "capability_inputs" / report_id / "pass_fail.json").read_text())
        assert pf["passed"] is False

    def test_pass_fail_false_when_unsupported(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        report = engine.create(
            capability_id="cap1",
            inputs=[{"name": "weird", "input_type": "quantum", "value": "x"}],
        )
        report_id = report["report_id"]

        pf = json.loads((tmp_path / "capability_inputs" / report_id / "pass_fail.json").read_text())
        assert pf["passed"] is False

    def test_summary_md_contains_header(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        report = engine.create(capability_id="cap1", inputs=[])
        report_id = report["report_id"]

        md = (
            tmp_path / "capability_inputs" / report_id / "capability_input_summary.md"
        ).read_text()
        assert "# Capability Input Report" in md


# ---------------------------------------------------------------------------
# Persistence and retrieval
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        report = engine.create(capability_id="cap1", inputs=[])
        report_id = report["report_id"]

        loaded = engine.get_report(report_id)
        assert loaded is not None
        assert loaded["report_id"] == report_id

    def test_list_reports(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        engine.create(capability_id="cap1", inputs=[])
        engine.create(capability_id="cap2", inputs=[{"name": "x", "value": "y"}])

        reports = engine.list_reports()
        assert len(reports) == 2

    def test_export_report(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        report = engine.create(capability_id="cap1", inputs=[])
        report_id = report["report_id"]

        md = engine.export_report(report_id)
        assert "# Capability Input Report" in md


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            engine.get_report("../etc/passwd")

    def test_empty_id_rejected(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("")

    def test_whitespace_id_rejected(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("   ")

    def test_symlink_escape_rejected(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        input_dir = tmp_path / "capability_inputs"
        input_dir.mkdir(exist_ok=True)
        link_name = input_dir / "evil-link"
        link_name.symlink_to("/tmp")
        with pytest.raises(ValueError, match="escapes artifacts root"):
            engine._safe_input_path("evil-link")

    def test_nonexistent_report_returns_none(self, tmp_path):
        engine = CapabilityInputEngine(artifacts_root=str(tmp_path))
        assert engine.get_report("nonexistent-id") is None


# ---------------------------------------------------------------------------
# CommandRegistry integration
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_commands_registered(self):
        from axiom_core.runner.command_registry import command_names

        names = set(command_names())
        assert "capability-input-create" in names
        assert "capability-inputs" in names
        assert "capability-input-show" in names
        assert "capability-input-export" in names


# ---------------------------------------------------------------------------
# Test selection mapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_capability_input_mapped(self):
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/capability_input.py"] == "tests/test_capability_input.py"
        )
