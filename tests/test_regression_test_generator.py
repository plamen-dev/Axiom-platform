"""Tests for Regression Test Generator v1 (PR #67).

Covers: bug class detection, test intent mapping, candidate generation,
pattern detection, persistence, evidence bundles, path traversal, and
deterministic ordering.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.regression_test_generator import (
    BugClass,
    BugPattern,
    CandidatePriority,
    FailureOrigin,
    RegressionTestCandidate,
    RegressionTestGenerator,
    TestIntent,
    TestIntentKind,
)


@pytest.fixture()
def generator(tmp_path):
    """Create a RegressionTestGenerator with temp DB and artifacts."""
    db_path = str(tmp_path / "test.db")
    artifacts = str(tmp_path / "artifacts")
    return RegressionTestGenerator(db_path=db_path, artifacts_root=artifacts)


@pytest.fixture()
def generator_with_findings(tmp_path):
    """Generator seeded with review findings in the DB."""
    db_path = str(tmp_path / "test.db")
    artifacts = str(tmp_path / "artifacts")

    from axiom_core.review_finding_registry import ReviewFindingRegistry
    registry = ReviewFindingRegistry(db_path=db_path)

    # Seed findings covering multiple bug classes
    registry.create_finding(
        title="Truthiness bug in validation",
        description="Empty string passes truthy check causing silent failure",
        category="bug",
        severity="high",
        source_file="src/axiom_core/validator.py",
    )
    registry.create_finding(
        title="Truthiness check missing for None",
        description="Function accepts None as valid when truthiness not checked",
        category="bug",
        severity="medium",
        source_file="src/axiom_core/processor.py",
    )
    registry.create_finding(
        title="Path traversal in run ID",
        description="CWE-22: run_id allows directory traversal via ../",
        category="security",
        severity="critical",
        source_file="src/axiom_core/runner/executor.py",
    )
    registry.create_finding(
        title="Enum serialization fails on round-trip",
        description="Enum.value not preserved when serializing to JSON",
        category="bug",
        severity="medium",
        source_file="src/axiom_core/models.py",
    )
    registry.create_finding(
        title="Misleading CLI exit code",
        description="CLI returns exit code 0 on partial failure",
        category="bug",
        severity="medium",
        source_file="src/axiom_cli/main.py",
    )

    return RegressionTestGenerator(db_path=db_path, artifacts_root=artifacts)


# ---------------------------------------------------------------------------
# Test: Bug class detection
# ---------------------------------------------------------------------------


class TestBugClassDetection:
    """Verify bug class auto-detection from text."""

    def test_truthiness_bug(self, generator):
        result = generator._detect_bug_class(
            "Empty string passes truthy check",
        )
        assert result == BugClass.TRUTHINESS_BUG.value

    def test_enum_serialization(self, generator):
        result = generator._detect_bug_class(
            "Enum serialization fails on round-trip",
        )
        assert result == BugClass.ENUM_SERIALIZATION.value

    def test_persistence_defect(self, generator):
        result = generator._detect_bug_class(
            "Data not persisted correctly in database write",
        )
        assert result == BugClass.PERSISTENCE_DEFECT.value

    def test_evidence_failure(self, generator):
        result = generator._detect_bug_class(
            "Evidence bundle incomplete: pass_fail.json missing",
        )
        assert result == BugClass.EVIDENCE_FAILURE.value

    def test_cli_exit_code(self, generator):
        result = generator._detect_bug_class(
            "Non-zero exit code not returned on error",
        )
        assert result == BugClass.CLI_EXIT_CODE.value

    def test_path_traversal(self, generator):
        result = generator._detect_bug_class(
            "CWE-22 path traversal in user-controlled ID",
        )
        assert result == BugClass.PATH_TRAVERSAL.value

    def test_command_injection(self, generator):
        result = generator._detect_bug_class(
            "CWE-88 argument injection via file paths",
        )
        assert result == BugClass.COMMAND_INJECTION.value

    def test_silent_exception(self, generator):
        result = generator._detect_bug_class(
            "Exception silently swallowed in error handler",
        )
        assert result == BugClass.SILENT_EXCEPTION.value

    def test_unknown_defaults_to_other(self, generator):
        result = generator._detect_bug_class("Some random issue")
        assert result == BugClass.OTHER.value

    def test_case_insensitive(self, generator):
        result = generator._detect_bug_class("PATH TRAVERSAL ISSUE")
        assert result == BugClass.PATH_TRAVERSAL.value


# ---------------------------------------------------------------------------
# Test: Test intent mapping
# ---------------------------------------------------------------------------


class TestIntentMapping:
    """Verify bug class -> test intent mapping."""

    __test__ = True

    def test_truthiness_intent(self, generator):
        intent = generator._intent_for_bug_class(BugClass.TRUTHINESS_BUG.value)
        assert intent.intent_kind == TestIntentKind.ASSERT_FALSY_REJECTED.value
        assert intent.assertion_hint

    def test_path_traversal_intent(self, generator):
        intent = generator._intent_for_bug_class(BugClass.PATH_TRAVERSAL.value)
        assert intent.intent_kind == TestIntentKind.ASSERT_PATH_REJECTED.value

    def test_unknown_intent(self, generator):
        intent = generator._intent_for_bug_class("nonexistent_class")
        assert intent.intent_kind == TestIntentKind.ASSERT_GENERIC.value


# ---------------------------------------------------------------------------
# Test: Priority assignment
# ---------------------------------------------------------------------------


class TestPriorityAssignment:
    """Verify bug class -> priority mapping."""

    def test_high_priority_security(self, generator):
        p = generator._priority_for_bug_class(BugClass.PATH_TRAVERSAL.value)
        assert p == CandidatePriority.HIGH.value

    def test_high_priority_injection(self, generator):
        p = generator._priority_for_bug_class(BugClass.COMMAND_INJECTION.value)
        assert p == CandidatePriority.HIGH.value

    def test_medium_priority_truthiness(self, generator):
        p = generator._priority_for_bug_class(BugClass.TRUTHINESS_BUG.value)
        assert p == CandidatePriority.MEDIUM.value

    def test_medium_priority_malformed_input(self, generator):
        p = generator._priority_for_bug_class(BugClass.MALFORMED_INPUT.value)
        assert p == CandidatePriority.MEDIUM.value

    def test_low_priority_other(self, generator):
        p = generator._priority_for_bug_class(BugClass.OTHER.value)
        assert p == CandidatePriority.LOW.value


# ---------------------------------------------------------------------------
# Test: Generate from findings
# ---------------------------------------------------------------------------


class TestGenerateFromFindings:
    """Verify generation from seeded review findings."""

    def test_candidates_generated(self, generator_with_findings):
        result = generator_with_findings.generate_from_findings()
        assert result["total_candidates"] == 5
        assert result["total_findings_analyzed"] == 5

    def test_bug_classes_detected(self, generator_with_findings):
        result = generator_with_findings.generate_from_findings()
        classes = {c["bug_class"] for c in result["candidates"]}
        assert BugClass.TRUTHINESS_BUG.value in classes
        assert BugClass.PATH_TRAVERSAL.value in classes
        assert BugClass.ENUM_SERIALIZATION.value in classes
        assert BugClass.CLI_EXIT_CODE.value in classes

    def test_pattern_detection(self, generator_with_findings):
        result = generator_with_findings.generate_from_findings()
        assert result["total_patterns"] >= 1
        truthiness_patterns = [
            p for p in result["patterns"]
            if p["bug_class"] == BugClass.TRUTHINESS_BUG.value
        ]
        assert len(truthiness_patterns) == 1
        assert truthiness_patterns[0]["occurrence_count"] == 2

    def test_deterministic_ordering(self, generator_with_findings):
        r1 = generator_with_findings.generate_from_findings()
        r2 = generator_with_findings.generate_from_findings()
        titles1 = [c["title"] for c in r1["candidates"]]
        titles2 = [c["title"] for c in r2["candidates"]]
        assert titles1 == titles2

    def test_semantic_priority_ordering(self, generator_with_findings):
        result = generator_with_findings.generate_from_findings()
        priorities = [c["priority"] for c in result["candidates"]]
        rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "unset": 4}
        ranks = [rank[p] for p in priorities]
        assert ranks == sorted(ranks)


# ---------------------------------------------------------------------------
# Test: Generate from explicit input
# ---------------------------------------------------------------------------


class TestGenerateFromInput:
    """Verify single-candidate creation from explicit input."""

    def test_create_with_auto_detection(self, generator):
        c = generator.generate_from_input(
            title="Path traversal in user input",
            description="CWE-22: ../etc/passwd",
            failure_origin="security",
        )
        assert c.bug_class == BugClass.PATH_TRAVERSAL.value
        assert c.test_intent == TestIntentKind.ASSERT_PATH_REJECTED.value
        assert c.priority == CandidatePriority.HIGH.value

    def test_create_with_explicit_class(self, generator):
        c = generator.generate_from_input(
            title="Custom bug",
            description="Some issue",
            failure_origin="human_review",
            bug_class="evidence_failure",
        )
        assert c.bug_class == BugClass.EVIDENCE_FAILURE.value
        assert c.test_intent == TestIntentKind.ASSERT_EVIDENCE_WRITTEN.value

    def test_create_with_target_file(self, generator):
        c = generator.generate_from_input(
            title="Bug in validator",
            description="Issue",
            failure_origin="review_finding",
            target_file="src/axiom_core/validator.py",
        )
        assert c.target_file == "src/axiom_core/validator.py"
        assert c.target_test_file == "tests/test_validator.py"

    def test_create_with_work_item_link(self, generator):
        c = generator.generate_from_input(
            title="Some bug",
            description="Issue",
            failure_origin="runtime_failure",
            source_work_item_id="wi-001",
        )
        assert c.source_work_item_id == "wi-001"

    def test_create_requires_title(self, generator):
        with pytest.raises(ValueError, match="title is required"):
            generator.generate_from_input(
                title="",
                description="Issue",
                failure_origin="review_finding",
            )

    def test_all_failure_origins(self, generator):
        for origin in FailureOrigin:
            c = generator.generate_from_input(
                title=f"Bug from {origin.value}",
                description="Issue",
                failure_origin=origin.value,
            )
            assert c.failure_origin == origin.value


# ---------------------------------------------------------------------------
# Test: Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    """Verify candidates persist and can be retrieved."""

    def test_list_candidates(self, generator):
        generator.generate_from_input(
            title="Bug A", description="A", failure_origin="review_finding",
        )
        generator.generate_from_input(
            title="Bug B", description="B", failure_origin="runtime_failure",
        )
        candidates = generator.list_candidates()
        assert len(candidates) == 2

    def test_get_candidate(self, generator):
        c = generator.generate_from_input(
            title="Bug A", description="A", failure_origin="review_finding",
        )
        result = generator.get_candidate(c.candidate_id)
        assert result is not None
        assert result["candidate_id"] == c.candidate_id
        assert result["title"] == "Regression: Bug A"

    def test_get_unknown_candidate(self, generator):
        result = generator.get_candidate("nonexistent")
        assert result is None

    def test_filter_by_bug_class(self, generator):
        generator.generate_from_input(
            title="Path issue CWE-22",
            description="Path traversal",
            failure_origin="security",
        )
        generator.generate_from_input(
            title="Some other bug",
            description="Random issue",
            failure_origin="review_finding",
        )
        results = generator.list_candidates(bug_class="path_traversal")
        assert len(results) == 1
        assert results[0]["bug_class"] == "path_traversal"

    def test_filter_by_status(self, generator):
        c = generator.generate_from_input(
            title="Bug A", description="A", failure_origin="review_finding",
        )
        generator.update_candidate_status(c.candidate_id, "accepted")
        results = generator.list_candidates(status="accepted")
        assert len(results) == 1

    def test_update_status(self, generator):
        c = generator.generate_from_input(
            title="Bug A", description="A", failure_origin="review_finding",
        )
        result = generator.update_candidate_status(c.candidate_id, "rejected")
        assert result is not None
        assert result["status"] == "rejected"

    def test_update_unknown_returns_none(self, generator):
        result = generator.update_candidate_status("nonexistent", "accepted")
        assert result is None


# ---------------------------------------------------------------------------
# Test: Evidence bundle
# ---------------------------------------------------------------------------


class TestEvidenceBundle:
    """Verify evidence artifacts are written correctly."""

    def test_evidence_files_created(self, generator_with_findings):
        result = generator_with_findings.generate_from_findings()
        evidence_dir = generator_with_findings.write_evidence(result)
        evidence_path = Path(evidence_dir)
        assert (evidence_path / "regression_request.json").exists()
        assert (evidence_path / "regression_result.json").exists()
        assert (evidence_path / "regression_summary.md").exists()
        assert (evidence_path / "pass_fail.json").exists()

    def test_pass_fail_json_valid(self, generator_with_findings):
        result = generator_with_findings.generate_from_findings()
        evidence_dir = generator_with_findings.write_evidence(result)
        pf = json.loads(
            (Path(evidence_dir) / "pass_fail.json").read_text(),
        )
        assert pf["passed"] is True
        assert pf["total_candidates"] == 5

    def test_result_json_valid(self, generator_with_findings):
        result = generator_with_findings.generate_from_findings()
        evidence_dir = generator_with_findings.write_evidence(result)
        data = json.loads(
            (Path(evidence_dir) / "regression_result.json").read_text(),
        )
        assert data["total_candidates"] == 5
        assert len(data["candidates"]) == 5

    def test_summary_md_content(self, generator_with_findings):
        result = generator_with_findings.generate_from_findings()
        evidence_dir = generator_with_findings.write_evidence(result)
        summary = (Path(evidence_dir) / "regression_summary.md").read_text()
        assert "Regression Test Generator Summary" in summary
        assert "Candidates" in summary


# ---------------------------------------------------------------------------
# Test: Path traversal
# ---------------------------------------------------------------------------


class TestPathTraversal:
    """Verify path traversal rejection in IDs."""

    def test_candidate_id_traversal(self, generator):
        with pytest.raises(ValueError, match="must not contain"):
            generator.get_candidate("../../etc/passwd")

    def test_run_id_traversal(self, generator):
        with pytest.raises(ValueError, match="must not contain"):
            generator.write_evidence({"run_id": "../../etc/passwd"})

    def test_slash_rejected(self, generator):
        with pytest.raises(ValueError, match="must not contain"):
            generator.get_candidate("foo/bar")

    def test_backslash_rejected(self, generator):
        with pytest.raises(ValueError, match="must not contain"):
            generator.get_candidate("foo\\bar")


# ---------------------------------------------------------------------------
# Test: Serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    """Verify to_dict() methods work correctly."""

    def test_candidate_to_dict(self):
        c = RegressionTestCandidate(
            candidate_id="test-001",
            title="Test Bug",
            bug_class="truthiness_bug",
        )
        d = c.to_dict()
        assert d["candidate_id"] == "test-001"
        assert d["title"] == "Test Bug"
        assert d["bug_class"] == "truthiness_bug"

    def test_pattern_to_dict(self):
        p = BugPattern(
            pattern_id="p-001",
            bug_class="path_traversal",
            occurrence_count=3,
        )
        d = p.to_dict()
        assert d["pattern_id"] == "p-001"
        assert d["occurrence_count"] == 3

    def test_intent_to_dict(self):
        i = TestIntent(
            intent_kind="assert_falsy_rejected",
            description="Assert falsy rejected",
        )
        d = i.to_dict()
        assert d["intent_kind"] == "assert_falsy_rejected"


# ---------------------------------------------------------------------------
# Test: Pattern listing
# ---------------------------------------------------------------------------


class TestPatternListing:
    """Verify bug pattern persistence and listing."""

    def test_patterns_persist(self, generator_with_findings):
        generator_with_findings.generate_from_findings()
        patterns = generator_with_findings.list_patterns()
        assert len(patterns) >= 1
        classes = {p["bug_class"] for p in patterns}
        assert BugClass.TRUTHINESS_BUG.value in classes

    def test_single_occurrence_excluded(self, generator_with_findings):
        generator_with_findings.generate_from_findings()
        patterns = generator_with_findings.list_patterns()
        for p in patterns:
            assert p["occurrence_count"] >= 2
