"""Tests for Session Question Registry v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.session_question_registry import (
    QuestionAnswer,
    QuestionPriority,
    QuestionStatus,
    SessionQuestion,
    SessionQuestionRegistry,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry(tmp_path: Path) -> SessionQuestionRegistry:
    return SessionQuestionRegistry(artifacts_root=str(tmp_path))


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestEnums:
    def test_question_status_values(self):
        assert QuestionStatus.OPEN.value == "open"
        assert QuestionStatus.RESOLVED.value == "resolved"
        assert QuestionStatus.DEFERRED.value == "deferred"
        assert QuestionStatus.CANCELLED.value == "cancelled"

    def test_question_priority_values(self):
        assert QuestionPriority.CRITICAL.value == "critical"
        assert QuestionPriority.HIGH.value == "high"
        assert QuestionPriority.MEDIUM.value == "medium"
        assert QuestionPriority.LOW.value == "low"


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_question_answer_to_dict(self):
        a = QuestionAnswer(content="test answer", source="reviewer")
        d = a.to_dict()
        assert d["content"] == "test answer"
        assert d["source"] == "reviewer"
        assert d["confidence"] == "medium"
        assert d["answer_id"]
        assert d["created_at"]

    def test_question_answer_auto_id(self):
        a1 = QuestionAnswer(content="a")
        a2 = QuestionAnswer(content="b")
        assert a1.answer_id != a2.answer_id

    def test_session_question_to_dict(self):
        q = SessionQuestion(text="Why?", context="Testing")
        d = q.to_dict()
        assert d["text"] == "Why?"
        assert d["context"] == "Testing"
        assert d["status"] == "open"
        assert d["priority"] == "medium"
        assert d["question_id"]
        assert d["created_at"]
        assert d["updated_at"]
        assert "question_summary" in d

    def test_session_question_summary(self):
        q = SessionQuestion(text="Q", answers=[
            QuestionAnswer(content="A1"),
        ])
        d = q.to_dict()
        summary = d["question_summary"]
        assert summary["total_answers"] == 1
        assert summary["is_resolved"] is False
        assert summary["has_answer"] is False

    def test_session_question_resolved_summary(self):
        a = QuestionAnswer(content="Answer")
        q = SessionQuestion(
            text="Q",
            status="resolved",
            answers=[a],
            resolved_answer_id=a.answer_id,
        )
        d = q.to_dict()
        summary = d["question_summary"]
        assert summary["is_resolved"] is True
        assert summary["has_answer"] is True


# ---------------------------------------------------------------------------
# Create question tests
# ---------------------------------------------------------------------------


class TestCreateQuestion:
    def test_create_minimal(self, registry: SessionQuestionRegistry):
        q = registry.create_question(text="Why?")
        assert q["text"] == "Why?"
        assert q["status"] == "open"
        assert q["priority"] == "medium"
        assert q["question_id"]

    def test_create_with_all_fields(self, registry: SessionQuestionRegistry):
        q = registry.create_question(
            text="Why this?",
            context="Testing context",
            priority="high",
            plan_id="plan-001",
            work_item_id="wi-001",
            rationale="Need to know",
        )
        assert q["text"] == "Why this?"
        assert q["context"] == "Testing context"
        assert q["priority"] == "high"
        assert q["plan_id"] == "plan-001"
        assert q["work_item_id"] == "wi-001"
        assert q["rationale"] == "Need to know"

    def test_create_persists(self, registry: SessionQuestionRegistry):
        q = registry.create_question(text="Persisted?")
        loaded = registry.get_question(q["question_id"])
        assert loaded is not None
        assert loaded["text"] == "Persisted?"

    def test_create_unique_ids(self, registry: SessionQuestionRegistry):
        q1 = registry.create_question(text="Q1")
        q2 = registry.create_question(text="Q2")
        assert q1["question_id"] != q2["question_id"]


# ---------------------------------------------------------------------------
# Get question tests
# ---------------------------------------------------------------------------


class TestGetQuestion:
    def test_get_existing(self, registry: SessionQuestionRegistry):
        q = registry.create_question(text="Exist?")
        loaded = registry.get_question(q["question_id"])
        assert loaded is not None
        assert loaded["question_id"] == q["question_id"]

    def test_get_nonexistent(self, registry: SessionQuestionRegistry):
        result = registry.get_question("nonexistent-id")
        assert result is None


# ---------------------------------------------------------------------------
# List questions tests
# ---------------------------------------------------------------------------


class TestListQuestions:
    def test_list_empty(self, registry: SessionQuestionRegistry):
        result = registry.list_questions()
        assert result == []

    def test_list_all(self, registry: SessionQuestionRegistry):
        registry.create_question(text="Q1")
        registry.create_question(text="Q2")
        result = registry.list_questions()
        assert len(result) == 2

    def test_list_filter_by_status(self, registry: SessionQuestionRegistry):
        q = registry.create_question(text="Q1")
        registry.resolve_question(
            q["question_id"], answer="A", source="test",
        )
        registry.create_question(text="Q2")
        open_qs = registry.list_questions(status="open")
        assert len(open_qs) == 1
        assert open_qs[0]["text"] == "Q2"

    def test_list_filter_by_plan_id(self, registry: SessionQuestionRegistry):
        registry.create_question(text="Q1", plan_id="plan-a")
        registry.create_question(text="Q2", plan_id="plan-b")
        result = registry.list_questions(plan_id="plan-a")
        assert len(result) == 1
        assert result[0]["plan_id"] == "plan-a"


# ---------------------------------------------------------------------------
# Resolve question tests
# ---------------------------------------------------------------------------


class TestResolveQuestion:
    def test_resolve_sets_status(self, registry: SessionQuestionRegistry):
        q = registry.create_question(text="Q")
        resolved = registry.resolve_question(
            q["question_id"],
            answer="The answer",
            source="reviewer",
            rationale="Makes sense",
        )
        assert resolved is not None
        assert resolved["status"] == "resolved"
        assert resolved["resolution_rationale"] == "Makes sense"
        assert resolved["resolved_answer_id"]
        assert len(resolved["answers"]) == 1
        assert resolved["answers"][0]["content"] == "The answer"
        assert resolved["answers"][0]["source"] == "reviewer"

    def test_resolve_nonexistent(self, registry: SessionQuestionRegistry):
        result = registry.resolve_question(
            "nonexistent", answer="A",
        )
        assert result is None

    def test_resolve_updates_timestamp(self, registry: SessionQuestionRegistry):
        q = registry.create_question(text="Q")
        original = q["updated_at"]
        resolved = registry.resolve_question(
            q["question_id"], answer="A",
        )
        assert resolved is not None
        assert resolved["updated_at"] >= original

    def test_resolve_recomputes_summary(self, registry: SessionQuestionRegistry):
        q = registry.create_question(text="Q")
        resolved = registry.resolve_question(
            q["question_id"], answer="A",
        )
        assert resolved is not None
        summary = resolved["question_summary"]
        assert summary["total_answers"] == 1
        assert summary["is_resolved"] is True
        assert summary["has_answer"] is True


# ---------------------------------------------------------------------------
# Add answer tests
# ---------------------------------------------------------------------------


class TestAddAnswer:
    def test_add_answer_without_resolving(self, registry: SessionQuestionRegistry):
        q = registry.create_question(text="Q")
        updated = registry.add_answer(
            q["question_id"],
            content="Candidate",
            source="AI",
            confidence="high",
        )
        assert updated is not None
        assert updated["status"] == "open"
        assert len(updated["answers"]) == 1
        assert updated["answers"][0]["content"] == "Candidate"
        assert updated["answers"][0]["confidence"] == "high"
        assert not updated["resolved_answer_id"]

    def test_add_multiple_answers(self, registry: SessionQuestionRegistry):
        q = registry.create_question(text="Q")
        registry.add_answer(q["question_id"], content="A1")
        updated = registry.add_answer(q["question_id"], content="A2")
        assert updated is not None
        assert len(updated["answers"]) == 2

    def test_add_answer_nonexistent(self, registry: SessionQuestionRegistry):
        result = registry.add_answer("nonexistent", content="A")
        assert result is None


# ---------------------------------------------------------------------------
# Update status tests
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    def test_update_to_deferred(self, registry: SessionQuestionRegistry):
        q = registry.create_question(text="Q")
        updated = registry.update_status(q["question_id"], "deferred")
        assert updated is not None
        assert updated["status"] == "deferred"

    def test_update_nonexistent(self, registry: SessionQuestionRegistry):
        result = registry.update_status("nonexistent", "open")
        assert result is None

    def test_update_invalid_status_raises(self, registry: SessionQuestionRegistry):
        q = registry.create_question(text="Q")
        with pytest.raises(ValueError, match="Invalid status"):
            registry.update_status(q["question_id"], "bogus")

    def test_update_updates_timestamp(self, registry: SessionQuestionRegistry):
        q = registry.create_question(text="Q")
        original = q["updated_at"]
        updated = registry.update_status(q["question_id"], "deferred")
        assert updated is not None
        assert updated["updated_at"] >= original


# ---------------------------------------------------------------------------
# Export question tests
# ---------------------------------------------------------------------------


class TestExportQuestion:
    def test_export_markdown(self, registry: SessionQuestionRegistry):
        q = registry.create_question(
            text="Why this approach?",
            context="Architecture decision",
            plan_id="plan-001",
            rationale="Need clarity",
        )
        md = registry.export_question(q["question_id"])
        assert "# Question: Why this approach?" in md
        assert "- Status: open" in md
        assert "- Plan ID: plan-001" in md
        assert "## Context" in md
        assert "Architecture decision" in md
        assert "## Rationale" in md
        assert "Need clarity" in md

    def test_export_with_answers(self, registry: SessionQuestionRegistry):
        q = registry.create_question(text="Q")
        resolved = registry.resolve_question(
            q["question_id"],
            answer="The answer",
            source="reviewer",
            rationale="Confirmed",
        )
        assert resolved is not None
        md = registry.export_question(q["question_id"])
        assert "## Answers (1)" in md
        assert "The answer" in md
        assert "**[ACCEPTED]**" in md
        assert "## Resolution Rationale" in md
        assert "Confirmed" in md

    def test_export_nonexistent_raises(self, registry: SessionQuestionRegistry):
        with pytest.raises(ValueError, match="Question not found"):
            registry.export_question("nonexistent")


# ---------------------------------------------------------------------------
# Evidence writing tests
# ---------------------------------------------------------------------------


class TestWriteEvidence:
    def test_evidence_files_created(self, registry: SessionQuestionRegistry):
        q = registry.create_question(text="Evidence Q")
        evidence_dir = registry.write_evidence(q["question_id"])
        p = Path(evidence_dir)
        assert (p / "question_request.json").exists()
        assert (p / "question_result.json").exists()
        assert (p / "question_summary.md").exists()
        assert (p / "pass_fail.json").exists()

    def test_evidence_request_valid_json(self, registry: SessionQuestionRegistry):
        q = registry.create_question(text="JSON Q", plan_id="plan-x")
        evidence_dir = registry.write_evidence(q["question_id"])
        p = Path(evidence_dir)
        req = json.loads((p / "question_request.json").read_text())
        assert req["question_id"] == q["question_id"]
        assert req["text"] == "JSON Q"
        assert req["plan_id"] == "plan-x"

    def test_evidence_result_valid_json(self, registry: SessionQuestionRegistry):
        q = registry.create_question(text="Result Q")
        evidence_dir = registry.write_evidence(q["question_id"])
        p = Path(evidence_dir)
        result = json.loads((p / "question_result.json").read_text())
        assert result["question_id"] == q["question_id"]
        assert "question_summary" in result

    def test_evidence_pass_fail(self, registry: SessionQuestionRegistry):
        q = registry.create_question(text="Pass Q")
        evidence_dir = registry.write_evidence(q["question_id"])
        p = Path(evidence_dir)
        pf = json.loads((p / "pass_fail.json").read_text())
        assert pf["passed"] is True
        assert pf["status"] == "open"

    def test_evidence_markdown_contains_header(self, registry: SessionQuestionRegistry):
        q = registry.create_question(text="MD Q")
        evidence_dir = registry.write_evidence(q["question_id"])
        p = Path(evidence_dir)
        md = (p / "question_summary.md").read_text()
        assert "# Question: MD Q" in md

    def test_evidence_nonexistent_raises(self, registry: SessionQuestionRegistry):
        with pytest.raises(ValueError, match="Question not found"):
            registry.write_evidence("nonexistent")


# ---------------------------------------------------------------------------
# ID validation tests
# ---------------------------------------------------------------------------


class TestIDValidation:
    def test_empty_id_raises(self, registry: SessionQuestionRegistry):
        with pytest.raises(ValueError, match="must not be empty"):
            registry.get_question("")

    def test_whitespace_only_raises(self, registry: SessionQuestionRegistry):
        with pytest.raises(ValueError, match="must not be empty"):
            registry.get_question("   ")

    def test_path_traversal_raises(self, registry: SessionQuestionRegistry):
        with pytest.raises(ValueError, match="must not contain"):
            registry.get_question("../etc/passwd")

    def test_forward_slash_raises(self, registry: SessionQuestionRegistry):
        with pytest.raises(ValueError, match="must not contain"):
            registry.get_question("a/b")

    def test_backslash_raises(self, registry: SessionQuestionRegistry):
        with pytest.raises(ValueError, match="must not contain"):
            registry.get_question("a\\b")


# ---------------------------------------------------------------------------
# Summary recomputation tests
# ---------------------------------------------------------------------------


class TestSummaryRecomputation:
    def test_summary_recomputed_on_resolve(self, registry: SessionQuestionRegistry):
        q = registry.create_question(text="Q")
        assert q["question_summary"]["total_answers"] == 0
        resolved = registry.resolve_question(q["question_id"], answer="A")
        assert resolved is not None
        assert resolved["question_summary"]["total_answers"] == 1
        assert resolved["question_summary"]["is_resolved"] is True

    def test_summary_recomputed_on_add_answer(self, registry: SessionQuestionRegistry):
        q = registry.create_question(text="Q")
        updated = registry.add_answer(q["question_id"], content="A1")
        assert updated is not None
        assert updated["question_summary"]["total_answers"] == 1
        assert updated["question_summary"]["is_resolved"] is False


# ---------------------------------------------------------------------------
# Deterministic ordering tests
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_questions_sorted_by_status_rank(self, registry: SessionQuestionRegistry):
        q1 = registry.create_question(text="Q1")
        registry.create_question(text="Q2")
        registry.resolve_question(q1["question_id"], answer="A")
        questions = registry.list_questions()
        assert len(questions) == 2
        assert questions[0]["status"] == "open"
        assert questions[1]["status"] == "resolved"

    def test_questions_sorted_by_priority_within_status(
        self, registry: SessionQuestionRegistry,
    ):
        registry.create_question(text="Low", priority="low")
        registry.create_question(text="Critical", priority="critical")
        registry.create_question(text="High", priority="high")
        questions = registry.list_questions()
        priorities = [q["priority"] for q in questions]
        assert priorities == ["critical", "high", "low"]


# ---------------------------------------------------------------------------
# Command registry spec tests
# ---------------------------------------------------------------------------


class TestCommandRegistrySpecs:
    def test_question_create_registered(self):
        from axiom_core.runner.command_registry import get_command
        cmd = get_command("question-create")
        assert cmd is not None
        assert cmd.classification.value == "read_only"
        assert cmd.safety_level.value == "safe"

    def test_question_create_has_evidence_outputs(self):
        from axiom_core.runner.command_registry import get_command
        cmd = get_command("question-create")
        assert cmd is not None
        names = [e.location for e in cmd.evidence_outputs]
        assert "question_request.json" in names
        assert "question_result.json" in names
        assert "question_summary.md" in names
        assert "pass_fail.json" in names

    def test_questions_registered(self):
        from axiom_core.runner.command_registry import get_command
        cmd = get_command("questions")
        assert cmd is not None
        assert cmd.classification.value == "read_only"

    def test_question_show_registered(self):
        from axiom_core.runner.command_registry import get_command
        cmd = get_command("question-show")
        assert cmd is not None
        assert cmd.classification.value == "read_only"

    def test_question_resolve_registered(self):
        from axiom_core.runner.command_registry import get_command
        cmd = get_command("question-resolve")
        assert cmd is not None
        assert cmd.classification.value == "read_only"
        names = [e.location for e in cmd.evidence_outputs]
        assert "question_request.json" in names
        assert "pass_fail.json" in names


# ---------------------------------------------------------------------------
# Test selection mapping test
# ---------------------------------------------------------------------------


class TestSelectionMapping:
    def test_mapping_exists(self):
        from axiom_core.test_selection_engine import _FILE_TO_TEST
        assert (
            _FILE_TO_TEST["src/axiom_core/session_question_registry.py"]
            == "tests/test_session_question_registry.py"
        )
