"""Tests for KnowledgeSourceRegistry — PR #36 acceptance criteria."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from axiom_core.knowledge_registry import (
    KnowledgeSourceMetadata,
    KnowledgeSourceRegistry,
    KnowledgeSourceStatus,
    KnowledgeSourceType,
)


@pytest.fixture()
def registry(tmp_path: Path) -> KnowledgeSourceRegistry:
    """Isolated registry using a temp SQLite database."""
    db_path = str(tmp_path / "test_knowledge.db")
    return KnowledgeSourceRegistry(db_path=db_path)


def _make_source(
    source_id: str = "ks_001",
    source_name: str = "Local Audit Spine Doc",
    source_type: KnowledgeSourceType = KnowledgeSourceType.ARCHITECTURE_DOC,
    path: str | None = "docs/architecture/local-audit-and-run-spine.md",
    enabled: bool = True,
    trust_level: str = "high",
) -> KnowledgeSourceMetadata:
    return KnowledgeSourceMetadata(
        source_id=source_id,
        source_name=source_name,
        source_type=source_type,
        path=path,
        enabled=enabled,
        trust_level=trust_level,
    )


# ===========================================================================
# Test 1: Sources can be registered
# ===========================================================================


class TestSourceRegistration:
    def test_register_new_source(self, registry: KnowledgeSourceRegistry) -> None:
        source = _make_source()
        result = registry.register(source)
        assert result.source_id == "ks_001"
        assert result.source_name == "Local Audit Spine Doc"

    def test_register_updates_existing(self, registry: KnowledgeSourceRegistry) -> None:
        source = _make_source()
        registry.register(source)
        updated = _make_source(source_name="Updated Name")
        registry.register(updated)
        fetched = registry.get("ks_001")
        assert fetched is not None
        assert fetched.source_name == "Updated Name"

    def test_register_multiple_types(self, registry: KnowledgeSourceRegistry) -> None:
        for i, st in enumerate(KnowledgeSourceType):
            registry.register(_make_source(source_id=f"ks_{i:03d}", source_type=st))
        assert registry.source_count() == len(KnowledgeSourceType)

    def test_source_has_timestamps(self, registry: KnowledgeSourceRegistry) -> None:
        source = _make_source()
        registry.register(source)
        fetched = registry.get("ks_001")
        assert fetched is not None
        assert fetched.created_at is not None
        assert fetched.updated_at is not None


# ===========================================================================
# Test 2: Sources can be listed
# ===========================================================================


class TestSourceListing:
    def test_list_empty_registry(self, registry: KnowledgeSourceRegistry) -> None:
        sources = registry.list_sources()
        assert sources == []

    def test_list_returns_registered_sources(self, registry: KnowledgeSourceRegistry) -> None:
        registry.register(_make_source(source_id="ks_001", source_name="Alpha"))
        registry.register(_make_source(source_id="ks_002", source_name="Beta"))
        sources = registry.list_sources()
        assert len(sources) == 2
        names = [s.source_name for s in sources]
        assert "Alpha" in names
        assert "Beta" in names

    def test_list_ordered_by_name(self, registry: KnowledgeSourceRegistry) -> None:
        registry.register(_make_source(source_id="ks_002", source_name="Zeta"))
        registry.register(_make_source(source_id="ks_001", source_name="Alpha"))
        sources = registry.list_sources()
        assert sources[0].source_name == "Alpha"
        assert sources[1].source_name == "Zeta"

    def test_list_filter_by_name(self, registry: KnowledgeSourceRegistry) -> None:
        registry.register(_make_source(source_id="ks_001", source_name="Grid Docs"))
        registry.register(_make_source(source_id="ks_002", source_name="Health Docs"))
        results = registry.list_sources(name_filter="Grid")
        assert len(results) == 1
        assert results[0].source_name == "Grid Docs"

    def test_list_filter_by_type(self, registry: KnowledgeSourceRegistry) -> None:
        registry.register(_make_source(source_id="ks_001", source_type=KnowledgeSourceType.RUNBOOK))
        registry.register(_make_source(source_id="ks_002", source_type=KnowledgeSourceType.SKILL))
        results = registry.list_sources(source_type=KnowledgeSourceType.RUNBOOK)
        assert len(results) == 1
        assert results[0].source_type == KnowledgeSourceType.RUNBOOK


# ===========================================================================
# Test 3: JSON output valid
# ===========================================================================


class TestJsonOutput:
    def test_json_output_is_valid(self, registry: KnowledgeSourceRegistry) -> None:
        registry.register(_make_source(source_id="ks_001"))
        registry.register(_make_source(source_id="ks_002", source_name="Another"))
        output = registry.to_json()
        parsed = json.loads(output)
        assert isinstance(parsed, list)
        assert len(parsed) == 2

    def test_json_contains_required_fields(self, registry: KnowledgeSourceRegistry) -> None:
        registry.register(_make_source())
        output = registry.to_json()
        parsed = json.loads(output)
        item = parsed[0]
        required = {"source_id", "source_name", "source_type", "path", "created_at", "updated_at", "enabled", "deprecated", "trust_level", "notes"}
        assert required.issubset(set(item.keys()))

    def test_json_source_type_is_string(self, registry: KnowledgeSourceRegistry) -> None:
        registry.register(_make_source())
        output = registry.to_json()
        parsed = json.loads(output)
        assert parsed[0]["source_type"] == "architecture_doc"

    def test_json_filter_by_name(self, registry: KnowledgeSourceRegistry) -> None:
        registry.register(_make_source(source_id="ks_001", source_name="Match Me"))
        registry.register(_make_source(source_id="ks_002", source_name="Skip"))
        output = registry.to_json(name_filter="Match")
        parsed = json.loads(output)
        assert len(parsed) == 1
        assert parsed[0]["source_name"] == "Match Me"


# ===========================================================================
# Test 4: Refresh deterministic
# ===========================================================================


class TestRefresh:
    def test_refresh_returns_same_result_twice(self, registry: KnowledgeSourceRegistry) -> None:
        registry.register(_make_source(source_id="ks_001"))
        registry.register(_make_source(source_id="ks_002", source_name="B"))
        first = registry.refresh()
        second = registry.refresh()
        assert len(first) == len(second)
        assert [s.source_id for s in first] == [s.source_id for s in second]

    def test_refresh_excludes_disabled(self, registry: KnowledgeSourceRegistry) -> None:
        registry.register(_make_source(source_id="ks_001"))
        registry.register(_make_source(source_id="ks_002", source_name="B"))
        registry.disable("ks_002")
        results = registry.refresh()
        assert len(results) == 1
        assert results[0].source_id == "ks_001"


# ===========================================================================
# Test 5: Disabled sources excluded
# ===========================================================================


class TestDisabledExclusion:
    def test_disabled_excluded_from_default_list(self, registry: KnowledgeSourceRegistry) -> None:
        registry.register(_make_source(source_id="ks_001"))
        registry.register(_make_source(source_id="ks_002", source_name="To Disable"))
        registry.disable("ks_002")
        sources = registry.list_sources()
        assert len(sources) == 1
        assert sources[0].source_id == "ks_001"

    def test_disabled_included_when_requested(self, registry: KnowledgeSourceRegistry) -> None:
        registry.register(_make_source(source_id="ks_001"))
        registry.register(_make_source(source_id="ks_002", source_name="Disabled"))
        registry.disable("ks_002")
        sources = registry.list_sources(include_disabled=True)
        assert len(sources) == 2

    def test_disable_returns_false_for_unknown(self, registry: KnowledgeSourceRegistry) -> None:
        assert registry.disable("nonexistent") is False

    def test_enable_restores_source(self, registry: KnowledgeSourceRegistry) -> None:
        registry.register(_make_source(source_id="ks_001"))
        registry.disable("ks_001")
        assert len(registry.list_sources()) == 0
        registry.enable("ks_001")
        assert len(registry.list_sources()) == 1

    def test_deprecated_status(self, registry: KnowledgeSourceRegistry) -> None:
        registry.register(_make_source(source_id="ks_001"))
        registry.deprecate("ks_001")
        fetched = registry.get("ks_001")
        assert fetched is not None
        assert fetched.status == KnowledgeSourceStatus.DEPRECATED


# ===========================================================================
# Test 6: Unknown source handled
# ===========================================================================


class TestUnknownSourceHandling:
    def test_get_unknown_returns_none(self, registry: KnowledgeSourceRegistry) -> None:
        assert registry.get("nonexistent_id") is None

    def test_enable_unknown_returns_false(self, registry: KnowledgeSourceRegistry) -> None:
        assert registry.enable("nonexistent_id") is False

    def test_deprecate_unknown_returns_false(self, registry: KnowledgeSourceRegistry) -> None:
        assert registry.deprecate("nonexistent_id") is False

    def test_unknown_source_type_preserved(self, registry: KnowledgeSourceRegistry) -> None:
        """If a source is stored with an unknown type string, it is still retrievable."""
        source = KnowledgeSourceMetadata(
            source_id="ks_weird",
            source_name="Weird Source",
            source_type="future_unknown_type",  # type: ignore[arg-type]
            trust_level="low",
        )
        registry.register(source)
        fetched = registry.get("ks_weird")
        assert fetched is not None
        assert fetched.source_type == "future_unknown_type"
