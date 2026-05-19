"""Tests for capability registry metadata."""

from axiom_core.capability_registry import (
    CapabilityMetadata,
    CapabilityRegistry,
    get_default_registry,
)


class TestCapabilityMetadata:
    def test_defaults(self):
        meta = CapabilityMetadata(name="Test", description="A test capability")
        assert meta.supports_simulate is True
        assert meta.requires_revit_document is True
        assert meta.status == "validated"
        assert meta.parameter_schema == {}


class TestCapabilityRegistry:
    def test_register_and_get(self):
        registry = CapabilityRegistry()
        meta = CapabilityMetadata(name="Foo", description="Foo capability")
        registry.register(meta)

        result = registry.get("Foo")
        assert result is not None
        assert result.name == "Foo"
        assert result.description == "Foo capability"

    def test_get_unknown_returns_none(self):
        registry = CapabilityRegistry()
        assert registry.get("DoesNotExist") is None

    def test_is_registered(self):
        registry = CapabilityRegistry()
        meta = CapabilityMetadata(name="Bar", description="Bar cap")
        registry.register(meta)

        assert registry.is_registered("Bar") is True
        assert registry.is_registered("Baz") is False

    def test_list_all(self):
        registry = CapabilityRegistry()
        registry.register(CapabilityMetadata(name="A", description="a"))
        registry.register(CapabilityMetadata(name="B", description="b"))

        all_caps = registry.list_all()
        assert len(all_caps) == 2
        names = {c.name for c in all_caps}
        assert names == {"A", "B"}

    def test_list_names(self):
        registry = CapabilityRegistry()
        registry.register(CapabilityMetadata(name="X", description="x"))
        registry.register(CapabilityMetadata(name="Y", description="y"))

        assert set(registry.list_names()) == {"X", "Y"}

    def test_register_overwrites(self):
        registry = CapabilityRegistry()
        registry.register(CapabilityMetadata(name="A", description="v1"))
        registry.register(CapabilityMetadata(name="A", description="v2"))

        assert registry.get("A").description == "v2"
        assert len(registry.list_all()) == 1


class TestDefaultRegistry:
    def test_create_grids_registered(self):
        registry = get_default_registry()
        meta = registry.get("CreateGrids")
        assert meta is not None
        assert meta.status == "validated"
        assert meta.supports_simulate is True
        assert meta.requires_revit_document is True
        assert "HorizontalCount" in meta.parameter_schema["properties"]
        assert "VerticalCount" in meta.parameter_schema["properties"]
        assert "SpacingFeet" in meta.parameter_schema["properties"]

    def test_create_levels_validated(self):
        registry = get_default_registry()
        meta = registry.get("CreateLevels")
        assert meta is not None
        assert meta.status == "validated"
        assert meta.supports_simulate is True
        assert meta.requires_revit_document is True
        assert "LevelCount" in meta.parameter_schema["properties"]

    def test_inventory_model_registered(self):
        registry = get_default_registry()
        meta = registry.get("InventoryModel")
        assert meta is not None
        assert meta.status == "validated"
        assert meta.supports_simulate is True

    def test_default_registry_names(self):
        registry = get_default_registry()
        names = set(registry.list_names())
        assert "CreateGrids" in names
        assert "CreateLevels" in names
        assert "InventoryModel" in names
