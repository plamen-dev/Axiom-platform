"""Model Health Readiness Evidence Consumer v1 (PR #156).

A *thin* adapter that turns the Model Health readiness producer
(:func:`axiom_core.model_health.execute_health_run`, which writes
``axiom_capability_readiness.json``) from an **orphaned** producer into one with
a real state/evidence consumer. It closes the **narrow Model Health slice** of
the EVID-001 finding from PR #144/#154: the readiness artifact previously had
only *read-only* consumers (``server_tools.axiom_capability_readiness_get`` /
``axiom_model_health_get_latest``) which mutate no durable state.

What this consumer does
-----------------------
For each capability entry in a validated ``axiom_capability_readiness.json`` it:

* validates the artifact schema and the entry's required fields;
* preserves provenance (source artifact path, ``generated_at_utc``, the
  ``capability`` identity, and the producing run id when discoverable);
* de-duplicates via a stable fingerprint so re-ingesting the same readiness
  snapshot does not re-record a second mutation;
* quarantines conflicting readiness (two different labels for the same
  capability within one artifact) instead of silently picking one;
* rejects malformed/missing entries (no state recorded from bad evidence);
* optionally quarantines stale snapshots (opt-in ``max_age_seconds``);
* persists a small, queryable intake record per capability following the
  repository's standard per-engine ``report.json`` + ``pass_fail.json``
  convention, under ``<artifacts_root>/model_health_readiness_intake/``.

What this consumer deliberately does NOT do
--------------------------------------------
Readiness is a **precondition assessment** (can this capability run against the
current model?), **not** an execution outcome. It therefore is *not* mapped
onto :class:`~axiom_core.capability_confidence.CapabilityConfidenceEngine`
execution/success/failure factors: doing so would fabricate execution history
and corrupt the existing confidence math. Whether (and how) readiness should
influence confidence is an **open readiness-doctrine question routed to
Program 6** and is intentionally left open here.

Non-goals: no new evidence framework, no new registry, no readiness doctrine,
no confidence-math change, no implementation-worker/retry/GPR behavior. This is
an adapter/coordinator that reuses existing artifact/path-safety conventions.

EVID-001 scope: this closes **only** the Model Health readiness evidence slice.
Broader EVID-001 remains open for other producers not covered here.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from axiom_core.artifact_paths import is_within_sandbox

SCHEMA_VERSION = "1.0"

# Valid readiness labels emitted by the Model Health producer
# (see axiom_core.model_health.CapabilityReadiness.readiness).
VALID_READINESS = {"READY", "WARNING", "BLOCKED", "UNKNOWN"}


class ReadinessDecision(str, Enum):
    """What the consumer did with one capability's readiness evidence."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"
    DUPLICATE = "duplicate"


@dataclass
class ReadinessRecord:
    """A durable readiness-state snapshot for one capability."""

    capability: str = ""
    readiness: str = "UNKNOWN"
    risk_level: str = ""
    execute_available: bool = False
    dry_run_available: bool = False
    generated_at_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "readiness": self.readiness,
            "risk_level": self.risk_level,
            "execute_available": self.execute_available,
            "dry_run_available": self.dry_run_available,
            "generated_at_utc": self.generated_at_utc,
        }


@dataclass
class ReadinessApplyResult:
    """Outcome of consuming one ``axiom_capability_readiness.json`` artifact."""

    source_path: str = ""
    generated_at_utc: str = ""
    error: str | None = None
    records: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "generated_at_utc": self.generated_at_utc,
            "error": self.error,
            "capabilities_seen": len(self.records),
            "accepted": sum(
                1
                for r in self.records
                if r.get("decision") == ReadinessDecision.ACCEPTED.value
            ),
            "duplicate": sum(
                1
                for r in self.records
                if r.get("decision") == ReadinessDecision.DUPLICATE.value
            ),
            "quarantined": sum(
                1
                for r in self.records
                if r.get("decision") == ReadinessDecision.QUARANTINED.value
            ),
            "rejected": sum(
                1
                for r in self.records
                if r.get("decision") == ReadinessDecision.REJECTED.value
            ),
            "records": self.records,
        }


