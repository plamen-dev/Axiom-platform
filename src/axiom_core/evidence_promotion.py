"""Evidence to Promotion Loop v1 (M2).

A *thin* adapter that routes execution evidence into a capability's existing
confidence/readiness state instead of leaving it as an inert artifact. It
proves the M2 milestone: execution evidence *changes capability state*.

This module introduces **no new promotion framework, no promotion doctrine and
no new registry**. It is a coordinator only: it reads the evidence bundle that
``execution-chain-run`` already produces, derives a pass/fail outcome from the
chain trace, and feeds it into the existing
:class:`~axiom_core.capability_confidence.CapabilityConfidenceEngine`. The
confidence record (keyed by ``capability_id``) is the durable capability state;
this loop only accumulates one run's outcome onto the prior state.

Decision handling (reusing existing timestamp/state structures):

* passing evidence raises confidence (success factor accumulates);
* failing evidence lowers / does not raise confidence (failure factor
  accumulates), and can drop readiness to ``blocked``;
* evidence without a capability identity is **quarantined** (no state change);
* evidence with no determinable outcome is treated as **missing** and rejected
  (no state change);
* stale evidence (older than an opt-in ``max_age_seconds``, measured from the
  existing ``created_at`` timestamp) is **quarantined** (no state change).

A small intake record is persisted per application so the decision
(accepted / rejected / quarantined), the reason, the before/after state and the
links back to the capability / result / artifact / report are queryable. This
record is an audit artifact following the repository's standard per-engine
``report.json`` + evidence convention; it is **not** a new promotion registry.

Non-goals: no promotion doctrine, no full Evidence-to-Promotion architecture,
no new object family, no Execution Graph Synthesizer, no Organizational State
schema, no Purpose/Layer Index implementation (M3 is recorded as a hook only).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from axiom_core.capability_confidence import (
    CapabilityConfidenceEngine,
    _level_from_score,
)

SCHEMA_VERSION = "1.0"


class EvidencePromotionError(RuntimeError):
    """Raised when an intake record cannot be read back from disk."""


class EvidenceOutcome(str, Enum):
    """The pass/fail outcome derived from one run's evidence."""

    PASS = "pass"
    FAIL = "fail"
    MISSING = "missing"


class EvidenceDecision(str, Enum):
    """What the loop did with the evidence."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


# Tokens that map an evidence ``status`` string onto a pass/fail outcome.
_PASS_TOKENS = {"pass", "passed", "success", "succeeded", "complete", "ok", "true"}
_FAIL_TOKENS = {"fail", "failed", "failure", "error", "errored", "false"}


def _readiness_from_score(score: float) -> str:
    """Map a confidence score onto a deterministic readiness flag.

    Reuses the confidence score thresholds rather than defining a new scale:
    ``ready`` mirrors high/very-high confidence, ``blocked`` mirrors very-low.
    """
    if score >= 0.7:
        return "ready"
    if score >= 0.3:
        return "provisional"
    return "blocked"


@dataclass
class CapabilityStateSnapshot:
    """A before/after view of a capability's confidence-backed state."""

    capability_id: str = ""
    score: float = 0.0
    confidence_level: str = "very_low"
    readiness: str = "blocked"
    execution_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    confidence_report_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "score": self.score,
            "confidence_level": self.confidence_level,
            "readiness": self.readiness,
            "execution_count": self.execution_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "confidence_report_id": self.confidence_report_id,
        }


