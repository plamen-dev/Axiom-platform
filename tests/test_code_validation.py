"""Tests for Code Validation Orchestrator v1 (PR #62)."""

from __future__ import annotations

import json

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_artifacts(tmp_path, monkeypatch):
    """Set up artifact directories and env vars."""
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("AXIOM_ARTIFACTS_ROOT", str(artifacts))
    monkeypatch.setenv("AXIOM_WORKSPACE_ROOT", str(tmp_path))
    return artifacts


@pytest.fixture()
def successful_patch_run(tmp_artifacts):
    """Create a successful patch run result in artifacts."""
    run_id = "patch-run-001"
    run_dir = tmp_artifacts / "patch_runs" / run_id
    run_dir.mkdir(parents=True)

    result = {
        "run_id": run_id,
        "proposal_id": "prop-001",
        "plan_id": "plan-001",
        "simulate": False,
        "status": "completed",
        "steps": [
            {
                "step_id": "step-1",
                "file_path": "tests/test_example.py",
                "edit_type": "add",
                "description": "Add test file",
                "status": "applied",
            },
            {
                "step_id": "step-2",
                "file_path": "src/axiom_core/example.py",
                "edit_type": "add",
                "description": "Add source file",
                "status": "applied",
            },
        ],
        "result": {"success": True, "steps_applied": 2, "steps_failed": 0},
        "started_at": "2026-05-06T00:00:00+00:00",
        "completed_at": "2026-05-06T00:00:01+00:00",
    }
    (run_dir / "patch_result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8",
    )
    return run_id


@pytest.fixture()
def simulated_patch_run(tmp_artifacts):
    """Create a simulated (but successful) patch run."""
    run_id = "patch-run-sim"
    run_dir = tmp_artifacts / "patch_runs" / run_id
    run_dir.mkdir(parents=True)

    result = {
        "run_id": run_id,
        "proposal_id": "prop-sim",
        "plan_id": "plan-sim",
        "simulate": True,
        "status": "simulated",
        "steps": [
            {
                "step_id": "step-1",
                "file_path": "src/axiom_core/new_module.py",
                "edit_type": "add",
                "description": "Add module",
                "status": "simulated",
            },
        ],
        "result": {"success": True, "steps_applied": 0, "steps_simulated": 1},
        "started_at": "2026-05-06T00:00:00+00:00",
        "completed_at": "2026-05-06T00:00:01+00:00",
    }
    (run_dir / "patch_result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8",
    )
    return run_id


@pytest.fixture()
def failed_patch_run(tmp_artifacts):
    """Create a failed patch run."""
    run_id = "patch-run-fail"
    run_dir = tmp_artifacts / "patch_runs" / run_id
    run_dir.mkdir(parents=True)

    result = {
        "run_id": run_id,
        "proposal_id": "prop-fail",
        "status": "failed",
        "steps": [],
        "result": {"success": False, "steps_failed": 1},
    }
    (run_dir / "patch_result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8",
    )
    return run_id


@pytest.fixture()
def orchestrator(tmp_artifacts, tmp_path):
    from axiom_core.code_validation import CodeValidationOrchestrator

    return CodeValidationOrchestrator(
        artifacts_root=str(tmp_artifacts),
        workspace_root=str(tmp_path),
    )


# ---------------------------------------------------------------------------
# TestEnums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_validation_run_statuses(self):
        from axiom_core.code_validation import ValidationRunStatus

        assert ValidationRunStatus.PENDING.value == "pending"
        assert ValidationRunStatus.PASSED.value == "passed"
        assert ValidationRunStatus.FAILED.value == "failed"
        assert ValidationRunStatus.SIMULATED.value == "simulated"
        assert ValidationRunStatus.REFUSED.value == "refused"

    def test_stage_statuses(self):
        from axiom_core.code_validation import StageStatus

        assert StageStatus.PASSED.value == "passed"
        assert StageStatus.FAILED.value == "failed"
        assert StageStatus.SKIPPED.value == "skipped"
        assert StageStatus.REFUSED.value == "refused"
        assert StageStatus.BLOCKED.value == "blocked"
        assert StageStatus.SIMULATED.value == "simulated"

    def test_stage_kinds(self):
        from axiom_core.code_validation import StageKind

        assert StageKind.TARGETED_TESTS.value == "targeted_tests"
        assert StageKind.FULL_PYTEST.value == "full_pytest"
        assert StageKind.RUFF.value == "ruff"
        assert StageKind.CLI_WALKTHROUGH.value == "cli_walkthrough"
        assert StageKind.ARTIFACT_INSPECTION.value == "artifact_inspection"


