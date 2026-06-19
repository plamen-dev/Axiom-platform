"""Tests for PR Draft Generator v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_artifacts(tmp_path: Path) -> Path:
    """Create a temporary artifacts directory."""
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    return artifacts


@pytest.fixture()
def successful_validation_run(tmp_artifacts: Path) -> str:
    """Create a validation run artifact with simulated success."""
    run_id = "val-run-001"
    run_dir = tmp_artifacts / "code_validation_runs" / run_id
    run_dir.mkdir(parents=True)

    data = {
        "run_id": run_id,
        "patch_run_id": "patch-run-001",
        "proposal_id": "proposal-001",
        "simulate": True,
        "status": "simulated",
        "stages": [
            {
                "kind": "targeted_tests",
                "status": "simulated",
                "required": True,
            },
            {
                "kind": "full_pytest",
                "status": "simulated",
                "required": True,
            },
            {
                "kind": "ruff",
                "status": "simulated",
                "required": True,
            },
        ],
        "evidence": [
            {
                "artifact_type": "validation_request",
                "artifact_path": f"{run_dir}/validation_request.json",
            },
            {
                "artifact_type": "validation_summary",
                "artifact_path": f"{run_dir}/validation_summary.md",
            },
            {
                "artifact_type": "pass_fail",
                "artifact_path": f"{run_dir}/pass_fail.json",
            },
            {
                "artifact_type": "validation_result",
                "artifact_path": f"{run_dir}/validation_result.json",
            },
        ],
        "summary": {
            "total_stages": 3,
            "stages_passed": 0,
            "stages_failed": 0,
            "stages_skipped": 0,
            "stages_simulated": 3,
            "overall_passed": True,
        },
        "started_at": "2026-01-01T00:00:00+00:00",
        "completed_at": "2026-01-01T00:00:01+00:00",
    }
    (run_dir / "validation_result.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8",
    )
    return run_id


@pytest.fixture()
def successful_patch_run(tmp_artifacts: Path) -> str:
    """Create a patch run artifact."""
    run_id = "patch-run-001"
    run_dir = tmp_artifacts / "patch_runs" / run_id
    run_dir.mkdir(parents=True)

    data = {
        "run_id": run_id,
        "proposal_id": "proposal-001",
        "status": "completed",
        "steps": [
            {"file_path": "src/axiom_core/example.py", "edit_type": "modify", "status": "applied"},
            {"file_path": "tests/test_example.py", "edit_type": "modify", "status": "applied"},
        ],
        "result": {"success": True, "steps_applied": 2, "steps_failed": 0},
    }
    (run_dir / "patch_result.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8",
    )
    return run_id


@pytest.fixture()
def generator(tmp_artifacts: Path, tmp_path: Path):
    """Create a PRDraftGenerator with temp paths."""
    from axiom_core.pr_draft_generator import PRDraftGenerator

    return PRDraftGenerator(
        db_path=str(tmp_path / "test.db"),
        artifacts_root=str(tmp_artifacts),
    )


# ---------------------------------------------------------------------------
# Test: Generation from validation run
# ---------------------------------------------------------------------------


class TestGenerateFromValidationRun:
    """Test PR draft generation from a validation run ID."""

    def test_generates_draft_from_validation_run(
        self,
        generator,
        successful_validation_run,
        successful_patch_run,
    ):
        """Generates a draft with correct status and sections."""
        draft = generator.generate(validation_run_id=successful_validation_run)

        assert draft.status.value == "generated"
        assert draft.validation_run_id == successful_validation_run
        assert draft.patch_run_id == "patch-run-001"
        assert draft.proposal_id == "proposal-001"
        assert draft.summary is not None
        assert draft.validation_section is not None
        assert draft.strategic_section is not None

    def test_validation_section_populated(
        self,
        generator,
        successful_validation_run,
        successful_patch_run,
    ):
        """Validation section contains correct evidence links."""
        draft = generator.generate(validation_run_id=successful_validation_run)

        vs = draft.validation_section
        assert vs is not None
        assert vs.validation_run_id == "val-run-001"
        assert vs.overall_passed is True
        assert vs.status == "simulated"
        assert len(vs.evidence_paths) == 4

    def test_summary_has_files_changed(
        self,
        generator,
        successful_validation_run,
        successful_patch_run,
    ):
        """Summary includes file count from patch run."""
        draft = generator.generate(validation_run_id=successful_validation_run)

        assert draft.summary is not None
        assert draft.summary.files_changed == 2
        assert draft.summary.tests_affected == 1

    def test_commit_title_generated(
        self,
        generator,
        successful_validation_run,
        successful_patch_run,
    ):
        """Commit title is non-empty."""
        draft = generator.generate(validation_run_id=successful_validation_run)

        assert draft.summary is not None
        assert draft.summary.commit_title != ""


# ---------------------------------------------------------------------------
# Test: Validation run not found
# ---------------------------------------------------------------------------


class TestValidationRunNotFound:
    """Test behavior when validation run ID doesn't exist."""

    def test_unknown_validation_run_raises(self, generator):
        """Unknown validation run ID raises ValueError."""
        with pytest.raises(ValueError, match="Validation run not found"):
            generator.generate(validation_run_id="totally-nonexistent")

    def test_empty_inputs_raises(self, generator):
        """No inputs raises ValueError."""
        with pytest.raises(ValueError, match="At least one of"):
            generator.generate()


