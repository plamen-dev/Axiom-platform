"""Session Question Registry v1 — first-class question objects.

Creates durable question artifacts for engineering sessions. Questions
become trackable objects that can be created, resolved, and linked to
session plans and work items.

Consumes: Session Plans, Work Items.

Non-goals: no execution, no file mutation, no network dependency,
no assertions, no reports.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class QuestionStatus(str, Enum):
    """Status of a session question."""

    OPEN = "open"
    RESOLVED = "resolved"
    DEFERRED = "deferred"
    CANCELLED = "cancelled"


class QuestionPriority(str, Enum):
    """Priority of a session question."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Status ranking for deterministic sorting (open first)
_STATUS_RANK: dict[str, int] = {
    QuestionStatus.OPEN.value: 0,
    QuestionStatus.RESOLVED.value: 1,
    QuestionStatus.DEFERRED.value: 2,
    QuestionStatus.CANCELLED.value: 3,
}

# Priority ranking for deterministic sorting
_PRIORITY_RANK: dict[str, int] = {
    QuestionPriority.CRITICAL.value: 0,
    QuestionPriority.HIGH.value: 1,
    QuestionPriority.MEDIUM.value: 2,
    QuestionPriority.LOW.value: 3,
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class QuestionAnswer:
    """An answer to a session question."""

    answer_id: str = ""
    content: str = ""
    source: str = ""
    confidence: str = "medium"
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.answer_id:
            self.answer_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer_id": self.answer_id,
            "content": self.content,
            "source": self.source,
            "confidence": self.confidence,
            "created_at": self.created_at,
        }


