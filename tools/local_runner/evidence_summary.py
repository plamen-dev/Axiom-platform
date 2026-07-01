"""Build a compact, tracked evidence summary (proof object) for the loop.

Backs the Local Runner ``emit_evidence_summary`` action. It reads only
runner-derived, sandbox-validated artifacts already produced inside the
workspace by the execution chain and (optionally) capability-evidence-apply,
and emits a durable, committable record under
``artifacts/validation_runs/<summary_id>/``.

Boundaries (approved for PR B, variant A):

* read-only — never mutates confidence / readiness / promotion / capability state;
* no task-supplied paths — the newest chain bundle is resolved by the runner;
* no raw stdout, no secrets, no absolute or machine-specific paths;
* no new evidence framework — this only *summarizes* existing artifacts.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"


def _rel(path: Path, workspace: Path) -> str:
    """Return ``path`` relative to ``workspace`` (posix), else just its name.

    Never returns an absolute or machine-specific path.
    """
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return path.name


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _git_commit(workspace: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
    except OSError:
        return None
    return out or None


def _find_intake_for_run(
    workspace: Path, run_id: str, evidence_id: str
) -> dict[str, Any] | None:
    """Return the newest intake report linked to this chain run / evidence.

    Matches by ``links.chain_run_id`` or ``links.evidence_id`` /
    ``evidence_fingerprint``. Returns ``None`` when the evidence has not been
    applied (emit is independent of apply by design).
    """
    intake_dir = workspace / "artifacts" / "capability_evidence_intake"
    if not intake_dir.is_dir():
        return None

    matches: list[tuple[float, dict[str, Any]]] = []
    for report_path in intake_dir.glob("*/report.json"):
        report = _load_json(report_path)
        if not report:
            continue
        links = report.get("links", {}) or {}
        fingerprint = str(report.get("evidence_fingerprint", ""))
        if (
            (run_id and links.get("chain_run_id") == run_id)
            or (evidence_id and links.get("evidence_id") == evidence_id)
            or (evidence_id and evidence_id in fingerprint)
        ):
            matches.append((report_path.stat().st_mtime, report))

    if not matches:
        return None
    matches.sort(key=lambda m: m[0], reverse=True)
    return matches[0][1]


def _confidence_readiness(state: dict[str, Any] | None) -> dict[str, Any]:
    state = state or {}
    return {
        "confidence_level": state.get("confidence_level"),
        "readiness": state.get("readiness"),
        "score": state.get("score"),
    }


def build_evidence_summary(
    workspace: str | Path,
    evidence_path: str | Path,
    summary_id: str | None = None,
) -> dict[str, Any]:
    """Assemble the evidence summary dict from workspace artifacts.

    ``evidence_path`` is the runner-resolved newest ``evidence.json`` bundle.
    """
    ws = Path(workspace)
    ev_path = Path(evidence_path)
    run_dir = ev_path.parent

    evidence = _load_json(ev_path) or {}
    trace = _load_json(run_dir / "trace.json") or {}

    references = evidence.get("references", {}) or {}
    quality = evidence.get("quality", {}) or {}
    capability_id = references.get("capability_id") or trace.get("capability_id")
    run_id = trace.get("run_id") or run_dir.name
    evidence_id = evidence.get("evidence_id") or trace.get("evidence_id") or ""

    intake = _find_intake_for_run(ws, run_id, evidence_id)

    source_paths: dict[str, str] = {
        "evidence_json": _rel(ev_path, ws),
    }
    if (run_dir / "trace.json").is_file():
        source_paths["trace_json"] = _rel(run_dir / "trace.json", ws)

    if intake is not None:
        decision = intake.get("decision")
        prior = intake.get("prior_state")
        updated = intake.get("updated_state")
        intake_id = intake.get("intake_id")
        if intake_id:
            source_paths["intake_report_json"] = (
                f"artifacts/capability_evidence_intake/{intake_id}/report.json"
            )
        confidence_report_id = (updated or {}).get("confidence_report_id")
        if confidence_report_id:
            source_paths["confidence_report_json"] = (
                f"artifacts/capability_confidence/{confidence_report_id}/report.json"
            )
        current_state = _confidence_readiness(updated or prior)
        before_after = {
            "before": _confidence_readiness(prior),
            "after": _confidence_readiness(updated),
        }
        state_changed = intake.get("state_changed")
    else:
        decision = "not_applied"
        current_state = _confidence_readiness(None)
        before_after = None
        state_changed = None

    return {
        "schema_version": SCHEMA_VERSION,
        "summary_id": summary_id or uuid.uuid4().hex,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(ws),
        "run_id": run_id,
        "capability_id": capability_id,
        "chain_status": trace.get("status"),
        "evidence_id": evidence_id,
        "quality_verdict": quality.get("verdict"),
        "quality_reason": quality.get("reason"),
        "decision": decision,
        "state_changed": state_changed,
        "current_state": current_state,
        "before_after": before_after,
        "source_artifacts": source_paths,
    }


def _render_markdown(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Evidence Summary")
    lines.append("")
    lines.append(f"- **Summary ID:** {summary.get('summary_id')}")
    lines.append(f"- **Generated (UTC):** {summary.get('generated_at_utc')}")
    lines.append(f"- **Git commit:** {summary.get('git_commit') or 'unknown'}")
    lines.append(f"- **Capability:** {summary.get('capability_id')}")
    lines.append(f"- **Chain run ID:** {summary.get('run_id')}")
    lines.append(f"- **Chain id-flow status:** {summary.get('chain_status')}")
    lines.append(f"- **Evidence quality:** {summary.get('quality_verdict')}")
    lines.append(f"- **Promotion decision:** {summary.get('decision')}")
    lines.append(f"- **State changed:** {summary.get('state_changed')}")
    lines.append("")

    cur = summary.get("current_state", {})
    lines.append("## Current capability state")
    lines.append("")
    lines.append(f"- Confidence: {cur.get('confidence_level')}")
    lines.append(f"- Readiness: {cur.get('readiness')}")
    lines.append(f"- Score: {cur.get('score')}")
    lines.append("")

    ba = summary.get("before_after")
    if ba:
        before = ba.get("before", {})
        after = ba.get("after", {})
        lines.append("## Before -> after")
        lines.append("")
        lines.append(
            f"- Confidence: {before.get('confidence_level')} -> "
            f"{after.get('confidence_level')}"
        )
        lines.append(
            f"- Readiness: {before.get('readiness')} -> {after.get('readiness')}"
        )
        lines.append("")

    lines.append("## Source artifacts (relative)")
    lines.append("")
    for name, rel in summary.get("source_artifacts", {}).items():
        lines.append(f"- **{name}:** `{rel}`")
    lines.append("")

    if summary.get("quality_reason"):
        lines.append("## Quality reason")
        lines.append("")
        lines.append(summary["quality_reason"])
        lines.append("")

    return "\n".join(lines)


def write_evidence_summary(
    workspace: str | Path, summary: dict[str, Any]
) -> tuple[str, str]:
    """Write ``evidence_summary.{json,md}`` and return their relative paths."""
    ws = Path(workspace)
    summary_id = summary["summary_id"]
    out_dir = ws / "artifacts" / "validation_runs" / summary_id
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "evidence_summary.json"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    md_path = out_dir / "evidence_summary.md"
    md_path.write_text(_render_markdown(summary), encoding="utf-8")

    return _rel(json_path, ws), _rel(md_path, ws)
