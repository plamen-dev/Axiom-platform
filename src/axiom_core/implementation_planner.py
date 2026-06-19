"""Implementation Plan Generator v1.

Generates structured implementation plans from approved work items using code
inventory and knowledge retrieval.  Read-only: never modifies any file, never
executes code, never creates PRs.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from sqlalchemy import String, Text
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


class ChangeType(str, Enum):
    """Kind of intended file change."""

    ADD = "add"
    MODIFY = "modify"
    DELETE = "delete"


class RiskLevel(str, Enum):
    """Risk severity for a plan note."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PlanStatus(str, Enum):
    """Lifecycle status of an implementation plan."""

    DRAFT = "draft"
    READY = "ready"
    SUPERSEDED = "superseded"


# ---------------------------------------------------------------------------
# ORM Rows
# ---------------------------------------------------------------------------


class ImplementationPlanRow(Base):
    """SQLAlchemy row for an implementation plan."""

    __tablename__ = "implementation_plans"

    plan_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    work_item_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    steps_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    file_changes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    test_plan_json: Mapped[str] = mapped_column(Text, nullable=True)
    risks_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    non_goals_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    evidence_requirements_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    related_symbols_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    related_knowledge_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[str] = mapped_column(String(50), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(50), nullable=False)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class FileChangeIntent:
    """Proposed change to a file."""

    def __init__(
        self,
        file_path: str = "",
        change_type: ChangeType = ChangeType.MODIFY,
        description: str = "",
        related_symbols: list[str] | None = None,
    ) -> None:
        self.file_path = file_path
        self.change_type = change_type
        self.description = description
        self.related_symbols = related_symbols or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "change_type": self.change_type.value,
            "description": self.description,
            "related_symbols": self.related_symbols,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileChangeIntent:
        return cls(
            file_path=data.get("file_path", ""),
            change_type=ChangeType(data.get("change_type", "modify")),
            description=data.get("description", ""),
            related_symbols=data.get("related_symbols", []),
        )


class ImplementationStep:
    """A single step in an implementation plan."""

    def __init__(
        self,
        step_number: int = 0,
        description: str = "",
        target_files: list[str] | None = None,
        verification: str = "",
    ) -> None:
        self.step_number = step_number
        self.description = description
        self.target_files = target_files or []
        self.verification = verification

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_number": self.step_number,
            "description": self.description,
            "target_files": self.target_files,
            "verification": self.verification,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImplementationStep:
        return cls(
            step_number=data.get("step_number", 0),
            description=data.get("description", ""),
            target_files=data.get("target_files", []),
            verification=data.get("verification", ""),
        )


class TestPlan:
    """Tests to run for the implementation."""

    def __init__(
        self,
        test_files: list[str] | None = None,
        new_tests_needed: list[str] | None = None,
        regression_commands: list[str] | None = None,
    ) -> None:
        self.test_files = test_files or []
        self.new_tests_needed = new_tests_needed or []
        self.regression_commands = regression_commands or []

    __test__ = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_files": self.test_files,
            "new_tests_needed": self.new_tests_needed,
            "regression_commands": self.regression_commands,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestPlan:
        return cls(
            test_files=data.get("test_files", []),
            new_tests_needed=data.get("new_tests_needed", []),
            regression_commands=data.get("regression_commands", []),
        )


class RiskNote:
    """A risk or concern for the implementation."""

    def __init__(
        self,
        description: str = "",
        level: RiskLevel = RiskLevel.LOW,
        mitigation: str = "",
    ) -> None:
        self.description = description
        self.level = level
        self.mitigation = mitigation

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "level": self.level.value,
            "mitigation": self.mitigation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RiskNote:
        return cls(
            description=data.get("description", ""),
            level=RiskLevel(data.get("level", "low")),
            mitigation=data.get("mitigation", ""),
        )


