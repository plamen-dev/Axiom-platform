"""Tests for the Failure Classification Framework v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.failure_classification_framework import (
    FailureCategory,
    FailureClassification,
    FailureClassificationEngine,
    FailureClassificationEvidence,
    FailureClassificationReport,
    FailureSeverity,
    FailureType,
)

from tests.conftest import make_symlink_or_skip


@pytest.fixture()
def engine(tmp_path: Path) -> FailureClassificationEngine:
    return FailureClassificationEngine(artifacts_root=str(tmp_path))


def _sample_classifications() -> list[dict]:
    return [
        {
            "outcome_id": "o1",
            "failure_type": "validation_failure",
            "category": "input",
            "severity": "error",
            "summary": "bad input",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "outcome_id": "o2",
            "failure_type": "test_failure",
            "category": "logic",
            "severity": "warning",
            "created_at": "2026-01-02T00:00:00+00:00",
        },
        {
            "outcome_id": "o3",
            "failure_type": "execution_failure",
            "category": "environment",
            "severity": "critical",
            "created_at": "2026-01-03T00:00:00+00:00",
        },
    ]


# ---------------------------------------------------------------------------
# TestModels
# ---------------------------------------------------------------------------


class TestModels:
    def test_classification_defaults(self) -> None:
        c = FailureClassification()
        assert c.classification_id
        assert c.created_at
        assert c.failure_type == "unknown_failure"
        assert c.category == "unknown"
        assert c.severity == "error"

    def test_report_defaults(self) -> None:
        r = FailureClassificationReport()
        assert r.report_id
        assert r.created_at
        assert r.classification_count == 0

    def test_evidence_defaults(self) -> None:
        e = FailureClassificationEvidence()
        assert e.evidence_id
        assert e.created_at


# ---------------------------------------------------------------------------
# TestCreate
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_empty(self, engine: FailureClassificationEngine) -> None:
        result = engine.create()
        assert result["classification_count"] == 0
        assert result["classifications"] == []

    def test_create_with_classifications(
        self, engine: FailureClassificationEngine
    ) -> None:
        result = engine.create(classifications=_sample_classifications())
        assert result["classification_count"] == 3

    def test_all_types(self, engine: FailureClassificationEngine) -> None:
        classifications = [
            {"outcome_id": f"o{t.value}", "failure_type": t.value}
            for t in FailureType
        ]
        result = engine.create(classifications=classifications)
        assert result["classification_count"] == len(FailureType)

    def test_all_categories(self, engine: FailureClassificationEngine) -> None:
        classifications = [
            {"outcome_id": f"o{c.value}", "category": c.value}
            for c in FailureCategory
        ]
        result = engine.create(classifications=classifications)
        assert result["classification_count"] == len(FailureCategory)

    def test_all_severities(self, engine: FailureClassificationEngine) -> None:
        classifications = [
            {"outcome_id": f"o{s.value}", "severity": s.value}
            for s in FailureSeverity
        ]
        result = engine.create(classifications=classifications)
        assert result["classification_count"] == len(FailureSeverity)


# ---------------------------------------------------------------------------
# TestSeverityCounts
# ---------------------------------------------------------------------------


class TestSeverityCounts:
    def test_severity_counts(self, engine: FailureClassificationEngine) -> None:
        result = engine.create(classifications=_sample_classifications())
        assert result["info_count"] == 0
        assert result["warning_count"] == 1
        assert result["error_count"] == 1
        assert result["critical_count"] == 1

    def test_info_counted(self, engine: FailureClassificationEngine) -> None:
        classifications = [
            {"outcome_id": "o1", "severity": "info"},
            {"outcome_id": "o2", "severity": "info"},
        ]
        result = engine.create(classifications=classifications)
        assert result["info_count"] == 2


# ---------------------------------------------------------------------------
# TestSeverityPersistence
# ---------------------------------------------------------------------------


class TestSeverityPersistence:
    def test_severity_persisted(self, engine: FailureClassificationEngine) -> None:
        result = engine.create(classifications=_sample_classifications())
        by_outcome = {c["outcome_id"]: c for c in result["classifications"]}
        assert by_outcome["o1"]["severity"] == "error"
        assert by_outcome["o3"]["severity"] == "critical"


# ---------------------------------------------------------------------------
# TestCategoryPersistence
# ---------------------------------------------------------------------------


class TestCategoryPersistence:
    def test_category_persisted(self, engine: FailureClassificationEngine) -> None:
        result = engine.create(classifications=_sample_classifications())
        by_outcome = {c["outcome_id"]: c for c in result["classifications"]}
        assert by_outcome["o1"]["category"] == "input"
        assert by_outcome["o2"]["category"] == "logic"

    def test_type_and_summary_persisted(
        self, engine: FailureClassificationEngine
    ) -> None:
        result = engine.create(classifications=_sample_classifications())
        by_outcome = {c["outcome_id"]: c for c in result["classifications"]}
        assert by_outcome["o1"]["failure_type"] == "validation_failure"
        assert by_outcome["o1"]["summary"] == "bad input"


# ---------------------------------------------------------------------------
# TestValidation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_type_rejected(
        self, engine: FailureClassificationEngine
    ) -> None:
        with pytest.raises(ValueError, match="Invalid failure_type"):
            engine.create(
                classifications=[{"outcome_id": "o1", "failure_type": "boom"}]
            )

    def test_invalid_category_rejected(
        self, engine: FailureClassificationEngine
    ) -> None:
        with pytest.raises(ValueError, match="Invalid category"):
            engine.create(
                classifications=[{"outcome_id": "o1", "category": "teleport"}]
            )

    def test_invalid_severity_rejected(
        self, engine: FailureClassificationEngine
    ) -> None:
        with pytest.raises(ValueError, match="Invalid severity"):
            engine.create(
                classifications=[{"outcome_id": "o1", "severity": "fatal"}]
            )

    def test_missing_outcome_id_rejected(
        self, engine: FailureClassificationEngine
    ) -> None:
        with pytest.raises(ValueError, match="outcome_id is required"):
            engine.create(classifications=[{"failure_type": "test_failure"}])


# ---------------------------------------------------------------------------
# TestDeterministicOrdering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_classifications_ordered(
        self, engine: FailureClassificationEngine
    ) -> None:
        result = engine.create(classifications=_sample_classifications())
        created = [c["created_at"] for c in result["classifications"]]
        assert created == sorted(created)

    def test_order_independent(self, engine: FailureClassificationEngine) -> None:
        r1 = engine.create(classifications=_sample_classifications())
        r2 = engine.create(
            classifications=list(reversed(_sample_classifications()))
        )
        keys1 = [(c["created_at"], c["outcome_id"]) for c in r1["classifications"]]
        keys2 = [(c["created_at"], c["outcome_id"]) for c in r2["classifications"]]
        assert keys1 == keys2


# ---------------------------------------------------------------------------
# TestEvidenceGeneration
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    def test_four_files_created(
        self, engine: FailureClassificationEngine
    ) -> None:
        result = engine.create(classifications=_sample_classifications())
        report_dir = Path(engine._report_dir) / result["report_id"]
        expected = {
            "failure_classification_request.json",
            "failure_classification_result.json",
            "failure_classification_summary.md",
            "pass_fail.json",
        }
        actual = {f.name for f in report_dir.iterdir() if f.is_file()}
        assert expected.issubset(actual)

    def test_request_valid_json(
        self, engine: FailureClassificationEngine
    ) -> None:
        result = engine.create(classifications=_sample_classifications())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads(
            (report_dir / "failure_classification_request.json").read_text()
        )
        assert len(data["classifications"]) == 3

    def test_result_valid_json(
        self, engine: FailureClassificationEngine
    ) -> None:
        result = engine.create(classifications=_sample_classifications())
        report_dir = Path(engine._report_dir) / result["report_id"]
        data = json.loads(
            (report_dir / "failure_classification_result.json").read_text()
        )
        assert data["report_id"] == result["report_id"]
        assert data["classification_count"] == 3

    def test_summary_has_sections(
        self, engine: FailureClassificationEngine
    ) -> None:
        result = engine.create(classifications=_sample_classifications())
        report_dir = Path(engine._report_dir) / result["report_id"]
        md = (report_dir / "failure_classification_summary.md").read_text()
        assert "# Failure Classification Report" in md
        assert "## Severity Counts" in md
        assert "## Category Counts" in md
        assert "## Classifications" in md

    def test_pass_fail_passes_no_error_or_critical(
        self, engine: FailureClassificationEngine
    ) -> None:
        classifications = [
            {"outcome_id": "o1", "severity": "info"},
            {"outcome_id": "o2", "severity": "warning"},
        ]
        result = engine.create(classifications=classifications)
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True
        assert pf["status"] == "passed"

    def test_pass_fail_fails_on_error(
        self, engine: FailureClassificationEngine
    ) -> None:
        result = engine.create(classifications=_sample_classifications())
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is False
        assert pf["error_count"] == 1
        assert pf["critical_count"] == 1

    def test_pass_fail_empty_passes(
        self, engine: FailureClassificationEngine
    ) -> None:
        result = engine.create()
        report_dir = Path(engine._report_dir) / result["report_id"]
        pf = json.loads((report_dir / "pass_fail.json").read_text())
        assert pf["passed"] is True


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_get_report(self, engine: FailureClassificationEngine) -> None:
        result = engine.create(classifications=_sample_classifications())
        loaded = engine.get_report(result["report_id"])
        assert loaded is not None
        assert loaded["report_id"] == result["report_id"]
        assert loaded["classification_count"] == 3

    def test_list_reports_deterministic(
        self, engine: FailureClassificationEngine
    ) -> None:
        engine.create(classifications=_sample_classifications())
        engine.create()
        reports = engine.list_reports()
        assert len(reports) == 2
        assert reports[0]["created_at"] <= reports[1]["created_at"]


# ---------------------------------------------------------------------------
# TestExport
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_returns_markdown(
        self, engine: FailureClassificationEngine
    ) -> None:
        result = engine.create(classifications=_sample_classifications())
        md = engine.export_report(result["report_id"])
        assert "# Failure Classification Report" in md
        assert "VALIDATION_FAILURE" in md

    def test_export_nonexistent_raises(
        self, engine: FailureClassificationEngine
    ) -> None:
        with pytest.raises(ValueError, match="not found"):
            engine.export_report("nonexistent-id-abc123")


# ---------------------------------------------------------------------------
# TestSafety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_path_traversal_rejected(
        self, engine: FailureClassificationEngine
    ) -> None:
        with pytest.raises(ValueError):
            engine.get_report("../../etc/passwd")

    def test_empty_id_rejected(self, engine: FailureClassificationEngine) -> None:
        with pytest.raises(ValueError):
            engine.get_report("")

    def test_whitespace_id_rejected(
        self, engine: FailureClassificationEngine
    ) -> None:
        with pytest.raises(ValueError):
            engine.get_report("   ")

    def test_symlink_escape_rejected(
        self, engine: FailureClassificationEngine, tmp_path: Path
    ) -> None:
        target = tmp_path / "outside"
        target.mkdir()
        link = Path(engine._report_dir) / "evil-link"
        make_symlink_or_skip(link, target)
        with pytest.raises(ValueError):
            engine.get_report("evil-link")

    def test_nonexistent_returns_none(
        self, engine: FailureClassificationEngine
    ) -> None:
        result = engine.get_report("valid-but-missing-id")
        assert result is None


# ---------------------------------------------------------------------------
# TestCommandRegistryIntegration
# ---------------------------------------------------------------------------


class TestCommandRegistryIntegration:
    def test_commands_registered(self) -> None:
        from axiom_core.runner.command_registry import command_names

        names = command_names()
        expected = {
            "failure-classification-create",
            "failure-classification-show",
            "failure-classification-export",
        }
        assert expected.issubset(set(names))


# ---------------------------------------------------------------------------
# TestSelectionMapping
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_failure_classification_mapped(self) -> None:
        from axiom_core.test_selection_engine import _FILE_TO_TEST

        assert (
            _FILE_TO_TEST["src/axiom_core/failure_classification_framework.py"]
            == "tests/test_failure_classification_framework.py"
        )
