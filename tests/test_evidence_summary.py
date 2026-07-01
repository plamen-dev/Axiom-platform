"""Tests for the Local Runner ``emit_evidence_summary`` action (PR B, variant A).

Covers the evidence-summary proof object: substantive vs EMPTY/quarantined
bundles, no-bundle blocked-with-guidance, no absolute paths, no raw stdout leak,
and the allowlist boundary (only the explicit named action, no task-supplied
summary/evidence paths).
"""

import json
import sys
from pathlib import Path

# Add tools/ to path so we can import the local_runner package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from local_runner.evidence_summary import (  # noqa: E402
    build_evidence_summary,
    write_evidence_summary,
)
from local_runner.local_runner import (  # noqa: E402
    ALLOWED_ACTIONS,
    WORKSPACE_ROOTS_ENV,
    execute_task,
    validate_task,
)


def _write_bundle(
    ws: Path,
    run_id: str,
    capability_id: str,
    metrics: dict,
    quality_verdict: str,
    status: str = "PASS",
    write_trace: bool = True,
) -> Path:
    """Create artifacts/execution_chain/<run_id>/{evidence,trace}.json."""
    run_dir = ws / "artifacts" / "execution_chain" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    evidence_id = f"ev-{run_id}"
    zero_metrics = [] if quality_verdict == "SUBSTANTIVE" else ["module_count"]
    evidence = {
        "evidence_id": evidence_id,
        "metrics": metrics,
        "quality": {
            "verdict": quality_verdict,
            "reason": f"{quality_verdict.lower()} evidence for {capability_id}",
            "required_metrics": ["module_count"],
            "zero_metrics": zero_metrics,
            "schema_version": "1.0",
        },
        "references": {
            "capability_id": capability_id,
            "result_id": f"res-{run_id}",
            "artifact_id": f"art-{run_id}",
        },
        "summary": f"Evidence for {capability_id} chain run.",
    }
    (run_dir / "evidence.json").write_text(json.dumps(evidence), encoding="utf-8")
    if write_trace:
        trace = {
            "run_id": run_id,
            "capability_id": capability_id,
            "status": status,
            "created_at": "2026-01-01T00:00:00+00:00",
            "evidence_id": evidence_id,
        }
        (run_dir / "trace.json").write_text(json.dumps(trace), encoding="utf-8")
    return run_dir / "evidence.json"


def _write_intake(
    ws: Path,
    intake_id: str,
    run_id: str,
    decision: str,
    prior: dict,
    updated: dict,
    state_changed: bool,
) -> None:
    """Create artifacts/capability_evidence_intake/<intake_id>/report.json."""
    d = ws / "artifacts" / "capability_evidence_intake" / intake_id
    d.mkdir(parents=True, exist_ok=True)
    evidence_id = f"ev-{run_id}"
    report = {
        "intake_id": intake_id,
        "decision": decision,
        "state_changed": state_changed,
        "prior_state": prior,
        "updated_state": updated,
        "evidence_fingerprint": f"evidence_id:{evidence_id}",
        "links": {
            "chain_run_id": run_id,
            "evidence_id": evidence_id,
            "evidence_path": f"artifacts/execution_chain/{run_id}/evidence.json",
        },
    }
    (d / "report.json").write_text(json.dumps(report), encoding="utf-8")


_SUBSTANTIVE_STATE_PRIOR = {
    "confidence_level": "very_low",
    "readiness": "blocked",
    "score": 0.0,
    "confidence_report_id": "",
}
_SUBSTANTIVE_STATE_UPDATED = {
    "confidence_level": "very_high",
    "readiness": "ready",
    "score": 1.0,
    "confidence_report_id": "conf-1",
}
_EMPTY_STATE = {
    "confidence_level": "very_low",
    "readiness": "blocked",
    "score": 0.0,
    "confidence_report_id": "",
}