# ---------------------------------------------------------------------------
# Test: Evidence artifacts written
# ---------------------------------------------------------------------------


class TestEvidenceArtifacts:
    """Test that all 4 evidence files are written."""

    def test_all_four_evidence_files_exist(
        self,
        generator,
        successful_validation_run,
        successful_patch_run,
        tmp_artifacts,
    ):
        """pr_request, pr_result, pr_summary, pass_fail all written."""
        draft = generator.generate(validation_run_id=successful_validation_run)

        run_dir = tmp_artifacts / "pr_drafts" / draft.draft_id
        assert (run_dir / "pr_request.json").exists()
        assert (run_dir / "pr_result.json").exists()
        assert (run_dir / "pr_summary.md").exists()
        assert (run_dir / "pass_fail.json").exists()

    def test_pr_request_valid_json(
        self,
        generator,
        successful_validation_run,
        successful_patch_run,
        tmp_artifacts,
    ):
        """pr_request.json is valid JSON with expected keys."""
        draft = generator.generate(validation_run_id=successful_validation_run)

        run_dir = tmp_artifacts / "pr_drafts" / draft.draft_id
        data = json.loads((run_dir / "pr_request.json").read_text(encoding="utf-8"))
        assert data["draft_id"] == draft.draft_id
        assert data["validation_run_id"] == successful_validation_run
        assert "requested_at" in data

    def test_pr_result_contains_full_draft(
        self,
        generator,
        successful_validation_run,
        successful_patch_run,
        tmp_artifacts,
    ):
        """pr_result.json contains the full draft serialization."""
        draft = generator.generate(validation_run_id=successful_validation_run)

        run_dir = tmp_artifacts / "pr_drafts" / draft.draft_id
        data = json.loads((run_dir / "pr_result.json").read_text(encoding="utf-8"))
        assert data["status"] == "generated"
        assert data["validation_run_id"] == successful_validation_run
        assert data["summary"] is not None
        assert data["validation_section"] is not None
        assert data["strategic_section"] is not None

    def test_pass_fail_indicates_success(
        self,
        generator,
        successful_validation_run,
        successful_patch_run,
        tmp_artifacts,
    ):
        """pass_fail.json indicates success for generated draft."""
        draft = generator.generate(validation_run_id=successful_validation_run)

        run_dir = tmp_artifacts / "pr_drafts" / draft.draft_id
        data = json.loads((run_dir / "pass_fail.json").read_text(encoding="utf-8"))
        assert data["passed"] is True
        assert data["status"] == "generated"

    def test_summary_md_has_title(
        self,
        generator,
        successful_validation_run,
        successful_patch_run,
        tmp_artifacts,
    ):
        """pr_summary.md contains PR Draft Summary header."""
        draft = generator.generate(validation_run_id=successful_validation_run)

        run_dir = tmp_artifacts / "pr_drafts" / draft.draft_id
        content = (run_dir / "pr_summary.md").read_text(encoding="utf-8")
        assert "# PR Draft Summary" in content
        assert draft.draft_id in content