class ModelHealthReadinessConsumer:
    """Ingests Model Health readiness evidence into durable, queryable state.

    Reuses the repository's per-engine artifact convention; owns no new
    framework or registry abstraction. The intake records under
    ``model_health_readiness_intake/`` are the durable readiness state this
    consumer produces.
    """

    def __init__(self, artifacts_root: str | None = None) -> None:
        if artifacts_root is None:
            artifacts_root = os.path.join(os.getcwd(), "artifacts")
        self._artifacts_root = Path(artifacts_root)
        self._intake_dir = self._artifacts_root / "model_health_readiness_intake"
        self._intake_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def apply(
        self,
        readiness_path: str,
        max_age_seconds: int | None = None,
        now: datetime | None = None,
    ) -> ReadinessApplyResult:
        """Consume one ``axiom_capability_readiness.json`` artifact.

        Each capability entry is validated and recorded independently. A
        single malformed entry is rejected without affecting the others. The
        whole artifact is rejected only when it cannot be read or is not the
        expected shape.
        """
        now = now or datetime.now(timezone.utc)
        result = ReadinessApplyResult(source_path=readiness_path)

        bundle, load_error = self._load_bundle(readiness_path)
        if load_error is not None:
            result.error = load_error
            result.records.append(
                self._record(
                    capability="",
                    readiness="UNKNOWN",
                    decision=ReadinessDecision.REJECTED,
                    reason=load_error,
                    source_path=readiness_path,
                    generated_at_utc="",
                    now=now,
                )
            )
            return result

        generated_at = str(bundle.get("generated_at_utc", "")).strip()
        result.generated_at_utc = generated_at
        run_id = self._run_id_of(readiness_path)

        # Opt-in staleness quarantine for the whole snapshot.
        stale_reason = None
        if max_age_seconds is not None:
            stale_reason = self._staleness_reason(generated_at, max_age_seconds, now)

        # Detect conflicting labels for the same capability within this artifact.
        conflicts = self._conflicting_capabilities(bundle.get("capabilities") or [])

        seen_fingerprints: set[str] = set()
        for entry in bundle.get("capabilities") or []:
            field_error = self._entry_error(entry)
            if field_error is not None:
                result.records.append(
                    self._record(
                        capability=str((entry or {}).get("capability", "")).strip()
                        if isinstance(entry, dict)
                        else "",
                        readiness="UNKNOWN",
                        decision=ReadinessDecision.REJECTED,
                        reason=field_error,
                        source_path=readiness_path,
                        generated_at_utc=generated_at,
                        run_id=run_id,
                        now=now,
                    )
                )
                continue

            capability = str(entry["capability"]).strip()
            readiness = str(entry["readiness"]).strip()
            snapshot = ReadinessRecord(
                capability=capability,
                readiness=readiness,
                risk_level=str(entry.get("risk_level", "")),
                execute_available=bool(entry.get("execute_available", False)),
                dry_run_available=bool(entry.get("dry_run_available", False)),
                generated_at_utc=generated_at,
            )

            if capability in conflicts:
                result.records.append(
                    self._record(
                        capability=capability,
                        readiness=readiness,
                        decision=ReadinessDecision.QUARANTINED,
                        reason=(
                            f"conflicting readiness for {capability} within one "
                            f"artifact ({conflicts[capability]}); quarantined "
                            f"rather than silently resolved"
                        ),
                        source_path=readiness_path,
                        generated_at_utc=generated_at,
                        run_id=run_id,
                        snapshot=snapshot,
                        now=now,
                    )
                )
                continue

            if stale_reason is not None:
                result.records.append(
                    self._record(
                        capability=capability,
                        readiness=readiness,
                        decision=ReadinessDecision.QUARANTINED,
                        reason=stale_reason,
                        source_path=readiness_path,
                        generated_at_utc=generated_at,
                        run_id=run_id,
                        snapshot=snapshot,
                        now=now,
                    )
                )
                continue

            fingerprint = self._fingerprint(capability, readiness, generated_at)
            duplicate_of = self._already_accepted(capability, fingerprint)
            if duplicate_of is not None or fingerprint in seen_fingerprints:
                result.records.append(
                    self._record(
                        capability=capability,
                        readiness=readiness,
                        decision=ReadinessDecision.DUPLICATE,
                        reason=(
                            f"duplicate readiness (fingerprint {fingerprint}) "
                            f"already recorded for {capability}; not re-recorded"
                        ),
                        source_path=readiness_path,
                        generated_at_utc=generated_at,
                        run_id=run_id,
                        snapshot=snapshot,
                        fingerprint=fingerprint,
                        duplicate_of=duplicate_of or "",
                        now=now,
                    )
                )
                continue

            seen_fingerprints.add(fingerprint)
            result.records.append(
                self._record(
                    capability=capability,
                    readiness=readiness,
                    decision=ReadinessDecision.ACCEPTED,
                    reason=(
                        f"readiness {readiness} recorded for {capability} "
                        f"(provenance preserved; confidence math not mutated — "
                        f"readiness->confidence doctrine is an open Program 6 "
                        f"question)"
                    ),
                    source_path=readiness_path,
                    generated_at_utc=generated_at,
                    run_id=run_id,
                    snapshot=snapshot,
                    fingerprint=fingerprint,
                    now=now,
                )
            )

        return result

    # ------------------------------------------------------------------
    # Bundle parsing / validation
    # ------------------------------------------------------------------

    @staticmethod
    def _load_bundle(readiness_path: str) -> tuple[dict[str, Any], str | None]:
        path = Path(readiness_path)
        if not path.exists():
            return {}, f"readiness artifact not found: {readiness_path}"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return {}, f"readiness artifact is not readable JSON: {exc}"
        if not isinstance(data, dict):
            return {}, "readiness artifact is not a JSON object"
        if not isinstance(data.get("capabilities"), list):
            return {}, "readiness artifact missing required 'capabilities' list"
        return data, None

    @staticmethod
    def _entry_error(entry: Any) -> str | None:
        """Return a reason string if a capability entry is malformed, else None."""
        if not isinstance(entry, dict):
            return "capability entry is not a JSON object"
        capability = entry.get("capability")
        if not isinstance(capability, str) or not capability.strip():
            return "capability entry missing required non-empty 'capability'"
        readiness = entry.get("readiness")
        if not isinstance(readiness, str) or not readiness.strip():
            return f"capability '{capability}' missing required 'readiness'"
        if readiness.strip() not in VALID_READINESS:
            return (
                f"capability '{capability}' has invalid readiness "
                f"'{readiness}' (expected one of {sorted(VALID_READINESS)})"
            )
        return None

    @staticmethod
    def _conflicting_capabilities(
        capabilities: list[Any],
    ) -> dict[str, str]:
        """Map capability -> rendered label set when a capability appears with
        more than one distinct readiness label in the same artifact."""
        labels: dict[str, set[str]] = {}
        for entry in capabilities:
            if not isinstance(entry, dict):
                continue
            cap = entry.get("capability")
            rd = entry.get("readiness")
            if not isinstance(cap, str) or not cap.strip():
                continue
            if not isinstance(rd, str) or not rd.strip():
                continue
            labels.setdefault(cap.strip(), set()).add(rd.strip())
        return {
            cap: ", ".join(sorted(rds))
            for cap, rds in labels.items()
            if len(rds) > 1
        }

    @staticmethod
    def _run_id_of(readiness_path: str) -> str:
        """Best-effort producing run id: the parent folder name (run-spine)."""
        parent = Path(readiness_path).parent.name
        return parent if parent and parent != "." else ""

    @staticmethod
    def _fingerprint(capability: str, readiness: str, generated_at: str) -> str:
        canonical = json.dumps(
            {"c": capability, "r": readiness, "g": generated_at}, sort_keys=True
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    def _already_accepted(self, capability: str, fingerprint: str) -> str | None:
        for record in self.list_intakes(capability=capability):
            if record.get("decision") != ReadinessDecision.ACCEPTED.value:
                continue
            if record.get("evidence_fingerprint") == fingerprint:
                return str(record.get("intake_id", ""))
        return None

    @staticmethod
    def _staleness_reason(
        generated_at: str, max_age_seconds: int, now: datetime
    ) -> str | None:
        if not generated_at:
            return None
        try:
            created = datetime.fromisoformat(generated_at)
        except ValueError:
            return None
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = (now - created).total_seconds()
        if age > max_age_seconds:
            return (
                f"stale readiness: produced {round(age)}s ago "
                f"(max_age_seconds={max_age_seconds})"
            )
        return None

    # ------------------------------------------------------------------
    # Intake record (queryable audit; reuses report.json/pass_fail convention)
    # ------------------------------------------------------------------

    def _record(
        self,
        capability: str,
        readiness: str,
        decision: ReadinessDecision,
        reason: str,
        source_path: str,
        generated_at_utc: str,
        now: datetime,
        run_id: str = "",
        snapshot: ReadinessRecord | None = None,
        fingerprint: str = "",
        duplicate_of: str = "",
    ) -> dict[str, Any]:
        snapshot = snapshot or ReadinessRecord(
            capability=capability,
            readiness=readiness,
            generated_at_utc=generated_at_utc,
        )
        intake_id = str(uuid4())
        record = {
            "intake_id": intake_id,
            "schema_version": SCHEMA_VERSION,
            "created_at": now.isoformat(),
            "capability": capability,
            "readiness": readiness,
            "evidence_kind": "model_health_readiness",
            "evidence_fingerprint": fingerprint,
            "decision": decision.value,
            "accepted": decision is ReadinessDecision.ACCEPTED,
            "duplicate_of": duplicate_of,
            "reason": reason,
            "provenance": {
                "source_artifact": source_path,
                "producer": "axiom_core.model_health.execute_health_run",
                "producer_run_id": run_id,
                "generated_at_utc": generated_at_utc,
            },
            "readiness_state": snapshot.to_dict(),
            "confidence_mutated": False,
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
            "capability": record["capability"],
            "readiness": record["readiness"],
            "decision": record["decision"],
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

    def list_intakes(self, capability: str = "") -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if not self._intake_dir.exists():
            return records
        sandbox = self._intake_dir.resolve()
        for entry in self._intake_dir.iterdir():
            if not entry.is_dir():
                continue
            resolved = entry.resolve()
            if not is_within_sandbox(resolved, sandbox):
                continue
            record_file = entry / "report.json"
            if not record_file.exists():
                continue
            try:
                data = json.loads(record_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if capability and data.get("capability") != capability:
                continue
            records.append(data)
        records.sort(key=lambda r: r.get("created_at", ""))
        return records

    def current_readiness(self, capability: str) -> dict[str, Any] | None:
        """Return the most recently *accepted* readiness state for a capability."""
        accepted = [
            r
            for r in self.list_intakes(capability=capability)
            if r.get("decision") == ReadinessDecision.ACCEPTED.value
        ]
        if not accepted:
            return None
        latest = max(accepted, key=lambda r: r.get("created_at", ""))
        return latest.get("readiness_state")

    # ------------------------------------------------------------------
    # Path safety (reuses shared cross-platform helper from PR #151)
    # ------------------------------------------------------------------

    def _safe_path(self, intake_id: str) -> Path:
        self._validate_id_segment(intake_id, "intake_id")
        target = (self._intake_dir / intake_id).resolve()
        sandbox = self._intake_dir.resolve()
        if not is_within_sandbox(target, sandbox):
            raise ValueError(f"Resolved path escapes artifacts root: {intake_id!r}")
        return target

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"{name} must not be empty or whitespace")
        if ".." in value or "/" in value or "\\" in value:
            raise ValueError(f"{name} must not contain '..', '/', or '\\': {value!r}")
