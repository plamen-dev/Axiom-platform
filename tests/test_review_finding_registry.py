"""Tests for Review Finding Ingestion v1."""

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
def registry(tmp_artifacts: Path, tmp_path: Path):
    """Create a ReviewFindingRegistry with temp paths."""
    from axiom_core.review_finding_registry import ReviewFindingRegistry

    return ReviewFindingRegistry(
        db_path=str(tmp_path / "test.db"),
        artifacts_root=str(tmp_artifacts),
    )


# ---------------------------------------------------------------------------
# Test: Create finding
# ---------------------------------------------------------------------------


class TestCreateFinding:
    """Test creating review findings."""

    def test_creates_finding_with_defaults(self, registry):
        """Creates a finding with default category/severity."""
        finding = registry.create_finding(title="Test bug")

        assert finding.finding_id != ""
        assert finding.title == "Test bug"
        assert finding.category == "informational"
        assert finding.severity == "informational"
        assert finding.status == "open"

    def test_creates_finding_with_all_fields(self, registry):
        """Creates a finding with all fields specified."""
        finding = registry.create_finding(
            title="Path traversal in patch_run_id",
            description="patch_run_id from artifact data not validated",
            category="security",
            severity="high",
            source_pr="PR #63",
            source_file="src/axiom_core/pr_draft_generator.py",
            source_line="252",
            draft_id="draft-001",
            validation_run_id="val-001",
        )

        assert finding.category == "security"
        assert finding.severity == "high"
        assert finding.source_pr == "PR #63"
        assert finding.source_file == "src/axiom_core/pr_draft_generator.py"
        assert finding.draft_id == "draft-001"

    def test_empty_title_raises(self, registry):
        """Empty title raises ValueError."""
        with pytest.raises(ValueError, match="title is required"):
            registry.create_finding(title="")

    def test_invalid_category_raises(self, registry):
        """Invalid category raises ValueError."""
        with pytest.raises(ValueError, match="Invalid category"):
            registry.create_finding(title="test", category="bogus")

    def test_invalid_severity_raises(self, registry):
        """Invalid severity raises ValueError."""
        with pytest.raises(ValueError, match="Invalid severity"):
            registry.create_finding(title="test", severity="bogus")


# ---------------------------------------------------------------------------
# Test: Pattern detection
# ---------------------------------------------------------------------------


class TestPatternDetection:
    """Test automatic pattern detection from finding text."""

    def test_detects_path_traversal_pattern(self, registry):
        """Detects path traversal from title keywords."""
        finding = registry.create_finding(
            title="Path traversal in patch_run_id",
            category="security",
            severity="high",
        )
        assert finding.pattern == "path_traversal"

    def test_detects_command_injection_pattern(self, registry):
        """Detects command injection from description."""
        finding = registry.create_finding(
            title="Command injection via unsanitized args",
            category="security",
            severity="high",
        )
        assert finding.pattern == "command_injection"

    def test_detects_cwe_22_lowercase(self, registry):
        """CWE identifiers match after lowercasing."""
        finding = registry.create_finding(
            title="CWE-22 vulnerability in path handling",
            category="security",
            severity="high",
        )
        assert finding.pattern == "path_traversal"

    def test_detects_cwe_88_lowercase(self, registry):
        """CWE-88 matches after lowercasing."""
        finding = registry.create_finding(
            title="CWE-88 argument injection",
            category="security",
            severity="high",
        )
        assert finding.pattern == "command_injection"

    def test_detects_truthiness_bug(self, registry):
        """Detects truthiness bug pattern."""
        finding = registry.create_finding(
            title="Truthiness bug in status field",
            category="bug",
            severity="medium",
        )
        assert finding.pattern == "truthiness_bug"

    def test_detects_persistence_defect(self, registry):
        """Detects persistence defect pattern."""
        finding = registry.create_finding(
            title="Missing updated_at in save handler",
            category="bug",
            severity="medium",
        )
        assert finding.pattern == "persistence_defect"

    def test_defaults_to_other(self, registry):
        """Unrecognized text defaults to 'other'."""
        finding = registry.create_finding(
            title="Generic finding with no keywords",
            category="informational",
        )
        assert finding.pattern == "other"

    def test_explicit_pattern_overrides_detection(self, registry):
        """Explicitly specified pattern is used instead of detection."""
        finding = registry.create_finding(
            title="Some finding",
            pattern="stage_ordering",
        )
        assert finding.pattern == "stage_ordering"


