"""Capability State Registry v1 (PR #27) — durable capability lifecycle state.

Axiom can already discover, define, validate, govern, execute, and produce
evidence for capabilities. What it lacked was a durable *memory* of where each
capability sits in its lifecycle. This module provides that state layer by
**summarizing existing sources** into one durable per-capability record:

* the **Runner Command Registry** (PR #22) — which command a capability drives
  and whether it is allowed,
* the **Capability Validation Registry** (PR #24) — which capabilities have a
  validation definition (and their adapter / capability type),
* **Capability Execution Runner** evidence bundles (PR #26) under
  ``artifacts/capability_runs/`` — execution outcomes,
* **Validation Evidence Runner** bundles (PR #25) under
  ``artifacts/validation_evidence/`` — validation outcomes,
* **DiscoveryHarness** candidate capabilities (PR #20), when a SQLite session is
  supplied — discovered candidates.

This is state/governance infrastructure ONLY. It executes nothing, retries
nothing, promotes nothing, schedules nothing, and contains no learning loop.
``promotion_candidate`` is a non-binding derived flag for a *future* promotion
engine — it triggers no action here.

State is derived deterministically: capabilities are keyed by ``capability_name``
and events are ordered by ``(at, run_id)`` so the same inputs always yield the
same snapshot. Persistence reuses the shared SQLite stack
(:mod:`axiom_core.database` + the declarative ``Base`` in
:mod:`axiom_core.models`); no new database technology is introduced.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import sessionmaker

from axiom_core.database import get_session
from axiom_core.models import (
    CandidateCapabilityRow,
    CapabilityStateEventRow,
    CapabilityStateRow,
)
from axiom_core.runner import capability_runner as caprun
from axiom_core.runner import command_registry as cmdreg
from axiom_core.validation import validation_registry as valreg

_logger = logging.getLogger(__name__)

DEFAULT_CAPABILITY_RUNS_BASE = "artifacts/capability_runs"
DEFAULT_VALIDATION_EVIDENCE_BASE = "artifacts/validation_evidence"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    """Best-effort ISO-8601 parse to naive UTC (SQLite stores naive datetimes)."""
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        dt = datetime.fromtimestamp(0, tz=timezone.utc)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ---------------------------------------------------------------------------
# Lifecycle status taxonomy
# ---------------------------------------------------------------------------


class CapabilityStatus(str, Enum):
    """Where a capability currently sits in its lifecycle.

    ``denied`` extends the suggested set because the Capability Execution Runner
    (PR #26) emits it for capabilities that are not cataloged; tracking it keeps
    the lifecycle truthful. No status here implies any autonomous action.
    """

    DISCOVERED = "discovered"                  # surfaced as a discovery candidate
    DEFINED = "defined"                        # known capability, no richer signal yet
    VALIDATION_DEFINED = "validation_defined"  # has a validation registry definition
    VALIDATION_PASSED = "validation_passed"    # latest validation evidence passed
    VALIDATION_FAILED = "validation_failed"    # latest validation evidence failed
    EXECUTABLE = "executable"                  # an execution runner can drive it
    EXECUTION_PASSED = "execution_passed"      # latest execution evidence passed
    EXECUTION_FAILED = "execution_failed"      # latest execution evidence failed
    BLOCKED = "blocked"                        # latest run blocked (prereqs unmet)
    REFUSED = "refused"                        # latest run refused by policy
    UNSUPPORTED = "unsupported"                # known but no runner support yet
    DENIED = "denied"                          # not cataloged — denied by default
    DEPRECATED = "deprecated"                  # retired (never set automatically)


# Outcome string (from a pass_fail.json / result.json) → status, per evidence
# kind. Both maps are total over the runner/evidence outcome vocabularies.
_EXECUTION_OUTCOME_STATUS: dict[str, CapabilityStatus] = {
    "passed": CapabilityStatus.EXECUTION_PASSED,
    "failed": CapabilityStatus.EXECUTION_FAILED,
    "refused": CapabilityStatus.REFUSED,
    "blocked": CapabilityStatus.BLOCKED,
    "unsupported": CapabilityStatus.UNSUPPORTED,
    "denied": CapabilityStatus.DENIED,
}
_VALIDATION_OUTCOME_STATUS: dict[str, CapabilityStatus] = {
    "passed": CapabilityStatus.VALIDATION_PASSED,
    "failed": CapabilityStatus.VALIDATION_FAILED,
    "refused": CapabilityStatus.REFUSED,
    "blocked": CapabilityStatus.BLOCKED,
    "unsupported": CapabilityStatus.UNSUPPORTED,
    "denied": CapabilityStatus.DENIED,
}

EXECUTION = "execution"
VALIDATION = "validation"


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapabilityHistoryEvent:
    """One observed lifecycle event derived from a single evidence bundle."""

    capability_name: str
    kind: str             # EXECUTION | VALIDATION
    outcome: str
    run_id: str
    evidence_path: str
    at: str               # ISO timestamp from the bundle (finished/started)
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "capability_name": self.capability_name,
            "kind": self.kind,
            "outcome": self.outcome,
            "run_id": self.run_id,
            "evidence_path": self.evidence_path,
            "at": self.at,
            "detail": self.detail,
        }


@dataclass
class CapabilityHistory:
    """The ordered event history for a single capability (oldest first)."""

    capability_name: str
    events: list[CapabilityHistoryEvent] = field(default_factory=list)

    def add(self, event: CapabilityHistoryEvent) -> None:
        self.events.append(event)

    def sorted_events(self) -> list[CapabilityHistoryEvent]:
        return sorted(self.events, key=lambda e: (e.at, e.run_id, e.kind))

    def latest(self, kind: str | None = None) -> CapabilityHistoryEvent | None:
        candidates = [e for e in self.sorted_events() if kind is None or e.kind == kind]
        return candidates[-1] if candidates else None

    def to_dict(self) -> dict:
        return {
            "capability_name": self.capability_name,
            "events": [e.to_dict() for e in self.sorted_events()],
        }


# ---------------------------------------------------------------------------
# State + snapshot
# ---------------------------------------------------------------------------


@dataclass
class CapabilityState:
    """The durable lifecycle state record for one capability."""

    capability_name: str
    adapter: str
    capability_type: str
    current_status: CapabilityStatus
    source_registry: str
    first_seen_at: str
    last_seen_at: str
    last_validation_run_id: Optional[str] = None
    last_execution_run_id: Optional[str] = None
    last_evidence_path: Optional[str] = None
    pass_count: int = 0
    fail_count: int = 0
    refused_count: int = 0
    blocked_count: int = 0
    unsupported_count: int = 0
    last_error_summary: str = ""
    promotion_candidate: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "capability_name": self.capability_name,
            "adapter": self.adapter,
            "capability_type": self.capability_type,
            "current_status": self.current_status.value,
            "source_registry": self.source_registry,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "last_validation_run_id": self.last_validation_run_id,
            "last_execution_run_id": self.last_execution_run_id,
            "last_evidence_path": self.last_evidence_path,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "refused_count": self.refused_count,
            "blocked_count": self.blocked_count,
            "unsupported_count": self.unsupported_count,
            "last_error_summary": self.last_error_summary,
            "promotion_candidate": self.promotion_candidate,
            "metadata": self.metadata,
        }


@dataclass
class CapabilitySnapshot:
    """A point-in-time view of every tracked capability's state."""

    generated_at: str
    states: list[CapabilityState] = field(default_factory=list)

    def names(self) -> list[str]:
        return [s.capability_name for s in self.states]

    def get(self, capability_name: str) -> CapabilityState | None:
        for s in self.states:
            if s.capability_name == capability_name:
                return s
        return None

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for s in self.states:
            counts[s.current_status.value] = counts.get(s.current_status.value, 0) + 1
        return dict(sorted(counts.items()))

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "count": len(self.states),
            "status_counts": self.status_counts(),
            "promotion_candidates": sorted(
                s.capability_name for s in self.states if s.promotion_candidate),
            "capabilities": [s.to_dict() for s in self.states],
        }