# ---------------------------------------------------------------------------
# Test: Deterministic output
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Test that draft generation is deterministic."""

    def test_structural_fields_identical_across_runs(
        self,
        tmp_artifacts,
        successful_validation_run,
        successful_patch_run,
        tmp_path,
    ):
        """Two generations of the same input produce structurally identical output."""
        from axiom_core.pr_draft_generator import PRDraftGenerator

        g1 = PRDraftGenerator(
            db_path=str(tmp_path / "test1.db"),
            artifacts_root=str(tmp_artifacts),
        )
        g2 = PRDraftGenerator(
            db_path=str(tmp_path / "test2.db"),
            artifacts_root=str(tmp_artifacts),
        )

        draft1 = g1.generate(validation_run_id=successful_validation_run)
        draft2 = g2.generate(validation_run_id=successful_validation_run)

        d1 = draft1.to_dict()
        d2 = draft2.to_dict()

        # IDs and timestamps differ, structural content should be same
        assert d1["summary"]["commit_title"] == d2["summary"]["commit_title"]
        assert d1["summary"]["files_changed"] == d2["summary"]["files_changed"]
        assert d1["validation_section"]["overall_passed"] == d2["validation_section"]["overall_passed"]
        assert d1["strategic_section"] == d2["strategic_section"]
        assert d1["known_limitations"] == d2["known_limitations"]


# ---------------------------------------------------------------------------
# Test: List and get drafts
# ---------------------------------------------------------------------------


class TestListAndGetDrafts:
    """Test listing and retrieving drafts."""

    def test_list_drafts_returns_generated(
        self,
        generator,
        successful_validation_run,
        successful_patch_run,
    ):
        """List returns at least the draft we just generated."""
        generator.generate(validation_run_id=successful_validation_run)
        drafts = generator.list_drafts()

        assert len(drafts) >= 1
        assert drafts[0]["status"] == "generated"

    def test_get_draft_returns_specific(
        self,
        generator,
        successful_validation_run,
        successful_patch_run,
    ):
        """Get returns the specific draft by ID."""
        draft = generator.generate(validation_run_id=successful_validation_run)
        result = generator.get_draft(draft.draft_id)

        assert result is not None
        assert result["draft_id"] == draft.draft_id
        assert result["status"] == "generated"

    def test_get_unknown_returns_none(self, generator):
        """Unknown draft ID returns None."""
        result = generator.get_draft("nonexistent-id")
        assert result is None

    def test_list_empty_returns_empty(self, generator):
        """Empty artifacts dir returns empty list."""
        assert generator.list_drafts() == []


# ---------------------------------------------------------------------------
# Test: Path traversal rejection
# ---------------------------------------------------------------------------


class TestPathTraversal:
    """Test rejection of path traversal in IDs."""

    def test_validation_run_id_traversal_rejected(self, generator):
        """Path traversal in validation_run_id raises ValueError."""
        with pytest.raises(ValueError, match="must not contain"):
            generator.generate(validation_run_id="../../etc/passwd")

    def test_draft_id_traversal_rejected(self, generator):
        """Path traversal in get_draft raises ValueError."""
        with pytest.raises(ValueError, match="must not contain"):
            generator.get_draft("../secrets")

    def test_slash_in_id_rejected(self, generator):
        """Slash in ID raises ValueError."""
        with pytest.raises(ValueError, match="must not contain"):
            generator.generate(validation_run_id="foo/bar")

    def test_backslash_in_id_rejected(self, generator):
        """Backslash in ID raises ValueError."""
        with pytest.raises(ValueError, match="must not contain"):
            generator.generate(validation_run_id="foo\\bar")

    def test_artifact_patch_run_id_traversal_rejected(
        self, tmp_artifacts, tmp_path,
    ):
        """patch_run_id from artifact data is validated before path construction."""
        from axiom_core.pr_draft_generator import PRDraftGenerator

        run_id = "val-crafted"
        run_dir = tmp_artifacts / "code_validation_runs" / run_id
        run_dir.mkdir(parents=True)

        data = {
            "run_id": run_id,
            "patch_run_id": "../../etc/shadow",
            "proposal_id": "",
            "status": "simulated",
            "stages": [],
            "evidence": [],
            "summary": {"overall_passed": True},
        }
        (run_dir / "validation_result.json").write_text(
            json.dumps(data), encoding="utf-8",
        )

        g = PRDraftGenerator(
            db_path=str(tmp_path / "test.db"),
            artifacts_root=str(tmp_artifacts),
        )
        with pytest.raises(ValueError, match="must not contain"):
            g.generate(validation_run_id=run_id)


# ---------------------------------------------------------------------------
# Test: Strategic section
# ---------------------------------------------------------------------------


class TestStrategicSection:
    """Test strategic section generation."""

    def test_non_goals_present(
        self,
        generator,
        successful_validation_run,
        successful_patch_run,
    ):
        """Strategic section includes non-goals."""
        draft = generator.generate(validation_run_id=successful_validation_run)

        ss = draft.strategic_section
        assert ss is not None
        assert len(ss.non_goals) > 0
        assert "No PR opening" in ss.non_goals

    def test_what_did_not_change_present(
        self,
        generator,
        successful_validation_run,
        successful_patch_run,
    ):
        """Strategic section includes what did not change."""
        draft = generator.generate(validation_run_id=successful_validation_run)

        ss = draft.strategic_section
        assert ss is not None
        assert len(ss.what_did_not_change) > 0
        assert any("Git" in item for item in ss.what_did_not_change)

    def test_next_step_present(
        self,
        generator,
        successful_validation_run,
        successful_patch_run,
    ):
        """Strategic section has a next recommended step."""
        draft = generator.generate(validation_run_id=successful_validation_run)

        ss = draft.strategic_section
        assert ss is not None
        assert ss.next_recommended_step != ""


# ---------------------------------------------------------------------------
# Test: Empty sections handled gracefully
# ---------------------------------------------------------------------------


class TestEmptySections:
    """Test graceful handling when upstream data is minimal."""

    def test_validation_run_with_no_patch_run(self, tmp_artifacts, tmp_path):
        """Draft generates even if patch run artifact doesn't exist."""
        from axiom_core.pr_draft_generator import PRDraftGenerator

        # Create validation run pointing to non-existent patch run
        run_id = "val-orphan"
        run_dir = tmp_artifacts / "code_validation_runs" / run_id
        run_dir.mkdir(parents=True)

        data = {
            "run_id": run_id,
            "patch_run_id": "nonexistent-patch",
            "proposal_id": "",
            "status": "simulated",
            "stages": [],
            "evidence": [],
            "summary": {"overall_passed": True, "stages_passed": 0},
        }
        (run_dir / "validation_result.json").write_text(
            json.dumps(data), encoding="utf-8",
        )

        g = PRDraftGenerator(
            db_path=str(tmp_path / "test.db"),
            artifacts_root=str(tmp_artifacts),
        )
        draft = g.generate(validation_run_id=run_id)

        assert draft.status.value == "generated"
        assert draft.summary is not None
        assert draft.summary.files_changed == 0

    def test_no_limitations_when_proposal_missing(
        self,
        generator,
        successful_validation_run,
        successful_patch_run,
    ):
        """Known limitations is empty when proposal has no risks."""
        draft = generator.generate(validation_run_id=successful_validation_run)
        assert draft.known_limitations == []


# ---------------------------------------------------------------------------
# Test: to_dict serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    """Test that to_dict produces valid serializable output."""

    def test_to_dict_is_json_serializable(
        self,
        generator,
        successful_validation_run,
        successful_patch_run,
    ):
        """to_dict output can be serialized to JSON without errors."""
        draft = generator.generate(validation_run_id=successful_validation_run)
        data = draft.to_dict()

        serialized = json.dumps(data, indent=2, default=str)
        assert len(serialized) > 100

        parsed = json.loads(serialized)
        assert parsed["status"] == "generated"
        assert parsed["draft_id"] == draft.draft_id
