"""Tests for execution log — JSONL and SQLite persistence."""

import json
from uuid import uuid4

from axiom_core.database import create_db_engine, init_db, make_session_factory
from axiom_core.execution_log import log_execution
from axiom_core.models import PromptExecutionRow
from axiom_core.prompt_resolver import ResolvedPrompt
from axiom_core.schemas import StepStatus, ToolResult


def _make_resolved():
    return ResolvedPrompt(
        capability_name="CreateGrids",
        params={"HorizontalCount": 10, "VerticalCount": 0, "SpacingFeet": 10.0},
        assumptions=["No horizontal grids created"],
        raw_prompt="Create 10 vertical gridlines",
    )


def _make_results():
    return [
        ToolResult(
            step_id=uuid4(),
            status=StepStatus.SUCCESS,
            created_ids=["grid-1", "grid-2"],
            duration_ms=42,
            warnings=["minor warning"],
            errors=[],
        )
    ]


class _FakePlan:
    class Status:
        value = "COMPLETED"

    status = Status()


class _FakeEvent:
    def to_dict(self):
        return {"event_type": "test", "data": {}}


class TestJSONLLog:
    def test_writes_jsonl_record(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AXIOM_LOG_DIR", str(tmp_path))

        resolved = _make_resolved()
        results = _make_results()

        log_path = log_execution(
            prompt="Create 10 vertical gridlines",
            resolved=resolved,
            results=results,
            plan=_FakePlan(),
            events=[_FakeEvent()],
            mode="simulation",
            status="SUCCESS",
        )

        assert log_path.exists()
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 1

        record = json.loads(lines[0])
        assert record["prompt"] == "Create 10 vertical gridlines"
        assert record["mode"] == "simulation"
        assert record["status"] == "SUCCESS"
        assert record["capability"] == "CreateGrids"
        assert record["parameters"]["HorizontalCount"] == 10
        assert len(record["assumptions"]) == 1
        assert len(record["results"]) == 1
        assert record["results"][0]["created_ids"] == ["grid-1", "grid-2"]

    def test_appends_multiple_records(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AXIOM_LOG_DIR", str(tmp_path))

        for _ in range(3):
            log_execution(
                prompt="test",
                resolved=_make_resolved(),
                results=_make_results(),
                plan=_FakePlan(),
                events=[],
                mode="simulation",
                status="SUCCESS",
            )

        log_path = tmp_path / "execution.jsonl"
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 3


class TestSQLitePersistence:
    def test_persists_to_sqlite(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AXIOM_LOG_DIR", str(tmp_path))

        db_path = str(tmp_path / "test.db")
        engine = create_db_engine(db_path)
        init_db(engine)
        sf = make_session_factory(engine)

        resolved = _make_resolved()
        results = _make_results()

        log_execution(
            prompt="Create 10 vertical gridlines",
            resolved=resolved,
            results=results,
            plan=_FakePlan(),
            events=[],
            mode="simulation",
            status="SUCCESS",
            session_factory=sf,
        )

        with sf() as session:
            rows = session.query(PromptExecutionRow).all()
            assert len(rows) == 1

            row = rows[0]
            assert row.prompt == "Create 10 vertical gridlines"
            assert row.mode == "simulation"
            assert row.status == "SUCCESS"
            assert row.capability == "CreateGrids"
            assert row.created_count == 2
            assert row.duration_ms == 42
            assert json.loads(row.parameters_json)["HorizontalCount"] == 10
            assert json.loads(row.assumptions_json) == ["No horizontal grids created"]
            assert json.loads(row.created_ids_json) == ["grid-1", "grid-2"]
            assert json.loads(row.errors_json) == []
            assert json.loads(row.warnings_json) == ["minor warning"]

    def test_no_session_factory_still_writes_jsonl(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AXIOM_LOG_DIR", str(tmp_path))

        log_path = log_execution(
            prompt="test",
            resolved=_make_resolved(),
            results=_make_results(),
            plan=_FakePlan(),
            events=[],
            mode="execution",
            status="SUCCESS",
            session_factory=None,
        )

        assert log_path.exists()
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 1
