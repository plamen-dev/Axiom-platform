"""Tests for the Axiom Validation Automation Loop v0.

Covers (per spec):
- evidence scanner finds the latest run across mocked user roots
- pass/fail classifier detects missing linked_preview
- pass/fail classifier detects target_ids_match false
- admin/non-admin context is recorded
- result_summary (and the full artifact bundle) is generated
- no arbitrary shell execution (only fixed allowlisted argv lists)
- bounded retry budget is configurable (default 5) and recorded
"""

from __future__ import annotations

import json
from pathlib import Path

from axiom_cli.main import cli
from axiom_core import validation_loop as vl
from click.testing import CliRunner

# ---------------------------------------------------------------------------
# Helpers — build mock evidence run folders
# ---------------------------------------------------------------------------


def _write_apply_run(
    evidence_dir: Path,
    run_name: str,
    *,
    initiated_from: str = "preview_approval",
    targeted_by_ids: bool = True,
    target_ids_match: bool = True,
    model_modified: bool = True,
    element_statuses: list[str] | None = None,
    include_linked_preview: bool = True,
    include_linked_metadata: bool = True,
) -> Path:
    """Create a mock SetParameterValue apply-run evidence folder."""
    if element_statuses is None:
        element_statuses = ["success"]
    run = evidence_dir / run_name
    run.mkdir(parents=True, exist_ok=True)

    (run / "result_summary.md").write_text("# SetParameterValue Result", encoding="utf-8")
    (run / "request.json").write_text(
        json.dumps(
            {
                "raw_prompt": "Apply Set Comments to Axiom test 001 for 1 Walls",
                "mode": "apply",
                "initiated_from": initiated_from,
                "targeted_by_ids": targeted_by_ids,
            }
        ),
        encoding="utf-8",
    )
    (run / "changes.json").write_text(
        json.dumps(
            {
                "mode": "apply",
                "initiated_from": initiated_from,
                "targeted_by_ids": targeted_by_ids,
                "model_modified": model_modified,
                "elements": [
                    {"element_id": 1000 + i, "status": s}
                    for i, s in enumerate(element_statuses)
                ],
            }
        ),
        encoding="utf-8",
    )
    if include_linked_preview:
        (run / "linked_preview.json").write_text(json.dumps({"mode": "preview"}), encoding="utf-8")
    if include_linked_metadata:
        (run / "linked_preview_metadata.json").write_text(
            json.dumps(
                {
                    "initiated_from": initiated_from,
                    "target_ids_match": target_ids_match,
                    "element_ids_previewed": [1000],
                    "element_ids_applied": [1000],
                }
            ),
            encoding="utf-8",
        )
    return run


# ---------------------------------------------------------------------------
# Evidence scanner
# ---------------------------------------------------------------------------


class TestEvidenceScanner:
    def test_finds_latest_run_across_mocked_user_roots(self, tmp_path):
        """Scanner searches multiple user profiles and picks the latest apply run."""
        # Two mocked user profiles, each with its own Axiom evidence dir.
        root_a = tmp_path / "Users" / "IMSAdmin" / "AppData" / "Local" / "Axiom" / "parameter_edit_runs"
        root_b = tmp_path / "Users" / "Plamen" / "AppData" / "Local" / "Axiom" / "parameter_edit_runs"
        root_a.mkdir(parents=True)
        root_b.mkdir(parents=True)

        old = _write_apply_run(root_a, "spv_20260101_000001")
        new = _write_apply_run(root_b, "spv_20260102_000002")
        # Force mtime ordering: old < new.
        import os
        os.utime(old, (1_700_000_000, 1_700_000_000))
        os.utime(new, (1_700_001_000, 1_700_001_000))

        scan = vl.scan_evidence([str(root_a), str(root_b)])
        assert len(scan.runs) == 2
        assert scan.latest_apply_run is not None
        assert scan.latest_apply_run.name == "spv_20260102_000002"

    def test_apply_run_requires_changes_json(self, tmp_path):
        """A preview-only run (no changes.json) is not treated as an apply run."""
        root = tmp_path / "Axiom" / "parameter_edit_runs"
        root.mkdir(parents=True)
        preview_only = root / "spv_preview"
        preview_only.mkdir()
        (preview_only / "preview.json").write_text("{}", encoding="utf-8")

        scan = vl.scan_evidence([str(root)])
        assert scan.latest_run is not None
        assert scan.latest_apply_run is None

    def test_missing_dirs_are_skipped(self, tmp_path):
        scan = vl.scan_evidence([str(tmp_path / "does_not_exist")])
        assert scan.runs == []
        assert scan.latest_apply_run is None