@dataclass
class SessionQuestion:
    """A durable session question artifact."""

    question_id: str = ""
    text: str = ""
    context: str = ""
    status: str = "open"
    priority: str = "medium"
    plan_id: str = ""
    work_item_id: str = ""
    rationale: str = ""
    answers: list[QuestionAnswer] = field(default_factory=list)
    resolved_answer_id: str = ""
    resolution_rationale: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.question_id:
            self.question_id = str(uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "text": self.text,
            "context": self.context,
            "status": self.status,
            "priority": self.priority,
            "plan_id": self.plan_id,
            "work_item_id": self.work_item_id,
            "rationale": self.rationale,
            "answers": [a.to_dict() for a in self.answers],
            "resolved_answer_id": self.resolved_answer_id,
            "resolution_rationale": self.resolution_rationale,
            "question_summary": self._question_summary(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def _question_summary(self) -> dict[str, Any]:
        return {
            "total_answers": len(self.answers),
            "is_resolved": self.status == QuestionStatus.RESOLVED.value,
            "has_answer": bool(self.resolved_answer_id),
        }


# ---------------------------------------------------------------------------
# Core registry
# ---------------------------------------------------------------------------


class SessionQuestionRegistry:
    """Durable registry for session question artifacts."""

    def __init__(
        self,
        artifacts_root: str = "",
    ) -> None:
        self._artifacts_root = artifacts_root or os.environ.get(
            "AXIOM_ARTIFACTS_ROOT", "artifacts",
        )
        self._questions_dir = Path(self._artifacts_root) / "session_questions"
        self._questions_dir.mkdir(parents=True, exist_ok=True)

    # -- ID validation ------------------------------------------------------

    @staticmethod
    def _validate_id_segment(value: str, name: str) -> None:
        if not value or not value.strip():
            msg = f"{name} must not be empty"
            raise ValueError(msg)
        if ".." in value or "/" in value or "\\" in value:
            msg = f"{name} must not contain '..', '/', or '\\': {value!r}"
            raise ValueError(msg)

    # -- Create question ----------------------------------------------------

    def create_question(
        self,
        text: str,
        context: str = "",
        priority: str = "medium",
        plan_id: str = "",
        work_item_id: str = "",
        rationale: str = "",
    ) -> dict[str, Any]:
        """Create a new session question."""
        question = SessionQuestion(
            text=text,
            context=context,
            priority=priority,
            plan_id=plan_id,
            work_item_id=work_item_id,
            rationale=rationale,
        )
        self._persist_question(question)
        return question.to_dict()

    # -- Get question -------------------------------------------------------

    def get_question(self, question_id: str) -> dict[str, Any] | None:
        """Get a question by ID."""
        self._validate_id_segment(question_id, "question_id")
        return self._load_question(question_id)

    # -- List questions -----------------------------------------------------

    def list_questions(
        self,
        status: str = "",
        plan_id: str = "",
    ) -> list[dict[str, Any]]:
        """List all questions, optionally filtered by status or plan_id."""
        questions: list[dict[str, Any]] = []
        if not self._questions_dir.exists():
            return questions

        for entry in sorted(self._questions_dir.iterdir()):
            if not entry.is_dir():
                continue
            q_file = entry / "question.json"
            if not q_file.exists():
                continue
            try:
                data = json.loads(q_file.read_text(encoding="utf-8"))
                if status and data.get("status") != status:
                    continue
                if plan_id and data.get("plan_id") != plan_id:
                    continue
                questions.append(data)
            except (json.JSONDecodeError, OSError):
                _logger.warning("Could not read question %s", entry.name)

        questions.sort(
            key=lambda q: (
                _STATUS_RANK.get(q.get("status", ""), 99),
                _PRIORITY_RANK.get(q.get("priority", ""), 99),
                q.get("created_at", ""),
            ),
        )
        return questions

    # -- Resolve question ---------------------------------------------------

    _VALID_STATUSES = frozenset(s.value for s in QuestionStatus)

    def resolve_question(
        self,
        question_id: str,
        answer: str,
        source: str = "",
        rationale: str = "",
    ) -> dict[str, Any] | None:
        """Resolve a question with an answer."""
        self._validate_id_segment(question_id, "question_id")
        question = self._load_question(question_id)
        if question is None:
            return None

        answer_obj = QuestionAnswer(
            content=answer,
            source=source,
        )
        question.setdefault("answers", []).append(answer_obj.to_dict())
        question["resolved_answer_id"] = answer_obj.answer_id
        question["resolution_rationale"] = rationale
        question["status"] = QuestionStatus.RESOLVED.value
        question["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_question(question_id, question)
        return question

    # -- Add answer ---------------------------------------------------------

    def add_answer(
        self,
        question_id: str,
        content: str,
        source: str = "",
        confidence: str = "medium",
    ) -> dict[str, Any] | None:
        """Add an answer candidate without resolving."""
        self._validate_id_segment(question_id, "question_id")
        question = self._load_question(question_id)
        if question is None:
            return None

        answer_obj = QuestionAnswer(
            content=content,
            source=source,
            confidence=confidence,
        )
        question.setdefault("answers", []).append(answer_obj.to_dict())
        question["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_question(question_id, question)
        return question

    # -- Update status ------------------------------------------------------

    def update_status(
        self,
        question_id: str,
        status: str,
    ) -> dict[str, Any] | None:
        """Update question status."""
        self._validate_id_segment(question_id, "question_id")
        if status not in self._VALID_STATUSES:
            msg = f"Invalid status {status!r}, expected one of {sorted(self._VALID_STATUSES)}"
            raise ValueError(msg)
        question = self._load_question(question_id)
        if question is None:
            return None
        question["status"] = status
        question["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_question(question_id, question)
        return question

    # -- Export question -----------------------------------------------------

    def export_question(self, question_id: str) -> str:
        """Export question as markdown."""
        self._validate_id_segment(question_id, "question_id")
        question = self._load_question(question_id)
        if question is None:
            msg = f"Question not found: {question_id}"
            raise ValueError(msg)

        lines = [
            f"# Question: {question.get('text', '')}\n",
            f"- Question ID: {question_id}",
            f"- Status: {question.get('status', '')}",
            f"- Priority: {question.get('priority', '')}",
        ]

        if question.get("plan_id"):
            lines.append(f"- Plan ID: {question['plan_id']}")
        if question.get("work_item_id"):
            lines.append(f"- Work Item ID: {question['work_item_id']}")
        lines.append(f"- Created: {question.get('created_at', '')}")

        if question.get("context"):
            lines.append(f"\n## Context\n\n{question['context']}")

        if question.get("rationale"):
            lines.append(f"\n## Rationale\n\n{question['rationale']}")

        answers = question.get("answers", [])
        if answers:
            lines.append(f"\n## Answers ({len(answers)})\n")
            resolved_id = question.get("resolved_answer_id", "")
            for a in answers:
                marker = " **[ACCEPTED]**" if a.get("answer_id") == resolved_id else ""
                src = f" (source: {a['source']})" if a.get("source") else ""
                lines.append(f"- {a.get('content', '')}{src}{marker}")

        if question.get("resolution_rationale"):
            lines.append(
                f"\n## Resolution Rationale\n\n{question['resolution_rationale']}",
            )

        return "\n".join(lines) + "\n"

    # -- Evidence writing ---------------------------------------------------

    def write_evidence(self, question_id: str) -> str:
        """Write evidence bundle for a question."""
        self._validate_id_segment(question_id, "question_id")
        question = self._load_question(question_id)
        if question is None:
            msg = f"Question not found: {question_id}"
            raise ValueError(msg)

        evidence_dir = self._questions_dir / question_id
        evidence_dir.mkdir(parents=True, exist_ok=True)

        request_data = {
            "question_id": question_id,
            "text": question.get("text", ""),
            "status": question.get("status", ""),
            "priority": question.get("priority", ""),
            "plan_id": question.get("plan_id", ""),
            "work_item_id": question.get("work_item_id", ""),
            "created_at": question.get("created_at", ""),
        }
        (evidence_dir / "question_request.json").write_text(
            json.dumps(request_data, indent=2, default=str),
        )

        (evidence_dir / "question_result.json").write_text(
            json.dumps(question, indent=2, default=str),
        )

        (evidence_dir / "question_summary.md").write_text(
            self.export_question(question_id),
        )

        summary = question.get("question_summary", {})
        pass_fail = {
            "passed": question.get("status") in (
                QuestionStatus.OPEN.value,
                QuestionStatus.RESOLVED.value,
            ),
            "question_id": question_id,
            "status": question.get("status", ""),
            "total_answers": summary.get("total_answers", 0),
            "is_resolved": summary.get("is_resolved", False),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (evidence_dir / "pass_fail.json").write_text(
            json.dumps(pass_fail, indent=2, default=str),
        )

        return str(evidence_dir)

    # -- Internal helpers ---------------------------------------------------

    def _persist_question(self, question: SessionQuestion) -> None:
        q_dir = self._questions_dir / question.question_id
        q_dir.mkdir(parents=True, exist_ok=True)
        (q_dir / "question.json").write_text(
            json.dumps(question.to_dict(), indent=2, default=str),
        )

    def _load_question(self, question_id: str) -> dict[str, Any] | None:
        q_path = self._questions_dir / question_id / "question.json"
        if not q_path.exists():
            return None
        return json.loads(q_path.read_text(encoding="utf-8"))

    @staticmethod
    def _recompute_question_summary(data: dict[str, Any]) -> None:
        """Recalculate question_summary from current state."""
        answers = data.get("answers", [])
        data["question_summary"] = {
            "total_answers": len(answers),
            "is_resolved": data.get("status") == QuestionStatus.RESOLVED.value,
            "has_answer": bool(data.get("resolved_answer_id")),
        }

    def _write_question(
        self, question_id: str, data: dict[str, Any],
    ) -> None:
        self._recompute_question_summary(data)
        q_dir = self._questions_dir / question_id
        q_dir.mkdir(parents=True, exist_ok=True)
        (q_dir / "question.json").write_text(
            json.dumps(data, indent=2, default=str),
        )
