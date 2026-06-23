"""Tests for the Capability Impact Framework v1."""

from __future__ import annotations

import json

import pytest
from axiom_core.capability_impact import (
    CapabilityImpact,
    CapabilityImpactArea,
    CapabilityImpactEngine,
    CapabilityImpactEvidence,
    CapabilityImpactReport,
    CapabilityImpactType,
    CapabilityOpportunity,
    CapabilityOpportunityPriority,
)


def _impact(capability_id: str, itype: str, area: str, **kw) -> dict:
    data = {
        "capability_id": capability_id,
        "impact_type": itype,
        "impact_area": area,
        "impact_summary": kw.get("impact_summary", f"{itype} {area}"),
        "significance": kw.get("significance", ""),
    }
    if "created_at" in kw:
        data["created_at"] = kw["created_at"]
    if "impact_id" in kw:
        data["impact_id"] = kw["impact_id"]
    if "raw_payload" in kw:
        data["raw_payload"] = kw["raw_payload"]
    return data


def _opp(capability_id: str, title: str, **kw) -> dict:
    data = {
        "capability_id": capability_id,
        "title": title,
        "description": kw.get("description", ""),
        "priority": kw.get("priority", "NORMAL"),
    }
    if "related_capability_ids" in kw:
        data["related_capability_ids"] = kw["related_capability_ids"]
    if "opportunity_id" in kw:
        data["opportunity_id"] = kw["opportunity_id"]
    return data


@pytest.fixture
def engine(tmp_path):
    return CapabilityImpactEngine(artifacts_root=str(tmp_path / "artifacts"))


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_impact_round_trip(self):
        i = CapabilityImpact(
            impact_id="i-1",
            capability_id="cap-122",
            impact_type="AUTOMATED",
            impact_area="ENGINEERING",
            impact_summary="automated grid creation",
            significance="high",
            created_at="2026-01-01T00:00:00+00:00",
            raw_payload={"k": "v"},
        )
        restored = CapabilityImpact.from_dict(i.to_dict())
        assert restored == i

    def test_impact_gets_id_and_timestamp(self):
        i = CapabilityImpact(
            capability_id="a", impact_type="ENABLED", impact_area="TESTING"
        )
        assert i.impact_id
        assert i.created_at

    def test_opportunity_round_trip(self):
        o = CapabilityOpportunity(
            opportunity_id="o-1",
            capability_id="cap-122",
            title="extend to walls",
            description="d",
            priority="STRATEGIC",
            related_capability_ids=["cap-123"],
        )
        restored = CapabilityOpportunity.from_dict(o.to_dict())
        assert restored == o

    def test_opportunity_gets_id_and_default_priority(self):
        o = CapabilityOpportunity(capability_id="a", title="t")
        assert o.opportunity_id
        assert o.priority == "NORMAL"

    def test_report_defaults(self):
        report = CapabilityImpactReport()
        assert report.report_id
        assert report.created_at
        assert report.impact_count == 0
        assert report.schema_version == "1.0"

    def test_evidence_defaults(self):
        ev = CapabilityImpactEvidence(report_id="rep-1")
        assert ev.evidence_id
        assert ev.created_at
        assert ev.report_id == "rep-1"

    def test_all_impact_types_present(self):
        assert {t.value for t in CapabilityImpactType} == {
            "ENABLED",
            "IMPROVED",
            "AUTOMATED",
            "SIMPLIFIED",
            "VALIDATED",
            "DOCUMENTED",
            "CONNECTED",
            "EXTENDED",
        }

    def test_all_impact_areas_present(self):
        assert {a.value for a in CapabilityImpactArea} == {
            "ENGINEERING",
            "OPERATIONS",
            "KNOWLEDGE",
            "TESTING",
            "WORKERS",
            "GOVERNANCE",
            "ORGANIZATION",
        }

    def test_all_priorities_present(self):
        assert {p.value for p in CapabilityOpportunityPriority} == {
            "LOW",
            "NORMAL",
            "HIGH",
            "STRATEGIC",
        }


