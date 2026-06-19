"""Tests for the Code Review Policy Engine v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.code_review_policy import (
    CodeReviewPolicyEngine,
    PolicyCategory,
    PolicyEvaluationResult,
    PolicyOrigin,
    PolicySeverity,
    PolicyViolation,
    ReviewPolicy,
    _check_classification_distinctness,
    _check_cli_exit_code,
    _check_enum_serialization,
    _check_evidence_bundle,
    _check_path_traversal,
    _check_silent_exception,
    _check_truthiness,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_artifacts(tmp_path: Path) -> Path:
    return tmp_path / "artifacts"


@pytest.fixture()
def engine(tmp_path: Path, tmp_artifacts: Path) -> CodeReviewPolicyEngine:
    return CodeReviewPolicyEngine(
        repo_root=str(tmp_path),
        artifacts_root=str(tmp_artifacts),
    )


@pytest.fixture()
def sample_file(tmp_path: Path) -> Path:
    src = tmp_path / "src" / "axiom_core"
    src.mkdir(parents=True)
    code = src / "sample.py"
    code.write_text("""\
import os

def process(value):
    if value:
        return value.strip()
    try:
        result = do_something()
    except:
        pass
    return None
""")
    return code


# ---------------------------------------------------------------------------
# Data model tests
# ---------------------------------------------------------------------------


class TestDataModels:
    def test_review_policy_to_dict(self):
        p = ReviewPolicy(
            name="test_policy",
            category="truthiness",
            severity="high",
        )
        d = p.to_dict()
        assert d["name"] == "test_policy"
        assert d["category"] == "truthiness"
        assert d["severity"] == "high"
        assert d["policy_id"]

    def test_policy_violation_to_dict(self):
        v = PolicyViolation(
            policy_name="test",
            category="bug",
            severity="high",
            file_path="test.py",
            line_number=10,
        )
        d = v.to_dict()
        assert d["policy_name"] == "test"
        assert d["line_number"] == 10
        assert d["violation_id"]

    def test_evaluation_result_to_dict(self):
        r = PolicyEvaluationResult(
            files_evaluated=["a.py", "b.py"],
            policies_checked=5,
        )
        d = r.to_dict()
        assert d["files_evaluated"] == ["a.py", "b.py"]
        assert d["policies_checked"] == 5
        assert d["passed"] is True
        assert d["total_violations"] == 0

    def test_evaluation_result_severity_counts(self):
        r = PolicyEvaluationResult()
        r.violations = [
            PolicyViolation(severity="high"),
            PolicyViolation(severity="high"),
            PolicyViolation(severity="medium"),
        ]
        d = r.to_dict()
        assert d["violations_by_severity"] == {"high": 2, "medium": 1}


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestEnums:
    def test_severity_values(self):
        assert PolicySeverity.CRITICAL.value == "critical"
        assert PolicySeverity.INFO.value == "info"

    def test_origin_values(self):
        assert PolicyOrigin.DEVIN_REVIEW.value == "devin_review"
        assert PolicyOrigin.SECURITY.value == "security"

    def test_category_values(self):
        assert PolicyCategory.TRUTHINESS.value == "truthiness"
        assert PolicyCategory.PATH_TRAVERSAL.value == "path_traversal"


# ---------------------------------------------------------------------------
# Individual check tests
# ---------------------------------------------------------------------------


class TestTruthinessCheck:
    def test_detects_truthiness(self):
        source = "def f(x):\n    if x:\n        return x\n"
        violations = _check_truthiness(source, "test.py")
        assert len(violations) >= 1
        assert violations[0].category == "truthiness"

    def test_clean_code(self):
        source = "def f(x):\n    if x is not None:\n        return x\n"
        violations = _check_truthiness(source, "test.py")
        assert len(violations) == 0

    def test_syntax_error_graceful(self):
        violations = _check_truthiness("def f(:", "test.py")
        assert violations == []


class TestSilentExceptionCheck:
    def test_bare_except(self):
        source = "try:\n    x = 1\nexcept:\n    pass\n"
        violations = _check_silent_exception(source, "test.py")
        assert any(v.category == "silent_exception" for v in violations)

    def test_except_pass(self):
        source = "try:\n    x = 1\nexcept ValueError:\n    pass\n"
        violations = _check_silent_exception(source, "test.py")
        assert any("pass" in v.description for v in violations)

    def test_clean_except(self):
        source = "try:\n    x = 1\nexcept ValueError:\n    log(e)\n"
        violations = _check_silent_exception(source, "test.py")
        assert len(violations) == 0


class TestEvidenceBundleCheck:
    def test_missing_pass_fail(self):
        source = "def write_evidence(self):\n    json.dump(result)\n"
        violations = _check_evidence_bundle(source, "test.py")
        assert any(v.category == "evidence_bundle" for v in violations)

    def test_has_pass_fail(self):
        source = "def write_evidence(self):\n    pass_fail = {}\n"
        violations = _check_evidence_bundle(source, "test.py")
        assert len(violations) == 0


class TestCliExitCodeCheck:
    def test_sys_exit_in_main(self):
        source = "import sys\nsys.exit(1)\n"
        violations = _check_cli_exit_code(source, "main.py")
        assert any(v.category == "cli_exit_code" for v in violations)

    def test_not_main_file(self):
        source = "import sys\nsys.exit(1)\n"
        violations = _check_cli_exit_code(source, "other.py")
        assert len(violations) == 0


class TestEnumSerializationCheck:
    def test_clean_code(self):
        source = "x = 1 + 2\n"
        violations = _check_enum_serialization(source, "test.py")
        assert len(violations) == 0


class TestPathTraversalCheck:
    def test_detects_unvalidated_path(self):
        source = "path = os.path.join(base, request.id)\n"
        violations = _check_path_traversal(source, "test.py")
        assert any(v.category == "path_traversal" for v in violations)


class TestClassificationDistinctnessCheck:
    def test_overlapping_sets(self):
        source = (
            'a = {"x", "y", "z"}\n'
            'b = {"y", "w", "v"}\n'
        )
        violations = _check_classification_distinctness(source, "test.py")
        assert any(v.category == "classification_distinctness" for v in violations)

    def test_disjoint_sets(self):
        source = (
            'a = {"x", "y"}\n'
            'b = {"w", "z"}\n'
        )
        violations = _check_classification_distinctness(source, "test.py")
        assert len(violations) == 0


# ---------------------------------------------------------------------------
# Engine integration tests
# ---------------------------------------------------------------------------


class TestEngineEvaluateFiles:
    def test_evaluate_python_file(self, engine, sample_file, tmp_path):
        rel = str(sample_file.relative_to(tmp_path))
        result = engine.evaluate_files([rel])
        assert result["policies_checked"] == 7
        assert result["total_violations"] > 0
        assert isinstance(result["violations"], list)

    def test_skips_non_python(self, engine):
        result = engine.evaluate_files(["README.md"])
        assert result["total_violations"] == 0

    def test_missing_file_graceful(self, engine):
        result = engine.evaluate_files(["nonexistent.py"])
        assert result["total_violations"] == 0

    def test_deterministic_ordering(self, engine, sample_file, tmp_path):
        rel = str(sample_file.relative_to(tmp_path))
        r1 = engine.evaluate_files([rel])
        r2 = engine.evaluate_files([rel])
        assert [v["violation_id"] for v in r1["violations"]] != [
            v["violation_id"] for v in r2["violations"]
        ]  # IDs differ
        assert [v["policy_name"] for v in r1["violations"]] == [
            v["policy_name"] for v in r2["violations"]
        ]  # order same

    def test_passed_false_on_high_severity(self, engine, sample_file, tmp_path):
        rel = str(sample_file.relative_to(tmp_path))
        result = engine.evaluate_files([rel])
        has_high = any(
            v["severity"] in ("high", "critical")
            for v in result["violations"]
        )
        if has_high:
            assert result["passed"] is False


class TestEngineEvaluateSource:
    def test_evaluate_source_string(self, engine):
        source = "def f(x):\n    if x:\n        return x\n"
        result = engine.evaluate_source(source, "test.py")
        assert result["total_violations"] >= 1
        assert result["files_evaluated"] == ["test.py"]

    def test_evaluate_clean_source(self, engine):
        source = "x = 1\n"
        result = engine.evaluate_source(source, "test.py")
        assert result["total_violations"] == 0
        assert result["passed"] is True


class TestListPolicies:
    def test_list_all_policies(self, engine):
        policies = engine.list_policies()
        assert len(policies) == 7
        names = {p["name"] for p in policies}
        assert "truthiness_ambiguity" in names
        assert "silent_exception_swallowing" in names
        assert "evidence_bundle_guarantee" in names
        assert "cli_exit_code_consistency" in names
        assert "enum_serialization_fragility" in names
        assert "path_traversal_risk" in names
        assert "classification_distinctness" in names


# ---------------------------------------------------------------------------
# Evidence writing tests
# ---------------------------------------------------------------------------


class TestEvidenceBundle:
    def test_writes_four_files(self, engine, tmp_artifacts):
        result = engine.evaluate_files(["test.py"])
        evidence_dir = engine.write_evidence(result)
        p = Path(evidence_dir)
        assert (p / "policy_request.json").exists()
        assert (p / "policy_result.json").exists()
        assert (p / "policy_summary.md").exists()
        assert (p / "pass_fail.json").exists()

    def test_evidence_valid_json(self, engine, tmp_artifacts):
        result = engine.evaluate_files(["test.py"])
        evidence_dir = engine.write_evidence(result)
        p = Path(evidence_dir)
        for fname in ["policy_request.json", "policy_result.json", "pass_fail.json"]:
            data = json.loads((p / fname).read_text())
            assert isinstance(data, dict)

    def test_summary_content(self, engine, tmp_artifacts):
        result = engine.evaluate_files(["test.py"])
        evidence_dir = engine.write_evidence(result)
        summary = (Path(evidence_dir) / "policy_summary.md").read_text()
        assert "Code Review Policy Evaluation Summary" in summary

    def test_pass_fail_structure(self, engine, tmp_artifacts):
        result = engine.evaluate_files(["test.py"])
        evidence_dir = engine.write_evidence(result)
        pf = json.loads(
            (Path(evidence_dir) / "pass_fail.json").read_text(),
        )
        assert "passed" in pf
        assert "run_id" in pf
        assert "timestamp" in pf


# ---------------------------------------------------------------------------
# Path traversal security tests
# ---------------------------------------------------------------------------


class TestPathTraversal:
    def test_validate_id_segment_rejects_dots(self, engine):
        with pytest.raises(ValueError, match="must not contain"):
            engine._validate_id_segment("../../etc", "run_id")

    def test_validate_id_segment_rejects_slash(self, engine):
        with pytest.raises(ValueError, match="must not contain"):
            engine._validate_id_segment("a/b", "run_id")

    def test_validate_id_segment_rejects_backslash(self, engine):
        with pytest.raises(ValueError, match="must not contain"):
            engine._validate_id_segment("a\\b", "run_id")

    def test_write_evidence_rejects_traversal(self, engine):
        result = {"run_id": "../../etc/passwd"}
        with pytest.raises(ValueError, match="must not contain"):
            engine.write_evidence(result)