# ---------------------------------------------------------------------------
# Test: Get and list findings
# ---------------------------------------------------------------------------


class TestGetAndListFindings:
    """Test retrieving and listing findings."""

    def test_get_finding_by_id(self, registry):
        """Get returns the specific finding."""
        created = registry.create_finding(title="Test finding")
        found = registry.get_finding(created.finding_id)

        assert found is not None
        assert found.finding_id == created.finding_id
        assert found.title == "Test finding"

    def test_get_unknown_returns_none(self, registry):
        """Unknown ID returns None."""
        assert registry.get_finding("nonexistent") is None

    def test_list_returns_all(self, registry):
        """List returns all findings."""
        registry.create_finding(title="Finding 1")
        registry.create_finding(title="Finding 2")

        findings = registry.list_findings()
        assert len(findings) == 2

    def test_list_filters_by_category(self, registry):
        """List filters by category."""
        registry.create_finding(title="Bug 1", category="bug", severity="high")
        registry.create_finding(title="Info 1")

        bugs = registry.list_findings(category="bug")
        assert len(bugs) == 1
        assert bugs[0].title == "Bug 1"

    def test_list_filters_by_severity(self, registry):
        """List filters by severity."""
        registry.create_finding(title="Crit 1", category="bug", severity="critical")
        registry.create_finding(title="Low 1", category="bug", severity="low")

        crits = registry.list_findings(severity="critical")
        assert len(crits) == 1
        assert crits[0].title == "Crit 1"

    def test_list_filters_by_pattern(self, registry):
        """List filters by pattern kind."""
        registry.create_finding(
            title="Path traversal issue", category="security", severity="high",
        )
        registry.create_finding(title="Minor style nit")

        traversals = registry.list_findings(pattern="path_traversal")
        assert len(traversals) == 1

    def test_list_empty_returns_empty(self, registry):
        """Empty registry returns empty list."""
        assert registry.list_findings() == []


# ---------------------------------------------------------------------------
# Test: Update finding
# ---------------------------------------------------------------------------


class TestUpdateFinding:
    """Test updating finding status and resolution."""

    def test_update_status(self, registry):
        """Updates status and creates history."""
        finding = registry.create_finding(title="Test finding")
        updated = registry.update_finding(
            finding.finding_id, status="resolved",
        )

        assert updated.status == "resolved"

    def test_update_resolution(self, registry):
        """Updates resolution text."""
        finding = registry.create_finding(title="Test finding")
        updated = registry.update_finding(
            finding.finding_id,
            status="resolved",
            resolution="Fixed in commit abc123",
        )

        assert updated.resolution == "Fixed in commit abc123"

    def test_invalid_status_raises(self, registry):
        """Invalid status raises ValueError."""
        finding = registry.create_finding(title="Test")
        with pytest.raises(ValueError, match="Invalid status"):
            registry.update_finding(finding.finding_id, status="bogus")

    def test_unknown_finding_raises(self, registry):
        """Unknown finding ID raises ValueError."""
        with pytest.raises(ValueError, match="Finding not found"):
            registry.update_finding("nonexistent", status="resolved")

    def test_no_changes_raises(self, registry):
        """No changes specified raises ValueError."""
        finding = registry.create_finding(title="Test")
        with pytest.raises(ValueError, match="No changes specified"):
            registry.update_finding(finding.finding_id)


# ---------------------------------------------------------------------------
# Test: Duplicate merge
# ---------------------------------------------------------------------------


class TestDuplicateMerge:
    """Test duplicate finding merge behavior."""

    def test_merge_marks_as_duplicate(self, registry):
        """Merge marks finding as duplicate."""
        f1 = registry.create_finding(title="Original")
        f2 = registry.create_finding(title="Duplicate")

        merged = registry.merge_duplicate(f2.finding_id, f1.finding_id)
        assert merged.status == "duplicate"
        assert f1.finding_id in merged.resolution

    def test_self_merge_raises(self, registry):
        """Cannot merge finding with itself."""
        f = registry.create_finding(title="Test")
        with pytest.raises(ValueError, match="duplicate of itself"):
            registry.merge_duplicate(f.finding_id, f.finding_id)

    def test_unknown_source_raises(self, registry):
        """Unknown source finding raises ValueError."""
        f = registry.create_finding(title="Target")
        with pytest.raises(ValueError, match="Finding not found"):
            registry.merge_duplicate("nonexistent", f.finding_id)

    def test_unknown_target_raises(self, registry):
        """Unknown target finding raises ValueError."""
        f = registry.create_finding(title="Source")
        with pytest.raises(ValueError, match="Target finding not found"):
            registry.merge_duplicate(f.finding_id, "nonexistent")


