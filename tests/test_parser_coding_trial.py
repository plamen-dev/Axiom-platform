"""Tests for ParserCodingTrialRunner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.parser_coding_trial import ParserCodingTrialRunner


class TestRunTrial:
    def test_basic_trial(self, tmp_path: Path) -> None:
        runner = ParserCodingTrialRunner(artifacts_root=str(tmp_path))
        trial = runner.run_trial(
            code_file="src/axiom_core/text_utils.py",
            test_file="tests/test_text_utils.py",
            function_name="parse_key_value_lines",
        )
        assert trial["trial_id"]
        assert trial["code_file"] == "src/axiom_core/text_utils.py"
        assert trial["test_file"] == "tests/test_text_utils.py"
        assert trial["function_name"] == "parse_key_value_lines"
        assert isinstance(trial["validation_results"], list)
        assert len(trial["validation_results"]) == 2
        assert isinstance(trial["all_passed"], bool)
        assert trial["created_at"]

    def test_evidence_files_created(self, tmp_path: Path) -> None:
        runner = ParserCodingTrialRunner(artifacts_root=str(tmp_path))
        trial = runner.run_trial()
        trials_dir = tmp_path / "parser_coding_trials" / trial["trial_id"]
        assert (trials_dir / "parser_coding_trial_request.json").exists()
        assert (trials_dir / "parser_coding_trial_result.json").exists()
        assert (trials_dir / "parser_coding_trial_summary.md").exists()
        assert (trials_dir / "pass_fail.json").exists()

    def test_evidence_valid_json(self, tmp_path: Path) -> None:
        runner = ParserCodingTrialRunner(artifacts_root=str(tmp_path))
        trial = runner.run_trial()
        trials_dir = tmp_path / "parser_coding_trials" / trial["trial_id"]
        for fname in [
            "parser_coding_trial_request.json",
            "parser_coding_trial_result.json",
            "pass_fail.json",
        ]:
            data = json.loads((trials_dir / fname).read_text(encoding="utf-8"))
            assert isinstance(data, dict)

    def test_pass_fail_structure(self, tmp_path: Path) -> None:
        runner = ParserCodingTrialRunner(artifacts_root=str(tmp_path))
        trial = runner.run_trial()
        trials_dir = tmp_path / "parser_coding_trials" / trial["trial_id"]
        pf = json.loads(
            (trials_dir / "pass_fail.json").read_text(encoding="utf-8"),
        )
        assert "passed" in pf
        assert "trial_id" in pf
        assert "escalation_needed" in pf
        assert "repair_needed" in pf

    def test_summary_markdown(self, tmp_path: Path) -> None:
        runner = ParserCodingTrialRunner(artifacts_root=str(tmp_path))
        trial = runner.run_trial(function_name="parse_key_value_lines")
        trials_dir = tmp_path / "parser_coding_trials" / trial["trial_id"]
        md = (trials_dir / "parser_coding_trial_summary.md").read_text(
            encoding="utf-8",
        )
        assert "# Parser Coding Trial: parse_key_value_lines" in md
        assert "## Validation Results" in md
        assert "## Escalation / Repair" in md

    def test_custom_description(self, tmp_path: Path) -> None:
        runner = ParserCodingTrialRunner(artifacts_root=str(tmp_path))
        trial = runner.run_trial(description="Custom parser trial")
        assert trial["description"] == "Custom parser trial"

    def test_validation_results_structure(self, tmp_path: Path) -> None:
        runner = ParserCodingTrialRunner(artifacts_root=str(tmp_path))
        trial = runner.run_trial()
        for vr in trial["validation_results"]:
            assert "label" in vr
            assert "command" in vr
            assert "exit_code" in vr

    def test_no_escalation_on_success(self, tmp_path: Path) -> None:
        runner = ParserCodingTrialRunner(artifacts_root=str(tmp_path))
        trial = runner.run_trial()
        if trial["all_passed"]:
            assert trial["escalation_needed"] is False
            assert trial["repair_needed"] is False


class TestSafeTrialPath:
    def test_normal_path(self, tmp_path: Path) -> None:
        runner = ParserCodingTrialRunner(artifacts_root=str(tmp_path))
        path = runner._safe_trial_path("valid-id")
        assert path.is_relative_to(tmp_path)

    def test_symlink_blocked(self, tmp_path: Path) -> None:
        runner = ParserCodingTrialRunner(artifacts_root=str(tmp_path))
        trials_dir = tmp_path / "parser_coding_trials"
        outside = tmp_path / "outside"
        outside.mkdir()
        symlink = trials_dir / "evil-link"
        symlink.symlink_to(outside)
        with pytest.raises(ValueError, match="escapes artifacts root"):
            runner._safe_trial_path("evil-link")


class TestGenerateSummary:
    def test_passed_summary(self) -> None:
        trial = {
            "trial_id": "test-id",
            "code_file": "src/test.py",
            "test_file": "tests/test.py",
            "function_name": "parse_key_value_lines",
            "description": "Parser trial",
            "all_passed": True,
            "escalation_needed": False,
            "created_at": "2026-01-01",
            "validation_results": [
                {"label": "pytest", "exit_code": 0, "command": "pytest", "stdout": "ok"},
            ],
        }
        md = ParserCodingTrialRunner._generate_summary(trial)
        assert "PASSED" in md
        assert "No escalation" in md

    def test_failed_summary(self) -> None:
        trial = {
            "trial_id": "test-id",
            "code_file": "src/test.py",
            "test_file": "tests/test.py",
            "function_name": "parse_key_value_lines",
            "description": "",
            "all_passed": False,
            "escalation_needed": True,
            "created_at": "2026-01-01",
            "validation_results": [
                {"label": "pytest", "exit_code": 1, "command": "pytest", "stdout": "fail"},
            ],
        }
        md = ParserCodingTrialRunner._generate_summary(trial)
        assert "FAILED" in md
        assert "Escalation object needed: YES" in md


class TestCommandRegistryIntegration:
    def test_trial_command_registered(self) -> None:
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("parser-coding-trial")
        assert cmd is not None
        assert cmd.classification.value == "read_only"
        assert cmd.safety_level.value == "safe"

    def test_trial_evidence_outputs(self) -> None:
        from axiom_core.runner.command_registry import get_command

        cmd = get_command("parser-coding-trial")
        assert cmd is not None
        locations = {eo.location for eo in cmd.evidence_outputs}
        assert "parser_coding_trial_request.json" in locations
        assert "parser_coding_trial_result.json" in locations
        assert "parser_coding_trial_summary.md" in locations
        assert "pass_fail.json" in locations


class TestSelectionMapping:
    def test_mapping_exists(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        key = "src/axiom_core/parser_coding_trial.py"
        assert key in _FILE_TO_TEST
        assert _FILE_TO_TEST[key] == "tests/test_parser_coding_trial.py"