# ---------------------------------------------------------------------------
# TestDataModels
# ---------------------------------------------------------------------------


class TestDataModels:
    def test_evidence_to_dict(self):
        from axiom_core.code_validation import CodeValidationEvidence

        ev = CodeValidationEvidence(
            artifact_type="test", artifact_path="/a/b", description="desc",
        )
        d = ev.to_dict()
        assert d["artifact_type"] == "test"
        assert d["artifact_path"] == "/a/b"

    def test_stage_result_to_dict(self):
        from axiom_core.code_validation import CodeValidationStageResult

        r = CodeValidationStageResult(
            exit_code=0, stdout="ok", stderr="", duration_ms=100,
        )
        d = r.to_dict()
        assert d["exit_code"] == 0
        assert d["stdout_length"] == 2
        assert d["duration_ms"] == 100

    def test_stage_to_dict(self):
        from axiom_core.code_validation import (
            CodeValidationStage,
            StageKind,
            StageStatus,
        )

        stage = CodeValidationStage(
            kind=StageKind.RUFF,
            command="poetry run ruff check .",
            description="Lint",
            required=True,
            status=StageStatus.PASSED,
        )
        d = stage.to_dict()
        assert d["kind"] == "ruff"
        assert d["required"] is True
        assert d["status"] == "passed"

    def test_summary_to_dict(self):
        from axiom_core.code_validation import CodeValidationSummary

        s = CodeValidationSummary(
            total_stages=5, stages_passed=3, stages_failed=1,
            stages_skipped=1, overall_passed=False,
            error="One or more required stages failed",
        )
        d = s.to_dict()
        assert d["total_stages"] == 5
        assert d["overall_passed"] is False

    def test_run_to_dict(self):
        from axiom_core.code_validation import CodeValidationRun

        run = CodeValidationRun(
            patch_run_id="pr-1", proposal_id="p-1", simulate=False,
        )
        d = run.to_dict()
        assert d["patch_run_id"] == "pr-1"
        assert d["proposal_id"] == "p-1"
        assert isinstance(d["stages"], list)
        assert isinstance(d["evidence"], list)


# ---------------------------------------------------------------------------
# TestSafetyGates
# ---------------------------------------------------------------------------


class TestSafetyGates:
    def test_unknown_patch_run_refused(self, orchestrator):
        with pytest.raises(ValueError, match="Patch run not found"):
            orchestrator.validate("nonexistent-run-id")

    def test_failed_patch_run_refused(self, orchestrator, failed_patch_run):
        with pytest.raises(ValueError, match="only completed or simulated"):
            orchestrator.validate(failed_patch_run)

    def test_successful_patch_run_accepted(
        self, orchestrator, successful_patch_run,
    ):
        run = orchestrator.validate(successful_patch_run, simulate=True)
        assert run.status.value in ("simulated", "passed", "failed")
        assert run.patch_run_id == successful_patch_run

    def test_simulated_patch_run_accepted(
        self, orchestrator, simulated_patch_run,
    ):
        run = orchestrator.validate(simulated_patch_run, simulate=True)
        assert run.patch_run_id == simulated_patch_run


# ---------------------------------------------------------------------------
# TestSimulateMode
# ---------------------------------------------------------------------------