# ---------------------------------------------------------------------------
# Create / determinism
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_counts(self, engine):
        report = engine.create(
            impacts=[
                _impact("cap-123", "AUTOMATED", "ENGINEERING"),
                _impact("cap-124", "VALIDATED", "TESTING"),
            ]
        )
        assert report["impact_count"] == 2
        assert report["impact_type_counts"] == {
            "AUTOMATED": 1,
            "VALIDATED": 1,
        }
        assert report["impact_area_counts"] == {
            "ENGINEERING": 1,
            "TESTING": 1,
        }

    def test_deterministic_ordering(self, engine):
        # Adversarial input; expected sort (capability, area, type, id).
        report = engine.create(
            impacts=[
                _impact("cap-126", "IMPROVED", "OPERATIONS"),
                _impact("cap-122", "ENABLED", "TESTING"),
                _impact("cap-124", "AUTOMATED", "ENGINEERING"),
                _impact("cap-122", "DOCUMENTED", "KNOWLEDGE"),
            ]
        )
        order = [
            (
                i["capability_id"],
                i["impact_area"],
                i["impact_type"],
            )
            for i in report["impacts"]
        ]
        assert order == [
            ("cap-122", "KNOWLEDGE", "DOCUMENTED"),
            ("cap-122", "TESTING", "ENABLED"),
            ("cap-124", "ENGINEERING", "AUTOMATED"),
            ("cap-126", "OPERATIONS", "IMPROVED"),
        ]

    def test_ordering_is_input_independent(self, engine):
        impacts = [
            _impact("a", "ENABLED", "TESTING"),
            _impact("c", "AUTOMATED", "ENGINEERING"),
            _impact("a", "IMPROVED", "OPERATIONS"),
        ]
        r1 = engine.create(impacts=list(impacts))
        r2 = engine.create(impacts=list(reversed(impacts)))
        key = lambda rep: [  # noqa: E731
            (x["capability_id"], x["impact_area"], x["impact_type"])
            for x in rep["impacts"]
        ]
        assert key(r1) == key(r2)

    def test_opportunities_sorted(self, engine):
        report = engine.create(
            impacts=[_impact("a", "ENABLED", "TESTING")],
            opportunities=[
                _opp("cap-b", "zeta plan"),
                _opp("cap-a", "alpha plan"),
            ],
        )
        titles = [o["title"] for o in report["opportunities"]]
        assert titles == ["alpha plan", "zeta plan"]

    def test_strategic_opportunity_count(self, engine):
        report = engine.create(
            impacts=[_impact("a", "ENABLED", "TESTING")],
            opportunities=[
                _opp("a", "t1", priority="STRATEGIC"),
                _opp("a", "t2", priority="HIGH"),
                _opp("a", "t3", priority="STRATEGIC"),
            ],
        )
        assert report["opportunity_count"] == 3
        assert report["strategic_opportunity_count"] == 2

    def test_raw_payload_preserved(self, engine):
        report = engine.create(
            impacts=[
                _impact(
                    "a",
                    "AUTOMATED",
                    "ENGINEERING",
                    raw_payload={"nested": {"deep": [1, 2, 3]}},
                )
            ],
            raw_metadata={"source": "program-0"},
        )
        assert report["impacts"][0]["raw_payload"] == {
            "nested": {"deep": [1, 2, 3]}
        }
        assert report["raw_metadata"] == {"source": "program-0"}

    def test_significance_preserved(self, engine):
        report = engine.create(
            impacts=[
                _impact(
                    "a", "AUTOMATED", "ENGINEERING", significance="strategic"
                )
            ]
        )
        assert report["impacts"][0]["significance"] == "strategic"

    def test_schema_version_preserved(self, engine):
        report = engine.create(
            impacts=[_impact("a", "ENABLED", "TESTING")]
        )
        assert report["schema_version"] == "1.0"
        assert report["impacts"][0]["schema_version"] == "1.0"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_type_normalized_to_uppercase(self, engine):
        report = engine.create(
            impacts=[_impact("a", "automated", "engineering")]
        )
        assert report["impacts"][0]["impact_type"] == "AUTOMATED"
        assert report["impacts"][0]["impact_area"] == "ENGINEERING"

    def test_invalid_type_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid impact_type"):
            engine.create(impacts=[_impact("a", "NONSENSE", "TESTING")])

    def test_invalid_area_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid impact_area"):
            engine.create(impacts=[_impact("a", "ENABLED", "NOWHERE")])

    def test_missing_capability_rejected(self, engine):
        with pytest.raises(ValueError, match="capability_id is required"):
            engine.create(impacts=[_impact("", "ENABLED", "TESTING")])

    def test_missing_type_rejected(self, engine):
        with pytest.raises(ValueError, match="impact_type is required"):
            engine.create(impacts=[_impact("a", "", "TESTING")])

    def test_missing_area_rejected(self, engine):
        with pytest.raises(ValueError, match="impact_area is required"):
            engine.create(impacts=[_impact("a", "ENABLED", "")])

    def test_opportunity_priority_normalized(self, engine):
        report = engine.create(
            impacts=[_impact("a", "ENABLED", "TESTING")],
            opportunities=[_opp("a", "t", priority="strategic")],
        )
        assert report["opportunities"][0]["priority"] == "STRATEGIC"

    def test_invalid_priority_rejected(self, engine):
        with pytest.raises(ValueError, match="Invalid priority"):
            engine.create(
                impacts=[_impact("a", "ENABLED", "TESTING")],
                opportunities=[_opp("a", "t", priority="URGENT")],
            )

    def test_opportunity_missing_capability_rejected(self, engine):
        with pytest.raises(ValueError, match="capability_id is required"):
            engine.create(
                opportunities=[_opp("", "t")],
            )

    def test_opportunity_missing_title_rejected(self, engine):
        with pytest.raises(ValueError, match="title is required"):
            engine.create(
                opportunities=[_opp("a", "")],
            )

    def test_related_capability_ids_deduped_sorted(self, engine):
        report = engine.create(
            impacts=[_impact("a", "ENABLED", "TESTING")],
            opportunities=[
                _opp(
                    "a",
                    "t",
                    related_capability_ids=["z", "a", "z", "m"],
                )
            ],
        )
        assert report["opportunities"][0]["related_capability_ids"] == [
            "a",
            "m",
            "z",
        ]


