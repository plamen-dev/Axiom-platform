"""Codebase Inventory and Symbol Registry v1.

Read-only registry of repo structure: files, modules, classes, functions,
CLI commands, tests, docs, and architecture docs.  Axiom uses this to
understand its own codebase before planning code changes.

No code modification, no execution, no refactoring.
"""

from __future__ import annotations

import ast
import json
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
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


class FileCategory(str, Enum):
    """Classification of a file's role in the codebase."""

    SOURCE = "source"
    TEST = "test"
    CLI = "cli"
    ARCHITECTURE_DOC = "architecture_doc"
    RUNBOOK = "runbook"
    LOG_DOC = "log_doc"
    CONFIG = "config"
    ARTIFACT = "artifact"
    OTHER = "other"


class SymbolKind(str, Enum):
    """Kind of code symbol."""

    CLASS = "class"
    FUNCTION = "function"
    CLI_COMMAND = "cli_command"
    ENUM = "enum"
    CONSTANT = "constant"
    MODULE = "module"


# ---------------------------------------------------------------------------
# ORM Rows
# ---------------------------------------------------------------------------


class CodeFileRow(Base):
    """SQLAlchemy row for a file in the codebase."""

    __tablename__ = "code_files"

    file_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    path: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)
    category: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    module_name: Mapped[str] = mapped_column(String(500), nullable=True)
    line_count: Mapped[int] = mapped_column(nullable=False, default=0)
    size_bytes: Mapped[int] = mapped_column(nullable=False, default=0)
    scanned_at: Mapped[str] = mapped_column(String(50), nullable=False)


class CodeSymbolRow(Base):
    """SQLAlchemy row for a code symbol."""

    __tablename__ = "code_symbols"

    symbol_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    qualified_name: Mapped[str] = mapped_column(String(1000), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False, index=True)
    line_number: Mapped[int] = mapped_column(nullable=False, default=0)
    parent_symbol: Mapped[str] = mapped_column(String(500), nullable=True)
    docstring: Mapped[str] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)
    scanned_at: Mapped[str] = mapped_column(String(50), nullable=False)


class TestCoverageRow(Base):
    """Link between a test file and the module it tests."""

    __tablename__ = "test_coverage_refs"

    ref_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    test_file: Mapped[str] = mapped_column(String(1000), nullable=False, index=True)
    target_module: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    scanned_at: Mapped[str] = mapped_column(String(50), nullable=False)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class CodeFileRecord:
    """A file in the codebase."""

    def __init__(
        self,
        file_id: str = "",
        path: str = "",
        category: FileCategory = FileCategory.OTHER,
        module_name: str | None = None,
        line_count: int = 0,
        size_bytes: int = 0,
        scanned_at: str | None = None,
    ) -> None:
        self.file_id = file_id or str(uuid4())
        self.path = path
        self.category = category
        self.module_name = module_name
        self.line_count = line_count
        self.size_bytes = size_bytes
        self.scanned_at = scanned_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "path": self.path,
            "category": self.category.value,
            "module_name": self.module_name,
            "line_count": self.line_count,
            "size_bytes": self.size_bytes,
            "scanned_at": self.scanned_at,
        }


class CodeSymbol:
    """A symbol (class, function, CLI command, etc.) in the codebase."""

    def __init__(
        self,
        symbol_id: str = "",
        name: str = "",
        qualified_name: str = "",
        kind: SymbolKind = SymbolKind.FUNCTION,
        file_path: str = "",
        line_number: int = 0,
        parent_symbol: str | None = None,
        docstring: str | None = None,
        metadata: dict[str, Any] | None = None,
        scanned_at: str | None = None,
    ) -> None:
        self.symbol_id = symbol_id or str(uuid4())
        self.name = name
        self.qualified_name = qualified_name
        self.kind = kind
        self.file_path = file_path
        self.line_number = line_number
        self.parent_symbol = parent_symbol
        self.docstring = docstring
        self.metadata = metadata
        self.scanned_at = scanned_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol_id": self.symbol_id,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "kind": self.kind.value,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "parent_symbol": self.parent_symbol,
            "docstring": self.docstring,
            "metadata": self.metadata,
            "scanned_at": self.scanned_at,
        }