# ---------------------------------------------------------------------------
# Artifact scanning (read-only)
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _scan_bundles(
    base: Path,
    result_filename: str,
    kind: str,
    *,
    fallback_to_dir: bool,
) -> list[CapabilityHistoryEvent]:
    """Summarize evidence bundles under ``base`` into history events.

    Layout is ``<base>/<dir>/<run_id>/{pass_fail.json,<result_filename>}``. The
    capability name comes from the result's ``capability_name``. When that is
    absent/null, execution bundles fall back to the directory name
    (``fallback_to_dir=True``); validation bundles do not — a validation with no
    associated capability (e.g. an infrastructure validation like
    ``CommandRegistry``) is not a capability lifecycle event and is skipped.
    Read-only; never triggers a run.
    """
    events: list[CapabilityHistoryEvent] = []
    if not base.is_dir():
        return events
    for cap_dir in sorted(base.iterdir()):
        if not cap_dir.is_dir():
            continue
        for run_dir in sorted(cap_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            pass_fail = _read_json(run_dir / "pass_fail.json")
            result = _read_json(run_dir / result_filename)
            data = {**pass_fail, **result}  # result fields win where both exist
            outcome = data.get("outcome")
            if not outcome:
                continue
            capability_name = result.get("capability_name")
            if not capability_name and fallback_to_dir:
                capability_name = cap_dir.name
            if not capability_name:
                continue
            at = data.get("finished_at") or data.get("started_at") or ""
            events.append(
                CapabilityHistoryEvent(
                    capability_name=capability_name,
                    kind=kind,
                    outcome=str(outcome),
                    run_id=run_dir.name,
                    evidence_path=str(run_dir),
                    at=at,
                    detail=str(data.get("reason", "")),
                )
            )
    return events


def _load_candidate_capabilities(session_factory: sessionmaker | None) -> dict[str, dict]:
    """Return ``{capability_name: {count, adapter}}`` for discovery candidates.

    Best-effort: returns empty if no session factory is supplied or the table is
    absent. Never executes discovery.
    """
    if session_factory is None:
        return {}
    try:
        with get_session(session_factory) as session:
            rows = session.query(
                CandidateCapabilityRow.capability,
                CandidateCapabilityRow.adapter,
            ).all()
    except Exception:
        return {}
    out: dict[str, dict] = {}
    for capability, adapter in rows:
        if not capability:
            continue
        entry = out.setdefault(capability, {"count": 0, "adapter": adapter or "revit"})
        entry["count"] += 1
    return out


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass
class _Seed:
    adapter: str = "revit"
    capability_type: str = ""
    sources: set[str] = field(default_factory=set)
    executable: bool = False
    validation_defined: bool = False
    discovered: bool = False
    command_name: str | None = None
    command_allowed: bool | None = None
    candidate_count: int = 0


class CapabilityStateRegistry:
    """Builds and persists durable capability lifecycle state.

    Read paths (``snapshot``/``get_state``/``history``) never write. Only
    :meth:`refresh` writes, and only when a ``session_factory`` is configured.
    """

    def __init__(
        self,
        *,
        capability_runs_base: str | Path = DEFAULT_CAPABILITY_RUNS_BASE,
        validation_evidence_base: str | Path = DEFAULT_VALIDATION_EVIDENCE_BASE,
        session_factory: sessionmaker | None = None,
    ) -> None:
        self.capability_runs_base = Path(capability_runs_base)
        self.validation_evidence_base = Path(validation_evidence_base)
        self.session_factory = session_factory

    # -- seeding -----------------------------------------------------------

    def _seeds(self) -> dict[str, _Seed]:
        seeds: dict[str, _Seed] = {}

        def seed_for(name: str) -> _Seed:
            return seeds.setdefault(name, _Seed())

        # Validation Registry — capabilities with a validation definition.
        for proc in valreg.list_procedures():
            s = seed_for(proc.capability_name)
            s.validation_defined = True
            s.adapter = proc.adapter or s.adapter
            s.capability_type = proc.capability_type.value
            s.sources.add("validation_registry")

        # Capability Execution Runner — capabilities with a safe executor, gated
        # against the Command Registry.
        for name, supported in caprun.SUPPORTED_CAPABILITIES.items():
            s = seed_for(name)
            s.executable = True
            s.command_name = supported.command_name
            s.command_allowed = cmdreg.is_allowed(supported.command_name)
            s.sources.add("command_registry")

        # DiscoveryHarness — candidate capabilities (best-effort, optional).
        for name, info in _load_candidate_capabilities(self.session_factory).items():
            s = seed_for(name)
            s.discovered = True
            s.candidate_count = info["count"]
            if not s.capability_type:
                s.adapter = info.get("adapter", s.adapter)
            s.sources.add("discovery")

        return seeds

    # -- building ----------------------------------------------------------

    def histories(self) -> dict[str, CapabilityHistory]:
        """Per-capability event history derived from evidence artifacts."""
        events = (
            _scan_bundles(self.capability_runs_base, "capability_result.json",
                          EXECUTION, fallback_to_dir=True)
            + _scan_bundles(self.validation_evidence_base, "validation_result.json",
                            VALIDATION, fallback_to_dir=False)
        )
        histories: dict[str, CapabilityHistory] = {}
        for ev in events:
            histories.setdefault(
                ev.capability_name, CapabilityHistory(ev.capability_name)).add(ev)
        return histories

    def build_snapshot(
        self,
        *,
        at: str | None = None,
        histories: dict[str, CapabilityHistory] | None = None,
    ) -> CapabilitySnapshot:
        """Deterministically derive a snapshot from registries + artifacts.

        Pure read: never writes to the database or filesystem. ``histories`` may
        be supplied to reuse a single artifact scan (so a caller that also
        persists the event history derives both from the same scan); when
        omitted it is scanned here.
        """
        generated_at = at or _now_iso()
        seeds = self._seeds()
        if histories is None:
            histories = self.histories()

        names = sorted(set(seeds) | set(histories))
        states = [
            self._build_state(name, seeds.get(name), histories.get(name), generated_at)
            for name in names
        ]
        return CapabilitySnapshot(generated_at=generated_at, states=states)

    def _build_state(
        self,
        name: str,
        seed: _Seed | None,
        history: CapabilityHistory | None,
        generated_at: str,
    ) -> CapabilityState:
        seed = seed or _Seed()
        events = history.sorted_events() if history else []

        pass_count = fail_count = refused_count = blocked_count = unsupported_count = 0
        denied_count = validation_pass = validation_fail = 0
        for ev in events:
            if ev.kind == EXECUTION:
                if ev.outcome == "passed":
                    pass_count += 1
                elif ev.outcome == "failed":
                    fail_count += 1
                elif ev.outcome == "refused":
                    refused_count += 1
                elif ev.outcome == "blocked":
                    blocked_count += 1
                elif ev.outcome == "unsupported":
                    unsupported_count += 1
                elif ev.outcome == "denied":
                    denied_count += 1
            elif ev.kind == VALIDATION:
                if ev.outcome == "passed":
                    validation_pass += 1
                elif ev.outcome == "failed":
                    validation_fail += 1

        latest_exec = next(
            (e for e in reversed(events) if e.kind == EXECUTION), None)
        latest_val = next(
            (e for e in reversed(events) if e.kind == VALIDATION), None)
        latest_any = events[-1] if events else None
        latest_failure = next(
            (e for e in reversed(events) if e.outcome != "passed"), None)

        current_status = self._derive_status(seed, latest_exec, latest_val)

        # first/last seen: span the observed evidence, anchored at refresh time.
        event_times = [e.at for e in events if e.at]
        first_seen_at = min(event_times) if event_times else generated_at
        last_seen_at = generated_at

        # Promotion candidate (non-binding): a validation-defined capability that
        # is currently passing, has at least one pass in the dimension that
        # determines that status, and no failures in either dimension. Counting
        # both dimensions keeps the VALIDATION_PASSED branch reachable for
        # capabilities that have a passing validation but no execution evidence
        # yet (execution-only counts would make that branch dead).
        promotion_candidate = (
            seed.validation_defined
            and current_status in (
                CapabilityStatus.EXECUTION_PASSED, CapabilityStatus.VALIDATION_PASSED)
            and (pass_count + validation_pass) >= 1
            and fail_count == 0
            and validation_fail == 0
        )

        metadata = {
            "sources": sorted(seed.sources) if seed.sources else ["artifact"],
            "executable": seed.executable,
            "validation_defined": seed.validation_defined,
            "discovered": seed.discovered,
            "command_name": seed.command_name,
            "command_allowed": seed.command_allowed,
            "candidate_count": seed.candidate_count,
            "denied_count": denied_count,
            "validation_pass_count": validation_pass,
            "validation_fail_count": validation_fail,
            "event_count": len(events),
        }

        source_registry = "+".join(sorted(seed.sources)) if seed.sources else "artifact"

        return CapabilityState(
            capability_name=name,
            adapter=seed.adapter,
            capability_type=seed.capability_type,
            current_status=current_status,
            source_registry=source_registry,
            first_seen_at=first_seen_at,
            last_seen_at=last_seen_at,
            last_validation_run_id=latest_val.run_id if latest_val else None,
            last_execution_run_id=latest_exec.run_id if latest_exec else None,
            last_evidence_path=latest_any.evidence_path if latest_any else None,
            pass_count=pass_count,
            fail_count=fail_count,
            refused_count=refused_count,
            blocked_count=blocked_count,
            unsupported_count=unsupported_count,
            last_error_summary=latest_failure.detail if latest_failure else "",
            promotion_candidate=promotion_candidate,
            metadata=metadata,
        )

    @staticmethod
    def _derive_status(
        seed: _Seed,
        latest_exec: CapabilityHistoryEvent | None,
        latest_val: CapabilityHistoryEvent | None,
    ) -> CapabilityStatus:
        """Deterministic current status: newest execution > newest validation >
        definitional status (executable > validation_defined > discovered >
        defined)."""
        if latest_exec is not None:
            return _EXECUTION_OUTCOME_STATUS.get(
                latest_exec.outcome, CapabilityStatus.DEFINED)
        if latest_val is not None:
            return _VALIDATION_OUTCOME_STATUS.get(
                latest_val.outcome, CapabilityStatus.DEFINED)
        if seed.executable:
            return CapabilityStatus.EXECUTABLE
        if seed.validation_defined:
            return CapabilityStatus.VALIDATION_DEFINED
        if seed.discovered:
            return CapabilityStatus.DISCOVERED
        return CapabilityStatus.DEFINED

    # -- persistence -------------------------------------------------------

    def refresh(self, *, at: str | None = None) -> CapabilitySnapshot:
        """Rebuild state from registries/artifacts and persist it.

        Requires a ``session_factory``. Idempotent: capability rows are upserted
        (preserving ``first_seen_at``) and the event history is rebuilt.
        """
        if self.session_factory is None:
            raise ValueError("refresh requires a session_factory")
        # Scan the artifacts once so the persisted state summary and the
        # persisted event history always derive from the same snapshot of disk.
        histories = self.histories()
        snapshot = self.build_snapshot(at=at, histories=histories)
        self._persist(snapshot, histories)
        return snapshot

    def _persist(
        self,
        snapshot: CapabilitySnapshot,
        histories: dict[str, CapabilityHistory],
    ) -> None:
        with get_session(self.session_factory) as session:
            for state in snapshot.states:
                row = (
                    session.query(CapabilityStateRow)
                    .filter_by(capability_name=state.capability_name)
                    .one_or_none()
                )
                first_seen = _parse_iso(state.first_seen_at)
                last_seen = _parse_iso(state.last_seen_at)
                values = {
                    "capability_name": state.capability_name,
                    "adapter": state.adapter,
                    "capability_type": state.capability_type,
                    "current_status": state.current_status.value,
                    "source_registry": state.source_registry,
                    "last_seen_at": last_seen,
                    "last_validation_run_id": state.last_validation_run_id,
                    "last_execution_run_id": state.last_execution_run_id,
                    "last_evidence_path": state.last_evidence_path,
                    "pass_count": state.pass_count,
                    "fail_count": state.fail_count,
                    "refused_count": state.refused_count,
                    "blocked_count": state.blocked_count,
                    "unsupported_count": state.unsupported_count,
                    "last_error_summary": state.last_error_summary,
                    "promotion_candidate": state.promotion_candidate,
                    "metadata_json": json.dumps(state.metadata),
                }
                if row is None:
                    session.add(CapabilityStateRow(first_seen_at=first_seen, **values))
                else:
                    # Preserve the earliest first_seen_at across refreshes.
                    if row.first_seen_at is None or first_seen < row.first_seen_at:
                        row.first_seen_at = first_seen
                    for key, value in values.items():
                        setattr(row, key, value)

            # Rebuild the event history deterministically.
            session.query(CapabilityStateEventRow).delete()
            for history in histories.values():
                for ev in history.sorted_events():
                    session.add(CapabilityStateEventRow(
                        capability_name=ev.capability_name,
                        kind=ev.kind,
                        outcome=ev.outcome,
                        run_id=ev.run_id,
                        evidence_path=ev.evidence_path,
                        at=ev.at,
                        detail=ev.detail,
                    ))

    def load_snapshot(self) -> CapabilitySnapshot | None:
        """Load the persisted snapshot, or None if nothing is persisted."""
        if self.session_factory is None:
            return None
        try:
            with get_session(self.session_factory) as session:
                rows = session.query(CapabilityStateRow).all()
                states = []
                for r in rows:
                    try:
                        states.append(self._state_from_row(r))
                    except Exception:
                        _logger.debug(
                            "Skipping corrupt CapabilityStateRow %s",
                            getattr(r, "capability_name", "?"),
                            exc_info=True,
                        )
        except Exception:
            # No capability_states table yet (db predates this feature).
            return None
        if not states:
            return None
        states.sort(key=lambda s: s.capability_name)
        generated_at = max((s.last_seen_at for s in states), default=_now_iso())
        return CapabilitySnapshot(generated_at=generated_at, states=states)

    def load_history(self, capability_name: str) -> CapabilityHistory:
        """Load persisted history for one capability (empty if none/no db)."""
        history = CapabilityHistory(capability_name)
        if self.session_factory is None:
            return history
        with get_session(self.session_factory) as session:
            rows = (
                session.query(CapabilityStateEventRow)
                .filter_by(capability_name=capability_name)
                .all()
            )
        for r in rows:
            history.add(CapabilityHistoryEvent(
                capability_name=r.capability_name,
                kind=r.kind,
                outcome=r.outcome,
                run_id=r.run_id,
                evidence_path=r.evidence_path,
                at=r.at,
                detail=r.detail,
            ))
        return history

    @staticmethod
    def _state_from_row(row: CapabilityStateRow) -> CapabilityState:
        try:
            metadata = json.loads(row.metadata_json) if row.metadata_json else {}
        except ValueError:
            metadata = {}
        return CapabilityState(
            capability_name=row.capability_name,
            adapter=row.adapter,
            capability_type=row.capability_type,
            current_status=CapabilityStatus(row.current_status),
            source_registry=row.source_registry,
            first_seen_at=row.first_seen_at.isoformat() if row.first_seen_at else "",
            last_seen_at=row.last_seen_at.isoformat() if row.last_seen_at else "",
            last_validation_run_id=row.last_validation_run_id,
            last_execution_run_id=row.last_execution_run_id,
            last_evidence_path=row.last_evidence_path,
            pass_count=row.pass_count,
            fail_count=row.fail_count,
            refused_count=row.refused_count,
            blocked_count=row.blocked_count,
            unsupported_count=row.unsupported_count,
            last_error_summary=row.last_error_summary,
            promotion_candidate=row.promotion_candidate,
            metadata=metadata,
        )

    # -- convenience read API ---------------------------------------------

    def snapshot(self, *, prefer_persisted: bool = True) -> CapabilitySnapshot:
        """Return the persisted snapshot if available, else build in-memory.

        Read-only — never writes. When nothing is persisted (or no db is
        configured) it falls back to a freshly built snapshot so the command is
        useful before the first ``--refresh``.
        """
        if prefer_persisted:
            persisted = self.load_snapshot()
            if persisted is not None:
                return persisted
        return self.build_snapshot()

    def get_state(self, capability_name: str) -> CapabilityState | None:
        return self.snapshot().get(capability_name)