# ---------------------------------------------------------------------------
# Pass/fail
# ---------------------------------------------------------------------------


def _read_pass_fail(engine, report_id: str) -> dict:
    path = engine._report_dir / report_id / "pass_fail.json"
    return json.loads(path.read_text(encoding="utf-8"))


class TestPassFail:
    def test_pass_with_impacts(self, engine):
        report = engine.create(
            impacts=[_impact("a", "ENABLED", "TESTING")]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is True
        assert pf["impact_count"] == 1
        assert pf["status"] == "passed"

    def test_empty_report_fails(self, engine):
        report = engine.create(impacts=[])
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["impact_count"] == 0
        assert pf["status"] == "failed"

    def test_opportunities_only_fails(self, engine):
        # No impacts -> fails even with opportunities present.
        report = engine.create(
            opportunities=[_opp("a", "t", priority="STRATEGIC")]
        )
        pf = _read_pass_fail(engine, report["report_id"])
        assert pf["passed"] is False
        assert pf["strategic_opportunity_count"] == 1

    def test_evidence_bundle_files_written(self, engine):
        report = engine.create(
            impacts=[_impact("a", "ENABLED", "TESTING")]
        )
        report_dir = engine._report_dir / report["report_id"]
        for name in (
            "capability_impact_request.json",
            "capability_impact_result.json",
            "capability_impact_summary.md",
            "pass_fail.json",
            "report.json",
        ):
            assert (report_dir / name).exists()


# ---------------------------------------------------------------------------
# Append-only
# ---------------------------------------------------------------------------


class TestAppend:
    def test_append_preserves_and_adds(self, engine):
        created = engine.create(
            impacts=[_impact("a", "ENABLED", "TESTING")]
        )
        report_id = created["report_id"]
        appended = engine.append(
            report_id,
            impacts=[_impact("b", "AUTOMATED", "ENGINEERING")],
            opportunities=[_opp("b", "extend")],
        )
        assert appended["report_id"] == report_id
        assert appended["impact_count"] == 2
        assert appended["opportunity_count"] == 1
        caps = {i["capability_id"] for i in appended["impacts"]}
        assert caps == {"a", "b"}

    def test_append_missing_report_raises(self, engine):
        with pytest.raises(ValueError, match="Report not found"):
            engine.append("does-not-exist", impacts=[])


# ---------------------------------------------------------------------------
# Retrieval / exports
# ---------------------------------------------------------------------------


class TestRetrievalExport:
    def test_get_report_round_trip(self, engine):
        created = engine.create(
            impacts=[_impact("a", "ENABLED", "TESTING")]
        )
        loaded = engine.get_report(created["report_id"])
        assert loaded["report_id"] == created["report_id"]
        assert loaded["impact_count"] == 1

    def test_get_missing_returns_none(self, engine):
        assert engine.get_report("missing-id") is None

    def test_list_reports_sorted(self, engine):
        engine.create(impacts=[_impact("a", "ENABLED", "TESTING")])
        engine.create(impacts=[_impact("c", "AUTOMATED", "ENGINEERING")])
        reports = engine.list_reports()
        assert len(reports) == 2

    def test_export_json_valid(self, engine):
        created = engine.create(
            impacts=[_impact("a", "ENABLED", "TESTING")]
        )
        out = engine.export_report(created["report_id"], fmt="json")
        parsed = json.loads(out)
        assert parsed["report_id"] == created["report_id"]

    def test_export_markdown_headings(self, engine):
        created = engine.create(
            impacts=[_impact("a", "AUTOMATED", "ENGINEERING")],
            opportunities=[_opp("a", "extend", priority="STRATEGIC")],
        )
        out = engine.export_report(created["report_id"], fmt="markdown")
        assert "# Capability Impact Report" in out
        assert "## Impact Type Counts" in out
        assert "## Impact Area Counts" in out
        assert "## Impacts" in out
        assert "## Opportunities" in out
        assert "[AUTOMATED]" in out
        assert "[STRATEGIC]" in out

    def test_export_csv_rows(self, engine):
        created = engine.create(
            impacts=[
                _impact("a", "AUTOMATED", "ENGINEERING"),
                _impact("a", "ENABLED", "TESTING"),
            ],
            opportunities=[_opp("a", "extend")],
        )
        out = engine.export_report(created["report_id"], fmt="csv")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        assert lines[0].startswith("record_kind,")
        # header + 2 impacts + 1 opportunity
        assert len(lines) == 4

    def test_export_invalid_format_raises(self, engine):
        created = engine.create(
            impacts=[_impact("a", "ENABLED", "TESTING")]
        )
        with pytest.raises(ValueError, match="Invalid export format"):
            engine.export_report(created["report_id"], fmt="xml")

    def test_export_missing_raises(self, engine):
        with pytest.raises(ValueError, match="Report not found"):
            engine.export_report("missing-id", fmt="json")


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


class TestPathSafety:
    def test_traversal_rejected_on_get(self, engine):
        with pytest.raises(ValueError, match="must not contain"):
            engine.get_report("../../etc")

    def test_traversal_rejected_on_export(self, engine):
        with pytest.raises(ValueError, match="must not contain"):
            engine.export_report("../../etc", fmt="json")

    def test_empty_id_rejected(self, engine):
        with pytest.raises(ValueError, match="must not be empty"):
            engine.get_report("   ")