class EvidencePromotionLoop:
    """Routes execution evidence into existing capability confidence/readiness.

    The loop owns no state model: it reuses :class:`CapabilityConfidenceEngine`
    as the durable capability-state store and persists a small intake record per
    application for queryability.
    """

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._confidence = CapabilityConfidenceEngine(artifacts_root=str(artifacts_root))
        self._intake_dir = self._artifacts_root / "capability_evidence_intake"
        self._intake_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def apply(
        self,
        evidence_path: str,
        capability_id: str = "",
        max_age_seconds: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Apply one evidence bundle to the capability's state.

        ``evidence_path`` is the ``evidence.json`` produced by
        ``execution-chain-run`` (or any bundle carrying a capability identity and
        a determinable pass/fail outcome). ``capability_id`` overrides the
        identity carried by the bundle. ``max_age_seconds`` opts in to staleness
        quarantine using the bundle's ``created_at`` timestamp.
        """
        now = now or datetime.now(timezone.utc)
        bundle, load_error = self._load_bundle(evidence_path)
        self._trace_cache = self._trace(bundle, evidence_path)

        resolved_capability = capability_id.strip() or self._capability_of(bundle)
        links = self._links(bundle, evidence_path)

        # 1. Missing evidence file / unreadable bundle.
        if load_error is not None:
            return self._record(
                resolved_capability, evidence_path, EvidenceOutcome.MISSING,
                EvidenceDecision.REJECTED, load_error, links, now,
            )

        # 2. No capability identity -> quarantine.
        if not resolved_capability:
            return self._record(
                "", evidence_path, self._outcome(bundle)[0],
                EvidenceDecision.QUARANTINED,
                "evidence lacks a capability identity", links, now,
            )

        # 3. Stale evidence -> quarantine (opt-in).
        if max_age_seconds is not None:
            stale_reason = self._staleness_reason(bundle, max_age_seconds, now)
            if stale_reason is not None:
                return self._record(
                    resolved_capability, evidence_path, self._outcome(bundle)[0],
                    EvidenceDecision.QUARANTINED, stale_reason, links, now,
                )

        # 4. Determine pass/fail outcome.
        outcome, outcome_reason = self._outcome(bundle)
        if outcome is EvidenceOutcome.MISSING:
            return self._record(
                resolved_capability, evidence_path, outcome,
                EvidenceDecision.REJECTED, outcome_reason, links, now,
            )

        # 5. Accepted: accumulate the outcome onto prior confidence state.
        prior = self._current_state(resolved_capability)
        execution_count = prior.execution_count + 1
        success_count = prior.success_count + (1 if outcome is EvidenceOutcome.PASS else 0)
        failure_count = prior.failure_count + (1 if outcome is EvidenceOutcome.FAIL else 0)

        report = self._confidence.create(
            capability_id=resolved_capability,
            execution_count=execution_count,
            success_count=success_count,
            failure_count=failure_count,
        )
        updated = CapabilityStateSnapshot(
            capability_id=resolved_capability,
            score=report["score"],
            confidence_level=report["confidence_level"],
            readiness=_readiness_from_score(report["score"]),
            execution_count=execution_count,
            success_count=success_count,
            failure_count=failure_count,
            confidence_report_id=report["report_id"],
        )
        reason = (
            f"{outcome.value} evidence accumulated onto prior state "
            f"({prior.success_count}/{prior.execution_count} -> "
            f"{success_count}/{execution_count}); "
            f"confidence {prior.confidence_level} -> {updated.confidence_level}, "
            f"readiness {prior.readiness} -> {updated.readiness}"
        )
        return self._record(
            resolved_capability, evidence_path, outcome,
            EvidenceDecision.ACCEPTED, reason, links, now,
            prior=prior, updated=updated,
        )

    # ------------------------------------------------------------------
    # State retrieval (reuses the confidence engine as the state store)
    # ------------------------------------------------------------------

    def _current_state(self, capability_id: str) -> CapabilityStateSnapshot:
        """Return the most recent confidence-backed state for a capability."""
        reports = [
            r
            for r in self._confidence.list_reports()
            if r.get("capability_id") == capability_id
        ]
        if not reports:
            return CapabilityStateSnapshot(capability_id=capability_id)
        latest = max(reports, key=lambda r: r.get("created_at", ""))
        factors = (latest.get("confidence") or {}).get("factors", {})
        score = float(latest.get("score", 0.0))
        return CapabilityStateSnapshot(
            capability_id=capability_id,
            score=score,
            confidence_level=latest.get("confidence_level", _level_from_score(score)),
            readiness=_readiness_from_score(score),
            execution_count=int(factors.get("execution_count", 0)),
            success_count=int(factors.get("success_count", 0)),
            failure_count=int(factors.get("failure_count", 0)),
            confidence_report_id=latest.get("report_id", ""),
        )

    def current_state(self, capability_id: str) -> dict[str, Any]:
        """Public, queryable current state for a capability."""
        return self._current_state(capability_id).to_dict()

    # ------------------------------------------------------------------
    # Bundle parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _load_bundle(evidence_path: str) -> tuple[dict[str, Any], str | None]:
        path = Path(evidence_path)
        if not path.exists():
            return {}, f"evidence file not found: {evidence_path}"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return {}, f"evidence file is not readable JSON: {exc}"
        if not isinstance(data, dict):
            return {}, "evidence bundle is not a JSON object"
        return data, None

    @staticmethod
    def _capability_of(bundle: dict[str, Any]) -> str:
        references = bundle.get("references") or {}
        candidate = bundle.get("capability_id") or references.get("capability_id") or ""
        return str(candidate).strip()

    def _trace(self, bundle: dict[str, Any], evidence_path: str) -> dict[str, Any]:
        """Read the sibling ``trace.json`` of an execution-chain evidence file."""
        trace_path = Path(evidence_path).with_name("trace.json")
        if not trace_path.exists():
            return {}
        try:
            data = json.loads(trace_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _outcome(self, bundle: dict[str, Any]) -> tuple[EvidenceOutcome, str]:
        """Derive pass/fail from the bundle, then its sibling chain trace."""
        if "passed" in bundle and isinstance(bundle["passed"], bool):
            if bundle["passed"]:
                return EvidenceOutcome.PASS, "bundle.passed is true"
            return EvidenceOutcome.FAIL, "bundle.passed is false"

        status = bundle.get("status")
        if isinstance(status, str) and status.strip():
            token = status.strip().lower()
            if token in _PASS_TOKENS:
                return EvidenceOutcome.PASS, f"bundle.status={status!r}"
            if token in _FAIL_TOKENS:
                return EvidenceOutcome.FAIL, f"bundle.status={status!r}"

        trace = self._pending_trace
        trace_status = trace.get("status")
        if isinstance(trace_status, str) and trace_status.strip():
            token = trace_status.strip().lower()
            if token in _PASS_TOKENS:
                return EvidenceOutcome.PASS, f"chain trace.status={trace_status!r}"
            if token in _FAIL_TOKENS:
                return EvidenceOutcome.FAIL, f"chain trace.status={trace_status!r}"

        return (
            EvidenceOutcome.MISSING,
            "no determinable pass/fail outcome in evidence or chain trace",
        )

    @staticmethod
    def _created_at(bundle: dict[str, Any], trace: dict[str, Any]) -> str:
        return str(bundle.get("created_at") or trace.get("created_at") or "")

    def _staleness_reason(
        self, bundle: dict[str, Any], max_age_seconds: int, now: datetime
    ) -> str | None:
        created_raw = self._created_at(bundle, self._pending_trace)
        if not created_raw:
            return None
        try:
            created = datetime.fromisoformat(created_raw)
        except ValueError:
            return None
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = (now - created).total_seconds()
        if age > max_age_seconds:
            return (
                f"stale evidence: produced {round(age)}s ago "
                f"(max_age_seconds={max_age_seconds})"
            )
        return None

    @staticmethod
    def _links(bundle: dict[str, Any], evidence_path: str) -> dict[str, str]:
        references = bundle.get("references") or {}
        return {
            "evidence_id": str(bundle.get("evidence_id", "")),
            "evidence_path": evidence_path,
            "result_id": str(references.get("result_id", "")),
            "artifact_id": str(references.get("artifact_id", "")),
        }

    # ------------------------------------------------------------------
    # Intake record (queryable audit; reuses report.json/evidence convention)
    # ------------------------------------------------------------------

    def _record(
        self,
        capability_id: str,
        evidence_path: str,
        outcome: EvidenceOutcome,
        decision: EvidenceDecision,
        reason: str,
        links: dict[str, str],
        now: datetime,
        prior: CapabilityStateSnapshot | None = None,
        updated: CapabilityStateSnapshot | None = None,
    ) -> dict[str, Any]:
        prior = prior or CapabilityStateSnapshot(capability_id=capability_id)
        updated = updated or prior
        # Attach the terminal report id from the chain trace, if present.
        trace = self._pending_trace
        if trace.get("report_id"):
            links = {**links, "report_id": str(trace.get("report_id", ""))}
            links["chain_run_id"] = str(trace.get("run_id", ""))

        intake_id = str(uuid4())
        record = {
            "intake_id": intake_id,
            "schema_version": SCHEMA_VERSION,
            "created_at": now.isoformat(),
            "capability_id": capability_id,
            "evidence_path": evidence_path,
            "evidence_outcome": outcome.value,
            "decision": decision.value,
            "accepted": decision is EvidenceDecision.ACCEPTED,
            "reason": reason,
            "links": links,
            "prior_state": prior.to_dict(),
            "updated_state": updated.to_dict(),
            "state_changed": prior.to_dict() != updated.to_dict(),
            "m3_hook": self._m3_hook(capability_id),
        }
        self._persist(intake_id, record)
        return record

    def _persist(self, intake_id: str, record: dict[str, Any]) -> None:
        record_dir = self._safe_path(intake_id)
        record_dir.mkdir(parents=True, exist_ok=True)
        (record_dir / "report.json").write_text(
            json.dumps(record, indent=2, default=str), encoding="utf-8"
        )
        pass_fail = {
            "passed": record["accepted"],
            "intake_id": intake_id,
            "capability_id": record["capability_id"],
            "decision": record["decision"],
            "evidence_outcome": record["evidence_outcome"],
            "status": "passed" if record["accepted"] else "failed",
            "timestamp": record["created_at"],
        }
        (record_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str), encoding="utf-8"
        )

    # ------------------------------------------------------------------
    # Retrieval / query
    # ------------------------------------------------------------------

    def get_intake(self, intake_id: str) -> dict[str, Any] | None:
        self._validate_id_segment(intake_id, "intake_id")
        record_file = self._safe_path(intake_id) / "report.json"
        if not record_file.exists():
            return None
        return json.loads(record_file.read_text(encoding="utf-8"))

    def list_intakes(self, capability_id: str = "") -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if not self._intake_dir.exists():
            return records
        sandbox = self._intake_dir.resolve()
        for entry in self._intake_dir.iterdir():
            if not entry.is_dir():
                continue
            resolved = entry.resolve()
            if not str(resolved).startswith(str(sandbox) + "/") and resolved != sandbox:
                continue
            record_file = entry / "report.json"
            if not record_file.exists():
                continue
            try:
                data = json.loads(record_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if capability_id and data.get("capability_id") != capability_id:
                continue
            records.append(data)
        records.sort(key=lambda r: r.get("created_at", ""))
        return records

    # ------------------------------------------------------------------
    # Hooks (recorded only)
    # ------------------------------------------------------------------

    @staticmethod
    def _m3_hook(capability_id: str) -> dict[str, Any]:
        return {
            "semantic_info_useful": [
                "capability purpose (what a pass/fail actually means for it)",
                "capability layer (to weight evidence by criticality)",
                "intended use / consumers (who depends on this readiness)",
                "dependencies (whether upstream capabilities were also exercised)",
                "evidence expectations (what coverage a 'pass' should require)",
            ],
            "note": (
                "Purpose/Layer Index (M3) is NOT implemented in this PR. Recorded "
                "only: outcome was mapped to confidence factors without semantic "
                f"weighting for {capability_id or '<unknown capability>'}."
            ),
        }

    # ------------------------------------------------------------------
    # Per-call trace cache + path safety
    # ------------------------------------------------------------------

    @property
    def _pending_trace(self) -> dict[str, Any]:
        return getattr(self, "_trace_cache", {})

    def _safe_path(self, intake_id: str) -> Path:
        self._validate_id_segment(intake_id, "intake_id")
        target = (self._intake_dir / intake_id).resolve()
        sandbox = self._intake_dir.resolve()
        if not str(target).startswith(str(sandbox) + "/") and target != sandbox:
            raise ValueError(f"Resolved path escapes artifacts root: {intake_id!r}")
        return target

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"{name} must not be empty or whitespace")
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(f"{name} must not contain '..', '/', or '\\': {value!r}")
