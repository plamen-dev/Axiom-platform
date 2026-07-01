"""Tests for Codebase Inventory and Symbol Registry v1."""

import json
import textwrap
from pathlib import PureWindowsPath

import pytest
from axiom_core.codebase_inventory import (
    CodebaseInventory,
    CodeFileRecord,
    CodeSurface,
    CodeSymbol,
    CodeSymbolRegistry,
    FileCategory,
    SymbolKind,
    TestCoverageReference,
)


@pytest.fixture()
def registry(tmp_path, monkeypatch):
    db = str(tmp_path / "codebase.db")
    monkeypatch.setenv("AXIOM_DB_PATH", db)
    return CodeSymbolRegistry(db_path=db)


@pytest.fixture()
def sample_repo(tmp_path):
    """Create a minimal repo structure for scanning."""
    src = tmp_path / "src" / "axiom_core"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("")
    (src / "models.py").write_text(textwrap.dedent("""\
        from enum import Enum

        class SafetyLevel(str, Enum):
            SAFE = "safe"
            HIGH_RISK = "high_risk"

        class BaseModel:
            def validate(self):
                pass

        MAX_RETRIES = 3
    """))

    cli_dir = tmp_path / "src" / "axiom_cli"
    cli_dir.mkdir(parents=True)
    (cli_dir / "__init__.py").write_text("")
    (cli_dir / "main.py").write_text(textwrap.dedent("""\
        import click

        @click.group()
        def cli():
            pass

        @cli.command("demo")
        def demo_cmd():
            \"\"\"Run demo.\"\"\"
            pass
    """))

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("")
    (tests_dir / "test_models.py").write_text(textwrap.dedent("""\
        from axiom_core.models import BaseModel

        def test_validate():
            m = BaseModel()
            m.validate()
    """))

    docs_arch = tmp_path / "docs" / "architecture"
    docs_arch.mkdir(parents=True)
    (docs_arch / "overview.md").write_text("# Architecture\n\nOverview.")

    docs_rb = tmp_path / "docs" / "runbooks"
    docs_rb.mkdir(parents=True)
    (docs_rb / "deploy.md").write_text("# Deploy\n\nSteps.")

    docs_logs = tmp_path / "docs" / "logs"
    docs_logs.mkdir(parents=True)
    (docs_logs / "ledger.md").write_text("# Ledger")

    (tmp_path / "pyproject.toml").write_text("[tool.poetry]\nname = 'test'")

    artifacts = tmp_path / "artifacts" / "runs"
    artifacts.mkdir(parents=True)
    (artifacts / "report.md").write_text("# Report")

    return tmp_path


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_file_categories(self):
        assert len(FileCategory) == 9
        assert FileCategory.SOURCE.value == "source"
        assert FileCategory.TEST.value == "test"
        assert FileCategory.CLI.value == "cli"
        assert FileCategory.ARCHITECTURE_DOC.value == "architecture_doc"
        assert FileCategory.RUNBOOK.value == "runbook"
        assert FileCategory.LOG_DOC.value == "log_doc"
        assert FileCategory.CONFIG.value == "config"
        assert FileCategory.ARTIFACT.value == "artifact"
        assert FileCategory.OTHER.value == "other"

    def test_symbol_kinds(self):
        assert len(SymbolKind) == 6
        assert SymbolKind.CLASS.value == "class"
        assert SymbolKind.FUNCTION.value == "function"
        assert SymbolKind.CLI_COMMAND.value == "cli_command"
        assert SymbolKind.ENUM.value == "enum"
        assert SymbolKind.CONSTANT.value == "constant"
        assert SymbolKind.MODULE.value == "module"


# ---------------------------------------------------------------------------
# CodebaseInventory scanner
# ---------------------------------------------------------------------------