# ---------------------------------------------------------------------------
# Bounded retry budget
# ---------------------------------------------------------------------------


class TestRetryBudget:
    def test_default_max_attempts_is_five(self):
        assert vl.DEFAULT_MAX_ATTEMPTS == 5

    def test_retry_exhausts_budget_when_no_evidence(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        calls = []
        scan, attempts = vl.scan_evidence_with_retry(
            [str(empty)], max_attempts=4, wait_seconds=0.01,
            sleep_fn=lambda s: calls.append(s),
        )
        assert scan.latest_apply_run is None
        assert attempts == 4
        # Waited between attempts (n-1 times).
        assert len(calls) == 3

    def test_retry_overridable_to_larger_number(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        _, attempts = vl.scan_evidence_with_retry(
            [str(empty)], max_attempts=20, wait_seconds=0, sleep_fn=lambda s: None
        )
        assert attempts == 20

    def test_retry_stops_early_when_evidence_appears(self, tmp_path):
        root = tmp_path / "Axiom" / "parameter_edit_runs"
        root.mkdir(parents=True)
        _write_apply_run(root, "spv_1")
        _, attempts = vl.scan_evidence_with_retry(
            [str(root)], max_attempts=10, wait_seconds=0, sleep_fn=lambda s: None
        )
        assert attempts == 1


# ---------------------------------------------------------------------------
# Condition evaluation + classifier
# ---------------------------------------------------------------------------


class TestConditionsAndClassifier:
    def test_all_conditions_pass_for_good_evidence(self, tmp_path):
        root = tmp_path / "Axiom" / "parameter_edit_runs"
        root.mkdir(parents=True)
        run = _write_apply_run(root, "spv_good")
        results = vl.evaluate_wall_comments_conditions(str(run))
        assert all(c.passed for c in results), [c.name for c in results if not c.passed]

    def test_classifier_detects_missing_linked_preview(self, tmp_path):
        root = tmp_path / "Axiom" / "parameter_edit_runs"
        root.mkdir(parents=True)
        run = _write_apply_run(root, "spv_no_linked", include_linked_preview=False)
        results = vl.evaluate_wall_comments_conditions(str(run))

        failed = [c.name for c in results if not c.passed]
        assert "linked_preview_json_exists" in failed

        classification = vl.classify_run(
            is_admin=False,
            tests_ran=False,
            tests_passed=None,
            deploy_attempted=False,
            deploy_status="skipped",
            evidence_found=True,
            manual_step_pending=False,
            condition_results=results,
        )
        assert classification.classification == vl.CLASS_EVIDENCE_MISSING
        assert "linked_preview_json_exists" in classification.failed_conditions

    def test_classifier_detects_target_ids_match_false(self, tmp_path):
        root = tmp_path / "Axiom" / "parameter_edit_runs"
        root.mkdir(parents=True)
        run = _write_apply_run(root, "spv_mismatch", target_ids_match=False)
        results = vl.evaluate_wall_comments_conditions(str(run))

        failed = [c.name for c in results if not c.passed]
        assert "target_ids_match_true" in failed
        # All required files are present, so this is a mismatch, not missing.
        assert not [c.name for c in results if c.kind == "file" and not c.passed]

        classification = vl.classify_run(
            is_admin=False,
            tests_ran=False,
            tests_passed=None,
            deploy_attempted=False,
            deploy_status="skipped",
            evidence_found=True,
            manual_step_pending=False,
            condition_results=results,
        )
        assert classification.classification == vl.CLASS_EVIDENCE_MISMATCH
        assert "target_ids_match_true" in classification.failed_conditions

    def test_classifier_detects_failed_elements(self, tmp_path):
        root = tmp_path / "Axiom" / "parameter_edit_runs"
        root.mkdir(parents=True)
        run = _write_apply_run(root, "spv_failed", element_statuses=["success", "failed"])
        results = vl.evaluate_wall_comments_conditions(str(run))
        classification = vl.classify_run(
            is_admin=False, tests_ran=False, tests_passed=None,
            deploy_attempted=False, deploy_status="skipped",
            evidence_found=True, manual_step_pending=False,
            condition_results=results,
        )
        assert classification.classification == vl.CLASS_EVIDENCE_MISMATCH
        assert "no_failed_elements" in classification.failed_conditions

    def test_classifier_tests_failed_takes_precedence(self):
        classification = vl.classify_run(
            is_admin=False, tests_ran=True, tests_passed=False,
            deploy_attempted=True, deploy_status="needs_admin",
            evidence_found=False, manual_step_pending=True,
            condition_results=[],
        )
        assert classification.classification == vl.CLASS_TESTS_FAILED

    def test_classifier_needs_admin(self):
        classification = vl.classify_run(
            is_admin=False, tests_ran=True, tests_passed=True,
            deploy_attempted=True, deploy_status="needs_admin",
            evidence_found=False, manual_step_pending=False,
            condition_results=[],
        )
        assert classification.classification == vl.CLASS_NEEDS_ADMIN

    def test_classifier_deploy_failed(self):
        classification = vl.classify_run(
            is_admin=True, tests_ran=True, tests_passed=True,
            deploy_attempted=True, deploy_status="failed",
            evidence_found=False, manual_step_pending=False,
            condition_results=[],
        )
        assert classification.classification == vl.CLASS_DEPLOY_FAILED

    def test_classifier_revit_manual_step_pending(self):
        classification = vl.classify_run(
            is_admin=True, tests_ran=True, tests_passed=True,
            deploy_attempted=False, deploy_status="skipped",
            evidence_found=False, manual_step_pending=True,
            condition_results=[],
        )
        assert classification.classification == vl.CLASS_REVIT_MANUAL_STEP_PENDING

    def test_classifier_evidence_missing_when_no_run(self):
        results = vl.evaluate_wall_comments_conditions(None)
        classification = vl.classify_run(
            is_admin=True, tests_ran=False, tests_passed=None,
            deploy_attempted=False, deploy_status="skipped",
            evidence_found=False, manual_step_pending=False,
            condition_results=results,
        )
        assert classification.classification == vl.CLASS_EVIDENCE_MISSING

    def test_deploy_output_classification(self):
        assert vl.classify_deploy_output(0, "ok") == "success"
        assert vl.classify_deploy_output(1, "Access to the path is denied") == "needs_admin"
        assert vl.classify_deploy_output(1, "build error CS1002") == "failed"


# ---------------------------------------------------------------------------
# Context recording
# ---------------------------------------------------------------------------


class TestContext:
    def test_admin_non_admin_context_recorded(self):
        ctx = vl.record_context()
        assert "is_admin" in ctx
        assert isinstance(ctx["is_admin"], bool)
        assert "user" in ctx
        assert "platform" in ctx
        assert "timestamp" in ctx


# ---------------------------------------------------------------------------
# Scenario resolution
# ---------------------------------------------------------------------------


class TestScenarios:
    def test_alias_resolves_to_full_scenario(self):
        sc = vl.resolve_scenario("set_parameter_preview_apply")
        assert sc is not None
        assert sc["id"] == "set_parameter_preview_apply_wall_comments"

    def test_full_id_resolves(self):
        sc = vl.resolve_scenario("set_parameter_preview_apply_wall_comments")
        assert sc is not None

    def test_unknown_scenario_returns_none(self):
        assert vl.resolve_scenario("not_a_scenario") is None

    def test_unsafe_scenario_name_rejected(self):
        assert vl.resolve_scenario("evil; rm -rf /") is None


# ---------------------------------------------------------------------------
# Full run + result_summary generation
# ---------------------------------------------------------------------------


class TestRunValidation:
    def test_scan_phase_pass_generates_full_bundle(self, tmp_path):
        ev = tmp_path / "Axiom" / "parameter_edit_runs"
        ev.mkdir(parents=True)
        _write_apply_run(ev, "spv_good")
        out = tmp_path / "validation_runs"

        result = vl.run_validation(
            scenario_name="set_parameter_preview_apply",
            phase="scan",
            evidence_dirs=[str(ev)],
            repo_root=str(tmp_path),
            output_dir=str(out),
            sleep_fn=lambda s: None,
        )
        assert result.classification == vl.CLASS_PASS
        assert not result.human_action_required

        run_dir = Path(result.artifact_dir)
        # result_summary.md is generated.
        assert (run_dir / "result_summary.md").exists()
        summary = (run_dir / "result_summary.md").read_text(encoding="utf-8")
        assert "Validation Run Summary" in summary
        assert "Classification" in summary
        # Core bundle artifacts present for the scan phase.
        for name in ("request.json", "environment.json", "git_state.json",
                     "evidence_scan.json", "pass_fail.json"):
            assert (run_dir / name).exists(), name
        # No human packet on pass.
        assert not (run_dir / "human_action_required.md").exists()

    def test_pre_phase_produces_manual_steps_and_pending(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        out = tmp_path / "validation_runs"

        result = vl.run_validation(
            scenario_name="set_parameter_preview_apply_wall_comments",
            phase="pre",
            do_tests=False,
            do_deploy=False,
            evidence_dirs=[str(empty)],
            repo_root=str(tmp_path),
            output_dir=str(out),
            sleep_fn=lambda s: None,
        )
        assert result.classification == vl.CLASS_REVIT_MANUAL_STEP_PENDING
        assert result.human_action_required

        run_dir = Path(result.artifact_dir)
        for name in ("manual_revit_steps.md", "human_action_required.md",
                     "test_results.json", "deploy_result.json",
                     "deployed_dll_timestamps.json"):
            assert (run_dir / name).exists(), name
        steps = (run_dir / "manual_revit_steps.md").read_text(encoding="utf-8")
        assert "Set Comments to Axiom test 001 for 1 Walls" in steps

    def test_max_attempts_recorded_and_overridable(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        out = tmp_path / "validation_runs"

        result = vl.run_validation(
            scenario_name="set_parameter_preview_apply",
            phase="scan",
            evidence_dirs=[str(empty)],
            repo_root=str(tmp_path),
            output_dir=str(out),
            max_attempts=7,
            attempt_wait_seconds=0,
            sleep_fn=lambda s: None,
        )
        pf = json.loads((Path(result.artifact_dir) / "pass_fail.json").read_text())
        assert pf["max_attempts"] == 7
        assert pf["attempts_made"] == 7
        assert result.classification == vl.CLASS_EVIDENCE_MISSING


# ---------------------------------------------------------------------------
# Security — no arbitrary shell execution
# ---------------------------------------------------------------------------


class TestNoArbitraryShell:
    def test_all_test_commands_are_fixed_argv_lists(self):
        """Every test command is a list of string tokens, never a shell string."""
        for name, argv in vl.TEST_COMMANDS.items():
            assert isinstance(argv, list), name
            assert all(isinstance(tok, str) for tok in argv), name
            # First token is a known executable, not a shell.
            assert argv[0] in ("poetry", "git"), name

    def test_deploy_command_is_fixed_argv(self):
        cmd = vl.deploy_command("2027")
        assert isinstance(cmd, list)
        assert cmd[0] == "powershell"
        # Points at the repo's deploy script, not arbitrary input.
        assert any("deploy-revit-2027.ps1" in tok for tok in cmd)

    def test_pull_branch_rejects_unsafe_names(self, tmp_path):
        # Initialize a git repo so the function has a valid cwd.
        res = vl.pull_branch(str(tmp_path), "main; rm -rf /")
        assert res["ok"] is False
        assert "unsafe branch name" in res["error"]

    def test_run_validation_has_no_shell_string_param(self):
        """run_validation accepts no free-form command/shell parameter."""
        import inspect
        params = set(inspect.signature(vl.run_validation).parameters)
        for forbidden in ("command", "cmd", "shell", "args"):
            assert forbidden not in params


# ---------------------------------------------------------------------------
# CLI exit codes — wrappers / CI rely on non-zero on failure
# ---------------------------------------------------------------------------


class TestCliExitCodes:
    def test_unknown_scenario_exits_nonzero(self, tmp_path):
        result = CliRunner().invoke(
            cli,
            ["validation-run", "--scenario", "not_a_scenario", "--phase", "scan",
             "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 1

    def test_pass_exits_zero(self, tmp_path):
        ev = tmp_path / "Axiom" / "parameter_edit_runs"
        ev.mkdir(parents=True)
        _write_apply_run(ev, "spv_good")
        result = CliRunner().invoke(
            cli,
            ["validation-run", "--scenario", "set_parameter_preview_apply",
             "--phase", "scan", "--evidence-root", str(ev),
             "--max-attempts", "1", "--attempt-wait-seconds", "0",
             "--output-dir", str(tmp_path / "runs")],
        )
        assert result.exit_code == 0

    def test_evidence_missing_exits_nonzero(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = CliRunner().invoke(
            cli,
            ["validation-run", "--scenario", "set_parameter_preview_apply",
             "--phase", "scan", "--evidence-root", str(empty),
             "--max-attempts", "1", "--attempt-wait-seconds", "0",
             "--output-dir", str(tmp_path / "runs")],
        )
        assert result.exit_code == 1

    def test_pre_phase_manual_pending_exits_zero(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = CliRunner().invoke(
            cli,
            ["validation-run", "--scenario", "set_parameter_preview_apply",
             "--phase", "pre", "--no-tests", "--evidence-root", str(empty),
             "--output-dir", str(tmp_path / "runs"), "--repo-root", str(tmp_path)],
        )
        # Pending live Revit step is the expected handoff, not a failure.
        assert result.exit_code == 0
