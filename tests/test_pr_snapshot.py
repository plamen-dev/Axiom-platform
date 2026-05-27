"""Tests for the pr-snapshot and evidence-update CLI commands."""

import json
from pathlib import Path

import pytest
from axiom_cli.main import cli
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sample_summary_file(tmp_path):
    summary = tmp_path / "summary.md"
    summary.write_text(
        "## Summary\n\n"
        "Fixed export path collision bug.\n\n"
        "## Root Cause\n\n"
        "Second-level timestamp precision caused overwrites.\n\n"
        "## Changes\n\n"
        "Added milliseconds + atomic counter to filename.\n\n"
        "## What Did NOT Change\n\n"
        "No extraction behavior modified.\n\n"
        "## Validation Results\n\n"
        "278 exports, 0 duplicates.\n\n"
        "## Safety Notes\n\n"
        "Direct full-model extraction remains blocked.\n\n"
        "## Known Limitations\n\n"
        "Only Snowdon Towers validated.\n\n"
        "## Artifact Paths\n\n"
        "artifacts/parameter_registry_candidates/<run_id>/\n\n"
        "### Notes\n\n"
        "No runtime code changed.\n",
        encoding="utf-8",
    )
    return summary


@pytest.fixture
def sample_validation_file(tmp_path):
    validation = tmp_path / "validation.md"
    validation.write_text(
        "278 successful exports, 0 duplicate paths\n"
        "6,444 unique definitions\n"
        "20/20 priority coverage\n",
        encoding="utf-8",
    )
    return validation


@pytest.fixture
def sample_changed_files(tmp_path):
    changed = tmp_path / "changed_files.txt"
    changed.write_text(
        "src/axiom_revit/Axiom.RevitAddin/PromptCommand.cs\n"
        "src/axiom_cli/main.py\n"
        "tests/test_inventory.py\n",
        encoding="utf-8",
    )
    return changed


@pytest.fixture
def sample_commits_file(tmp_path):
    commits = tmp_path / "commits.txt"
    commits.write_text(
        "abc1234 fix: unique export filenames\n"
        "def5678 fix: manifest duplicate detection\n",
        encoding="utf-8",
    )
    return commits