class ImplementationPlan:
    """A structured implementation plan generated from a work item."""

    def __init__(
        self,
        plan_id: str = "",
        work_item_id: str = "",
        title: str = "",
        summary: str = "",
        status: PlanStatus = PlanStatus.DRAFT,
        steps: list[ImplementationStep] | None = None,
        file_changes: list[FileChangeIntent] | None = None,
        test_plan: TestPlan | None = None,
        risks: list[RiskNote] | None = None,
        non_goals: list[str] | None = None,
        evidence_requirements: list[str] | None = None,
        related_symbols: list[str] | None = None,
        related_knowledge: list[str] | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.plan_id = plan_id or str(uuid4())
        self.work_item_id = work_item_id
        self.title = title
        self.summary = summary
        self.status = status
        self.steps = steps or []
        self.file_changes = file_changes or []
        self.test_plan = test_plan or TestPlan()
        self.risks = risks or []
        self.non_goals = non_goals or []
        self.evidence_requirements = evidence_requirements or []
        self.related_symbols = related_symbols or []
        self.related_knowledge = related_knowledge or []
        self.created_at = created_at or now
        self.updated_at = updated_at or now

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "work_item_id": self.work_item_id,
            "title": self.title,
            "summary": self.summary,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "file_changes": [f.to_dict() for f in self.file_changes],
            "test_plan": self.test_plan.to_dict(),
            "risks": [r.to_dict() for r in self.risks],
            "non_goals": self.non_goals,
            "evidence_requirements": self.evidence_requirements,
            "related_symbols": self.related_symbols,
            "related_knowledge": self.related_knowledge,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: ImplementationPlanRow) -> ImplementationPlan:
        steps_data = json.loads(row.steps_json) if row.steps_json else []
        fc_data = json.loads(row.file_changes_json) if row.file_changes_json else []
        tp_data = json.loads(row.test_plan_json) if row.test_plan_json else {}
        risks_data = json.loads(row.risks_json) if row.risks_json else []
        ng = json.loads(row.non_goals_json) if row.non_goals_json else []
        ev = json.loads(row.evidence_requirements_json) if row.evidence_requirements_json else []
        syms = json.loads(row.related_symbols_json) if row.related_symbols_json else []
        know = json.loads(row.related_knowledge_json) if row.related_knowledge_json else []

        return cls(
            plan_id=row.plan_id,
            work_item_id=row.work_item_id,
            title=row.title,
            summary=row.summary or "",
            status=PlanStatus(row.status),
            steps=[ImplementationStep.from_dict(s) for s in steps_data],
            file_changes=[FileChangeIntent.from_dict(f) for f in fc_data],
            test_plan=TestPlan.from_dict(tp_data) if tp_data else TestPlan(),
            risks=[RiskNote.from_dict(r) for r in risks_data],
            non_goals=ng,
            evidence_requirements=ev,
            related_symbols=syms,
            related_knowledge=know,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


# ---------------------------------------------------------------------------
# ImplementationPlanner — the planning engine
# ---------------------------------------------------------------------------


class ImplementationPlanner:
    """Generates implementation plans from approved work items.

    Consumes WorkItemRegistry, CodeSymbolRegistry, and optionally
    KnowledgeGraph / SemanticRetrievalEngine / CapabilityValidationRegistry
    to build structured, deterministic plans. Read-only: never modifies
    files, never executes code, never creates PRs.
    """

    def __init__(self, db_path: str | None = None) -> None:
        effective_path = db_path or os.environ.get("AXIOM_DB_PATH")
        engine = create_db_engine(effective_path)
        init_db(engine)
        self._session_factory = make_session_factory(engine)

    def generate(
        self,
        work_item_id: str,
        work_item_registry: Any,
        code_registry: Any,
        knowledge_graph: Any | None = None,
        retrieval_engine: Any | None = None,
        validation_registry: Any | None = None,
    ) -> ImplementationPlan:
        """Generate an implementation plan for a work item.

        Raises ValueError if the work item is not found or not approved.
        """
        item = work_item_registry.get_item(work_item_id)
        if item is None:
            raise ValueError(f"Work item not found: {work_item_id}")

        from axiom_core.work_item_registry import WorkItemStatus

        allowed_statuses = {
            WorkItemStatus.APPROVED,
            WorkItemStatus.IN_PROGRESS,
        }
        if item.status not in allowed_statuses:
            raise ValueError(
                f"Work item {work_item_id} has status '{item.status.value}', "
                f"expected one of: {', '.join(s.value for s in allowed_statuses)}"
            )

        target_files = self._identify_target_files(item, code_registry)
        related_symbols = self._identify_related_symbols(item, code_registry)
        file_changes = self._build_file_changes(item, target_files, related_symbols)
        steps = self._build_steps(item, file_changes)
        test_plan = self._build_test_plan(item, target_files, code_registry)
        risks = self._assess_risks(item, file_changes, code_registry)
        non_goals = self._derive_non_goals(item)
        evidence_reqs = self._derive_evidence_requirements(item)

        related_knowledge: list[str] = []
        if knowledge_graph is not None:
            related_knowledge = self._query_knowledge(item, knowledge_graph)

        plan = ImplementationPlan(
            work_item_id=work_item_id,
            title=f"Implementation Plan: {item.title}",
            summary=self._build_summary(item, file_changes),
            steps=steps,
            file_changes=file_changes,
            test_plan=test_plan,
            risks=risks,
            non_goals=non_goals,
            evidence_requirements=evidence_reqs,
            related_symbols=[s for s in related_symbols],
            related_knowledge=related_knowledge,
        )

        self._persist(plan)
        return plan

    def get_plan(self, plan_id: str) -> ImplementationPlan | None:
        with get_session(self._session_factory) as session:
            row = session.get(ImplementationPlanRow, plan_id)
            if row is None:
                return None
            return ImplementationPlan.from_row(row)

    def get_plan_for_work_item(self, work_item_id: str) -> ImplementationPlan | None:
        with get_session(self._session_factory) as session:
            row = (
                session.query(ImplementationPlanRow)
                .filter(
                    ImplementationPlanRow.work_item_id == work_item_id,
                    ImplementationPlanRow.status != PlanStatus.SUPERSEDED.value,
                )
                .order_by(ImplementationPlanRow.created_at.desc())
                .first()
            )
            if row is None:
                return None
            return ImplementationPlan.from_row(row)

    def list_plans(
        self,
        status: PlanStatus | None = None,
    ) -> list[ImplementationPlan]:
        with get_session(self._session_factory) as session:
            query = session.query(ImplementationPlanRow)
            if status is not None:
                query = query.filter(ImplementationPlanRow.status == status.value)
            query = query.order_by(ImplementationPlanRow.created_at.desc())
            return [ImplementationPlan.from_row(row) for row in query.all()]

    # -- persistence --------------------------------------------------------

    def _persist(self, plan: ImplementationPlan) -> None:
        with get_session(self._session_factory) as session:
            previous = (
                session.query(ImplementationPlanRow)
                .filter(
                    ImplementationPlanRow.work_item_id == plan.work_item_id,
                    ImplementationPlanRow.plan_id != plan.plan_id,
                    ImplementationPlanRow.status != PlanStatus.SUPERSEDED.value,
                )
                .all()
            )
            for prev in previous:
                prev.status = PlanStatus.SUPERSEDED.value
            row = ImplementationPlanRow(
                plan_id=plan.plan_id,
                work_item_id=plan.work_item_id,
                title=plan.title,
                summary=plan.summary,
                status=plan.status.value,
                steps_json=json.dumps([s.to_dict() for s in plan.steps]),
                file_changes_json=json.dumps([f.to_dict() for f in plan.file_changes]),
                test_plan_json=json.dumps(plan.test_plan.to_dict()),
                risks_json=json.dumps([r.to_dict() for r in plan.risks]),
                non_goals_json=json.dumps(plan.non_goals),
                evidence_requirements_json=json.dumps(plan.evidence_requirements),
                related_symbols_json=json.dumps(plan.related_symbols),
                related_knowledge_json=json.dumps(plan.related_knowledge),
                created_at=plan.created_at,
                updated_at=plan.updated_at,
            )
            session.add(row)

    # -- planning helpers ---------------------------------------------------

    def _identify_target_files(
        self,
        item: Any,
        code_registry: Any,
    ) -> list[str]:
        keywords = self._extract_keywords(item)
        files = code_registry.list_files()
        matched: list[str] = []
        for f in files:
            path_lower = f.path.lower()
            mod_lower = (f.module_name or "").lower()
            for kw in keywords:
                if kw in path_lower or kw in mod_lower:
                    matched.append(f.path)
                    break
        return sorted(set(matched))

    def _identify_related_symbols(
        self,
        item: Any,
        code_registry: Any,
    ) -> list[str]:
        keywords = self._extract_keywords(item)
        symbols = code_registry.list_symbols()
        matched: list[str] = []
        for s in symbols:
            name_lower = s.name.lower()
            qname_lower = s.qualified_name.lower()
            for kw in keywords:
                if kw in name_lower or kw in qname_lower:
                    matched.append(s.qualified_name)
                    break
        return sorted(set(matched))

    def _build_file_changes(
        self,
        item: Any,
        target_files: list[str],
        related_symbols: list[str],
    ) -> list[FileChangeIntent]:
        from axiom_core.work_item_registry import WorkItemType

        changes: list[FileChangeIntent] = []

        if item.item_type == WorkItemType.FEATURE:
            change_type = ChangeType.ADD
            desc_prefix = "Add/update"
        elif item.item_type == WorkItemType.BUG_FIX:
            change_type = ChangeType.MODIFY
            desc_prefix = "Fix"
        elif item.item_type == WorkItemType.CLEANUP:
            change_type = ChangeType.MODIFY
            desc_prefix = "Clean up"
        elif item.item_type == WorkItemType.REFACTOR:
            change_type = ChangeType.MODIFY
            desc_prefix = "Refactor"
        else:
            change_type = ChangeType.MODIFY
            desc_prefix = "Update"

        for fp in target_files:
            mod_path = fp.replace("/", ".").removesuffix(".py")
            if mod_path.startswith("src."):
                mod_path = mod_path[4:]
            file_syms = [s for s in related_symbols if mod_path in s]
            changes.append(FileChangeIntent(
                file_path=fp,
                change_type=change_type,
                description=f"{desc_prefix} in {fp}",
                related_symbols=file_syms,
            ))

        return changes

    def _build_steps(
        self,
        item: Any,
        file_changes: list[FileChangeIntent],
    ) -> list[ImplementationStep]:
        steps: list[ImplementationStep] = []
        step_num = 1

        if file_changes:
            for fc in file_changes:
                steps.append(ImplementationStep(
                    step_number=step_num,
                    description=fc.description,
                    target_files=[fc.file_path],
                    verification=f"ruff check {fc.file_path}",
                ))
                step_num += 1

        steps.append(ImplementationStep(
            step_number=step_num,
            description="Run targeted tests",
            target_files=[],
            verification="poetry run pytest -x -q",
        ))
        step_num += 1

        steps.append(ImplementationStep(
            step_number=step_num,
            description="Run lint check",
            target_files=[],
            verification="poetry run ruff check",
        ))

        return steps

    def _build_test_plan(
        self,
        item: Any,
        target_files: list[str],
        code_registry: Any,
    ) -> TestPlan:
        test_files: list[str] = []
        coverage_refs = code_registry.list_test_coverage()

        target_modules = set()
        for tf in target_files:
            mod = tf.replace("/", ".").removesuffix(".py")
            if mod.startswith("src."):
                mod = mod[4:]
            target_modules.add(mod)

        for ref in coverage_refs:
            if ref.target_module in target_modules:
                test_files.append(ref.test_file)

        new_tests: list[str] = []
        from axiom_core.work_item_registry import WorkItemType

        if item.item_type == WorkItemType.FEATURE:
            new_tests.append(f"tests/test_{self._slug(item.title)}.py")
        elif item.item_type == WorkItemType.BUG_FIX:
            new_tests.append(f"Regression test for: {item.title}")

        return TestPlan(
            test_files=sorted(set(test_files)),
            new_tests_needed=new_tests,
            regression_commands=["poetry run pytest -x -q", "poetry run ruff check"],
        )

    def _assess_risks(
        self,
        item: Any,
        file_changes: list[FileChangeIntent],
        code_registry: Any,
    ) -> list[RiskNote]:
        risks: list[RiskNote] = []

        if len(file_changes) > 5:
            risks.append(RiskNote(
                description=f"Large change scope: {len(file_changes)} files",
                level=RiskLevel.MEDIUM,
                mitigation="Consider splitting into smaller PRs",
            ))

        cli_files = [fc for fc in file_changes if "cli" in fc.file_path.lower()]
        if cli_files:
            risks.append(RiskNote(
                description="CLI surface changes may affect user-facing behavior",
                level=RiskLevel.MEDIUM,
                mitigation="Run end-to-end CLI tests after changes",
            ))

        registry_files = [fc for fc in file_changes if "registry" in fc.file_path.lower()]
        if registry_files:
            risks.append(RiskNote(
                description="Registry changes may affect persistence layer",
                level=RiskLevel.MEDIUM,
                mitigation="Verify database migration compatibility",
            ))

        from axiom_core.work_item_registry import WorkItemType

        if item.item_type == WorkItemType.REFACTOR:
            risks.append(RiskNote(
                description="Refactoring may introduce subtle behavioral changes",
                level=RiskLevel.HIGH,
                mitigation="Ensure comprehensive test coverage before and after",
            ))

        return risks

    def _derive_non_goals(self, item: Any) -> list[str]:
        return [
            "No code execution",
            "No autonomous PR creation",
            "No modification of existing tests unless explicitly required",
        ]

    def _derive_evidence_requirements(self, item: Any) -> list[str]:
        from axiom_core.work_item_registry import WorkItemType

        reqs = ["All targeted tests pass", "ruff check clean"]
        if item.item_type == WorkItemType.BUG_FIX:
            reqs.append("Regression test proves fix")
        if item.item_type == WorkItemType.FEATURE:
            reqs.append("New test file with comprehensive coverage")
        return reqs

    def _query_knowledge(
        self,
        item: Any,
        knowledge_graph: Any,
    ) -> list[str]:
        try:
            nodes = knowledge_graph.list_nodes()
            keywords = self._extract_keywords(item)
            matched: list[str] = []
            for node in nodes:
                label_lower = node.label.lower()
                for kw in keywords:
                    if kw in label_lower:
                        matched.append(node.label)
                        break
            return sorted(set(matched))[:10]
        except Exception:
            return []

    def _build_summary(
        self,
        item: Any,
        file_changes: list[FileChangeIntent],
    ) -> str:
        return (
            f"{item.item_type.value.replace('_', ' ').title()}: {item.title}. "
            f"Affects {len(file_changes)} file(s)."
        )

    @staticmethod
    def _extract_keywords(item: Any) -> list[str]:
        text = f"{item.title} {item.description or ''}"
        words = text.lower().split()
        stop_words = {
            "a", "an", "the", "in", "on", "at", "to", "for", "of", "and",
            "or", "is", "are", "was", "were", "be", "been", "being", "have",
            "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "shall", "can", "not", "no", "but",
            "if", "then", "else", "when", "while", "with", "from", "by",
            "this", "that", "these", "those", "it", "its", "as", "so",
            "up", "out", "about", "into",
        }
        keywords = []
        for w in words:
            cleaned = w.strip(".,;:!?\"'()[]{}").replace("-", "_")
            if cleaned and cleaned not in stop_words and len(cleaned) > 2:
                keywords.append(cleaned)
        return list(dict.fromkeys(keywords))

    @staticmethod
    def _slug(text: str) -> str:
        return (
            text.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace(".", "_")[:50]
        )