class TestSubstantiveSummary:
    def test_summary_from_substantive_bundle(self, tmp_path):
        ev = _write_bundle(
            tmp_path,
            "run-sub",
            "self-model-build",
            {"module_count": 167, "import_edge_count": 359, "isolated_module_count": 9},
            "SUBSTANTIVE",
        )
        _write_intake(
            tmp_path,
            "intake-sub",
            "run-sub",
            "accepted",
            _SUBSTANTIVE_STATE_PRIOR,
            _SUBSTANTIVE_STATE_UPDATED,
            state_changed=True,
        )
        summary = build_evidence_summary(tmp_path, ev)

        assert summary["capability_id"] == "self-model-build"
        assert summary["run_id"] == "run-sub"
        assert summary["chain_status"] == "PASS"
        assert summary["quality_verdict"] == "SUBSTANTIVE"
        assert summary["decision"] == "accepted"
        assert summary["state_changed"] is True
        assert summary["current_state"]["confidence_level"] == "very_high"
        assert summary["current_state"]["readiness"] == "ready"
        assert summary["before_after"]["before"]["confidence_level"] == "very_low"
        assert summary["before_after"]["after"]["confidence_level"] == "very_high"
        assert summary["before_after"]["before"]["readiness"] == "blocked"
        assert summary["before_after"]["after"]["readiness"] == "ready"

    def test_summary_written_to_validation_runs(self, tmp_path):
        ev = _write_bundle(
            tmp_path,
            "run-sub",
            "self-model-build",
            {"module_count": 5},
            "SUBSTANTIVE",
        )
        summary = build_evidence_summary(tmp_path, ev)
        json_rel, md_rel = write_evidence_summary(tmp_path, summary)

        assert json_rel.startswith("artifacts/validation_runs/")
        assert json_rel.endswith("evidence_summary.json")
        assert md_rel.endswith("evidence_summary.md")
        json_path = tmp_path / json_rel
        md_path = tmp_path / md_rel
        assert json_path.is_file()
        assert md_path.is_file()
        # JSON round-trips and the markdown mentions the verdict.
        loaded = json.loads(json_path.read_text(encoding="utf-8"))
        assert loaded["summary_id"] == summary["summary_id"]
        assert "SUBSTANTIVE" in md_path.read_text(encoding="utf-8")


class TestEmptyQuarantinedSummary:
    def test_empty_bundle_quarantined_no_state_jump(self, tmp_path):
        ev = _write_bundle(
            tmp_path,
            "run-empty",
            "self-model-build",
            {"module_count": 0, "import_edge_count": 0, "isolated_module_count": 0},
            "EMPTY",
        )
        _write_intake(
            tmp_path,
            "intake-empty",
            "run-empty",
            "quarantined",
            _EMPTY_STATE,
            _EMPTY_STATE,
            state_changed=False,
        )
        summary = build_evidence_summary(tmp_path, ev)

        assert summary["quality_verdict"] == "EMPTY"
        assert summary["decision"] == "quarantined"
        assert summary["state_changed"] is False
        # No confidence / readiness jump for quarantined evidence.
        before = summary["before_after"]["before"]
        after = summary["before_after"]["after"]
        assert before["confidence_level"] == after["confidence_level"] == "very_low"
        assert before["readiness"] == after["readiness"] == "blocked"
        # Chain id-flow status is untouched (still PASS) even though quality=EMPTY.
        assert summary["chain_status"] == "PASS"

    def test_bundle_not_applied_yet(self, tmp_path):
        """Emit is independent of apply: no intake record -> decision not_applied."""
        ev = _write_bundle(
            tmp_path,
            "run-noapply",
            "self-model-build",
            {"module_count": 3},
            "SUBSTANTIVE",
        )
        summary = build_evidence_summary(tmp_path, ev)
        assert summary["decision"] == "not_applied"
        assert summary["before_after"] is None
        assert summary["current_state"]["confidence_level"] is None


class TestNoAbsolutePaths:
    def test_no_absolute_paths_in_summary(self, tmp_path):
        ev = _write_bundle(
            tmp_path,
            "run-abs",
            "self-model-build",
            {"module_count": 12},
            "SUBSTANTIVE",
        )
        _write_intake(
            tmp_path,
            "intake-abs",
            "run-abs",
            "accepted",
            _SUBSTANTIVE_STATE_PRIOR,
            _SUBSTANTIVE_STATE_UPDATED,
            state_changed=True,
        )
        summary = build_evidence_summary(tmp_path, ev)
        json_rel, md_rel = write_evidence_summary(tmp_path, summary)

        blob = json.dumps(summary) + (tmp_path / json_rel).read_text(encoding="utf-8")
        blob += (tmp_path / md_rel).read_text(encoding="utf-8")
        # Machine-specific workspace path must never appear.
        assert str(tmp_path) not in blob
        # Every recorded source artifact path is relative under artifacts/.
        for rel in summary["source_artifacts"].values():
            assert not rel.startswith("/")
            assert ":\\" not in rel
            assert ":/" not in rel
            assert rel.startswith("artifacts/")


