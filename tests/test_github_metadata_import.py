"""Comprehensive tests for GitHub Metadata Import Framework v1."""

from __future__ import annotations

import csv
import io
import json
import tempfile

import pytest
from axiom_core.github_metadata_import import (
    SCHEMA_VERSION,
    GitHubCommitMetadata,
    GitHubFileChangeMetadata,
    GitHubLabelMetadata,
    GitHubMetadataImport,
    GitHubMetadataImportEngine,
    GitHubMetadataImportEvidence,
    GitHubMetadataImportReport,
    GitHubMetadataImportStatus,
    GitHubPRMetadata,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tmp_engine() -> GitHubMetadataImportEngine:
    tmp = tempfile.mkdtemp()
    return GitHubMetadataImportEngine(artifacts_root=tmp)


def _metadata(**overrides) -> dict:
    data = {
        "global_capability_number": 124,
        "pr": {
            "repository_owner": "plamen-dev",
            "repository_name": "Axiom-platform",
            "repository_pr_number": 13,
            "repository_pr_url": (
                "https://github.com/plamen-dev/Axiom-platform/pull/13"
            ),
            "title": "PR #124 — GitHub Metadata Import Framework v1",
            "description": "Ingest GitHub metadata deterministically.",
            "author": "devin",
            "branch_name": "devin/github-metadata-import",
            "labels": [
                {"name": "framework", "color": "blue"},
                {"name": "automation", "color": "green"},
            ],
            "status": "merged",
            "merge_commit_sha": "abc123",
            "created_at": "2026-06-20T10:00:00+00:00",
            "updated_at": "2026-06-21T10:00:00+00:00",
            "merged_at": "2026-06-22T10:00:00+00:00",
        },
        "commits": [
            {
                "commit_sha": "ccc333",
                "author": "devin",
                "message": "third",
                "timestamp": "2026-06-20T12:00:00+00:00",
            },
            {
                "commit_sha": "aaa111",
                "author": "devin",
                "message": "first",
                "timestamp": "2026-06-20T10:30:00+00:00",
            },
            {
                "commit_sha": "bbb222",
                "author": "devin",
                "message": "second",
                "timestamp": "2026-06-20T11:00:00+00:00",
            },
        ],
        "files": [
            {
                "path": "src/zeta.py",
                "status": "modified",
                "additions": 5,
                "deletions": 2,
            },
            {
                "path": "src/alpha.py",
                "status": "added",
                "additions": 100,
                "deletions": 0,
            },
        ],
        "raw_metadata": {"source": "fixture", "nested": {"k": "v"}},
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_label_round_trip(self) -> None:
        label = GitHubLabelMetadata(
            name="framework", color="blue", description="x"
        )
        assert GitHubLabelMetadata.from_dict(label.to_dict()) == label

    def test_commit_round_trip(self) -> None:
        commit = GitHubCommitMetadata(
            commit_sha="abc", author="d", message="m", timestamp="t"
        )
        assert GitHubCommitMetadata.from_dict(commit.to_dict()) == commit

    def test_file_round_trip(self) -> None:
        change = GitHubFileChangeMetadata(
            path="a.py", status="added", additions=1, deletions=2
        )
        assert GitHubFileChangeMetadata.from_dict(change.to_dict()) == change

    def test_pr_round_trip(self) -> None:
        pr = GitHubPRMetadata.from_dict(_metadata()["pr"])
        assert GitHubPRMetadata.from_dict(pr.to_dict()) == pr

    def test_import_defaults(self) -> None:
        imp = GitHubMetadataImport()
        assert imp.import_id
        assert imp.created_at
        assert imp.schema_version == SCHEMA_VERSION

    def test_report_defaults(self) -> None:
        report = GitHubMetadataImportReport()
        assert report.report_id
        assert report.created_at

    def test_evidence_defaults(self) -> None:
        ev = GitHubMetadataImportEvidence()
        assert ev.evidence_id
        assert ev.created_at

    def test_all_import_statuses(self) -> None:
        assert {s.value for s in GitHubMetadataImportStatus} == {
            "imported",
            "partial_import",
            "failed",
        }


# ---------------------------------------------------------------------------
# Import core
# ---------------------------------------------------------------------------


class TestImport:
    def test_import_success(self) -> None:
        engine = _tmp_engine()
        report = engine.import_metadata(metadata=_metadata())
        assert report["status"] == "imported"
        assert report["repository"] == "plamen-dev/Axiom-platform"
        assert report["repository_pr_number"] == 13
        assert report["global_capability_number"] == 124
        assert report["commit_count"] == 3
        assert report["file_count"] == 2
        assert report["label_count"] == 2
        assert report["total_additions"] == 105
        assert report["total_deletions"] == 2

    def test_commits_sorted_deterministically(self) -> None:
        engine = _tmp_engine()
        report = engine.import_metadata(metadata=_metadata())
        commits = report["metadata_import"]["commits"]
        shas = [c["commit_sha"] for c in commits]
        # Sorted by (timestamp, commit_sha): aaa111, bbb222, ccc333.
        assert shas == ["aaa111", "bbb222", "ccc333"]

    def test_files_sorted_deterministically(self) -> None:
        engine = _tmp_engine()
        report = engine.import_metadata(metadata=_metadata())
        files = report["metadata_import"]["files"]
        paths = [f["path"] for f in files]
        assert paths == ["src/alpha.py", "src/zeta.py"]

    def test_labels_sorted_deterministically(self) -> None:
        engine = _tmp_engine()
        report = engine.import_metadata(metadata=_metadata())
        labels = report["metadata_import"]["labels"]
        names = [label["name"] for label in labels]
        assert names == ["automation", "framework"]

    def test_raw_payload_preserved(self) -> None:
        engine = _tmp_engine()
        report = engine.import_metadata(metadata=_metadata())
        raw = report["metadata_import"]["raw_metadata"]
        assert raw == {"source": "fixture", "nested": {"k": "v"}}

    def test_schema_version_preserved(self) -> None:
        engine = _tmp_engine()
        report = engine.import_metadata(metadata=_metadata())
        assert report["schema_version"] == SCHEMA_VERSION
        assert report["metadata_import"]["schema_version"] == SCHEMA_VERSION

    def test_deterministic_output_across_runs(self) -> None:
        report_a = _tmp_engine().import_metadata(metadata=_metadata())
        report_b = _tmp_engine().import_metadata(metadata=_metadata())
        # Ordering and counts are stable regardless of run-specific ids.
        assert [c["commit_sha"] for c in report_a["metadata_import"]["commits"]] == [
            c["commit_sha"] for c in report_b["metadata_import"]["commits"]
        ]
        assert report_a["timeline_event_type_counts"] == (
            report_b["timeline_event_type_counts"]
        )


# ---------------------------------------------------------------------------
# Integration: registry entry + timeline events
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_registry_entry_populated(self) -> None:
        engine = _tmp_engine()
        report = engine.import_metadata(metadata=_metadata())
        entry = report["registry_entry"]
        assert entry["global_capability_number"] == 124
        assert entry["capability_name"].startswith("PR #124")
        assert entry["status"] == "merged"
        assert entry["repository"]["repository_owner"] == "plamen-dev"
        assert entry["repository"]["repository_pr_number"] == 13
        assert entry["repository"]["merge_sha"] == "abc123"
        assert entry["worker"]["worker_id"] == "devin"
        assert entry["affected_files"] == ["src/alpha.py", "src/zeta.py"]
        assert entry["raw_metadata"]["source"] == "fixture"

    def test_registry_status_mapping_open(self) -> None:
        md = _metadata()
        md["pr"]["status"] = "open"
        md["pr"]["merged_at"] = ""
        report = _tmp_engine().import_metadata(metadata=md)
        assert report["registry_entry"]["status"] == "open"

    def test_timeline_events_created(self) -> None:
        engine = _tmp_engine()
        report = engine.import_metadata(metadata=_metadata())
        events = report["timeline_events"]
        types = [e["event_type"] for e in events]
        assert types == ["pr_created", "pr_ready", "pr_merged"]
        assert report["timeline_event_type_counts"] == {
            "pr_created": 1,
            "pr_ready": 1,
            "pr_merged": 1,
        }

    def test_timeline_events_skip_missing_merge(self) -> None:
        md = _metadata()
        md["pr"]["status"] = "open"
        md["pr"]["merged_at"] = ""
        report = _tmp_engine().import_metadata(metadata=md)
        types = [e["event_type"] for e in report["timeline_events"]]
        assert types == ["pr_created", "pr_ready"]
        assert "pr_merged" not in types

    def test_timeline_events_reference_pr(self) -> None:
        report = _tmp_engine().import_metadata(metadata=_metadata())
        first = report["timeline_events"][0]
        ref = first["references"][0]
        assert ref["reference_type"] == "pr_url"
        assert ref["target"].endswith("/pull/13")


# ---------------------------------------------------------------------------
# Manual overrides
# ---------------------------------------------------------------------------


class TestManualOverride:
    def test_repo_override(self) -> None:
        md = _metadata()
        report = _tmp_engine().import_metadata(
            metadata=md, repo="other-owner/other-repo"
        )
        assert report["repository"] == "other-owner/other-repo"

    def test_pr_number_override(self) -> None:
        report = _tmp_engine().import_metadata(metadata=_metadata(), pr_number=99)
        assert report["repository_pr_number"] == 99

    def test_global_number_override(self) -> None:
        report = _tmp_engine().import_metadata(
            metadata=_metadata(), global_capability_number=200
        )
        assert report["global_capability_number"] == 200

    def test_bad_repo_override_raises(self) -> None:
        with pytest.raises(ValueError, match="owner/name"):
            _tmp_engine().import_metadata(metadata=_metadata(), repo="bad")


# ---------------------------------------------------------------------------
# Duplicate + malformed handling
# ---------------------------------------------------------------------------


class TestDuplicateAndMalformed:
    def test_duplicate_import_rejected(self) -> None:
        engine = _tmp_engine()
        engine.import_metadata(metadata=_metadata())
        with pytest.raises(ValueError, match="Duplicate import"):
            engine.import_metadata(metadata=_metadata())

    def test_distinct_pr_not_rejected(self) -> None:
        engine = _tmp_engine()
        engine.import_metadata(metadata=_metadata())
        report = engine.import_metadata(metadata=_metadata(), pr_number=14)
        assert report["repository_pr_number"] == 14

    def test_missing_pr_identity_raises(self) -> None:
        md = _metadata()
        md["pr"]["repository_owner"] = ""
        with pytest.raises(ValueError, match="Malformed PR metadata"):
            _tmp_engine().import_metadata(metadata=md)

    def test_missing_pr_number_raises(self) -> None:
        md = _metadata()
        md["pr"]["repository_pr_number"] = 0
        with pytest.raises(ValueError, match="repository_pr_number"):
            _tmp_engine().import_metadata(metadata=md)

    def test_malformed_subrecords_partial_import(self) -> None:
        md = _metadata()
        md["commits"].append({"author": "x", "message": "no sha"})
        md["files"].append({"status": "added", "additions": 1})
        report = _tmp_engine().import_metadata(metadata=md)
        assert report["status"] == "partial_import"
        skipped = report["metadata_import"]["skipped"]
        assert any("commit" in s for s in skipped)
        assert any("file" in s for s in skipped)
        # Valid records are still imported.
        assert report["commit_count"] == 3
        assert report["file_count"] == 2

    def test_malformed_label_skipped(self) -> None:
        md = _metadata()
        md["pr"]["labels"].append({"color": "red"})
        report = _tmp_engine().import_metadata(metadata=md)
        assert report["status"] == "partial_import"
        assert report["label_count"] == 2


# ---------------------------------------------------------------------------
# Retrieval + export
# ---------------------------------------------------------------------------


class TestRetrievalExport:
    def test_show_round_trips(self) -> None:
        engine = _tmp_engine()
        report = engine.import_metadata(metadata=_metadata())
        loaded = engine.get_report(report["report_id"])
        assert loaded == report

    def test_list_reports(self) -> None:
        engine = _tmp_engine()
        engine.import_metadata(metadata=_metadata())
        engine.import_metadata(metadata=_metadata(), pr_number=14)
        reports = engine.list_reports()
        assert len(reports) == 2

    def test_show_missing_returns_none(self) -> None:
        engine = _tmp_engine()
        assert engine.get_report("nonexistent") is None

    def test_export_json(self) -> None:
        engine = _tmp_engine()
        report = engine.import_metadata(metadata=_metadata())
        out = engine.export_report(report["report_id"], fmt="json")
        parsed = json.loads(out)
        assert parsed["report_id"] == report["report_id"]

    def test_export_markdown(self) -> None:
        engine = _tmp_engine()
        report = engine.import_metadata(metadata=_metadata())
        out = engine.export_report(report["report_id"], fmt="markdown")
        assert "# GitHub Metadata Import" in out
        assert "## Summary" in out
        assert "## Timeline Event Counts" in out
        assert "## Commits" in out
        assert "## Changed Files" in out
        assert "[framework]" in out

    def test_export_csv(self) -> None:
        engine = _tmp_engine()
        report = engine.import_metadata(metadata=_metadata())
        out = engine.export_report(report["report_id"], fmt="csv")
        rows = list(csv.reader(io.StringIO(out)))
        assert rows[0][0] == "path"
        # header + 2 file rows
        assert len(rows) == 3
        assert rows[1][0] == "src/alpha.py"

    def test_export_invalid_format(self) -> None:
        engine = _tmp_engine()
        report = engine.import_metadata(metadata=_metadata())
        with pytest.raises(ValueError, match="Invalid export format"):
            engine.export_report(report["report_id"], fmt="xml")

    def test_export_missing_report(self) -> None:
        engine = _tmp_engine()
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent", fmt="json")


# ---------------------------------------------------------------------------
# Evidence bundle + pass/fail
# ---------------------------------------------------------------------------


class TestEvidence:
    def test_evidence_bundle_written(self) -> None:
        engine = _tmp_engine()
        report = engine.import_metadata(metadata=_metadata())
        report_dir = engine._safe_path(report["report_id"])
        for name in (
            "report.json",
            "github_import_request.json",
            "github_import_result.json",
            "github_import_summary.md",
            "github_import_files.csv",
            "pass_fail.json",
        ):
            assert (report_dir / name).exists(), name

    def test_pass_fail_passed(self) -> None:
        engine = _tmp_engine()
        report = engine.import_metadata(metadata=_metadata())
        report_dir = engine._safe_path(report["report_id"])
        pass_fail = json.loads(
            (report_dir / "pass_fail.json").read_text(encoding="utf-8")
        )
        assert pass_fail["passed"] is True
        assert pass_fail["import_status"] == "imported"
        assert pass_fail["skipped_count"] == 0

    def test_pass_fail_partial_fails(self) -> None:
        md = _metadata()
        md["commits"].append({"author": "x", "message": "no sha"})
        engine = _tmp_engine()
        report = engine.import_metadata(metadata=md)
        report_dir = engine._safe_path(report["report_id"])
        pass_fail = json.loads(
            (report_dir / "pass_fail.json").read_text(encoding="utf-8")
        )
        assert pass_fail["passed"] is False
        assert pass_fail["import_status"] == "partial_import"


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


class TestPathSafety:
    @pytest.mark.parametrize("bad", ["../escape", "a/b", "..", "a\\b"])
    def test_show_rejects_unsafe_ids(self, bad: str) -> None:
        engine = _tmp_engine()
        with pytest.raises(ValueError):
            engine.get_report(bad)

    @pytest.mark.parametrize("bad", ["../escape", "a/b", ".."])
    def test_export_rejects_unsafe_ids(self, bad: str) -> None:
        engine = _tmp_engine()
        with pytest.raises(ValueError):
            engine.export_report(bad, fmt="json")

# ---------------------------------------------------------------------------
# Backfill + sequence ledger
# ---------------------------------------------------------------------------


def _write_payload(directory, pr_number: int, title: str, **pr_overrides):
    payload = _metadata()
    payload.pop("global_capability_number", None)
    payload["pr"]["repository_pr_number"] = pr_number
    payload["pr"]["title"] = title
    payload["pr"].update(pr_overrides)
    path = directory / f"pr-{pr_number:04d}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestBackfill:
    def test_canonical_number_from_title(self) -> None:
        from axiom_core.github_metadata_import import (
            canonical_number_from_title,
        )

        assert canonical_number_from_title("PR #112 — Framework v1") == 112
        assert (
            canonical_number_from_title("Integration PR #143 — Loop v1")
            == 143
        )
        assert canonical_number_from_title("Fix CSV export bug") == 0
        assert canonical_number_from_title("") == 0

    def test_backfill_imports_and_derives_canonical(self, tmp_path) -> None:
        engine = GitHubMetadataImportEngine(
            artifacts_root=str(tmp_path / "artifacts")
        )
        payload_dir = tmp_path / "payloads"
        payload_dir.mkdir()
        _write_payload(payload_dir, 1, "PR #112 — Execution Outcome v1")
        _write_payload(payload_dir, 2, "PR #113 — Failure Classification v1")
        _write_payload(payload_dir, 3, "Fix CSV export bug")

        summary = engine.backfill(payload_dir)
        assert summary["imported_count"] == 3
        assert summary["failed_count"] == 0
        assert summary["canonical_gaps"] == [3]
        by_pr = {
            r["repository_pr_number"]: r["global_capability_number"]
            for r in summary["imported"]
        }
        assert by_pr == {1: 112, 2: 113, 3: 0}

    def test_backfill_is_rerunnable_duplicates_skipped(
        self, tmp_path
    ) -> None:
        engine = GitHubMetadataImportEngine(
            artifacts_root=str(tmp_path / "artifacts")
        )
        payload_dir = tmp_path / "payloads"
        payload_dir.mkdir()
        _write_payload(payload_dir, 1, "PR #112 — Execution Outcome v1")

        first = engine.backfill(payload_dir)
        second = engine.backfill(payload_dir)
        assert first["imported_count"] == 1
        assert second["imported_count"] == 0
        assert second["skipped_duplicates"] == [1]

    def test_backfill_records_malformed_payload_as_failed(
        self, tmp_path
    ) -> None:
        engine = GitHubMetadataImportEngine(
            artifacts_root=str(tmp_path / "artifacts")
        )
        payload_dir = tmp_path / "payloads"
        payload_dir.mkdir()
        (payload_dir / "bad.json").write_text("{not json", encoding="utf-8")

        summary = engine.backfill(payload_dir)
        assert summary["imported_count"] == 0
        assert summary["failed_count"] == 1
        assert summary["failed"][0]["file"] == "bad.json"

    def test_backfill_missing_dir_rejected(self, tmp_path) -> None:
        engine = GitHubMetadataImportEngine(
            artifacts_root=str(tmp_path / "artifacts")
        )
        with pytest.raises(ValueError):
            engine.backfill(tmp_path / "nope")

    def test_sequence_ledger_sorted_with_gaps(self, tmp_path) -> None:
        engine = GitHubMetadataImportEngine(
            artifacts_root=str(tmp_path / "artifacts")
        )
        payload_dir = tmp_path / "payloads"
        payload_dir.mkdir()
        _write_payload(payload_dir, 2, "PR #113 — Failure Classification v1")
        _write_payload(payload_dir, 1, "PR #112 — Execution Outcome v1")
        _write_payload(payload_dir, 3, "Fix CSV export bug")
        engine.backfill(payload_dir)

        ledger = engine.generate_sequence_ledger()
        lines = [line for line in ledger.splitlines() if line.startswith("|")]
        # header + separator + 3 rows, sorted by GitHub PR number
        assert len(lines) == 5
        assert "| 112 | #1 |" in lines[2]
        assert "| 113 | #2 |" in lines[3]
        assert "| — (gap) | #3 |" in lines[4]
        assert "Canonical gaps" in ledger