class TestPrSnapshot:
    """Tests for axiom pr-snapshot command."""

    def test_snapshot_creates_json_and_markdown(self, runner, tmp_path, sample_summary_file):
        out_dir = str(tmp_path / "pr_0009")
        result = runner.invoke(cli, [
            "pr-snapshot",
            "--pr", "9",
            "--title", "Export path collision fix",
            "--branch", "devin/fix-export-collision",
            "--status", "merged",
            "--summary-file", str(sample_summary_file),
            "--out", out_dir,
        ])
        assert result.exit_code == 0, result.output

        json_path = Path(out_dir) / "review_snapshot.json"
        md_path = Path(out_dir) / "review_snapshot.md"
        assert json_path.exists()
        assert md_path.exists()

        snapshot = json.loads(json_path.read_text(encoding="utf-8"))
        assert snapshot["pr_number"] == 9
        assert snapshot["title"] == "Export path collision fix"
        assert snapshot["branch"] == "devin/fix-export-collision"
        assert snapshot["status"] == "merged"

    def test_snapshot_required_fields_validated(self, runner, tmp_path):
        out_dir = str(tmp_path / "pr_0001")
        result = runner.invoke(cli, [
            "pr-snapshot",
            "--pr", "1",
            "--title", "Test PR",
            "--branch", "test-branch",
            "--status", "merged",
            "--out", out_dir,
        ])
        assert result.exit_code == 0, result.output

        json_path = Path(out_dir) / "review_snapshot.json"
        snapshot = json.loads(json_path.read_text(encoding="utf-8"))

        required_fields = [
            "pr_number", "title", "branch", "status", "merge_status",
            "summary", "review_checklist", "notes", "root_cause",
            "changes", "what_did_not_change", "validation_commands",
            "validation_results", "safety_notes", "known_limitations",
            "follow_up_tasks", "artifact_paths", "source_url",
            "verification_method", "status_source", "created_at",
        ]
        for field in required_fields:
            assert field in snapshot, f"Missing required field: {field}"

    def test_snapshot_parses_summary_sections(self, runner, tmp_path, sample_summary_file):
        out_dir = str(tmp_path / "pr_0009")
        result = runner.invoke(cli, [
            "pr-snapshot",
            "--pr", "9",
            "--title", "Test",
            "--branch", "test",
            "--status", "merged",
            "--summary-file", str(sample_summary_file),
            "--out", out_dir,
        ])
        assert result.exit_code == 0

        snapshot = json.loads(
            (Path(out_dir) / "review_snapshot.json").read_text(encoding="utf-8")
        )
        assert "export path collision" in snapshot["summary"].lower()
        assert "second-level" in snapshot["root_cause"].lower()
        assert "milliseconds" in snapshot["changes"].lower()
        assert "extraction behavior" in snapshot["what_did_not_change"].lower()
        assert "278" in snapshot["validation_results"]
        assert "blocked" in snapshot["safety_notes"].lower()
        assert "snowdon" in snapshot["known_limitations"].lower()

    def test_snapshot_validation_file_overrides_parsed(
        self, runner, tmp_path, sample_summary_file, sample_validation_file
    ):
        out_dir = str(tmp_path / "pr_0009")
        result = runner.invoke(cli, [
            "pr-snapshot",
            "--pr", "9",
            "--title", "Test",
            "--branch", "test",
            "--status", "merged",
            "--summary-file", str(sample_summary_file),
            "--validation-file", str(sample_validation_file),
            "--out", out_dir,
        ])
        assert result.exit_code == 0

        snapshot = json.loads(
            (Path(out_dir) / "review_snapshot.json").read_text(encoding="utf-8")
        )
        assert "6,444" in snapshot["validation_results"]

    def test_snapshot_copies_changed_files_and_commits(
        self, runner, tmp_path, sample_changed_files, sample_commits_file
    ):
        out_dir = str(tmp_path / "pr_0009")
        result = runner.invoke(cli, [
            "pr-snapshot",
            "--pr", "9",
            "--title", "Test",
            "--branch", "test",
            "--status", "merged",
            "--changed-files", str(sample_changed_files),
            "--commits-file", str(sample_commits_file),
            "--out", out_dir,
        ])
        assert result.exit_code == 0

        changed = (Path(out_dir) / "changed_files.txt").read_text(encoding="utf-8")
        assert "PromptCommand.cs" in changed

        commits = (Path(out_dir) / "commits.txt").read_text(encoding="utf-8")
        assert "abc1234" in commits

    def test_snapshot_default_output_dir(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, [
            "pr-snapshot",
            "--pr", "42",
            "--title", "Test",
            "--branch", "test",
            "--status", "open",
        ])
        assert result.exit_code == 0
        assert (tmp_path / "artifacts" / "pr_reviews" / "pr_0042" /
                "review_snapshot.json").exists()

    def test_snapshot_source_url_included(self, runner, tmp_path):
        out_dir = str(tmp_path / "pr_0009")
        result = runner.invoke(cli, [
            "pr-snapshot",
            "--pr", "9",
            "--title", "Test",
            "--branch", "test",
            "--status", "merged",
            "--source-url", "https://github.com/org/repo/pull/9",
            "--out", out_dir,
        ])
        assert result.exit_code == 0

        snapshot = json.loads(
            (Path(out_dir) / "review_snapshot.json").read_text(encoding="utf-8")
        )
        assert snapshot["source_url"] == "https://github.com/org/repo/pull/9"

        md = (Path(out_dir) / "review_snapshot.md").read_text(encoding="utf-8")
        assert "https://github.com/org/repo/pull/9" in md

    def test_snapshot_markdown_includes_all_sections(
        self, runner, tmp_path, sample_summary_file
    ):
        out_dir = str(tmp_path / "pr_0009")
        runner.invoke(cli, [
            "pr-snapshot",
            "--pr", "9",
            "--title", "Export collision fix",
            "--branch", "devin/fix",
            "--status", "merged",
            "--summary-file", str(sample_summary_file),
            "--out", out_dir,
        ])

        md = (Path(out_dir) / "review_snapshot.md").read_text(encoding="utf-8")
        assert "# PR #9: Export collision fix" in md
        assert "## Summary" in md
        assert "## Root Cause" in md
        assert "## Safety Notes" in md

    def test_snapshot_invalid_status_rejected(self, runner, tmp_path):
        result = runner.invoke(cli, [
            "pr-snapshot",
            "--pr", "1",
            "--title", "Test",
            "--branch", "test",
            "--status", "invalid_status",
            "--out", str(tmp_path / "out"),
        ])
        assert result.exit_code != 0

    def test_snapshot_default_verification_is_unverified(self, runner, tmp_path):
        out_dir = str(tmp_path / "pr_0001")
        runner.invoke(cli, [
            "pr-snapshot",
            "--pr", "1",
            "--title", "Test",
            "--branch", "test",
            "--status", "merged",
            "--out", out_dir,
        ])
        snapshot = json.loads(
            (Path(out_dir) / "review_snapshot.json").read_text(encoding="utf-8")
        )
        assert snapshot["verification_method"] == "unverified"
        assert "not verified" in snapshot["status_source"].lower()

    def test_snapshot_gh_cli_verification(self, runner, tmp_path):
        out_dir = str(tmp_path / "pr_0009")
        runner.invoke(cli, [
            "pr-snapshot",
            "--pr", "9",
            "--title", "Export fix",
            "--branch", "devin/fix",
            "--status", "merged",
            "--verification-method", "gh_cli",
            "--status-source", "gh pr view 9 --json state,mergedAt",
            "--out", out_dir,
        ])
        snapshot = json.loads(
            (Path(out_dir) / "review_snapshot.json").read_text(encoding="utf-8")
        )
        assert snapshot["verification_method"] == "gh_cli"
        assert "gh pr view" in snapshot["status_source"]

        md = (Path(out_dir) / "review_snapshot.md").read_text(encoding="utf-8")
        assert "verified: gh_cli" in md

    def test_snapshot_github_ui_manual_verification(self, runner, tmp_path):
        out_dir = str(tmp_path / "pr_0009")
        runner.invoke(cli, [
            "pr-snapshot",
            "--pr", "9",
            "--title", "Export fix",
            "--branch", "devin/fix",
            "--status", "merged",
            "--verification-method", "github_ui_manual",
            "--out", out_dir,
        ])
        snapshot = json.loads(
            (Path(out_dir) / "review_snapshot.json").read_text(encoding="utf-8")
        )
        assert snapshot["verification_method"] == "github_ui_manual"

        md = (Path(out_dir) / "review_snapshot.md").read_text(encoding="utf-8")
        assert "verified: github_ui_manual" in md

    def test_snapshot_git_inferred_merged_shows_qualified(self, runner, tmp_path):
        out_dir = str(tmp_path / "pr_0009")
        runner.invoke(cli, [
            "pr-snapshot",
            "--pr", "9",
            "--title", "Export fix",
            "--branch", "devin/fix",
            "--status", "merged",
            "--verification-method", "git_inferred",
            "--out", out_dir,
        ])
        md = (Path(out_dir) / "review_snapshot.md").read_text(encoding="utf-8")
        assert "git-inferred" in md
        assert "not verified" in md.lower()

    def test_snapshot_unverified_merged_shows_warning(self, runner, tmp_path):
        out_dir = str(tmp_path / "pr_0001")
        runner.invoke(cli, [
            "pr-snapshot",
            "--pr", "1",
            "--title", "Test",
            "--branch", "test",
            "--status", "merged",
            "--out", out_dir,
        ])
        md = (Path(out_dir) / "review_snapshot.md").read_text(encoding="utf-8")
        assert "UNVERIFIED" in md


