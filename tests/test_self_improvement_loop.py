"""Tests for SelfImprovementLoop v1 (PR #65)."""

from __future__ import annotations

import json
import os

import pytest


@pytest.fixture()
def tmp_db(tmp_path):
    """Provide a temporary database path."""
    db_path = str(tmp_path / "test.db")
    os.environ["AXIOM_DB_PATH"] = db_path
    os.environ["AXIOM_ARTIFACTS_ROOT"] = str(tmp_path / "artifacts")
    yield db_path
    os.environ.pop("AXIOM_DB_PATH", None)
    os.environ.pop("AXIOM_ARTIFACTS_ROOT", None)


@pytest.fixture()
def loop(tmp_db, tmp_path):
    """Provide a SelfImprovementLoop with a temp DB."""
    from axiom_core.self_improvement_loop import SelfImprovementLoop

    return SelfImprovementLoop(
        db_path=tmp_db,
        artifacts_root=str(tmp_path / "artifacts"),
    )


@pytest.fixture()
def populated_loop(tmp_db, tmp_path):
    """Provide a loop with review findings pre-loaded."""
    from axiom_core.review_finding_registry import ReviewFindingRegistry
    from axiom_core.self_improvement_loop import SelfImprovementLoop

    registry = ReviewFindingRegistry(
        db_path=tmp_db,
        artifacts_root=str(tmp_path / "artifacts"),
    )
    # Create findings with known patterns
    registry.create_finding(
        title="Path traversal in patch_run_id",
        category="security",
        severity="high",
        source_file="src/axiom_core/runner.py",
    )
    registry.create_finding(
        title="CWE-22 vulnerability in evidence loader",
        category="security",
        severity="critical",
        source_file="src/axiom_core/evidence.py",
    )
    registry.create_finding(
        title="Command injection via unsanitized args",
        category="security",
        severity="high",
    )
    registry.create_finding(
        title="Command injection in CLI builder",
        category="security",
        severity="high",
    )
    registry.create_finding(
        title="Missing updated_at in save handler",
        category="bug",
        severity="medium",
    )
    registry.create_finding(
        title="Truthiness bug in status field",
        category="bug",
        severity="high",
    )
    registry.create_finding(
        title="Truthiness bug in approval check",
        category="bug",
        severity="high",
    )
    registry.create_finding(
        title="Minor style nit",
        category="style",
        severity="low",
    )

    return SelfImprovementLoop(
        db_path=tmp_db,
        artifacts_root=str(tmp_path / "artifacts"),
    )


# ---------------------------------------------------------------------------
# Test: Analysis loop
# ---------------------------------------------------------------------------


class TestAnalysisLoop:
    """Test the core analysis loop."""

    def test_run_analysis_empty_db(self, loop):
        """Analysis on empty DB produces zero candidates."""
        result = loop.run_analysis()
        assert result["total_findings_analyzed"] == 0
        assert result["patterns_detected"] == 0
        assert result["candidates_generated"] == 0
        assert result["patterns"] == []
        assert result["candidates"] == []

    def test_run_analysis_with_findings(self, populated_loop, tmp_path):
        """Analysis on populated DB detects patterns and generates candidates."""
        result = populated_loop.run_analysis()
        assert result["total_findings_analyzed"] == 8
        assert result["patterns_detected"] >= 3
        assert result["candidates_generated"] >= 3

    def test_run_analysis_deterministic(self, populated_loop):
        """Two runs produce structurally identical results (different run_id/timestamps)."""
        result1 = populated_loop.run_analysis()
        result2 = populated_loop.run_analysis()
        # Same number of patterns/candidates
        assert result1["total_findings_analyzed"] == result2["total_findings_analyzed"]
        # Pattern kinds should be the same
        kinds1 = sorted(p["pattern_kind"] for p in result1["patterns"])
        kinds2 = sorted(p["pattern_kind"] for p in result2["patterns"])
        assert kinds1 == kinds2


# ---------------------------------------------------------------------------
# Test: Pattern detection
# ---------------------------------------------------------------------------


