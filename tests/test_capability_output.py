"""Tests for the Capability Output Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.capability_output import (
    CapabilityOutput,
    CapabilityOutputEngine,
    CapabilityOutputReport,
    CapabilityOutputValidationResult,
)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_output_defaults(self):
        out = CapabilityOutput(capability_id="cap1", name="result")
        assert out.output_id
        assert out.created_at
        assert out.status == "valid"
        assert out.required is True

    def test_validation_result_defaults(self):
        vr = CapabilityOutputValidationResult(output_id="o1")
        assert vr.result_id
        assert vr.valid is True
        assert vr.errors == []

    def test_report_defaults(self):
        report = CapabilityOutputReport(capability_id="cap1")
        assert report.report_id
        assert report.output_count == 0


# ---------------------------------------------------------------------------
# Engine - creation
# ---------------------------------------------------------------------------


class TestCreate:
    def test_empty_outputs(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        report = engine.create(capability_id="cap1", outputs=[])
        assert report["output_count"] == 0
        assert report["valid_count"] == 0

    def test_valid_text_output(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        outputs = [{"name": "greeting", "output_type": "text", "value": "hello"}]
        report = engine.create(capability_id="cap1", outputs=outputs)
        assert report["output_count"] == 1
        assert report["valid_count"] == 1
        assert report["invalid_count"] == 0

    def test_multiple_outputs(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        outputs = [
            {"name": "text_out", "output_type": "text", "value": "hi"},
            {"name": "num_out", "output_type": "number", "value": 42},
            {"name": "bool_out", "output_type": "boolean", "value": True},
        ]
        report = engine.create(capability_id="cap1", outputs=outputs)
        assert report["output_count"] == 3
        assert report["valid_count"] == 3

    def test_json_output_type(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        outputs = [{"name": "config", "output_type": "json", "value": {"key": "val"}}]
        report = engine.create(capability_id="cap1", outputs=outputs)
        assert report["valid_count"] == 1


# ---------------------------------------------------------------------------
# Engine - output status handling
# ---------------------------------------------------------------------------


class TestOutputStatus:
    def test_required_missing_value(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        outputs = [{"name": "required_out", "required": True, "value": None}]
        report = engine.create(capability_id="cap1", outputs=outputs)
        assert report["missing_count"] == 1

    def test_optional_missing_value(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        outputs = [{"name": "opt_out", "required": False, "value": None}]
        report = engine.create(capability_id="cap1", outputs=outputs)
        assert report["missing_count"] == 0
        assert report["valid_count"] == 1

    def test_unsupported_type(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        outputs = [{"name": "weird", "output_type": "quantum", "value": "x"}]
        report = engine.create(capability_id="cap1", outputs=outputs)
        assert report["unsupported_count"] == 1

    def test_type_mismatch_boolean(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        outputs = [{"name": "flag", "output_type": "boolean", "value": "yes"}]
        report = engine.create(capability_id="cap1", outputs=outputs)
        assert report["invalid_count"] == 1

    def test_type_mismatch_number(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        outputs = [{"name": "count", "output_type": "number", "value": "five"}]
        report = engine.create(capability_id="cap1", outputs=outputs)
        assert report["invalid_count"] == 1

    def test_type_mismatch_list(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        outputs = [{"name": "items", "output_type": "list", "value": "not-a-list"}]
        report = engine.create(capability_id="cap1", outputs=outputs)
        assert report["invalid_count"] == 1

    def test_type_mismatch_dictionary(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        outputs = [{"name": "data", "output_type": "dictionary", "value": [1, 2]}]
        report = engine.create(capability_id="cap1", outputs=outputs)
        assert report["invalid_count"] == 1

    def test_boolean_not_accepted_as_number(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        outputs = [{"name": "count", "output_type": "number", "value": True}]
        report = engine.create(capability_id="cap1", outputs=outputs)
        assert report["invalid_count"] == 1


# ---------------------------------------------------------------------------
# Engine - unknown capability ID handling
# ---------------------------------------------------------------------------


class TestUnknownCapabilityId:
    def test_unknown_capability_id_rejected(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        outputs = [{"name": "out", "output_type": "text", "value": "hi"}]
        report = engine.create(
            capability_id="unknown-cap",
            outputs=outputs,
            known_capability_ids=["cap1", "cap2"],
        )
        assert report["invalid_count"] == 1

    def test_known_capability_id_passes(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        outputs = [{"name": "out", "output_type": "text", "value": "hi"}]
        report = engine.create(
            capability_id="cap1",
            outputs=outputs,
            known_capability_ids=["cap1", "cap2"],
        )
        assert report["valid_count"] == 1
        assert report["invalid_count"] == 0

    def test_empty_known_ids_list_still_validates(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        outputs = [{"name": "out", "output_type": "text", "value": "hi"}]
        report = engine.create(
            capability_id="cap1",
            outputs=outputs,
            known_capability_ids=[],
        )
        assert report["invalid_count"] == 1


# ---------------------------------------------------------------------------
# Engine - deterministic ordering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_outputs_sorted_by_name(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        outputs = [
            {"name": "zebra", "output_type": "text", "value": "z"},
            {"name": "alpha", "output_type": "text", "value": "a"},
            {"name": "middle", "output_type": "text", "value": "m"},
        ]
        report = engine.create(capability_id="cap1", outputs=outputs)
        names = [o["name"] for o in report["outputs"]]
        assert names == ["alpha", "middle", "zebra"]


# ---------------------------------------------------------------------------
# Engine - evidence generation
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_evidence_files_created(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        report = engine.create(
            capability_id="cap1",
            outputs=[{"name": "out", "output_type": "text", "value": "hi"}],
        )
        report_id = report["report_id"]
        evidence_dir = tmp_path / "capability_outputs" / report_id

        assert (evidence_dir / "capability_output_request.json").exists()
        assert (evidence_dir / "capability_output_result.json").exists()
        assert (evidence_dir / "capability_output_summary.md").exists()
        assert (evidence_dir / "pass_fail.json").exists()

    def test_pass_fail_true_when_all_valid(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        report = engine.create(
            capability_id="cap1",
            outputs=[{"name": "out", "output_type": "text", "value": "hi"}],
        )
        report_id = report["report_id"]

        pf = json.loads(
            (tmp_path / "capability_outputs" / report_id / "pass_fail.json").read_text()
        )
        assert pf["passed"] is True

    def test_pass_fail_false_when_invalid(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        report = engine.create(
            capability_id="cap1",
            outputs=[{"name": "flag", "output_type": "boolean", "value": "wrong"}],
        )
        report_id = report["report_id"]

        pf = json.loads(
            (tmp_path / "capability_outputs" / report_id / "pass_fail.json").read_text()
        )
        assert pf["passed"] is False

    def test_pass_fail_false_when_missing(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        report = engine.create(
            capability_id="cap1",
            outputs=[{"name": "req", "required": True, "value": None}],
        )
        report_id = report["report_id"]

        pf = json.loads(
            (tmp_path / "capability_outputs" / report_id / "pass_fail.json").read_text()
        )
        assert pf["passed"] is False

    def test_pass_fail_false_when_unsupported(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        report = engine.create(
            capability_id="cap1",
            outputs=[{"name": "weird", "output_type": "quantum", "value": "x"}],
        )
        report_id = report["report_id"]

        pf = json.loads(
            (tmp_path / "capability_outputs" / report_id / "pass_fail.json").read_text()
        )
        assert pf["passed"] is False

    def test_summary_md_contains_header(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        report = engine.create(capability_id="cap1", outputs=[])
        report_id = report["report_id"]

        md = (
            tmp_path / "capability_outputs" / report_id / "capability_output_summary.md"
        ).read_text()
        assert "# Capability Output Report" in md


# ---------------------------------------------------------------------------
# Engine - persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report_returns_data(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        report = engine.create(capability_id="cap1", outputs=[])
        retrieved = engine.get_report(report["report_id"])
        assert retrieved is not None
        assert retrieved["report_id"] == report["report_id"]

    def test_get_report_not_found(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        result = engine.get_report("nonexistent-id")
        assert result is None

    def test_list_reports_order(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        engine.create(capability_id="cap1", outputs=[])
        engine.create(capability_id="cap2", outputs=[])
        reports = engine.list_reports()
        assert len(reports) >= 2
        timestamps = [r["created_at"] for r in reports]
        assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# Engine - safety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            engine.get_report("../../etc/passwd")

    def test_empty_id_rejected(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="empty"):
            engine.get_report("")

    def test_whitespace_id_rejected(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="empty"):
            engine.get_report("   ")

    def test_symlink_escape_rejected(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        with pytest.raises(ValueError, match="must not contain"):
            engine.get_report("foo/../../../etc/passwd")

    def test_nonexistent_report_returns_none(self, tmp_path):
        engine = CapabilityOutputEngine(artifacts_root=str(tmp_path))
        result = engine.get_report("valid-but-nonexistent-id")
        assert result is None


# ---------------------------------------------------------------------------
# Integration - CommandRegistry
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_commands_registered(self):
        from axiom_core.runner.command_registry import command_names

        names = set(command_names())
        assert "capability-output-create" in names
        assert "capability-outputs" in names
        assert "capability-output-show" in names
        assert "capability-output-export" in names


# ---------------------------------------------------------------------------
# Integration - test selection mapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_capability_output_mapped(self):
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/capability_output.py"]
            == "tests/test_capability_output.py"
        )