class CodeSurface:
    """Summary of the codebase surface area."""

    def __init__(
        self,
        total_files: int = 0,
        total_symbols: int = 0,
        files_by_category: dict[str, int] | None = None,
        symbols_by_kind: dict[str, int] | None = None,
        test_coverage_refs: int = 0,
        scanned_at: str | None = None,
    ) -> None:
        self.total_files = total_files
        self.total_symbols = total_symbols
        self.files_by_category = files_by_category or {}
        self.symbols_by_kind = symbols_by_kind or {}
        self.test_coverage_refs = test_coverage_refs
        self.scanned_at = scanned_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_files": self.total_files,
            "total_symbols": self.total_symbols,
            "files_by_category": self.files_by_category,
            "symbols_by_kind": self.symbols_by_kind,
            "test_coverage_refs": self.test_coverage_refs,
            "scanned_at": self.scanned_at,
        }


class TestCoverageReference:  # noqa: N801  # name matches spec
    """Link between a test file and the module it tests."""

    __test__ = False

    def __init__(
        self,
        test_file: str = "",
        target_module: str = "",
        scanned_at: str | None = None,
    ) -> None:
        self.test_file = test_file
        self.target_module = target_module
        self.scanned_at = scanned_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_file": self.test_file,
            "target_module": self.target_module,
            "scanned_at": self.scanned_at,
        }


# ---------------------------------------------------------------------------
# CodebaseInventory — repo scanner
# ---------------------------------------------------------------------------