class TestPatternDetection:
    """Test pattern detection from findings."""

    def test_detects_path_traversal_pattern(self, populated_loop):
        """Detects path_traversal as a repeated pattern."""
        result = populated_loop.run_analysis()
        pattern_kinds = {p["pattern_kind"] for p in result["patterns"]}
        assert "path_traversal" in pattern_kinds

    def test_path_traversal_count(self, populated_loop):
        """Path traversal has exactly 2 occurrences."""
        result = populated_loop.run_analysis()
        pt = [p for p in result["patterns"] if p["pattern_kind"] == "path_traversal"]
        assert len(pt) == 1
        assert pt[0]["occurrence_count"] == 2

    def test_detects_command_injection(self, populated_loop):
        """Detects command_injection pattern."""
        result = populated_loop.run_analysis()
        pattern_kinds = {p["pattern_kind"] for p in result["patterns"]}
        assert "command_injection" in pattern_kinds

    def test_other_pattern_filtered_if_few(self, populated_loop):
        """'other' pattern requires 3+ occurrences to appear."""
        result = populated_loop.run_analysis()
        other_patterns = [
            p for p in result["patterns"] if p["pattern_kind"] == "other"
        ]
        # Only 1 'other' finding (style nit) so should not appear
        assert len(other_patterns) == 0

    def test_single_occurrence_patterns_excluded(self, tmp_db, tmp_path):
        """Patterns with only 1 occurrence are excluded (need 2+)."""
        from axiom_core.review_finding_registry import ReviewFindingRegistry
        from axiom_core.self_improvement_loop import SelfImprovementLoop

        registry = ReviewFindingRegistry(
            db_path=tmp_db,
            artifacts_root=str(tmp_path / "artifacts"),
        )
        registry.create_finding(
            title="Single persistence defect",
            category="bug",
            severity="high",
        )
        loop = SelfImprovementLoop(
            db_path=tmp_db,
            artifacts_root=str(tmp_path / "artifacts"),
        )
        result = loop.run_analysis()
        pattern_kinds = {p["pattern_kind"] for p in result["patterns"]}
        assert "persistence_defect" not in pattern_kinds


# ---------------------------------------------------------------------------
# Test: Candidate generation
# ---------------------------------------------------------------------------


class TestCandidateGeneration:
    """Test improvement candidate generation."""

    def test_generates_security_knowledge_update(self, populated_loop):
        """Security patterns trigger a knowledge update candidate."""
        result = populated_loop.run_analysis()
        knowledge_candidates = [
            c for c in result["candidates"]
            if c["category"] == "knowledge_update"
        ]
        assert len(knowledge_candidates) >= 1
        titles = [c["title"] for c in knowledge_candidates]
        assert any("security" in t.lower() for t in titles)

    def test_generates_missing_test_candidate(self, populated_loop):
        """Bug/security findings trigger a missing test candidate."""
        result = populated_loop.run_analysis()
        test_candidates = [
            c for c in result["candidates"]
            if c["category"] == "missing_test"
        ]
        assert len(test_candidates) >= 1

    def test_candidate_has_required_fields(self, populated_loop):
        """Every candidate has all required fields."""
        result = populated_loop.run_analysis()
        for c in result["candidates"]:
            assert "candidate_id" in c
            assert "title" in c
            assert "category" in c
            assert "priority" in c
            assert "status" in c
            assert c["status"] == "proposed"

    def test_candidate_priority_mapping(self, populated_loop):
        """Security patterns get critical priority."""
        result = populated_loop.run_analysis()
        security_candidates = [
            c for c in result["candidates"]
            if "path traversal" in c.get("title", "").lower()
        ]
        for c in security_candidates:
            assert c["priority"] == "critical"

    def test_target_files_populated(self, populated_loop):
        """Candidates from findings with source_file have target_files."""
        result = populated_loop.run_analysis()
        pt_candidates = [
            c for c in result["candidates"]
            if "path traversal" in c.get("title", "").lower()
        ]
        if pt_candidates:
            assert len(pt_candidates[0]["target_files"]) >= 1

    def test_recommendation_populated(self, populated_loop):
        """Pattern-based candidates have recommendations."""
        result = populated_loop.run_analysis()
        for c in result["candidates"]:
            if c["category"] in ("repeated_bug_class", "missing_test"):
                assert c["recommendation"], f"Missing recommendation: {c['title']}"


# ---------------------------------------------------------------------------
# Test: Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    """Test candidate and pattern persistence."""

    def test_candidates_persisted(self, populated_loop):
        """Candidates are persisted and retrievable."""
        populated_loop.run_analysis()
        candidates = populated_loop.list_candidates()
        assert len(candidates) >= 3

    def test_candidates_filter_by_category(self, populated_loop):
        """Candidates can be filtered by category."""
        populated_loop.run_analysis()
        knowledge = populated_loop.list_candidates(category="knowledge_update")
        all_candidates = populated_loop.list_candidates()
        assert len(knowledge) < len(all_candidates)
        for c in knowledge:
            assert c.category == "knowledge_update"

    def test_candidates_filter_by_priority(self, populated_loop):
        """Candidates can be filtered by priority."""
        populated_loop.run_analysis()
        critical = populated_loop.list_candidates(priority="critical")
        for c in critical:
            assert c.priority == "critical"

    def test_get_candidate_by_id(self, populated_loop):
        """Can retrieve a specific candidate by ID."""
        populated_loop.run_analysis()
        candidates = populated_loop.list_candidates()
        first = candidates[0]
        found = populated_loop.get_candidate(first.candidate_id)
        assert found is not None
        assert found.candidate_id == first.candidate_id
        assert found.title == first.title

    def test_get_unknown_candidate_returns_none(self, populated_loop):
        """Unknown candidate ID returns None."""
        assert populated_loop.get_candidate("nonexistent") is None

    def test_patterns_persisted(self, populated_loop):
        """Patterns are persisted and retrievable."""
        populated_loop.run_analysis()
        patterns = populated_loop.list_patterns()
        assert len(patterns) >= 3


