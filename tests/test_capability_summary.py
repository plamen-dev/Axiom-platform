"""Tests for the Capability Summary Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.capability_summary import (
    CapabilityNarrative,
    CapabilitySummary,
    CapabilitySummaryEngine,
    CapabilitySummaryEvidence,
    CapabilitySummaryReport,
)


def _summary(cap_id: str, name: str, created_at: str, **kw) -> dict:
    data = {
        "capability_id": cap_id,
        "capability_name": name,
        "purpose": kw.get("purpose", f"purpose-{cap_id}"),
        "summary": kw.get("summary", f"summary-{cap_id}"),
        "architectural_significance": kw.get("architectural_significance", ""),
        "created_at": created_at,
    }
    if "raw_metadata" in kw:
        data["raw_metadata"] = kw["raw_metadata"]
    return data


def _narrative(cap_id: str, created_at: str, **kw) -> dict:
    data = {
        "capability_id": cap_id,
        "context": kw.get("context", f"context-{cap_id}"),
        "rationale": kw.get("rationale", ""),
        "risks": kw.get("risks", ""),
        "lessons": kw.get("lessons", ""),
        "future_opportunities": kw.get("future_opportunities", ""),
        "created_at": created_at,
    }
    if "narrative_id" in kw:
        data["narrative_id"] = kw["narrative_id"]
    return data


@pytest.fixture
def engine(tmp_path):
    return CapabilitySummaryEngine(artifacts_root=str(tmp_path / "artifacts"))


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_summary_round_trip(self):
        s = CapabilitySummary(
            capability_id="cap-1",
            capability_name="Registry",
            purpose="identity",
            summary="canonical id layer",
            architectural_significance="pillar 1",
            created_at="2026-01-01T00:00:00+00:00",
            raw_metadata={"k": "v"},
        )
        restored = CapabilitySummary.from_dict(s.to_dict())
        assert restored == s

    def test_narrative_round_trip(self):
        n = CapabilityNarrative(
            narrative_id="n-1",
            capability_id="cap-1",
            context="ctx",
            rationale="why",
            risks="low",
            lessons="learned",
            future_opportunities="more",
            created_at="2026-01-01T00:00:00+00:00",
            raw_metadata={"k": "v"},
        )
        restored = CapabilityNarrative.from_dict(n.to_dict())
        assert restored == n

    def test_narrative_gets_id_and_timestamp(self):
        n = CapabilityNarrative(capability_id="cap-1")
        assert n.narrative_id
        assert n.created_at

    def test_report_defaults(self):
        r = CapabilitySummaryReport()
        assert r.report_id
        assert r.created_at
        assert r.schema_version == "1.0"

    def test_evidence_defaults(self):
        e = CapabilitySummaryEvidence(report_id="r-1")
        assert e.evidence_id
        assert e.created_at
        assert e.to_dict()["report_id"] == "r-1"


# ---------------------------------------------------------------------------
# Create + determinism
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_counts(self, engine):
        report = engine.create(
            summaries=[
                _summary("cap-a", "A", "2026-01-01T00:00:00+00:00"),
                _summary("cap-b", "B", "2026-01-02T00:00:00+00:00"),
            ],
            narratives=[_narrative("cap-a", "2026-01-01T00:00:00+00:00")],
        )
        assert report["summary_count"] == 2
        assert report["narrative_count"] == 1

    def test_summaries_sorted_deterministically(self, engine):
        report = engine.create(
            summaries=[
                _summary("cap-c", "C", "2026-01-03T00:00:00+00:00"),
                _summary("cap-a", "A", "2026-01-01T00:00:00+00:00"),
                _summary("cap-b", "B", "2026-01-02T00:00:00+00:00"),
            ]
        )
        ids = [s["capability_id"] for s in report["summaries"]]
        assert ids == ["cap-a", "cap-b", "cap-c"]

    def test_narratives_sorted_deterministically(self, engine):
        report = engine.create(
            summaries=[_summary("cap-a", "A", "2026-01-01T00:00:00+00:00")],
            narratives=[
                _narrative("cap-z", "2026-01-03T00:00:00+00:00"),
                _narrative("cap-a", "2026-01-01T00:00:00+00:00"),
            ],
        )
        ids = [n["capability_id"] for n in report["narratives"]]
        assert ids == ["cap-a", "cap-z"]

    def test_capability_counts_sorted(self, engine):
        report = engine.create(
            summaries=[
                _summary("cap-b", "B", "2026-01-02T00:00:00+00:00"),
                _summary("cap-a", "A", "2026-01-01T00:00:00+00:00"),
            ],
            narratives=[_narrative("cap-a", "2026-01-01T00:00:00+00:00")],
        )
        assert list(report["capability_counts"].keys()) == ["cap-a", "cap-b"]
        assert report["capability_counts"]["cap-a"] == 2
        assert report["capability_counts"]["cap-b"] == 1

    def test_output_stable_across_input_order(self, engine):
        a = _summary("cap-a", "A", "2026-01-01T00:00:00+00:00")
        b = _summary("cap-b", "B", "2026-01-02T00:00:00+00:00")
        r1 = engine.create(summaries=[a, b])
        r2 = engine.create(summaries=[b, a])
        assert [s["capability_id"] for s in r1["summaries"]] == [
            s["capability_id"] for s in r2["summaries"]
        ]

    def test_raw_payload_preserved(self, engine):
        report = engine.create(
            summaries=[
                _summary(
                    "cap-a",
                    "A",
                    "2026-01-01T00:00:00+00:00",
                    raw_metadata={"nested": {"k": "v"}},
                )
            ],
            raw_metadata={"source": "fixture"},
        )
        assert report["raw_metadata"] == {"source": "fixture"}
        assert report["summaries"][0]["raw_metadata"] == {"nested": {"k": "v"}}

    def test_schema_version_preserved(self, engine):
        report = engine.create(
            summaries=[_summary("cap-a", "A", "2026-01-01T00:00:00+00:00")]
        )
        assert report["schema_version"] == "1.0"
        assert report["summaries"][0]["schema_version"] == "1.0"

    def test_missing_capability_id_rejected(self, engine):
        with pytest.raises(ValueError, match="capability_id is required"):
            engine.create(
                summaries=[_summary("", "A", "2026-01-01T00:00:00+00:00")]
            )

    def test_missing_capability_name_rejected(self, engine):
        with pytest.raises(ValueError, match="capability_name is required"):
            engine.create(
                summaries=[_summary("cap-a", "", "2026-01-01T00:00:00+00:00")]
            )

    def test_narrative_missing_capability_id_rejected(self, engine):
        with pytest.raises(ValueError, match="capability_id is required"):
            engine.create(
                summaries=[_summary("cap-a", "A", "2026-01-01T00:00:00+00:00")],
                narratives=[_narrative("", "2026-01-01T00:00:00+00:00")],
            )


# ---------------------------------------------------------------------------
# Append-only behavior
# ---------------------------------------------------------------------------


class TestAppendOnly:
    def test_append_preserves_existing_and_grows(self, engine):
        report = engine.create(
            summaries=[_summary("cap-a", "A", "2026-01-01T00:00:00+00:00")]
        )
        rid = report["report_id"]
        appended = engine.append(
            rid,
            summaries=[_summary("cap-b", "B", "2026-01-02T00:00:00+00:00")],
            narratives=[_narrative("cap-b", "2026-01-02T00:00:00+00:00")],
        )
        assert appended["report_id"] == rid
        assert appended["summary_count"] == 2
        assert appended["narrative_count"] == 1
        ids = [s["capability_id"] for s in appended["summaries"]]
        assert ids == ["cap-a", "cap-b"]

    def test_append_resorts_into_global_order(self, engine):
        report = engine.create(
            summaries=[_summary("cap-b", "B", "2026-01-02T00:00:00+00:00")]
        )
        appended = engine.append(
            report["report_id"],
            summaries=[_summary("cap-a", "A", "2026-01-01T00:00:00+00:00")],
        )
        ids = [s["capability_id"] for s in appended["summaries"]]
        assert ids == ["cap-a", "cap-b"]

    def test_append_missing_report_raises(self, engine):
        with pytest.raises(ValueError, match="Report not found"):
            engine.append("does-not-exist", summaries=[])


# ---------------------------------------------------------------------------
# Retrieval + export
# ---------------------------------------------------------------------------


class TestRetrievalExport:
    def test_show_round_trip(self, engine):
        report = engine.create(
            summaries=[_summary("cap-a", "A", "2026-01-01T00:00:00+00:00")]
        )
        loaded = engine.get_report(report["report_id"])
        assert loaded == report

    def test_list_reports_sorted(self, engine):
        engine.create(
            summaries=[_summary("cap-a", "A", "2026-01-01T00:00:00+00:00")]
        )
        engine.create(
            summaries=[_summary("cap-b", "B", "2026-01-02T00:00:00+00:00")]
        )
        reports = engine.list_reports()
        assert len(reports) == 2

    def test_get_missing_returns_none(self, engine):
        assert engine.get_report("missing-xyz") is None

    def test_export_json_valid(self, engine):
        report = engine.create(
            summaries=[_summary("cap-a", "A", "2026-01-01T00:00:00+00:00")]
        )
        out = engine.export_report(report["report_id"], fmt="json")
        assert json.loads(out)["report_id"] == report["report_id"]

    def test_export_markdown_has_sections(self, engine):
        report = engine.create(
            summaries=[_summary("cap-a", "Alpha", "2026-01-01T00:00:00+00:00")],
            narratives=[_narrative("cap-a", "2026-01-01T00:00:00+00:00")],
        )
        out = engine.export_report(report["report_id"], fmt="markdown")
        assert "# Capability Summary Report" in out
        assert "## Capability Counts" in out
        assert "# Capability Summary" in out
        assert "# Capability Narrative" in out
        assert "[cap-a]" in out

    def test_export_csv_rows(self, engine):
        report = engine.create(
            summaries=[_summary("cap-a", "Alpha", "2026-01-01T00:00:00+00:00")],
            narratives=[_narrative("cap-a", "2026-01-01T00:00:00+00:00")],
        )
        out = engine.export_report(report["report_id"], fmt="csv")
        lines = out.strip().splitlines()
        assert lines[0].startswith("record_type,")
        assert any(row.startswith("summary,cap-a,") for row in lines)
        assert any(row.startswith("narrative,cap-a,") for row in lines)

    def test_export_invalid_format(self, engine):
        report = engine.create(
            summaries=[_summary("cap-a", "A", "2026-01-01T00:00:00+00:00")]
        )
        with pytest.raises(ValueError, match="Invalid export format"):
            engine.export_report(report["report_id"], fmt="xml")

    def test_export_missing_report(self, engine):
        with pytest.raises(ValueError, match="Report not found"):
            engine.export_report("missing-xyz", fmt="json")


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class TestEvidence:
    def test_evidence_bundle_written(self, engine, tmp_path):
        report = engine.create(
            summaries=[_summary("cap-a", "A", "2026-01-01T00:00:00+00:00")],
            narratives=[_narrative("cap-a", "2026-01-01T00:00:00+00:00")],
        )
        base = (
            tmp_path
            / "artifacts"
            / "capability_summary"
            / report["report_id"]
        )
        for name in (
            "capability_summary_request.json",
            "capability_summary_result.json",
            "capability_summary_summary.md",
            "capability_summary.md",
            "capability_narrative.md",
            "pass_fail.json",
            "report.json",
        ):
            assert (base / name).exists(), name

    def test_pass_fail_passed_when_summary_present(self, engine, tmp_path):
        report = engine.create(
            summaries=[_summary("cap-a", "A", "2026-01-01T00:00:00+00:00")]
        )
        pf = json.loads(
            (
                tmp_path
                / "artifacts"
                / "capability_summary"
                / report["report_id"]
                / "pass_fail.json"
            ).read_text()
        )
        assert pf["passed"] is True
        assert pf["status"] == "passed"
        assert pf["summary_count"] == 1

    def test_pass_fail_failed_when_empty(self, engine, tmp_path):
        report = engine.create(summaries=[])
        pf = json.loads(
            (
                tmp_path
                / "artifacts"
                / "capability_summary"
                / report["report_id"]
                / "pass_fail.json"
            ).read_text()
        )
        assert pf["passed"] is False
        assert pf["status"] == "failed"
        assert pf["summary_count"] == 0


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


class TestPathSafety:
    @pytest.mark.parametrize("bad", ["../etc", "a/b", "..", "a\\b", "  "])
    def test_show_rejects_unsafe_id(self, engine, bad):
        with pytest.raises(ValueError):
            engine.get_report(bad)

    @pytest.mark.parametrize("bad", ["../etc", "a/b", ".."])
    def test_export_rejects_unsafe_id(self, engine, bad):
        with pytest.raises(ValueError):
            engine.export_report(bad, fmt="json")

    def test_append_rejects_unsafe_id(self, engine):
        with pytest.raises(ValueError):
            engine.append("../etc", summaries=[])
