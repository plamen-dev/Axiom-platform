"""Trusted Capability Registry v1 — separates eligible from trusted.

Distinguishes:
    - **eligible for trust** (has passed validation)
    - **trusted by Axiom** (explicitly promoted by human action)

Promotion must be explicit. No automatic promotion. Mutation/high-risk
capabilities remain blocked regardless of trust status.

No execution, no learning, no autonomous promotion.

Persistence via SQLAlchemy/SQLite (reuses the Axiom database layer).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from axiom_core.database import (
    create_db_engine,
    get_session,
    init_db,
    make_session_factory,
)
from axiom_core.models import Base

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TrustStatus(str, Enum):
    """Trust lifecycle states for a capability."""

    UNKNOWN = "unknown"
    ELIGIBLE = "eligible"
    TRUSTED = "trusted"
    REVOKED = "revoked"
    BLOCKED = "blocked"


class TrustAction(str, Enum):
    """Actions recorded in trust history."""

    PROMOTED = "promoted"
    REVOKED = "revoked"
    BLOCKED = "blocked"
    ELIGIBILITY_GRANTED = "eligibility_granted"
    VALIDATION_PASSED = "validation_passed"
    VALIDATION_FAILED = "validation_failed"


# ---------------------------------------------------------------------------
# ORM Rows
# ---------------------------------------------------------------------------


class TrustedCapabilityRow(Base):
    """SQLAlchemy row for trusted capabilities."""

    __tablename__ = "trusted_capabilities"

    capability_name: Mapped[str] = mapped_column(String(200), primary_key=True)
    trust_status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    promoted_by: Mapped[str] = mapped_column(String(200), nullable=True)
    promoted_at: Mapped[str] = mapped_column(String(50), nullable=True)
    revoked_by: Mapped[str] = mapped_column(String(200), nullable=True)
    revoked_at: Mapped[str] = mapped_column(String(50), nullable=True)
    revocation_reason: Mapped[str] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=True)
    validation_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(50), nullable=False)


class TrustHistoryRow(Base):
    """Audit log for trust lifecycle events."""

    __tablename__ = "trust_history"

    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    capability_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=True)
    timestamp: Mapped[str] = mapped_column(String(50), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class TrustEvidence:
    """Evidence supporting a trust decision."""

    def __init__(
        self,
        evidence_type: str = "",
        reference_id: str | None = None,
        description: str | None = None,
        timestamp: str | None = None,
    ) -> None:
        self.evidence_type = evidence_type
        self.reference_id = reference_id
        self.description = description
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_type": self.evidence_type,
            "reference_id": self.reference_id,
            "description": self.description,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrustEvidence:
        return cls(
            evidence_type=data.get("evidence_type", ""),
            reference_id=data.get("reference_id"),
            description=data.get("description"),
            timestamp=data.get("timestamp"),
        )


class TrustRevocation:
    """Record of a trust revocation."""

    def __init__(
        self,
        capability_name: str = "",
        revoked_by: str = "",
        reason: str = "",
        timestamp: str | None = None,
    ) -> None:
        self.capability_name = capability_name
        self.revoked_by = revoked_by
        self.reason = reason
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_name": self.capability_name,
            "revoked_by": self.revoked_by,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


class TrustHistory:
    """History of trust actions for a capability."""

    def __init__(
        self,
        capability_name: str = "",
        events: list[dict[str, Any]] | None = None,
    ) -> None:
        self.capability_name = capability_name
        self.events = events if events is not None else []

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_name": self.capability_name,
            "events": self.events,
            "event_count": len(self.events),
        }


class TrustedCapability:
    """A capability with its trust status and evidence."""

    def __init__(
        self,
        capability_name: str = "",
        trust_status: TrustStatus | str = TrustStatus.UNKNOWN,
        promoted_by: str | None = None,
        promoted_at: str | None = None,
        revoked_by: str | None = None,
        revoked_at: str | None = None,
        revocation_reason: str | None = None,
        evidence: list[TrustEvidence] | None = None,
        validation_count: int = 0,
        failure_count: int = 0,
        metadata: dict[str, Any] | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.capability_name = capability_name
        if isinstance(trust_status, str):
            try:
                self.trust_status = TrustStatus(trust_status)
            except ValueError:
                self.trust_status = TrustStatus.UNKNOWN
        else:
            self.trust_status = trust_status
        self.promoted_by = promoted_by
        self.promoted_at = promoted_at
        self.revoked_by = revoked_by
        self.revoked_at = revoked_at
        self.revocation_reason = revocation_reason
        self.evidence = evidence if evidence is not None else []
        self.validation_count = validation_count
        self.failure_count = failure_count
        self.metadata = metadata if metadata is not None else {}
        self.created_at = created_at or now
        self.updated_at = updated_at or now

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_name": self.capability_name,
            "trust_status": self.trust_status.value,
            "promoted_by": self.promoted_by,
            "promoted_at": self.promoted_at,
            "revoked_by": self.revoked_by,
            "revoked_at": self.revoked_at,
            "revocation_reason": self.revocation_reason,
            "evidence": [e.to_dict() for e in self.evidence],
            "validation_count": self.validation_count,
            "failure_count": self.failure_count,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


# ---------------------------------------------------------------------------
# TrustedCapabilityRegistry
# ---------------------------------------------------------------------------


class TrustedCapabilityRegistry:
    """Separates eligible from trusted.

    Promotion must be explicit. No automatic promotion.
    Mutation/high-risk capabilities remain blocked.

    No execution, no learning, no autonomous promotion.
    """

    # Capabilities that can never be promoted regardless of evidence
    BLOCKED_CAPABILITIES = frozenset({
        "SetParameterValue",
        "DeleteElements",
        "MoveElements",
        "RotateElements",
        "CreateWalls",
        "CreateFloors",
        "CreateRoofs",
    })

    def __init__(self, db_path: str | None = None) -> None:
        engine = create_db_engine(db_path)
        init_db(engine)
        self._session_factory = make_session_factory(engine)

    def _record_history(
        self,
        session: Any,
        capability_name: str,
        action: TrustAction,
        actor: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        row = TrustHistoryRow(
            event_id=str(uuid4()),
            capability_name=capability_name,
            action=action.value,
            actor=actor,
            timestamp=datetime.now(timezone.utc).isoformat(),
            details_json=json.dumps(details, default=str) if details else None,
        )
        session.add(row)

    def _row_to_capability(self, row: TrustedCapabilityRow) -> TrustedCapability:
        evidence = []
        if row.evidence_json:
            for e in json.loads(row.evidence_json):
                evidence.append(TrustEvidence.from_dict(e))

        return TrustedCapability(
            capability_name=row.capability_name,
            trust_status=row.trust_status,
            promoted_by=row.promoted_by,
            promoted_at=row.promoted_at,
            revoked_by=row.revoked_by,
            revoked_at=row.revoked_at,
            revocation_reason=row.revocation_reason,
            evidence=evidence,
            validation_count=row.validation_count,
            failure_count=row.failure_count,
            metadata=json.loads(row.metadata_json) if row.metadata_json else {},
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    # --- Public API --------------------------------------------------------

    def get_capability(self, name: str) -> TrustedCapability | None:
        """Retrieve trust status for a capability."""
        with get_session(self._session_factory) as session:
            row = session.get(TrustedCapabilityRow, name)
            if row is None:
                return None
            return self._row_to_capability(row)

    def list_capabilities(
        self,
        status_filter: TrustStatus | None = None,
    ) -> list[TrustedCapability]:
        """List capabilities with optional status filter."""
        with get_session(self._session_factory) as session:
            q = session.query(TrustedCapabilityRow)
            if status_filter is not None:
                q = q.filter(TrustedCapabilityRow.trust_status == status_filter.value)
            q = q.order_by(TrustedCapabilityRow.capability_name)
            return [self._row_to_capability(r) for r in q.all()]

    def promote(
        self,
        capability_name: str,
        promoted_by: str = "human",
        evidence: list[TrustEvidence] | None = None,
    ) -> TrustedCapability:
        """Explicitly promote a capability to trusted status.

        Raises ValueError if capability is blocked (mutation/high-risk).
        Raises ValueError if capability has recorded failures.
        """
        if capability_name in self.BLOCKED_CAPABILITIES:
            raise ValueError(
                f"Cannot promote '{capability_name}': blocked (mutation/high-risk)"
            )

        now = datetime.now(timezone.utc).isoformat()
        effective_evidence = evidence if evidence is not None else []

        with get_session(self._session_factory) as session:
            row = session.get(TrustedCapabilityRow, capability_name)

            if row is not None and row.failure_count > 0:
                raise ValueError(
                    f"Cannot promote '{capability_name}': has {row.failure_count} recorded failure(s)"
                )

            if row is None:
                raise ValueError(
                    f"Cannot promote '{capability_name}': not registered "
                    "(must have at least one passing validation to become ELIGIBLE first)"
                )

            if row.trust_status not in (TrustStatus.ELIGIBLE.value, TrustStatus.REVOKED.value):
                raise ValueError(
                    f"Cannot promote '{capability_name}': current status is "
                    f"'{row.trust_status}' (must be ELIGIBLE or REVOKED to promote)"
                )

            row.trust_status = TrustStatus.TRUSTED.value
            row.promoted_by = promoted_by
            row.promoted_at = now
            row.revoked_by = None
            row.revoked_at = None
            row.revocation_reason = None
            if effective_evidence:
                existing = json.loads(row.evidence_json) if row.evidence_json else []
                existing.extend(e.to_dict() for e in effective_evidence)
                row.evidence_json = json.dumps(existing, default=str)
            row.updated_at = now

            self._record_history(
                session, capability_name, TrustAction.PROMOTED, actor=promoted_by
            )
            return self._row_to_capability(row)

    def revoke(
        self,
        capability_name: str,
        revoked_by: str = "human",
        reason: str = "",
    ) -> TrustedCapability | None:
        """Revoke trust from a capability. Returns None if not found."""
        now = datetime.now(timezone.utc).isoformat()
        with get_session(self._session_factory) as session:
            row = session.get(TrustedCapabilityRow, capability_name)
            if row is None:
                return None

            row.trust_status = TrustStatus.REVOKED.value
            row.revoked_by = revoked_by
            row.revoked_at = now
            row.revocation_reason = reason
            row.updated_at = now

            self._record_history(
                session, capability_name, TrustAction.REVOKED,
                actor=revoked_by, details={"reason": reason},
            )
            return self._row_to_capability(row)

    def record_validation(
        self,
        capability_name: str,
        passed: bool,
        evidence: TrustEvidence | None = None,
    ) -> TrustedCapability:
        """Record a validation result for a capability.

        If passed: increments validation_count, may grant eligibility.
        If failed: increments failure_count, blocks promotion.
        """
        is_blocked = capability_name in self.BLOCKED_CAPABILITIES
        now = datetime.now(timezone.utc).isoformat()
        with get_session(self._session_factory) as session:
            row = session.get(TrustedCapabilityRow, capability_name)
            if row is None:
                if passed and not is_blocked:
                    initial_status = TrustStatus.ELIGIBLE.value
                elif is_blocked:
                    initial_status = TrustStatus.BLOCKED.value
                else:
                    initial_status = TrustStatus.UNKNOWN.value
                row = TrustedCapabilityRow(
                    capability_name=capability_name,
                    trust_status=initial_status,
                    validation_count=1 if passed else 0,
                    failure_count=0 if passed else 1,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                if passed:
                    row.validation_count += 1
                    if row.trust_status == TrustStatus.UNKNOWN.value and not is_blocked:
                        row.trust_status = TrustStatus.ELIGIBLE.value
                else:
                    row.failure_count += 1
                row.updated_at = now

            if evidence:
                existing = json.loads(row.evidence_json) if row.evidence_json else []
                existing.append(evidence.to_dict())
                row.evidence_json = json.dumps(existing, default=str)

            action = TrustAction.VALIDATION_PASSED if passed else TrustAction.VALIDATION_FAILED
            self._record_history(session, capability_name, action)
            return self._row_to_capability(row)

    def get_history(self, capability_name: str) -> TrustHistory:
        """Get the full trust history for a capability."""
        with get_session(self._session_factory) as session:
            rows = (
                session.query(TrustHistoryRow)
                .filter(TrustHistoryRow.capability_name == capability_name)
                .order_by(TrustHistoryRow.timestamp)
                .all()
            )
            events = []
            for r in rows:
                event = {
                    "event_id": r.event_id,
                    "action": r.action,
                    "actor": r.actor,
                    "timestamp": r.timestamp,
                }
                if r.details_json:
                    event["details"] = json.loads(r.details_json)
                events.append(event)
            return TrustHistory(capability_name=capability_name, events=events)

    def capability_count(self) -> int:
        """Total number of tracked capabilities."""
        with get_session(self._session_factory) as session:
            return session.query(TrustedCapabilityRow).count()