# ---------------------------------------------------------------------------
# Test: History
# ---------------------------------------------------------------------------


class TestHistory:
    """Test audit history preservation."""

    def test_creation_recorded(self, registry):
        """Creation event recorded in history."""
        finding = registry.create_finding(title="Test")
        history = registry.get_history(finding.finding_id)

        assert len(history) >= 1
        assert history[0].action == "created"

    def test_status_change_recorded(self, registry):
        """Status change recorded in history."""
        finding = registry.create_finding(title="Test")
        registry.update_finding(finding.finding_id, status="resolved")

        history = registry.get_history(finding.finding_id)
        status_changes = [h for h in history if h.action == "status_change"]
        assert len(status_changes) == 1
        assert status_changes[0].old_value == "open"
        assert status_changes[0].new_value == "resolved"

    def test_duplicate_merge_recorded(self, registry):
        """Duplicate merge recorded in history."""
        f1 = registry.create_finding(title="Original")
        f2 = registry.create_finding(title="Duplicate")
        registry.merge_duplicate(f2.finding_id, f1.finding_id)

        history = registry.get_history(f2.finding_id)
        merges = [h for h in history if h.action == "duplicate_merge"]
        assert len(merges) == 1
        assert merges[0].details.get("duplicate_of") == f1.finding_id


# ---------------------------------------------------------------------------
# Test: Patterns
# ---------------------------------------------------------------------------


class TestPatterns:
    """Test pattern persistence and listing."""

    def test_pattern_persisted_for_non_other(self, registry):
        """Non-other pattern is persisted."""
        registry.create_finding(
            title="Path traversal detected", category="security", severity="high",
        )
        patterns = registry.list_patterns()
        assert len(patterns) >= 1
        assert patterns[0].kind == "path_traversal"

    def test_no_pattern_for_other(self, registry):
        """'other' pattern is not persisted."""
        registry.create_finding(title="Minor style nit")
        patterns = registry.list_patterns()
        assert len(patterns) == 0

    def test_filter_by_kind(self, registry):
        """Filter patterns by kind."""
        registry.create_finding(
            title="Path traversal issue", category="security", severity="high",
        )
        registry.create_finding(
            title="Command injection issue via shlex",
            category="security", severity="high",
        )

        path_patterns = registry.list_patterns(kind="path_traversal")
        assert len(path_patterns) == 1

        cmd_patterns = registry.list_patterns(kind="command_injection")
        assert len(cmd_patterns) == 1


# ---------------------------------------------------------------------------
# Test: Evidence ingestion
# ---------------------------------------------------------------------------