# ---------------------------------------------------------------------------
# Test: Evidence bundle
# ---------------------------------------------------------------------------


class TestEvidenceBundle:
    """Test evidence artifact writing."""

    def test_evidence_files_created(self, populated_loop, tmp_path):
        """All 4 evidence files are written."""
        result = populated_loop.run_analysis()
        run_id = result["run_id"]
        run_dir = tmp_path / "artifacts" / "self_improvement" / run_id
        assert run_dir.exists()
        assert (run_dir / "improvement_request.json").exists()
        assert (run_dir / "improvement_result.json").exists()
        assert (run_dir / "improvement_summary.md").exists()
        assert (run_dir / "pass_fail.json").exists()

    def test_evidence_request_valid(self, populated_loop, tmp_path):
        """improvement_request.json is valid."""
        result = populated_loop.run_analysis()
        run_id = result["run_id"]
        req = json.loads(
            (tmp_path / "artifacts" / "self_improvement" / run_id / "improvement_request.json").read_text()
        )
        assert req["run_id"] == run_id
        assert req["analysis_type"] == "self_improvement_v1"

    def test_evidence_pass_fail_valid(self, populated_loop, tmp_path):
        """pass_fail.json has passed=True."""
        result = populated_loop.run_analysis()
        run_id = result["run_id"]
        pf = json.loads(
            (tmp_path / "artifacts" / "self_improvement" / run_id / "pass_fail.json").read_text()
        )
        assert pf["passed"] is True
        assert pf["run_id"] == run_id

    def test_evidence_summary_content(self, populated_loop, tmp_path):
        """improvement_summary.md has correct header."""
        result = populated_loop.run_analysis()
        run_id = result["run_id"]
        summary = (
            tmp_path / "artifacts" / "self_improvement" / run_id / "improvement_summary.md"
        ).read_text()
        assert "# Self-Improvement Analysis Summary" in summary
        assert run_id in summary


# ---------------------------------------------------------------------------
# Test: Path traversal rejection
# ---------------------------------------------------------------------------


class TestPathTraversalRejection:
    """Test ID validation."""

    def test_candidate_id_traversal(self, loop):
        """Path traversal in candidate_id is rejected."""
        with pytest.raises(ValueError, match="must not contain"):
            loop.get_candidate("../../etc/passwd")

    def test_candidate_id_slash(self, loop):
        """Forward slash in candidate_id is rejected."""
        with pytest.raises(ValueError, match="must not contain"):
            loop.get_candidate("foo/bar")

    def test_candidate_id_backslash(self, loop):
        """Backslash in candidate_id is rejected."""
        with pytest.raises(ValueError, match="must not contain"):
            loop.get_candidate("foo\\bar")


# ---------------------------------------------------------------------------
# Test: Summary
# ---------------------------------------------------------------------------


class TestSummary:
    """Test analysis summary content."""

    def test_summary_has_pattern_breakdown(self, populated_loop):
        """Summary includes patterns_by_kind."""
        result = populated_loop.run_analysis()
        summary = result["summary"]
        assert "patterns_by_kind" in summary
        assert "path_traversal" in summary["patterns_by_kind"]

    def test_summary_has_candidate_breakdown(self, populated_loop):
        """Summary includes candidates_by_category and candidates_by_priority."""
        result = populated_loop.run_analysis()
        summary = result["summary"]
        assert "candidates_by_category" in summary
        assert "candidates_by_priority" in summary

    def test_summary_has_top_recommendation(self, populated_loop):
        """Summary includes top_recommendation."""
        result = populated_loop.run_analysis()
        summary = result["summary"]
        assert summary.get("top_recommendation"), "Missing top recommendation"


# ---------------------------------------------------------------------------
# Test: Deterministic ordering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    """Test ordering stability."""

    def test_candidates_ordered_by_creation(self, populated_loop):
        """Candidates are returned in creation order."""
        populated_loop.run_analysis()
        candidates = populated_loop.list_candidates()
        dates = [c.created_at for c in candidates]
        assert dates == sorted(dates)

    def test_patterns_ordered_by_creation(self, populated_loop):
        """Patterns are returned in creation order."""
        populated_loop.run_analysis()
        patterns = populated_loop.list_patterns()
        dates = [p.created_at for p in patterns]
        assert dates == sorted(dates)
