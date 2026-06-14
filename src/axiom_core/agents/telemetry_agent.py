"""TelemetryAgent — logs actions, errors, timings, results.

In this PR: logs to an in-memory list only.
SQLite telemetry persistence is a follow-up task (not wired here).
The _persist_event path exists but is not called by the vertical slice
CLI command because no session_factory is passed.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from axiom_core.database import get_session
from axiom_core.models import ExecutionTraceRow

_logger = logging.getLogger(__name__)


class TelemetryEvent:
    """A single telemetry event."""

    def __init__(
        self,
        event_type: str,
        data: dict[str, Any],
        timestamp: Optional[datetime] = None,
    ):
        self.event_id = str(uuid4())
        self.event_type = event_type
        self.data = data
        self.timestamp = timestamp or datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }


class TelemetryAgent:
    """Logs telemetry events to in-memory buffer.

    SQLite persistence is opt-in via session_factory parameter
    but is NOT wired in the current vertical slice CLI command.
    Follow-up: wire session_factory in axiom prompt command.
    """

    def __init__(self, session_factory: Optional[Any] = None):
        self._events: list[TelemetryEvent] = []
        self._session_factory = session_factory

    def log_event(
        self,
        event_type: str,
        data: dict[str, Any],
    ) -> TelemetryEvent:
        """Log a telemetry event."""
        event = TelemetryEvent(event_type=event_type, data=data)
        self._events.append(event)

        if self._session_factory is not None:
            self._persist_event(event)

        return event

    def get_events(
        self,
        event_type: Optional[str] = None,
    ) -> list[TelemetryEvent]:
        """Retrieve logged events, optionally filtered by type."""
        if event_type is None:
            return list(self._events)
        return [e for e in self._events if e.event_type == event_type]

    def _persist_event(self, event: TelemetryEvent) -> None:
        """Write event to SQLite via the ExecutionTrace table."""
        try:
            with get_session(self._session_factory) as session:
                row = ExecutionTraceRow(
                    trace_id=event.event_id,
                    job_id=event.data.get("plan_id", event.event_id),
                    plan_id=event.data.get("plan_id", event.event_id),
                    started_at=event.timestamp,
                    status=event.event_type,
                    results_json=json.dumps([event.to_dict()]),
                )
                session.merge(row)
        except Exception:
            _logger.debug("Failed to persist telemetry event %s", event.event_id, exc_info=True)
