"""Tests for Loop Runner v1."""

from __future__ import annotations

import json
from typing import Any

import pytest
from axiom_cli.main import cli
from axiom_core.loop_runner import MAX_LOOP_CYCLES, LoopRunner
from click.testing import CliRunner


@pytest.fixture
def runner(tmp_path: Any) -> LoopRunner:
    return LoopRunner(
        repo_root=".", artifacts_root=str(tmp_path / "artifacts")
    )


class TestLoopRun:
    def test_single_cycle_links_all_stages(
        self, runner: LoopRunner, tmp_path: Any
    ) -> None:
        report = runner.run(cycles=1)

        assert report["status"] == "passed"
        assert report["completed_cycles"] == 1
        assert len(report["cycles"]) == 1

        cycle = report["cycles"][0]
        assert cycle["gap_analysis"]["module_count"] > 0
        assert cycle["queue_report_id"]
        assert cycle["queued_item_count"] >= 1
        assert cycle["chain_run_id"]
        assert cycle["chain_status"] == "PASS"
        for key in (
            "plan_id",
            "attempt_id",
            "result_id",
            "artifact_id",
            "evidence_id",
            "report_id",
        ):
            assert cycle["chain_ids"][key]
        assert cycle["intake_id"]
        assert cycle["evidence_decision"] == "accepted"
        assert cycle["requeue_report_id"]
        assert cycle["requeue_report_id"] != cycle["queue_report_id"]

    def test_loop_report_persisted(
        self, runner: LoopRunner, tmp_path: Any
    ) -> None:
        report = runner.run(cycles=1)
        run_dir = (
            tmp_path / "artifacts" / "loop_runner" / report["loop_id"]
        )
        persisted = json.loads(
            (run_dir / "report.json").read_text(encoding="utf-8")
        )
        assert persisted["loop_id"] == report["loop_id"]
        pass_fail = json.loads(
            (run_dir / "pass_fail.json").read_text(encoding="utf-8")
        )
        assert pass_fail["passed"] is True
        assert pass_fail["completed_cycles"] == 1

    def test_two_cycles_accumulate_evidence(
        self, runner: LoopRunner
    ) -> None:
        report = runner.run(cycles=2)
        assert report["completed_cycles"] == 2
        first, second = report["cycles"]
        assert first["chain_run_id"] != second["chain_run_id"]
        assert first["intake_id"] != second["intake_id"]
        # Both distinct runs are accepted evidence.
        assert second["evidence_decision"] == "accepted"

    def test_cycles_bounded(self, runner: LoopRunner) -> None:
        with pytest.raises(ValueError, match="bounded"):
            runner.run(cycles=MAX_LOOP_CYCLES + 1)
        with pytest.raises(ValueError, match=">= 1"):
            runner.run(cycles=0)

    def test_chain_failure_stops_loop(
        self, tmp_path: Any, monkeypatch: Any
    ) -> None:
        from axiom_core.execution_chain_orchestrator import (
            ExecutionChainError,
        )

        loop = LoopRunner(
            repo_root=".", artifacts_root=str(tmp_path / "artifacts")
        )

        def _boom(capability: str) -> None:
            raise ExecutionChainError("synthetic chain failure")

        monkeypatch.setattr(loop._orchestrator, "run", _boom)
        report = loop.run(cycles=3)

        assert report["status"] == "failed"
        assert report["completed_cycles"] == 0
        assert len(report["cycles"]) == 1
        assert "synthetic chain failure" in report["cycles"][0]["chain_error"]

    def test_queue_items_include_executable_and_gaps(
        self, runner: LoopRunner
    ) -> None:
        gap_result = runner._gap_analysis()
        items = runner._queue_items(gap_result)
        assert items[0]["title"] == "execution-chain-run self-model-build"
        assert items[0]["priority"] == "high"
        assert len(items) <= 1 + 5
        for item in items[1:]:
            assert item["priority"] in {"high", "normal", "low"}

    def test_requeue_items_by_decision(self, runner: LoopRunner) -> None:
        accepted = runner._requeue_items(
            {
                "decision": "accepted",
                "capability_id": "self-model-build",
                "updated_state": {
                    "confidence_level": "low",
                    "readiness": "provisional",
                },
            }
        )
        assert accepted[0]["title"] == "re-validate self-model-build"
        assert accepted[0]["priority"] == "normal"

        rejected = runner._requeue_items(
            {
                "decision": "rejected",
                "capability_id": "self-model-build",
                "reason": "no determinable outcome",
            }
        )
        assert rejected[0]["priority"] == "high"
        assert "rejected" in rejected[0]["title"]


class TestCli:
    def test_cli_loop_run_json(self, tmp_path: Any) -> None:
        result = CliRunner().invoke(
            cli,
            [
                "loop-run",
                "--cycles",
                "1",
                "--artifacts-root",
                str(tmp_path / "artifacts"),
                "--json-output",
            ],
        )
        assert result.exit_code == 0, result.output
        report = json.loads(result.output)
        assert report["status"] == "passed"
        assert report["cycles"][0]["evidence_decision"] == "accepted"

    def test_cli_loop_run_rejects_excess_cycles(
        self, tmp_path: Any
    ) -> None:
        result = CliRunner().invoke(
            cli,
            [
                "loop-run",
                "--cycles",
                "99",
                "--artifacts-root",
                str(tmp_path / "artifacts"),
            ],
        )
        assert result.exit_code == 1
        assert "bounded" in result.output