class CodebaseInventory:
    """Scans a local repo to build an inventory of files and symbols.

    Read-only: never modifies any file. Uses Python's ``ast`` module for
    symbol extraction — no external static-analysis dependencies.
    """

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root).resolve()

    def scan(self) -> tuple[list[CodeFileRecord], list[CodeSymbol], list[TestCoverageReference]]:
        """Scan the repo and return files, symbols, and test coverage refs."""
        now = datetime.now(timezone.utc).isoformat()
        files: list[CodeFileRecord] = []
        symbols: list[CodeSymbol] = []
        coverage_refs: list[TestCoverageReference] = []

        for fpath in sorted(self.repo_root.rglob("*")):
            if not fpath.is_file():
                continue
            rel = str(fpath.relative_to(self.repo_root))
            if self._should_skip(rel):
                continue

            category = self._categorize(rel)
            line_count = 0
            size_bytes = fpath.stat().st_size

            if fpath.suffix == ".py":
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
                except OSError:
                    content = ""

                module_name = self._module_name(rel)
                files.append(CodeFileRecord(
                    path=rel,
                    category=category,
                    module_name=module_name,
                    line_count=line_count,
                    size_bytes=size_bytes,
                    scanned_at=now,
                ))

                py_symbols = self._extract_symbols(content, rel, module_name, now)
                symbols.extend(py_symbols)

                if category == FileCategory.TEST:
                    refs = self._infer_test_targets(content, rel, now)
                    coverage_refs.extend(refs)

            elif fpath.suffix == ".md":
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
                except OSError:
                    line_count = 0
                files.append(CodeFileRecord(
                    path=rel,
                    category=category,
                    module_name=None,
                    line_count=line_count,
                    size_bytes=size_bytes,
                    scanned_at=now,
                ))

            elif rel in (
                "pyproject.toml", "poetry.lock", ".gitignore",
                "contracts/pipe_message_schema.json",
            ) or fpath.suffix in (".json", ".toml", ".yml", ".yaml"):
                files.append(CodeFileRecord(
                    path=rel,
                    category=FileCategory.CONFIG if category == FileCategory.OTHER else category,
                    module_name=None,
                    line_count=0,
                    size_bytes=size_bytes,
                    scanned_at=now,
                ))

        return files, symbols, coverage_refs

    def extract_import_edges(self) -> list[tuple[str, str]]:
        """Return deterministic internal import edges ``(importer, imported)``.

        Walks every ``src/`` Python module with :mod:`ast` and records an edge
        whenever it imports another internal ``src/`` module. Standard-library
        and third-party imports are ignored, as are self-edges and duplicates.
        Read-only: never modifies any file. This makes the inventory the single
        source of truth for the repository's real import relationships.
        """
        known: set[str] = set()
        importer_files: list[tuple[str, str]] = []
        for fpath in sorted(self.repo_root.rglob("*.py")):
            if not fpath.is_file():
                continue
            rel = str(fpath.relative_to(self.repo_root))
            if self._should_skip(rel) or not rel.startswith("src/"):
                continue
            module_name = self._module_name(rel)
            if not module_name:
                continue
            known.add(module_name)
            importer_files.append((rel, module_name))

        edges: set[tuple[str, str]] = set()
        for rel, src_module in importer_files:
            try:
                content = (self.repo_root / rel).read_text(
                    encoding="utf-8", errors="replace"
                )
                tree = ast.parse(content, filename=rel)
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                for target in self._resolve_import_targets(node, known):
                    if target != src_module:
                        edges.add((src_module, target))
        return sorted(edges)

    @staticmethod
    def _resolve_import_targets(
        node: ast.AST, known: set[str]
    ) -> list[str]:
        """Resolve an AST import node to known internal module targets."""
        targets: list[str] = []
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in known:
                    targets.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # ignore relative imports
                return targets
            mod = node.module or ""
            if not mod:
                return targets
            resolved_sub = [
                f"{mod}.{a.name}"
                for a in node.names
                if f"{mod}.{a.name}" in known
            ]
            if resolved_sub:
                targets.extend(resolved_sub)
            elif mod in known:
                targets.append(mod)
        return targets

    def _should_skip(self, rel: str) -> bool:
        skip_prefixes = (
            ".git/", "__pycache__/", ".mypy_cache/", ".pytest_cache/",
            ".ruff_cache/", "node_modules/", ".venv/", "venv/",
            ".eggs/", ".egg-info/",
        )
        for prefix in skip_prefixes:
            if rel.startswith(prefix) or f"/{prefix}" in rel:
                return True
        if "/__pycache__/" in rel:
            return True
        return False

    def _categorize(self, rel: str) -> FileCategory:
        if rel.startswith("tests/"):
            return FileCategory.TEST
        if rel.startswith("src/axiom_cli/"):
            return FileCategory.CLI
        if rel.startswith("src/"):
            return FileCategory.SOURCE
        if rel.startswith("docs/architecture/"):
            return FileCategory.ARCHITECTURE_DOC
        if rel.startswith("docs/runbooks/"):
            return FileCategory.RUNBOOK
        if rel.startswith("docs/logs/"):
            return FileCategory.LOG_DOC
        if rel.startswith("artifacts/"):
            return FileCategory.ARTIFACT
        return FileCategory.OTHER

    def _module_name(self, rel: str) -> str | None:
        if not rel.endswith(".py"):
            return None
        parts = rel.replace("/", ".").removesuffix(".py")
        if parts.startswith("src."):
            parts = parts[4:]
        if parts.endswith(".__init__"):
            parts = parts.removesuffix(".__init__")
        return parts

    def _extract_symbols(
        self,
        content: str,
        rel_path: str,
        module_name: str | None,
        now: str,
    ) -> list[CodeSymbol]:
        symbols: list[CodeSymbol] = []
        try:
            tree = ast.parse(content, filename=rel_path)
        except SyntaxError:
            return symbols

        prefix = module_name or rel_path

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                kind = SymbolKind.ENUM if self._is_enum_class(node) else SymbolKind.CLASS
                symbols.append(CodeSymbol(
                    name=node.name,
                    qualified_name=f"{prefix}.{node.name}",
                    kind=kind,
                    file_path=rel_path,
                    line_number=node.lineno,
                    docstring=ast.get_docstring(node),
                    scanned_at=now,
                ))
                self._walk_class_body(node, prefix, rel_path, now, symbols)

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                meta = self._detect_cli_command(node)
                if meta is not None:
                    symbols.append(CodeSymbol(
                        name=meta["command_name"],
                        qualified_name=f"{prefix}.{meta['command_name']}",
                        kind=SymbolKind.CLI_COMMAND,
                        file_path=rel_path,
                        line_number=node.lineno,
                        docstring=ast.get_docstring(node),
                        metadata=meta,
                        scanned_at=now,
                    ))
                else:
                    symbols.append(CodeSymbol(
                        name=node.name,
                        qualified_name=f"{prefix}.{node.name}",
                        kind=SymbolKind.FUNCTION,
                        file_path=rel_path,
                        line_number=node.lineno,
                        docstring=ast.get_docstring(node),
                        scanned_at=now,
                    ))

            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.isupper():
                        symbols.append(CodeSymbol(
                            name=target.id,
                            qualified_name=f"{prefix}.{target.id}",
                            kind=SymbolKind.CONSTANT,
                            file_path=rel_path,
                            line_number=node.lineno,
                            scanned_at=now,
                        ))

        return symbols

    def _walk_class_body(
        self,
        cls_node: ast.ClassDef,
        prefix: str,
        rel_path: str,
        now: str,
        symbols: list[CodeSymbol],
    ) -> None:
        for child in ast.walk(cls_node):
            if child is cls_node:
                continue
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                parent = self._find_parent_class(cls_node, child)
                parent_name = parent.name if parent else cls_node.name
                symbols.append(CodeSymbol(
                    name=child.name,
                    qualified_name=f"{prefix}.{parent_name}.{child.name}",
                    kind=SymbolKind.FUNCTION,
                    file_path=rel_path,
                    line_number=child.lineno,
                    parent_symbol=parent_name,
                    docstring=ast.get_docstring(child),
                    scanned_at=now,
                ))
            elif isinstance(child, ast.ClassDef):
                kind = SymbolKind.ENUM if self._is_enum_class(child) else SymbolKind.CLASS
                symbols.append(CodeSymbol(
                    name=child.name,
                    qualified_name=f"{prefix}.{cls_node.name}.{child.name}",
                    kind=kind,
                    file_path=rel_path,
                    line_number=child.lineno,
                    parent_symbol=cls_node.name,
                    docstring=ast.get_docstring(child),
                    scanned_at=now,
                ))

    @staticmethod
    def _find_parent_class(root: ast.ClassDef, target: ast.AST) -> ast.ClassDef | None:
        for node in ast.walk(root):
            if isinstance(node, ast.ClassDef):
                for child in ast.iter_child_nodes(node):
                    if child is target:
                        return node
        return None

    def _is_enum_class(self, node: ast.ClassDef) -> bool:
        for base in node.bases:
            if isinstance(base, ast.Attribute) and base.attr == "Enum":
                return True
            if isinstance(base, ast.Name) and base.id == "str":
                continue
            if isinstance(base, ast.Name) and base.id == "Enum":
                return True
        return False

    def _detect_cli_command(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any] | None:
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                func = decorator.func
                if isinstance(func, ast.Attribute) and func.attr == "command":
                    if decorator.args:
                        arg = decorator.args[0]
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            return {"command_name": arg.value}
                    else:
                        cmd_name = node.name.replace("_", "-").removesuffix("-cmd")
                        return {"command_name": cmd_name}
        return None

    def _infer_test_targets(
        self,
        content: str,
        test_path: str,
        now: str,
    ) -> list[TestCoverageReference]:
        refs: list[TestCoverageReference] = []
        try:
            tree = ast.parse(content, filename=test_path)
        except SyntaxError:
            return refs

        seen: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom) and node.module:
                    mod = node.module
                    if mod.startswith("axiom_") and mod not in seen:
                        seen.add(mod)
                        refs.append(TestCoverageReference(
                            test_file=test_path,
                            target_module=mod,
                            scanned_at=now,
                        ))
        return refs


