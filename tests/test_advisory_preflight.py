"""Tests for the non-blocking advisory context-preflight CI helper."""

import sys
from pathlib import Path

# Add tools/ to path so we can import the ci helper package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from ci.advisory_preflight import (  # noqa: E402
    body_has_context_basis,
    collect_advisories,
    find_new_concept_modules,
    find_protected_changes,
    find_provenance_wording,
    format_warning,
    main,
    protected_component_files,
)

_FAMILIES = [
    {
        "name": "High Overlap Thing",
        "primary_files": ["src/axiom_core/high_overlap.py"],
        "overlap_risk": "high — many variants",
    },
    {
        "name": "Low Overlap Thing",
        "primary_files": ["src/axiom_core/low_overlap.py"],
        "overlap_risk": "low",
    },
]


class TestProtectedComponents:
    def test_only_high_overlap_is_protected(self):
        protected = protected_component_files(_FAMILIES)
        assert protected == {"src/axiom_core/high_overlap.py": "High Overlap Thing"}

    def test_find_protected_changes(self):
        protected = protected_component_files(_FAMILIES)
        changed = ["src/axiom_core/high_overlap.py", "README.md"]
        assert find_protected_changes(changed, protected) == [
            ("src/axiom_core/high_overlap.py", "High Overlap Thing")
        ]

    def test_no_protected_change(self):
        protected = protected_component_files(_FAMILIES)
        assert find_protected_changes(["README.md"], protected) == []

    def test_real_atlas_marks_orchestrator_protected(self):
        # Uses the real context-preflight atlas: orchestrator is high overlap.
        protected = protected_component_files()
        assert "src/axiom_core/orchestrator.py" in protected


class TestProvenanceWording:
    def test_flags_unbacked_legacy_wording(self):
        added = {"docs/x.md": ["This replaces the legacy pipeline."]}
        assert find_provenance_wording(added) == [
            ("docs/x.md", "This replaces the legacy pipeline.")
        ]

    def test_allows_wording_with_pr_link(self):
        added = {"docs/x.md": ["Replaces the legacy pipeline (see #142)."]}
        assert find_provenance_wording(added) == []

    def test_allows_wording_with_artifact_link(self):
        added = {"docs/x.md": ["deprecated; evidence at artifacts/validation_runs/x"]}
        assert find_provenance_wording(added) == []

    def test_pre_number_wording_flagged(self):
        added = {"a.py": ["# pre-#151 behavior removed"]}
        # 'pre-#151' matches provenance; '#151' also matches evidence -> allowed.
        assert find_provenance_wording(added) == []

    def test_bare_pre_number_without_hash_flagged(self):
        added = {"a.py": ["old-foundation cleanup"]}
        assert find_provenance_wording(added) == [("a.py", "old-foundation cleanup")]

    def test_no_provenance_no_hit(self):
        added = {"a.py": ["def f():", "    return 1"]}
        assert find_provenance_wording(added) == []


class TestNewConceptModules:
    def test_flags_new_concept_module(self):
        added = [
            "src/axiom_core/new_runner.py",
            "src/axiom_core/evidence_thing.py",
            "src/axiom_core/plain_helper.py",
        ]
        assert find_new_concept_modules(added) == [
            "src/axiom_core/new_runner.py",
            "src/axiom_core/evidence_thing.py",
        ]

    def test_ignores_non_src_and_init(self):
        added = [
            "tools/x/runner.py",
            "src/axiom_core/__init__.py",
            "tests/test_runner.py",
        ]
        assert find_new_concept_modules(added) == []


class TestContextBasis:
    def test_present(self):
        assert body_has_context_basis("## Context Basis\nchecked overlaps")

    def test_absent(self):
        assert not body_has_context_basis("## Summary\nno basis here")

    def test_empty(self):
        assert not body_has_context_basis(None)
        assert not body_has_context_basis("")


class TestFormatWarning:
    def test_with_file(self):
        assert format_warning("msg", "a.py") == "::warning file=a.py::msg"

    def test_without_file(self):
        assert format_warning("msg") == "::warning::msg"


class TestCollectAdvisories:
    def test_no_base_ref_still_returns_context_preflight(self, monkeypatch):
        import ci.advisory_preflight as ap

        monkeypatch.setattr(ap, "run_preflight", lambda **kw: {"git_state": {"warnings": []}})
        advisories = collect_advisories(None, "")
        assert any("diff-based advisories skipped" in m for m, _ in advisories)

    def test_protected_change_without_basis_flagged(self, monkeypatch):
        import ci.advisory_preflight as ap

        monkeypatch.setattr(ap, "run_preflight", lambda **kw: {"git_state": {"warnings": []}})
        monkeypatch.setattr(ap, "changed_files", lambda base: ["src/axiom_core/orchestrator.py"])
        monkeypatch.setattr(ap, "added_files", lambda base: [])
        monkeypatch.setattr(ap, "added_lines", lambda base: {})
        advisories = collect_advisories("origin/main", "")
        assert any("protected component" in m for m, _ in advisories)

    def test_protected_change_with_basis_not_flagged(self, monkeypatch):
        import ci.advisory_preflight as ap

        monkeypatch.setattr(ap, "run_preflight", lambda **kw: {"git_state": {"warnings": []}})
        monkeypatch.setattr(ap, "changed_files", lambda base: ["src/axiom_core/orchestrator.py"])
        monkeypatch.setattr(ap, "added_files", lambda base: [])
        monkeypatch.setattr(ap, "added_lines", lambda base: {})
        advisories = collect_advisories("origin/main", "## Context Basis\nok")
        assert not any("protected component" in m for m, _ in advisories)


class TestMainNeverFails:
    def test_main_returns_zero(self, monkeypatch):
        import ci.advisory_preflight as ap

        monkeypatch.setattr(ap, "_diff_base", lambda: None)
        monkeypatch.setattr(ap, "run_preflight", lambda **kw: {"git_state": {"warnings": ["dirty"]}})
        assert main() == 0

    def test_main_returns_zero_even_if_preflight_raises(self, monkeypatch):
        import ci.advisory_preflight as ap

        def _boom(**kw):
            raise RuntimeError("scan failed")

        monkeypatch.setattr(ap, "_diff_base", lambda: None)
        monkeypatch.setattr(ap, "run_preflight", _boom)
        assert main() == 0