class TestEvidenceUpdate:
    """Tests for axiom evidence-update command."""

    def _create_snapshot(self, runner, tmp_path, summary_file=None,
                         verification_method="unverified", status_source=None):
        out_dir = str(tmp_path / "pr_0009")
        args = [
            "pr-snapshot",
            "--pr", "9",
            "--title", "Export path collision fix",
            "--branch", "devin/fix-export-collision",
            "--status", "merged",
            "--merge-status", "merged to main 2026-05-06",
            "--verification-method", verification_method,
            "--out", out_dir,
        ]
        if summary_file:
            args.extend(["--summary-file", str(summary_file)])
        if status_source:
            args.extend(["--status-source", status_source])
        runner.invoke(cli, args)
        return out_dir

    def test_evidence_update_creates_proposed_text(
        self, runner, tmp_path, sample_summary_file
    ):
        snapshot_dir = self._create_snapshot(runner, tmp_path, sample_summary_file)
        result = runner.invoke(cli, [
            "evidence-update",
            "--from-pr-snapshot", snapshot_dir,
        ])
        assert result.exit_code == 0

        proposed_path = Path(snapshot_dir) / "proposed_ledger_entries.md"
        assert proposed_path.exists()

        proposed = proposed_path.read_text(encoding="utf-8")
        assert "pr-review-ledger.md" in proposed
        assert "founders-evidence-log.md" in proposed
        assert "PR #9" in proposed

    def test_evidence_update_includes_bug_entry_when_root_cause(
        self, runner, tmp_path, sample_summary_file
    ):
        snapshot_dir = self._create_snapshot(runner, tmp_path, sample_summary_file)
        result = runner.invoke(cli, [
            "evidence-update",
            "--from-pr-snapshot", snapshot_dir,
        ])
        assert result.exit_code == 0

        proposed = (Path(snapshot_dir) / "proposed_ledger_entries.md").read_text(
            encoding="utf-8"
        )
        assert "bug-validation-log.md" in proposed
        assert "BUG-NNN" in proposed

    def test_evidence_update_includes_behavior_entry_when_changes(
        self, runner, tmp_path, sample_summary_file
    ):
        snapshot_dir = self._create_snapshot(runner, tmp_path, sample_summary_file)
        result = runner.invoke(cli, [
            "evidence-update",
            "--from-pr-snapshot", snapshot_dir,
        ])
        assert result.exit_code == 0

        proposed = (Path(snapshot_dir) / "proposed_ledger_entries.md").read_text(
            encoding="utf-8"
        )
        assert "behavior-change-ledger.md" in proposed
        assert "BHV-NNN" in proposed

    def test_evidence_update_out_file(self, runner, tmp_path, sample_summary_file):
        snapshot_dir = self._create_snapshot(runner, tmp_path, sample_summary_file)
        out_file = str(tmp_path / "ledger_proposal.md")
        result = runner.invoke(cli, [
            "evidence-update",
            "--from-pr-snapshot", snapshot_dir,
            "--out", out_file,
        ])
        assert result.exit_code == 0
        assert Path(out_file).exists()

    def test_evidence_update_no_bug_entry_without_root_cause(self, runner, tmp_path):
        snapshot_dir = self._create_snapshot(runner, tmp_path)
        result = runner.invoke(cli, [
            "evidence-update",
            "--from-pr-snapshot", snapshot_dir,
        ])
        assert result.exit_code == 0

        proposed = (Path(snapshot_dir) / "proposed_ledger_entries.md").read_text(
            encoding="utf-8"
        )
        assert "bug-validation-log.md" not in proposed

    def test_evidence_update_missing_snapshot_json(self, runner, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        result = runner.invoke(cli, [
            "evidence-update",
            "--from-pr-snapshot", str(empty_dir),
        ])
        assert result.exit_code != 0

    def test_no_external_network_dependency(self, runner, tmp_path, sample_summary_file):
        """Verify that both commands work without any network access."""
        # Create snapshot
        out_dir = str(tmp_path / "pr_0009")
        r1 = runner.invoke(cli, [
            "pr-snapshot",
            "--pr", "9",
            "--title", "Test",
            "--branch", "test",
            "--status", "merged",
            "--summary-file", str(sample_summary_file),
            "--out", out_dir,
        ])
        assert r1.exit_code == 0

        # Generate evidence
        r2 = runner.invoke(cli, [
            "evidence-update",
            "--from-pr-snapshot", out_dir,
        ])
        assert r2.exit_code == 0

    def test_evidence_unverified_merged_shows_warning(self, runner, tmp_path):
        """Unverified 'merged' status must show UNVERIFIED warning in ledger entries."""
        snapshot_dir = self._create_snapshot(runner, tmp_path)
        runner.invoke(cli, [
            "evidence-update", "--from-pr-snapshot", snapshot_dir,
        ])
        proposed = (Path(snapshot_dir) / "proposed_ledger_entries.md").read_text(
            encoding="utf-8"
        )
        assert "UNVERIFIED" in proposed

    def test_evidence_verified_merged_shows_verified(self, runner, tmp_path):
        """gh_cli-verified 'merged' shows 'verified' in ledger entries."""
        snapshot_dir = self._create_snapshot(
            runner, tmp_path,
            verification_method="gh_cli",
            status_source="gh pr view 9 --json state",
        )
        runner.invoke(cli, [
            "evidence-update", "--from-pr-snapshot", snapshot_dir,
        ])
        proposed = (Path(snapshot_dir) / "proposed_ledger_entries.md").read_text(
            encoding="utf-8"
        )
        assert "verified: gh_cli" in proposed
        assert "UNVERIFIED" not in proposed

    def test_evidence_git_inferred_merged_shows_not_verified(self, runner, tmp_path):
        """git_inferred 'merged' must not present as verified fact."""
        snapshot_dir = self._create_snapshot(
            runner, tmp_path, verification_method="git_inferred",
        )
        runner.invoke(cli, [
            "evidence-update", "--from-pr-snapshot", snapshot_dir,
        ])
        proposed = (Path(snapshot_dir) / "proposed_ledger_entries.md").read_text(
            encoding="utf-8"
        )
        assert "git-inferred" in proposed
        assert "not verified" in proposed.lower()

    def test_evidence_includes_verification_field(
        self, runner, tmp_path, sample_summary_file
    ):
        """Founders-evidence-log entry must include verification method."""
        snapshot_dir = self._create_snapshot(
            runner, tmp_path, summary_file=sample_summary_file,
            verification_method="github_pr_api",
        )
        runner.invoke(cli, [
            "evidence-update", "--from-pr-snapshot", snapshot_dir,
        ])
        proposed = (Path(snapshot_dir) / "proposed_ledger_entries.md").read_text(
            encoding="utf-8"
        )
        assert "**Verification:**" in proposed
        assert "github_pr_api" in proposed