class TestNoStdoutLeak:
    def test_summary_has_no_raw_stdout_field(self, tmp_path):
        ev = _write_bundle(
            tmp_path,
            "run-nostdout",
            "self-model-build",
            {"module_count": 7},
            "SUBSTANTIVE",
        )
        summary = build_evidence_summary(tmp_path, ev)
        # Only the approved compact keys; no captured process output.
        assert "stdout" not in summary
        assert "stderr" not in summary
        for value in summary.values():
            if isinstance(value, str):
                assert "Traceback" not in value


class TestAllowlistBoundary:
    def test_action_is_allowlisted(self):
        assert "emit_evidence_summary" in ALLOWED_ACTIONS
        action_def = ALLOWED_ACTIONS["emit_evidence_summary"]
        assert action_def.get("emit_summary") is True
        # It runs no subprocess commands of its own.
        assert action_def.get("commands") == []

    def test_task_supplied_command_rejected(self):
        task = {
            "action": "emit_evidence_summary",
            "workspace": str(Path(__file__).resolve().parents[1]),
            "command": ["rm", "-rf", "/"],
        }
        error = validate_task(task)
        assert error is not None
        assert "Arbitrary command execution is not allowed" in error

    def test_task_supplied_paths_are_ignored(self, tmp_path, monkeypatch):
        """A task-supplied summary/evidence path must not steer the runner."""
        monkeypatch.setenv(WORKSPACE_ROOTS_ENV, str(tmp_path))
        ev = _write_bundle(
            tmp_path,
            "run-ignore",
            "self-model-build",
            {"module_count": 4},
            "SUBSTANTIVE",
        )
        assert ev.is_file()
        task = {
            "action": "emit_evidence_summary",
            "workspace": str(tmp_path),
            # These are ignored: the runner resolves its own newest bundle.
            "evidence": "/etc/passwd",
            "summary_path": "/tmp/anywhere",
        }
        result = execute_task(task, artifact_base=str(tmp_path / "runs"))
        assert result.status == "success"
        # Summary was written under the workspace, not the supplied path.
        written = list(
            (tmp_path / "artifacts" / "validation_runs").glob("*/evidence_summary.json")
        )
        assert len(written) == 1
        loaded = json.loads(written[0].read_text(encoding="utf-8"))
        assert loaded["run_id"] == "run-ignore"


class TestExecuteTaskEmit:
    def test_blocked_with_guidance_when_no_bundle(self, tmp_path, monkeypatch):
        monkeypatch.setenv(WORKSPACE_ROOTS_ENV, str(tmp_path))
        task = {"action": "emit_evidence_summary", "workspace": str(tmp_path)}
        result = execute_task(task, artifact_base=str(tmp_path / "runs"))
        assert result.status == "blocked"
        assert "execution_chain_run" in result.error_message

    def test_emit_produces_artifacts_and_no_stdout_dump(self, tmp_path, monkeypatch):
        monkeypatch.setenv(WORKSPACE_ROOTS_ENV, str(tmp_path))
        _write_bundle(
            tmp_path,
            "run-exec",
            "self-model-build",
            {"module_count": 21},
            "SUBSTANTIVE",
        )
        task = {"action": "emit_evidence_summary", "workspace": str(tmp_path)}
        result = execute_task(task, artifact_base=str(tmp_path / "runs"))
        assert result.status == "success"
        assert result.exit_code == 0
        # Runner stdout only points at the written files; no artifact dumps.
        assert "evidence_summary.json" in result.stdout
        assert str(tmp_path) not in result.stdout
        artifact_dir = Path(result.artifact_dir)
        assert (artifact_dir / "run_log.json").exists()
        assert (artifact_dir / "result_summary.md").exists()