class TestSimulateMode:
    def test_simulate_produces_simulated_status(
        self, orchestrator, successful_patch_run,
    ):
        run = orchestrator.validate(successful_patch_run, simulate=True)
        assert run.status.value == "simulated"

    def test_simulate_stages_marked_simulated_or_skipped(
        self, orchestrator, successful_patch_run,
    ):
        run = orchestrator.validate(successful_patch_run, simulate=True)
        for stage in run.stages:
            assert stage.status.value in ("simulated", "skipped")

    def test_simulate_writes_evidence(
        self, orchestrator, successful_patch_run, tmp_artifacts,
    ):
        run = orchestrator.validate(successful_patch_run, simulate=True)
        run_dir = tmp_artifacts / "code_validation_runs" / run.run_id
        assert (run_dir / "validation_request.json").exists()
        assert (run_dir / "validation_result.json").exists()
        assert (run_dir / "validation_summary.md").exists()
        assert (run_dir / "pass_fail.json").exists()

    def test_simulate_summary_reports_zero_failures(
        self, orchestrator, successful_patch_run,
    ):
        run = orchestrator.validate(successful_patch_run, simulate=True)
        assert run.summary is not None
        assert run.summary.stages_failed == 0
        assert run.summary.overall_passed is True


# ---------------------------------------------------------------------------
# TestStageOrdering
# ---------------------------------------------------------------------------


class TestStageOrdering:
    def test_deterministic_ordering(
        self, orchestrator, successful_patch_run,
    ):
        run1 = orchestrator.validate(successful_patch_run, simulate=True)
        run2 = orchestrator.validate(successful_patch_run, simulate=True)

        kinds1 = [s.kind.value for s in run1.stages]
        kinds2 = [s.kind.value for s in run2.stages]
        assert kinds1 == kinds2

    def test_stage_order_follows_spec(
        self, orchestrator, successful_patch_run,
    ):
        run = orchestrator.validate(successful_patch_run, simulate=True)
        kinds = [s.kind.value for s in run.stages]

        assert "targeted_tests" in kinds
        assert "full_pytest" in kinds
        assert "ruff" in kinds
        assert "cli_walkthrough" in kinds
        assert "artifact_inspection" in kinds

        pytest_idx = kinds.index("full_pytest")
        ruff_idx = kinds.index("ruff")
        walk_idx = kinds.index("cli_walkthrough")
        inspect_idx = kinds.index("artifact_inspection")
        assert pytest_idx < ruff_idx
        assert ruff_idx < walk_idx
        assert walk_idx < inspect_idx

    def test_targeted_tests_before_full_pytest(
        self, orchestrator, successful_patch_run,
    ):
        run = orchestrator.validate(successful_patch_run, simulate=True)
        kinds = [s.kind.value for s in run.stages]
        if "targeted_tests" in kinds:
            assert kinds.index("targeted_tests") < kinds.index("full_pytest")


# ---------------------------------------------------------------------------
# TestEvidence
# ---------------------------------------------------------------------------


class TestEvidence:
    def test_evidence_always_written(
        self, orchestrator, successful_patch_run, tmp_artifacts,
    ):
        run = orchestrator.validate(successful_patch_run, simulate=True)
        run_dir = tmp_artifacts / "code_validation_runs" / run.run_id

        assert (run_dir / "validation_request.json").exists()
        assert (run_dir / "validation_result.json").exists()
        assert (run_dir / "validation_summary.md").exists()
        assert (run_dir / "pass_fail.json").exists()

    def test_pass_fail_json_valid(
        self, orchestrator, successful_patch_run, tmp_artifacts,
    ):
        run = orchestrator.validate(successful_patch_run, simulate=True)
        run_dir = tmp_artifacts / "code_validation_runs" / run.run_id

        pf = json.loads(
            (run_dir / "pass_fail.json").read_text(encoding="utf-8"),
        )
        assert "run_id" in pf
        assert "passed" in pf
        assert "status" in pf
        assert pf["patch_run_id"] == successful_patch_run

    def test_validation_result_json_valid(
        self, orchestrator, successful_patch_run, tmp_artifacts,
    ):
        run = orchestrator.validate(successful_patch_run, simulate=True)
        run_dir = tmp_artifacts / "code_validation_runs" / run.run_id

        data = json.loads(
            (run_dir / "validation_result.json").read_text(encoding="utf-8"),
        )
        assert data["run_id"] == run.run_id
        assert data["patch_run_id"] == successful_patch_run
        assert isinstance(data["stages"], list)
        assert isinstance(data["summary"], dict)

    def test_summary_md_contains_stages(
        self, orchestrator, successful_patch_run, tmp_artifacts,
    ):
        run = orchestrator.validate(successful_patch_run, simulate=True)
        run_dir = tmp_artifacts / "code_validation_runs" / run.run_id

        md = (run_dir / "validation_summary.md").read_text(encoding="utf-8")
        assert "Code Validation Summary" in md
        assert run.run_id in md
        assert "Stages" in md