class TestScanner:
    def test_scan_finds_files(self, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        files, symbols, refs = scanner.scan()
        paths = {f.path for f in files}
        assert "src/axiom_core/models.py" in paths
        assert "src/axiom_cli/main.py" in paths
        assert "tests/test_models.py" in paths
        assert "docs/architecture/overview.md" in paths

    def test_scan_categorizes_files(self, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        files, _, _ = scanner.scan()
        by_path = {f.path: f for f in files}
        assert by_path["src/axiom_core/models.py"].category == FileCategory.SOURCE
        assert by_path["src/axiom_cli/main.py"].category == FileCategory.CLI
        assert by_path["tests/test_models.py"].category == FileCategory.TEST
        assert by_path["docs/architecture/overview.md"].category == FileCategory.ARCHITECTURE_DOC
        assert by_path["docs/runbooks/deploy.md"].category == FileCategory.RUNBOOK
        assert by_path["docs/logs/ledger.md"].category == FileCategory.LOG_DOC

    def test_scan_extracts_symbols(self, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        _, symbols, _ = scanner.scan()
        names = {s.name for s in symbols}
        assert "SafetyLevel" in names
        assert "BaseModel" in names
        assert "validate" in names
        assert "MAX_RETRIES" in names

    def test_scan_detects_enum(self, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        _, symbols, _ = scanner.scan()
        by_name = {s.name: s for s in symbols if s.name == "SafetyLevel"}
        assert "SafetyLevel" in by_name
        assert by_name["SafetyLevel"].kind == SymbolKind.ENUM

    def test_scan_detects_cli_commands(self, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        _, symbols, _ = scanner.scan()
        cli_cmds = [s for s in symbols if s.kind == SymbolKind.CLI_COMMAND]
        assert any(s.name == "demo" for s in cli_cmds)

    def test_scan_detects_constants(self, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        _, symbols, _ = scanner.scan()
        constants = [s for s in symbols if s.kind == SymbolKind.CONSTANT]
        assert any(s.name == "MAX_RETRIES" for s in constants)

    def test_scan_infers_test_targets(self, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        _, _, refs = scanner.scan()
        assert len(refs) >= 1
        assert any(r.target_module == "axiom_core.models" for r in refs)

    def test_rel_posix_normalizes_windows_separators(self):
        """Regression: repo-relative paths must use forward slashes on Windows.

        ``str(Path.relative_to())`` yields backslashes on Windows, which breaks
        every downstream ``startswith("src/")`` check and the module-name
        ``.replace("/", ".")`` logic — producing ``module_count=0`` /
        ``import_edge_count=0`` on Windows (see docs/logs/bug-validation-log.md).
        ``PureWindowsPath`` reproduces the backslash behavior cross-platform.
        """
        root = PureWindowsPath(r"C:\Dev\Axiom")
        fpath = PureWindowsPath(r"C:\Dev\Axiom\src\axiom_core\foo.py")
        rel = CodebaseInventory._rel_posix(fpath, root)
        assert rel == "src/axiom_core/foo.py"
        # Downstream classification then works for the normalized path.
        scanner = CodebaseInventory.__new__(CodebaseInventory)
        assert scanner._categorize(rel) == FileCategory.SOURCE
        assert scanner._module_name(rel) == "axiom_core.foo"

    def test_scan_module_name(self, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        files, _, _ = scanner.scan()
        by_path = {f.path: f for f in files}
        assert by_path["src/axiom_core/models.py"].module_name == "axiom_core.models"

    def test_scan_line_count(self, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        files, _, _ = scanner.scan()
        by_path = {f.path: f for f in files}
        assert by_path["src/axiom_core/models.py"].line_count > 0

    def test_scan_deterministic(self, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        files1, sym1, _ = scanner.scan()
        files2, sym2, _ = scanner.scan()
        assert [f.path for f in files1] == [f.path for f in files2]
        assert [s.qualified_name for s in sym1] == [s.qualified_name for s in sym2]

    def test_scan_skips_pycache(self, sample_repo):
        cache = sample_repo / "src" / "axiom_core" / "__pycache__"
        cache.mkdir()
        (cache / "models.cpython-312.pyc").write_bytes(b"\x00")
        scanner = CodebaseInventory(sample_repo)
        files, _, _ = scanner.scan()
        assert not any("__pycache__" in f.path for f in files)

    def test_scan_parent_symbol(self, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        _, symbols, _ = scanner.scan()
        validate = [s for s in symbols if s.name == "validate"]
        assert len(validate) == 1
        assert validate[0].parent_symbol == "BaseModel"

    def test_scan_docstring(self, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        _, symbols, _ = scanner.scan()
        demo = [s for s in symbols if s.name == "demo"]
        assert len(demo) == 1
        assert demo[0].docstring == "Run demo."

    def test_scan_handles_syntax_error(self, sample_repo):
        bad = sample_repo / "src" / "axiom_core" / "broken.py"
        bad.write_text("def oops(:\n  pass")
        scanner = CodebaseInventory(sample_repo)
        files, symbols, _ = scanner.scan()
        assert any(f.path == "src/axiom_core/broken.py" for f in files)

    def test_scan_config_files(self, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        files, _, _ = scanner.scan()
        by_path = {f.path: f for f in files}
        assert "pyproject.toml" in by_path

    def test_scan_artifact_files(self, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        files, _, _ = scanner.scan()
        artifact_files = [f for f in files if f.category == FileCategory.ARTIFACT]
        assert len(artifact_files) >= 1


# ---------------------------------------------------------------------------
# CodeSymbolRegistry persistence
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_refresh_and_surface(self, registry, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        files, symbols, refs = scanner.scan()
        surface = registry.refresh(files, symbols, refs)
        assert surface.total_files == len(files)
        assert surface.total_symbols == len(symbols)
        assert surface.test_coverage_refs == len(refs)

    def test_list_files(self, registry, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        files, symbols, refs = scanner.scan()
        registry.refresh(files, symbols, refs)
        result = registry.list_files()
        assert len(result) == len(files)

    def test_list_files_by_category(self, registry, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        files, symbols, refs = scanner.scan()
        registry.refresh(files, symbols, refs)
        source_files = registry.list_files(category=FileCategory.SOURCE)
        assert all(f.category == FileCategory.SOURCE for f in source_files)

    def test_list_symbols(self, registry, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        files, symbols, refs = scanner.scan()
        registry.refresh(files, symbols, refs)
        result = registry.list_symbols()
        assert len(result) == len(symbols)

    def test_list_symbols_by_kind(self, registry, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        files, symbols, refs = scanner.scan()
        registry.refresh(files, symbols, refs)
        classes = registry.list_symbols(kind=SymbolKind.CLASS)
        assert all(s.kind == SymbolKind.CLASS for s in classes)

    def test_get_symbol_by_name(self, registry, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        files, symbols, refs = scanner.scan()
        registry.refresh(files, symbols, refs)
        matches = registry.get_symbol("BaseModel")
        assert len(matches) >= 1
        assert matches[0].name == "BaseModel"

    def test_get_symbol_by_qualified_name(self, registry, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        files, symbols, refs = scanner.scan()
        registry.refresh(files, symbols, refs)
        matches = registry.get_symbol("axiom_core.models.BaseModel")
        assert len(matches) == 1

    def test_get_symbol_not_found(self, registry, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        files, symbols, refs = scanner.scan()
        registry.refresh(files, symbols, refs)
        matches = registry.get_symbol("NonExistent")
        assert matches == []

    def test_test_coverage_refs(self, registry, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        files, symbols, refs = scanner.scan()
        registry.refresh(files, symbols, refs)
        result = registry.list_test_coverage()
        assert len(result) == len(refs)

    def test_refresh_clears_old_data(self, registry, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        files, symbols, refs = scanner.scan()
        registry.refresh(files, symbols, refs)
        assert registry.get_surface().total_files > 0

        registry.refresh([], [], [])
        assert registry.get_surface().total_files == 0

    def test_surface_empty(self, registry):
        surface = registry.get_surface()
        assert surface.total_files == 0
        assert surface.total_symbols == 0

    def test_symbols_persist(self, registry, sample_repo):
        scanner = CodebaseInventory(sample_repo)
        files, symbols, refs = scanner.scan()
        registry.refresh(files, symbols, refs)
        reg2 = CodeSymbolRegistry(db_path=registry._session_factory.kw["bind"].url.database)
        matches = reg2.get_symbol("BaseModel")
        assert len(matches) >= 1


# ---------------------------------------------------------------------------
# Data model serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_file_record_to_dict(self):
        rec = CodeFileRecord(path="src/foo.py", category=FileCategory.SOURCE)
        d = rec.to_dict()
        assert d["path"] == "src/foo.py"
        assert d["category"] == "source"
        json.dumps(d, default=str)

    def test_symbol_to_dict(self):
        sym = CodeSymbol(
            name="Foo",
            qualified_name="mod.Foo",
            kind=SymbolKind.CLASS,
            file_path="src/mod.py",
        )
        d = sym.to_dict()
        assert d["name"] == "Foo"
        assert d["kind"] == "class"
        json.dumps(d, default=str)

    def test_surface_to_dict(self):
        s = CodeSurface(total_files=10, total_symbols=50)
        d = s.to_dict()
        assert d["total_files"] == 10
        json.dumps(d, default=str)

    def test_coverage_ref_to_dict(self):
        ref = TestCoverageReference(test_file="tests/test_x.py", target_module="x")
        d = ref.to_dict()
        assert d["test_file"] == "tests/test_x.py"
        json.dumps(d, default=str)

    def test_file_record_json_roundtrip(self):
        rec = CodeFileRecord(
            path="src/bar.py",
            category=FileCategory.TEST,
            module_name="bar",
            line_count=42,
        )
        payload = json.dumps(rec.to_dict(), default=str)
        parsed = json.loads(payload)
        assert parsed["path"] == "src/bar.py"
        assert parsed["line_count"] == 42
