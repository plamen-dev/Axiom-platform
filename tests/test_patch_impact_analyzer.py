"""Tests for PatchImpactAnalyzer v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.patch_impact_analyzer import (
    AffectedCommand,
    AffectedDoc,
    AffectedEvidence,
    AffectedSymbol,
    AffectedTest,
    HighRiskFlag,
    ImpactScope,
    PatchImpactAnalyzer,
)


@pytest.fixture()
def analyzer(tmp_path):
    db_path = str(tmp_path / "test.db")
    artifacts = str(tmp_path / "artifacts")
    return PatchImpactAnalyzer(db_path=db_path, artifacts_root=artifacts)


# ---------------------------------------------------------------------------
# Test: Data model serialization
# ---------------------------------------------------------------------------


class TestDataModels:
    def test_affected_symbol_to_dict(self):
        s = AffectedSymbol(name="MyClass", kind="class", file_path="a.py")
        d = s.to_dict()
        assert d["name"] == "MyClass"
        assert d["kind"] == "class"

    def test_affected_command_to_dict(self):
        c = AffectedCommand(command_name="test-cmd", is_read_only=True)
        d = c.to_dict()
        assert d["command_name"] == "test-cmd"
        assert d["is_read_only"] is True

    def test_affected_test_to_dict(self):
        t = AffectedTest(test_path="tests/test_a.py", reason="direct")
        d = t.to_dict()
        assert d["test_path"] == "tests/test_a.py"

    def test_affected_doc_to_dict(self):
        d = AffectedDoc(doc_path="docs/x.md", reason="convention")
        assert d.to_dict()["doc_path"] == "docs/x.md"

    def test_affected_evidence_to_dict(self):
        e = AffectedEvidence(artifact_path="a.json", contract_type="bundle")
        assert e.to_dict()["contract_type"] == "bundle"

    def test_high_risk_flag_to_dict(self):
        f = HighRiskFlag(risk_area="runner", impact_level="high")
        assert f.to_dict()["risk_area"] == "runner"

    def test_impact_scope_to_dict(self):
        scope = ImpactScope(proposal_id="p-1", changed_files=["a.py"])
        d = scope.to_dict()
        assert d["proposal_id"] == "p-1"
        assert d["total_files"] == 1
        assert d["scope_id"]
        assert d["created_at"]


# ---------------------------------------------------------------------------
# Test: High-risk area detection
# ---------------------------------------------------------------------------


class TestHighRiskDetection:
    def test_runner_path(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["src/axiom_core/runner/command_registry.py"],
        )
        flags = result["scope"]["high_risk_flags"]
        assert len(flags) >= 1
        assert any(f["risk_area"] == "runner" for f in flags)

    def test_persistence_path(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["src/axiom_core/database.py"],
        )
        flags = result["scope"]["high_risk_flags"]
        assert any(f["risk_area"] == "persistence" for f in flags)

    def test_mutation_path(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["src/axiom_core/patch_application.py"],
        )
        flags = result["scope"]["high_risk_flags"]
        assert any(f["risk_area"] == "mutation" for f in flags)
        assert any(f["impact_level"] == "critical" for f in flags)

    def test_revit_bridge_path(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["src/axiom_core/automation_bridge.py"],
        )
        flags = result["scope"]["high_risk_flags"]
        assert any(f["risk_area"] == "revit_bridge" for f in flags)

    def test_evidence_path(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["artifacts/some_run/pass_fail.json"],
        )
        flags = result["scope"]["high_risk_flags"]
        assert any(f["risk_area"] == "evidence" for f in flags)

    def test_security_input_normalization(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["src/axiom_core/input_normalization.py"],
        )
        flags = result["scope"]["high_risk_flags"]
        assert any(f["risk_area"] == "security" for f in flags)
        assert any(f["impact_level"] == "critical" for f in flags)

    def test_security_dialog_watcher(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["src/axiom_core/dialog_watcher.py"],
        )
        flags = result["scope"]["high_risk_flags"]
        assert any(f["risk_area"] == "security" for f in flags)

    def test_no_risk_for_normal_file(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["src/axiom_core/some_new_module.py"],
        )
        flags = result["scope"]["high_risk_flags"]
        assert len(flags) == 0


# ---------------------------------------------------------------------------
# Test: Command detection
# ---------------------------------------------------------------------------


class TestCommandDetection:
    def test_cli_main_affects_all_commands(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["src/axiom_cli/main.py"],
        )
        cmds = result["scope"]["affected_commands"]
        assert len(cmds) >= 1
        assert any("all CLI commands" in c["command_name"] for c in cmds)

    def test_registry_affects_all_commands(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["src/axiom_core/runner/command_registry.py"],
        )
        cmds = result["scope"]["affected_commands"]
        assert len(cmds) >= 1

    def test_core_module_detects_consuming_commands(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["src/axiom_core/patch_proposal.py"],
        )
        cmds = result["scope"]["affected_commands"]
        assert any("patch_proposal" in c["command_name"] for c in cmds)


# ---------------------------------------------------------------------------
# Test: Test detection
# ---------------------------------------------------------------------------


class TestTestDetection:
    def test_convention_fallback(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["src/axiom_core/some_module.py"],
        )
        tests = result["scope"]["affected_tests"]
        assert any("test_some_module" in t["test_path"] for t in tests)

    def test_docs_get_fallback(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["docs/architecture/something.md"],
        )
        tests = result["scope"]["affected_tests"]
        if tests:
            assert any(t["reason"] == "full_suite_fallback" for t in tests)


# ---------------------------------------------------------------------------
# Test: Doc detection
# ---------------------------------------------------------------------------


class TestDocDetection:
    def test_direct_doc_change(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["docs/architecture/runner.md"],
        )
        docs = result["scope"]["affected_docs"]
        assert any(d["reason"] == "direct_change" for d in docs)

    def test_module_convention_doc(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["src/axiom_core/patch_impact_analyzer.py"],
        )
        docs = result["scope"]["affected_docs"]
        assert any("patch-impact-analyzer" in d["doc_path"] for d in docs)


# ---------------------------------------------------------------------------
# Test: Evidence contract detection
# ---------------------------------------------------------------------------


class TestEvidenceDetection:
    def test_evidence_keyword_detected(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["artifacts/run_123/pass_fail.json"],
        )
        evidence = result["scope"]["affected_evidence"]
        assert len(evidence) >= 1


# ---------------------------------------------------------------------------
# Test: Overall impact computation
# ---------------------------------------------------------------------------


class TestOverallImpact:
    def test_critical_impact_for_mutation(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["src/axiom_core/patch_application.py"],
        )
        assert result["scope"]["overall_impact"] == "critical"
        assert result["scope"]["requires_full_suite"] is True

    def test_high_impact_for_runner(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["src/axiom_core/runner/command_registry.py"],
        )
        assert result["scope"]["overall_impact"] == "high"
        assert result["scope"]["requires_full_suite"] is True

    def test_medium_impact_for_many_files(self, analyzer):
        files = [f"src/axiom_core/module_{i}.py" for i in range(6)]
        result = analyzer.analyze_files(changed_files=files)
        assert result["scope"]["overall_impact"] == "medium"
        assert result["scope"]["requires_full_suite"] is True

    def test_low_impact_for_single_safe_file(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["src/axiom_core/some_new_thing.py"],
        )
        assert result["scope"]["overall_impact"] in ("low", "medium")


# ---------------------------------------------------------------------------
# Test: Evidence bundle writing
# ---------------------------------------------------------------------------


class TestEvidenceBundle:
    def test_evidence_files_created(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["src/axiom_core/models.py"],
        )
        evidence_dir = analyzer.write_evidence(result)
        edir = Path(evidence_dir)
        assert (edir / "impact_request.json").exists()
        assert (edir / "impact_result.json").exists()
        assert (edir / "impact_summary.md").exists()
        assert (edir / "pass_fail.json").exists()

    def test_pass_fail_valid_json(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["src/axiom_core/models.py"],
        )
        evidence_dir = analyzer.write_evidence(result)
        pf = json.loads(
            (Path(evidence_dir) / "pass_fail.json").read_text(),
        )
        assert "passed" in pf
        assert "run_id" in pf

    def test_result_valid_json(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["src/axiom_core/models.py"],
        )
        evidence_dir = analyzer.write_evidence(result)
        data = json.loads(
            (Path(evidence_dir) / "impact_result.json").read_text(),
        )
        assert "scope" in data

    def test_summary_content(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["src/axiom_core/models.py"],
        )
        evidence_dir = analyzer.write_evidence(result)
        summary = (Path(evidence_dir) / "impact_summary.md").read_text()
        assert "Patch Impact Analysis" in summary


# ---------------------------------------------------------------------------
# Test: Path traversal rejection
# ---------------------------------------------------------------------------


class TestPathTraversal:
    def test_proposal_id_traversal(self, analyzer):
        with pytest.raises(ValueError, match="must not contain"):
            analyzer.analyze_proposal("../../etc/passwd")

    def test_run_id_traversal(self, analyzer):
        result = {
            "run_id": "../../etc/shadow",
            "scope": {},
        }
        with pytest.raises(ValueError, match="must not contain"):
            analyzer.write_evidence(result)

    def test_slash_in_id(self, analyzer):
        with pytest.raises(ValueError, match="must not contain"):
            analyzer.analyze_proposal("abc/def")


# ---------------------------------------------------------------------------
# Test: Deterministic ordering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_flags_sorted_by_impact(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=[
                "src/axiom_core/runner/command_registry.py",
                "src/axiom_core/patch_application.py",
            ],
        )
        flags = result["scope"]["high_risk_flags"]
        impact_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        ranks = [impact_rank.get(f["impact_level"], 99) for f in flags]
        assert ranks == sorted(ranks)

    def test_files_sorted(self, analyzer):
        result = analyzer.analyze_files(
            changed_files=["src/b.py", "src/a.py"],
        )
        assert result["scope"]["changed_files"] == ["src/a.py", "src/b.py"]


# ---------------------------------------------------------------------------
# Test: Proposal loading (graceful failure)
# ---------------------------------------------------------------------------


class TestProposalLoading:
    def test_unknown_proposal(self, analyzer):
        with pytest.raises(ValueError, match="not found"):
            analyzer.analyze_proposal("nonexistent-proposal-id")