# ---------------------------------------------------------------------------
# TestPlaceholderStages
# ---------------------------------------------------------------------------


class TestPlaceholderStages:
    def test_cli_walkthrough_skipped(
        self, orchestrator, successful_patch_run,
    ):
        run = orchestrator.validate(successful_patch_run, simulate=True)
        walkthrough = [
            s for s in run.stages if s.kind.value == "cli_walkthrough"
        ]
        assert len(walkthrough) == 1
        assert walkthrough[0].status.value == "skipped"

    def test_artifact_inspection_skipped(
        self, orchestrator, successful_patch_run,
    ):
        run = orchestrator.validate(successful_patch_run, simulate=True)
        inspection = [
            s for s in run.stages if s.kind.value == "artifact_inspection"
        ]
        assert len(inspection) == 1
        assert inspection[0].status.value == "skipped"


# ---------------------------------------------------------------------------
# TestListAndGetRuns
# ---------------------------------------------------------------------------


class TestListAndGetRuns:
    def test_list_runs_empty(self, orchestrator):
        assert orchestrator.list_runs() == []

    def test_list_runs_after_validate(
        self, orchestrator, successful_patch_run,
    ):
        orchestrator.validate(successful_patch_run, simulate=True)
        runs = orchestrator.list_runs()
        assert len(runs) == 1
        assert runs[0]["patch_run_id"] == successful_patch_run

    def test_get_run_found(
        self, orchestrator, successful_patch_run,
    ):
        run = orchestrator.validate(successful_patch_run, simulate=True)
        data = orchestrator.get_run(run.run_id)
        assert data is not None
        assert data["run_id"] == run.run_id

    def test_get_run_not_found(self, orchestrator):
        assert orchestrator.get_run("nonexistent") is None


# ---------------------------------------------------------------------------
# TestJsonOutput
# ---------------------------------------------------------------------------


class TestJsonOutput:
    def test_run_json_roundtrip(
        self, orchestrator, successful_patch_run,
    ):
        run = orchestrator.validate(successful_patch_run, simulate=True)
        output = json.dumps(run.to_dict(), indent=2, default=str)
        parsed = json.loads(output)
        assert parsed["status"] == "simulated"
        assert isinstance(parsed["stages"], list)
        assert isinstance(parsed["summary"], dict)
        assert parsed["summary"]["overall_passed"] is True


# ---------------------------------------------------------------------------
# TestAllowlist
# ---------------------------------------------------------------------------


class TestAllowlist:
    def test_allowlisted_commands_recognized(self):
        from axiom_core.code_validation import CodeValidationOrchestrator

        o = CodeValidationOrchestrator.__new__(CodeValidationOrchestrator)
        assert o._is_command_allowed("poetry run pytest tests/test_x.py -x -q")
        assert o._is_command_allowed("poetry run pytest -x -q")
        assert o._is_command_allowed("poetry run ruff check src/x.py")

    def test_non_allowlisted_rejected(self):
        from axiom_core.code_validation import CodeValidationOrchestrator

        o = CodeValidationOrchestrator.__new__(CodeValidationOrchestrator)
        assert not o._is_command_allowed("rm -rf /")
        assert not o._is_command_allowed("git push origin main")
        assert not o._is_command_allowed("curl http://example.com")
        assert not o._is_command_allowed("python -c 'import os; os.system(\"ls\")'")


# ---------------------------------------------------------------------------
# TestChangedFileExtraction
# ---------------------------------------------------------------------------


class TestChangedFileExtraction:
    def test_extracts_files_from_steps(self, orchestrator, successful_patch_run):
        run = orchestrator.validate(successful_patch_run, simulate=True)
        targeted = [
            s for s in run.stages if s.kind.value == "targeted_tests"
        ]
        assert len(targeted) == 1
        assert "tests/test_example.py" in targeted[0].command

    def test_ruff_stage_includes_src_files(
        self, orchestrator, successful_patch_run,
    ):
        run = orchestrator.validate(successful_patch_run, simulate=True)
        ruff = [s for s in run.stages if s.kind.value == "ruff"]
        assert len(ruff) == 1
        assert "src/axiom_core/example.py" in ruff[0].command
        assert "tests/test_example.py" not in ruff[0].command