class TestEvidenceIngestion:
    """Test ingestion from evidence bundles."""

    def test_ingest_from_source_dir(self, registry, tmp_path):
        """Ingests findings from JSON files in a directory."""
        source_dir = tmp_path / "review_input"
        source_dir.mkdir()

        findings_data = [
            {
                "title": "Bug: missing validation",
                "category": "bug",
                "severity": "high",
                "source_file": "src/foo.py",
            },
            {
                "title": "Style: inconsistent naming",
                "category": "style",
                "severity": "low",
            },
        ]
        (source_dir / "findings.json").write_text(
            json.dumps(findings_data), encoding="utf-8",
        )

        result = registry.ingest_from_evidence(source_dir=str(source_dir))
        assert len(result) == 2
        assert result[0].title == "Bug: missing validation"
        assert result[0].category == "bug"

    def test_ingest_writes_evidence_bundle(
        self, registry, tmp_path, tmp_artifacts,
    ):
        """Ingestion writes all 4 evidence files."""
        source_dir = tmp_path / "review_input"
        source_dir.mkdir()

        (source_dir / "f.json").write_text(
            json.dumps({"title": "Test finding", "category": "bug", "severity": "high"}),
            encoding="utf-8",
        )

        registry.ingest_from_evidence(source_dir=str(source_dir))

        runs_dir = tmp_artifacts / "review_findings"
        assert runs_dir.exists()
        run_dirs = list(runs_dir.iterdir())
        assert len(run_dirs) == 1

        run_dir = run_dirs[0]
        assert (run_dir / "review_request.json").exists()
        assert (run_dir / "review_result.json").exists()
        assert (run_dir / "review_summary.md").exists()
        assert (run_dir / "pass_fail.json").exists()

        # Validate JSON content
        result = json.loads(
            (run_dir / "review_result.json").read_text(encoding="utf-8"),
        )
        assert result["total_findings"] == 1
        assert "bug" in result["categories"]

        summary = (run_dir / "review_summary.md").read_text(encoding="utf-8")
        assert "# Review Finding Ingestion Summary" in summary

        pf = json.loads(
            (run_dir / "pass_fail.json").read_text(encoding="utf-8"),
        )
        assert pf["passed"] is True

    def test_ingest_skips_invalid_json(self, registry, tmp_path):
        """Skips files with invalid JSON."""
        source_dir = tmp_path / "review_input"
        source_dir.mkdir()

        (source_dir / "bad.json").write_text("not json", encoding="utf-8")
        (source_dir / "good.json").write_text(
            json.dumps({"title": "Valid finding", "category": "bug", "severity": "high"}),
            encoding="utf-8",
        )

        result = registry.ingest_from_evidence(source_dir=str(source_dir))
        assert len(result) == 1

    def test_ingest_empty_dir_no_bundle(self, registry, tmp_path, tmp_artifacts):
        """Empty source dir produces no findings and no evidence bundle."""
        source_dir = tmp_path / "empty_input"
        source_dir.mkdir()

        result = registry.ingest_from_evidence(source_dir=str(source_dir))
        assert len(result) == 0

        runs_dir = tmp_artifacts / "review_findings"
        assert not runs_dir.exists()


# ---------------------------------------------------------------------------
# Test: Path traversal rejection
# ---------------------------------------------------------------------------


class TestPathTraversal:
    """Test rejection of path traversal in IDs."""

    def test_finding_id_traversal_rejected(self, registry):
        """Path traversal in finding_id raises ValueError."""
        with pytest.raises(ValueError, match="must not contain"):
            registry.get_finding("../../etc/passwd")

    def test_draft_id_traversal_rejected(self, registry):
        """Path traversal in draft_id raises ValueError."""
        with pytest.raises(ValueError, match="must not contain"):
            registry.ingest_from_evidence(draft_id="../../etc/passwd")

    def test_duplicate_of_traversal_rejected(self, registry):
        """Path traversal in duplicate_of_id raises ValueError."""
        f = registry.create_finding(title="Test")
        with pytest.raises(ValueError, match="must not contain"):
            registry.merge_duplicate(f.finding_id, "../secrets")


# ---------------------------------------------------------------------------
# Test: Deterministic ordering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    """Test that listing is deterministic."""

    def test_findings_ordered_by_created_at(self, registry):
        """Findings are returned in creation order."""
        registry.create_finding(title="First")
        registry.create_finding(title="Second")
        registry.create_finding(title="Third")

        findings = registry.list_findings()
        titles = [f.title for f in findings]
        assert titles == ["First", "Second", "Third"]

    def test_history_ordered_by_timestamp(self, registry):
        """History entries are returned in chronological order."""
        finding = registry.create_finding(title="Test")
        registry.update_finding(finding.finding_id, status="acknowledged")
        registry.update_finding(finding.finding_id, status="resolved")

        history = registry.get_history(finding.finding_id)
        actions = [h.action for h in history]
        assert actions[0] == "created"


# ---------------------------------------------------------------------------
# Test: Serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    """Test that to_dict produces valid serializable output."""

    def test_finding_to_dict_is_json_serializable(self, registry):
        """Finding to_dict can be serialized to JSON."""
        finding = registry.create_finding(
            title="Test", category="bug", severity="high",
        )
        data = finding.to_dict()
        serialized = json.dumps(data, indent=2, default=str)
        parsed = json.loads(serialized)
        assert parsed["title"] == "Test"
        assert parsed["category"] == "bug"