# ---------------------------------------------------------------------------
# CodeSymbolRegistry — persistence layer
# ---------------------------------------------------------------------------


class CodeSymbolRegistry:
    """Persistent registry of codebase files and symbols.

    Backed by SQLite. Supports refresh (clear + rescan) and read queries.
    Never modifies source files.
    """

    def __init__(self, db_path: str | None = None) -> None:
        effective_path = db_path or os.environ.get("AXIOM_DB_PATH")
        engine = create_db_engine(effective_path)
        init_db(engine)
        self._session_factory = make_session_factory(engine)

    # -- write (refresh) ----------------------------------------------------

    def refresh(
        self,
        files: list[CodeFileRecord],
        symbols: list[CodeSymbol],
        coverage_refs: list[TestCoverageReference],
    ) -> CodeSurface:
        now = datetime.now(timezone.utc).isoformat()
        with get_session(self._session_factory) as session:
            session.query(TestCoverageRow).delete()
            session.query(CodeSymbolRow).delete()
            session.query(CodeFileRow).delete()

            for f in files:
                session.add(CodeFileRow(
                    file_id=f.file_id,
                    path=f.path,
                    category=f.category.value,
                    module_name=f.module_name,
                    line_count=f.line_count,
                    size_bytes=f.size_bytes,
                    scanned_at=f.scanned_at,
                ))

            for s in symbols:
                session.add(CodeSymbolRow(
                    symbol_id=s.symbol_id,
                    name=s.name,
                    qualified_name=s.qualified_name,
                    kind=s.kind.value,
                    file_path=s.file_path,
                    line_number=s.line_number,
                    parent_symbol=s.parent_symbol,
                    docstring=s.docstring,
                    metadata_json=json.dumps(s.metadata) if s.metadata else None,
                    scanned_at=s.scanned_at,
                ))

            for ref in coverage_refs:
                session.add(TestCoverageRow(
                    ref_id=str(uuid4()),
                    test_file=ref.test_file,
                    target_module=ref.target_module,
                    scanned_at=ref.scanned_at,
                ))

        files_by_cat: dict[str, int] = {}
        for f in files:
            files_by_cat[f.category.value] = files_by_cat.get(f.category.value, 0) + 1
        symbols_by_kind: dict[str, int] = {}
        for s in symbols:
            symbols_by_kind[s.kind.value] = symbols_by_kind.get(s.kind.value, 0) + 1

        return CodeSurface(
            total_files=len(files),
            total_symbols=len(symbols),
            files_by_category=files_by_cat,
            symbols_by_kind=symbols_by_kind,
            test_coverage_refs=len(coverage_refs),
            scanned_at=now,
        )

    # -- read ---------------------------------------------------------------

    def get_surface(self) -> CodeSurface:
        with get_session(self._session_factory) as session:
            file_rows = session.query(CodeFileRow).all()
            symbol_rows = session.query(CodeSymbolRow).all()
            ref_count = session.query(TestCoverageRow).count()

            files_by_cat: dict[str, int] = {}
            for row in file_rows:
                files_by_cat[row.category] = files_by_cat.get(row.category, 0) + 1
            symbols_by_kind: dict[str, int] = {}
            for row in symbol_rows:
                symbols_by_kind[row.kind] = symbols_by_kind.get(row.kind, 0) + 1

            scanned_at = ""
            if file_rows:
                scanned_at = max(r.scanned_at for r in file_rows)

            return CodeSurface(
                total_files=len(file_rows),
                total_symbols=len(symbol_rows),
                files_by_category=files_by_cat,
                symbols_by_kind=symbols_by_kind,
                test_coverage_refs=ref_count,
                scanned_at=scanned_at,
            )

    def list_files(
        self,
        category: FileCategory | None = None,
    ) -> list[CodeFileRecord]:
        with get_session(self._session_factory) as session:
            query = session.query(CodeFileRow)
            if category is not None:
                query = query.filter(CodeFileRow.category == category.value)
            query = query.order_by(CodeFileRow.path.asc())
            return [
                CodeFileRecord(
                    file_id=row.file_id,
                    path=row.path,
                    category=FileCategory(row.category),
                    module_name=row.module_name,
                    line_count=row.line_count,
                    size_bytes=row.size_bytes,
                    scanned_at=row.scanned_at,
                )
                for row in query.all()
            ]

    def list_symbols(
        self,
        kind: SymbolKind | None = None,
        file_path: str | None = None,
    ) -> list[CodeSymbol]:
        with get_session(self._session_factory) as session:
            query = session.query(CodeSymbolRow)
            if kind is not None:
                query = query.filter(CodeSymbolRow.kind == kind.value)
            if file_path is not None:
                query = query.filter(CodeSymbolRow.file_path == file_path)
            query = query.order_by(CodeSymbolRow.qualified_name.asc())
            return [self._row_to_symbol(row) for row in query.all()]

    def get_symbol(self, name: str) -> list[CodeSymbol]:
        with get_session(self._session_factory) as session:
            rows = (
                session.query(CodeSymbolRow)
                .filter(
                    (CodeSymbolRow.name == name)
                    | (CodeSymbolRow.qualified_name == name)
                )
                .order_by(CodeSymbolRow.qualified_name.asc())
                .all()
            )
            return [self._row_to_symbol(row) for row in rows]

    def list_test_coverage(self) -> list[TestCoverageReference]:
        with get_session(self._session_factory) as session:
            rows = (
                session.query(TestCoverageRow)
                .order_by(TestCoverageRow.test_file.asc())
                .all()
            )
            return [
                TestCoverageReference(
                    test_file=row.test_file,
                    target_module=row.target_module,
                    scanned_at=row.scanned_at,
                )
                for row in rows
            ]

    def _row_to_symbol(self, row: CodeSymbolRow) -> CodeSymbol:
        metadata = None
        if row.metadata_json:
            metadata = json.loads(row.metadata_json)
        return CodeSymbol(
            symbol_id=row.symbol_id,
            name=row.name,
            qualified_name=row.qualified_name,
            kind=SymbolKind(row.kind),
            file_path=row.file_path,
            line_number=row.line_number,
            parent_symbol=row.parent_symbol,
            docstring=row.docstring,
            metadata=metadata,
            scanned_at=row.scanned_at,
        )