# ---------------------------------------------------------------------------
# TestPathTraversal
# ---------------------------------------------------------------------------


class TestPathTraversal:
    def test_patch_run_id_traversal_rejected(self, orchestrator):
        with pytest.raises(ValueError, match="must not contain"):
            orchestrator.validate("../../etc/passwd")

    def test_patch_run_id_slash_rejected(self, orchestrator):
        with pytest.raises(ValueError, match="must not contain"):
            orchestrator.validate("foo/bar")

    def test_run_id_traversal_rejected(self, orchestrator):
        with pytest.raises(ValueError, match="must not contain"):
            orchestrator.get_run("../secrets")

    def test_run_id_slash_rejected(self, orchestrator):
        with pytest.raises(ValueError, match="must not contain"):
            orchestrator.get_run("a/b")

    def test_empty_run_id_rejected(self, orchestrator):
        with pytest.raises(ValueError, match="must not contain"):
            orchestrator.get_run("")


# ---------------------------------------------------------------------------
# TestArgumentInjection
# ---------------------------------------------------------------------------


class TestArgumentInjection:
    def test_dash_file_path_rejected(self, tmp_artifacts, tmp_path):
        """File paths starting with '-' must be rejected."""
        run_id = "patch-run-dash"
        run_dir = tmp_artifacts / "patch_runs" / run_id
        run_dir.mkdir(parents=True)

        result = {
            "run_id": run_id,
            "proposal_id": "p",
            "status": "completed",
            "steps": [
                {"file_path": "--collect-only", "edit_type": "add", "status": "applied"},
            ],
            "result": {"success": True, "steps_applied": 1},
        }
        (run_dir / "patch_result.json").write_text(
            json.dumps(result), encoding="utf-8",
        )

        from axiom_core.code_validation import CodeValidationOrchestrator

        o = CodeValidationOrchestrator(
            artifacts_root=str(tmp_artifacts),
            workspace_root=str(tmp_path),
        )
        with pytest.raises(ValueError, match="must not start with"):
            o.validate(run_id, simulate=True)

    def test_dotdot_file_path_rejected(self, tmp_artifacts, tmp_path):
        """File paths with '..' must be rejected."""
        run_id = "patch-run-dotdot"
        run_dir = tmp_artifacts / "patch_runs" / run_id
        run_dir.mkdir(parents=True)

        result = {
            "run_id": run_id,
            "proposal_id": "p",
            "status": "completed",
            "steps": [
                {"file_path": "../../../etc/passwd", "edit_type": "add", "status": "applied"},
            ],
            "result": {"success": True, "steps_applied": 1},
        }
        (run_dir / "patch_result.json").write_text(
            json.dumps(result), encoding="utf-8",
        )

        from axiom_core.code_validation import CodeValidationOrchestrator

        o = CodeValidationOrchestrator(
            artifacts_root=str(tmp_artifacts),
            workspace_root=str(tmp_path),
        )
        with pytest.raises(ValueError, match="must not contain"):
            o.validate(run_id, simulate=True)


# ---------------------------------------------------------------------------
# TestEvidenceCompleteness
# ---------------------------------------------------------------------------


class TestEvidenceCompleteness:
    def test_result_json_contains_all_evidence(
        self, orchestrator, successful_patch_run, tmp_artifacts,
    ):
        """validation_result.json must contain all evidence entries."""
        run = orchestrator.validate(successful_patch_run, simulate=True)
        run_dir = tmp_artifacts / "code_validation_runs" / run.run_id

        data = json.loads(
            (run_dir / "validation_result.json").read_text(encoding="utf-8"),
        )
        evidence_types = {e["artifact_type"] for e in data["evidence"]}
        assert "validation_request" in evidence_types
        assert "validation_summary" in evidence_types
        assert "pass_fail" in evidence_types
        assert "validation_result" in evidence_types
        assert len(data["evidence"]) >= 4
