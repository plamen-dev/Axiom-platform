"""Tests for SetParameterValue v0 — constrained text parameter edit."""

import json

from axiom_core.set_parameter_value import (
    MAX_ELEMENT_COUNT,
    RegistryMatch,
    SetParameterRequest,
    load_registry_jsonl,
    parse_set_parameter_prompt,
    run_set_parameter_preview,
    validate_against_registry,
    validate_safety,
    write_evidence,
)

# ---------------------------------------------------------------------------
# Shared test registry data
# ---------------------------------------------------------------------------

def _make_registry() -> list[dict]:
    """Build a minimal registry for testing."""
    return [
        {
            "ObjectCategory": "Walls",
            "ParameterName": "Comments",
            "DataTypeLabel": "Text",
            "StorageType": "String",
            "IsReadOnly": False,
            "IsInstanceParam": True,
            "IsTypeParam": False,
            "ObservedCount": 42,
        },
        {
            "ObjectCategory": "Walls",
            "ParameterName": "Mark",
            "DataTypeLabel": "Text",
            "StorageType": "String",
            "IsReadOnly": False,
            "IsInstanceParam": True,
            "IsTypeParam": False,
            "ObservedCount": 38,
        },
        {
            "ObjectCategory": "Walls",
            "ParameterName": "Length",
            "DataTypeLabel": "Length",
            "StorageType": "Double",
            "IsReadOnly": True,
            "IsInstanceParam": True,
            "IsTypeParam": False,
            "ObservedCount": 50,
        },
        {
            "ObjectCategory": "Walls",
            "ParameterName": "Type Name",
            "DataTypeLabel": "Text",
            "StorageType": "String",
            "IsReadOnly": True,
            "IsInstanceParam": False,
            "IsTypeParam": True,
            "ObservedCount": 50,
        },
        {
            "ObjectCategory": "Doors",
            "ParameterName": "Comments",
            "DataTypeLabel": "Text",
            "StorageType": "String",
            "IsReadOnly": False,
            "IsInstanceParam": True,
            "IsTypeParam": False,
            "ObservedCount": 20,
        },
        {
            "ObjectCategory": "Doors",
            "ParameterName": "Mark",
            "DataTypeLabel": "Text",
            "StorageType": "String",
            "IsReadOnly": False,
            "IsInstanceParam": True,
            "IsTypeParam": False,
            "ObservedCount": 18,
        },
        {
            "ObjectCategory": "Mechanical Equipment",
            "ParameterName": "Comments",
            "DataTypeLabel": "Text",
            "StorageType": "String",
            "IsReadOnly": False,
            "IsInstanceParam": True,
            "IsTypeParam": False,
            "ObservedCount": 15,
        },
    ]


# =========================================================================
# Prompt parser tests
# =========================================================================


class TestPromptParser:
    """Parse example prompts into structured requests."""

    def test_preview_set_comments_walls(self):
        req = parse_set_parameter_prompt(
            'Set Comments to "Axiom test 001" for 3 Walls'
        )
        assert req.mode == "preview"
        assert req.parameter_name == "Comments"
        assert req.value == "Axiom test 001"
        assert req.element_count == 3
        assert req.category == "Walls"
        assert not req.parse_errors

    def test_preview_set_mark_doors(self):
        req = parse_set_parameter_prompt(
            'Set Mark to "AX-TEST" for 2 Doors'
        )
        assert req.mode == "preview"
        assert req.parameter_name == "Mark"
        assert req.value == "AX-TEST"
        assert req.element_count == 2
        assert req.category == "Doors"

    def test_preview_mechanical_equipment(self):
        req = parse_set_parameter_prompt(
            'Set Comments to "Checked by Axiom" for 5 Mechanical Equipment'
        )
        assert req.mode == "preview"
        assert req.parameter_name == "Comments"
        assert req.value == "Checked by Axiom"
        assert req.element_count == 5
        assert req.category == "Mechanical Equipment"

    def test_apply_set_comments_walls(self):
        req = parse_set_parameter_prompt(
            'Apply Set Comments to "Axiom test 001" for 3 Walls'
        )
        assert req.mode == "apply"
        assert req.parameter_name == "Comments"
        assert req.value == "Axiom test 001"
        assert req.element_count == 3
        assert req.category == "Walls"

    def test_apply_set_mark_doors(self):
        req = parse_set_parameter_prompt(
            'Apply Set Mark to "AX-TEST" for 2 Doors'
        )
        assert req.mode == "apply"
        assert req.parameter_name == "Mark"
        assert req.value == "AX-TEST"
        assert req.element_count == 2
        assert req.category == "Doors"

    def test_word_number_three(self):
        req = parse_set_parameter_prompt(
            'Set Comments to "test" for three Walls'
        )
        assert req.element_count == 3
        assert not req.parse_errors

    def test_word_number_five(self):
        req = parse_set_parameter_prompt(
            'Set Comments to "test" for five Doors'
        )
        assert req.element_count == 5

    def test_case_insensitive_apply(self):
        req = parse_set_parameter_prompt(
            'APPLY Set Comments to "test" for 2 Walls'
        )
        assert req.mode == "apply"
        assert req.parameter_name == "Comments"

    def test_case_insensitive_set(self):
        req = parse_set_parameter_prompt(
            'set comments to "test" for 2 walls'
        )
        assert req.parameter_name == "comments"
        assert req.category == "walls"

    def test_empty_prompt(self):
        req = parse_set_parameter_prompt("")
        assert req.parse_errors
        assert "Empty prompt" in req.parse_errors[0]

    def test_malformed_prompt(self):
        req = parse_set_parameter_prompt("do something random")
        assert req.parse_errors
        assert "must follow" in req.parse_errors[0]

    def test_unquoted_value_single_word(self):
        req = parse_set_parameter_prompt(
            "Set Mark to AX-TEST for 2 Doors"
        )
        assert not req.parse_errors
        assert req.parameter_name == "Mark"
        assert req.value == "AX-TEST"
        assert req.element_count == 2
        assert req.category == "Doors"

    def test_unquoted_value_multi_word(self):
        req = parse_set_parameter_prompt(
            "Set Comments to Axiom test 001 for 3 Walls"
        )
        assert not req.parse_errors
        assert req.parameter_name == "Comments"
        assert req.value == "Axiom test 001"
        assert req.element_count == 3
        assert req.category == "Walls"

    def test_unquoted_apply_mark(self):
        req = parse_set_parameter_prompt(
            "Apply Set Mark to AX-TEST for 2 Doors"
        )
        assert not req.parse_errors
        assert req.mode == "apply"
        assert req.parameter_name == "Mark"
        assert req.value == "AX-TEST"
        assert req.element_count == 2
        assert req.category == "Doors"

    def test_unquoted_apply_comments(self):
        req = parse_set_parameter_prompt(
            "Apply Set Comments to Axiom test 001 for 3 Walls"
        )
        assert not req.parse_errors
        assert req.mode == "apply"
        assert req.parameter_name == "Comments"
        assert req.value == "Axiom test 001"

    def test_unquoted_mechanical_equipment(self):
        req = parse_set_parameter_prompt(
            "Set Comments to Checked by Axiom for 5 Mechanical Equipment"
        )
        assert not req.parse_errors
        assert req.parameter_name == "Comments"
        assert req.value == "Checked by Axiom"
        assert req.element_count == 5
        assert req.category == "Mechanical Equipment"

    def test_raw_prompt_preserved(self):
        prompt = 'Set Comments to "test" for 2 Walls'
        req = parse_set_parameter_prompt(prompt)
        assert req.raw_prompt == prompt

    def test_value_containing_for_keyword(self):
        """Regression: value with 'for' should not confuse the parser."""
        req = parse_set_parameter_prompt(
            'Set Comments to "value for 5 things" for 3 Walls'
        )
        assert not req.parse_errors
        assert req.parameter_name == "Comments"
        assert req.value == "value for 5 things"
        assert req.element_count == 3
        assert req.category == "Walls"

    def test_unquoted_value_containing_for(self):
        """Unquoted value with 'for' matches the last 'for <N> <Cat>'."""
        req = parse_set_parameter_prompt(
            "Set Comments to value for testing for 3 Walls"
        )
        assert not req.parse_errors
        assert req.parameter_name == "Comments"
        assert req.value == "value for testing"
        assert req.element_count == 3
        assert req.category == "Walls"

    def test_unparseable_count(self):
        req = parse_set_parameter_prompt(
            'Set Comments to "test" for many Walls'
        )
        assert req.parse_errors
        assert "Cannot parse element count" in req.parse_errors[0]


# =========================================================================
# Registry validation tests
# =========================================================================


class TestRegistryValidation:
    """Validate requests against parameter registry data."""

    def test_valid_comments_on_walls(self):
        req = parse_set_parameter_prompt(
            'Set Comments to "test" for 3 Walls'
        )
        match = validate_against_registry(req, _make_registry())
        assert match.found
        assert match.category == "Walls"
        assert match.parameter_name == "Comments"
        assert match.data_type_label == "Text"
        assert not match.is_read_only
        assert match.is_instance_param

    def test_valid_mark_on_doors(self):
        req = parse_set_parameter_prompt(
            'Set Mark to "AX-TEST" for 2 Doors'
        )
        match = validate_against_registry(req, _make_registry())
        assert match.found
        assert match.category == "Doors"
        assert match.parameter_name == "Mark"

    def test_category_not_found(self):
        req = parse_set_parameter_prompt(
            'Set Comments to "test" for 3 Windows'
        )
        match = validate_against_registry(req, _make_registry())
        assert not match.found
        assert any("not found" in e for e in match.errors)

    def test_parameter_not_found_for_category(self):
        req = parse_set_parameter_prompt(
            'Set NonExistent to "test" for 3 Walls'
        )
        match = validate_against_registry(req, _make_registry())
        assert not match.found
        assert any("not found" in e for e in match.errors)

    def test_empty_registry(self):
        req = parse_set_parameter_prompt(
            'Set Comments to "test" for 3 Walls'
        )
        match = validate_against_registry(req, [])
        assert not match.found
        assert any("empty" in e.lower() for e in match.errors)

    def test_mechanical_equipment_multi_word_category(self):
        req = parse_set_parameter_prompt(
            'Set Comments to "test" for 3 Mechanical Equipment'
        )
        match = validate_against_registry(req, _make_registry())
        assert match.found
        assert match.category == "Mechanical Equipment"

    def test_read_only_parameter_detected(self):
        req = parse_set_parameter_prompt(
            'Set Length to "test" for 3 Walls'
        )
        match = validate_against_registry(req, _make_registry())
        assert match.found
        assert match.is_read_only

    def test_type_parameter_detected(self):
        req = parse_set_parameter_prompt(
            'Set Type Name to "test" for 3 Walls'
        )
        match = validate_against_registry(req, _make_registry())
        assert match.found
        assert match.is_type_param
        assert not match.is_instance_param


# =========================================================================
# Safety validation tests
# =========================================================================


class TestSafetyValidation:
    """Safety constraints reject unsafe operations."""

    def test_reject_missing_count(self):
        req = SetParameterRequest(element_count=0)
        match = RegistryMatch(found=True, data_type_label="Text",
                              is_instance_param=True)
        rejections = validate_safety(req, match)
        assert any("missing or zero" in r for r in rejections)

    def test_reject_count_above_cap(self):
        req = SetParameterRequest(element_count=10)
        match = RegistryMatch(found=True, data_type_label="Text",
                              is_instance_param=True)
        rejections = validate_safety(req, match)
        assert any("exceeds hard cap" in r for r in rejections)

    def test_reject_count_exactly_at_cap(self):
        req = SetParameterRequest(element_count=MAX_ELEMENT_COUNT)
        match = RegistryMatch(found=True, data_type_label="Text",
                              is_instance_param=True)
        rejections = validate_safety(req, match)
        assert not any("exceeds hard cap" in r for r in rejections)

    def test_reject_read_only(self):
        req = SetParameterRequest(element_count=3)
        match = RegistryMatch(
            found=True, parameter_name="Length",
            data_type_label="Text", is_read_only=True,
            is_instance_param=True,
        )
        rejections = validate_safety(req, match)
        assert any("read-only" in r for r in rejections)

    def test_reject_type_parameter(self):
        req = SetParameterRequest(element_count=3)
        match = RegistryMatch(
            found=True, parameter_name="Type Name",
            data_type_label="Text", is_instance_param=False,
            is_type_param=True,
        )
        rejections = validate_safety(req, match)
        assert any("not an instance" in r for r in rejections)

    def test_reject_non_text_parameter(self):
        req = SetParameterRequest(element_count=3)
        match = RegistryMatch(
            found=True, parameter_name="Length",
            data_type_label="Length", is_instance_param=True,
        )
        rejections = validate_safety(req, match)
        assert any("only Text" in r for r in rejections)

    def test_reject_ambiguous_categories(self):
        req = SetParameterRequest(element_count=3)
        match = RegistryMatch(
            found=False,
            ambiguous_categories=["Wall", "Walls"],
            errors=["Ambiguous category match: ['Wall', 'Walls']"],
        )
        rejections = validate_safety(req, match)
        assert any("Ambiguous category" in r for r in rejections)

    def test_reject_ambiguous_parameters(self):
        req = SetParameterRequest(element_count=3)
        match = RegistryMatch(
            found=False,
            ambiguous_parameters=["Mark", "MARK"],
            errors=["Ambiguous parameter match: ['Mark', 'MARK']"],
        )
        rejections = validate_safety(req, match)
        assert any("Ambiguous parameter" in r for r in rejections)

    def test_accept_valid_request(self):
        req = SetParameterRequest(element_count=3)
        match = RegistryMatch(
            found=True, parameter_name="Comments",
            data_type_label="Text", is_instance_param=True,
        )
        rejections = validate_safety(req, match)
        assert not rejections


# =========================================================================
# Preview / Apply tests
# =========================================================================


class TestPreviewApply:
    """Preview does not modify; apply requires explicit keyword."""

    def test_preview_does_not_modify(self):
        req = parse_set_parameter_prompt(
            'Set Comments to "test" for 3 Walls'
        )
        match = validate_against_registry(req, _make_registry())
        result = run_set_parameter_preview(req, match)
        assert result.status == "success"
        assert result.mode == "preview"
        assert not result.model_modified
        assert len(result.elements) == 3
        for e in result.elements:
            assert e.status == "preview"

    def test_apply_requires_keyword(self):
        req = parse_set_parameter_prompt(
            'Set Comments to "test" for 3 Walls'
        )
        assert req.mode == "preview"
        # Without "Apply", mode is preview
        match = validate_against_registry(req, _make_registry())
        result = run_set_parameter_preview(req, match)
        assert not result.model_modified

    def test_apply_marks_model_modified(self):
        req = parse_set_parameter_prompt(
            'Apply Set Comments to "test" for 3 Walls'
        )
        assert req.mode == "apply"
        match = validate_against_registry(req, _make_registry())
        result = run_set_parameter_preview(req, match)
        assert result.status == "success"
        assert result.mode == "apply"
        assert result.model_modified
        for e in result.elements:
            assert e.status == "success"

    def test_rejected_request_not_applied(self):
        req = parse_set_parameter_prompt(
            'Apply Set Comments to "test" for 10 Walls'
        )
        match = validate_against_registry(req, _make_registry())
        result = run_set_parameter_preview(req, match)
        assert result.status == "rejected"
        assert not result.model_modified
        assert "exceeds hard cap" in result.rejection_reason

    def test_preview_with_simulated_elements(self):
        req = parse_set_parameter_prompt(
            'Set Comments to "Axiom" for 2 Walls'
        )
        match = validate_against_registry(req, _make_registry())
        simulated = [
            {"element_id": 5001, "category": "Walls", "current_value": "old1"},
            {"element_id": 5002, "category": "Walls", "current_value": "old2"},
            {"element_id": 5003, "category": "Walls", "current_value": "old3"},
        ]
        result = run_set_parameter_preview(req, match, simulated_elements=simulated)
        assert len(result.elements) == 2  # limited to element_count
        assert result.elements[0].old_value == "old1"
        assert result.elements[0].new_value == "Axiom"
        assert result.elements[1].old_value == "old2"

    def test_element_count_respected(self):
        req = parse_set_parameter_prompt(
            'Set Comments to "test" for 5 Walls'
        )
        match = validate_against_registry(req, _make_registry())
        result = run_set_parameter_preview(req, match)
        assert len(result.elements) == 5

    def test_max_cap_element_count(self):
        req = parse_set_parameter_prompt(
            'Set Comments to "test" for 5 Walls'
        )
        match = validate_against_registry(req, _make_registry())
        result = run_set_parameter_preview(req, match)
        assert result.status == "success"
        assert len(result.elements) == MAX_ELEMENT_COUNT


# =========================================================================
# Evidence export tests
# =========================================================================


class TestEvidenceExport:
    """Evidence artifacts are created for every run."""

    def test_preview_creates_request_and_preview_json(self, tmp_path):
        req = parse_set_parameter_prompt(
            'Set Comments to "test" for 3 Walls'
        )
        match = validate_against_registry(req, _make_registry())
        result = run_set_parameter_preview(req, match)
        artifact_dir = write_evidence(req, match, result,
                                      artifact_base=str(tmp_path))

        assert (artifact_dir / "request.json").exists()
        assert (artifact_dir / "preview.json").exists()
        assert (artifact_dir / "result_summary.md").exists()
        # No changes.json for preview mode
        assert not (artifact_dir / "changes.json").exists()

    def test_apply_creates_changes_json(self, tmp_path):
        req = parse_set_parameter_prompt(
            'Apply Set Comments to "test" for 3 Walls'
        )
        match = validate_against_registry(req, _make_registry())
        result = run_set_parameter_preview(req, match)
        artifact_dir = write_evidence(req, match, result,
                                      artifact_base=str(tmp_path))

        assert (artifact_dir / "changes.json").exists()
        changes = json.loads((artifact_dir / "changes.json").read_text())
        assert changes["mode"] == "apply"
        assert changes["model_modified"] is True
        assert len(changes["changes"]) == 3

    def test_rejected_creates_evidence(self, tmp_path):
        req = parse_set_parameter_prompt(
            'Set Comments to "test" for 10 Walls'
        )
        match = validate_against_registry(req, _make_registry())
        result = run_set_parameter_preview(req, match)
        artifact_dir = write_evidence(req, match, result,
                                      artifact_base=str(tmp_path))

        assert (artifact_dir / "request.json").exists()
        assert (artifact_dir / "preview.json").exists()
        assert (artifact_dir / "result_summary.md").exists()

        preview = json.loads((artifact_dir / "preview.json").read_text())
        assert preview["status"] == "rejected"

    def test_result_summary_includes_prompt(self, tmp_path):
        req = parse_set_parameter_prompt(
            'Set Comments to "Axiom test" for 3 Walls'
        )
        match = validate_against_registry(req, _make_registry())
        result = run_set_parameter_preview(req, match)
        artifact_dir = write_evidence(req, match, result,
                                      artifact_base=str(tmp_path))

        summary = (artifact_dir / "result_summary.md").read_text()
        assert "Axiom test" in summary
        assert "Comments" in summary
        assert "Walls" in summary
        assert "preview" in summary.lower()

    def test_result_summary_includes_element_table(self, tmp_path):
        req = parse_set_parameter_prompt(
            'Set Comments to "test" for 2 Walls'
        )
        match = validate_against_registry(req, _make_registry())
        result = run_set_parameter_preview(req, match)
        artifact_dir = write_evidence(req, match, result,
                                      artifact_base=str(tmp_path))

        summary = (artifact_dir / "result_summary.md").read_text()
        assert "Element ID" in summary
        assert "Old Value" in summary
        assert "New Value" in summary

    def test_request_json_content(self, tmp_path):
        req = parse_set_parameter_prompt(
            'Set Mark to "AX-001" for 2 Doors'
        )
        match = validate_against_registry(req, _make_registry())
        result = run_set_parameter_preview(req, match)
        artifact_dir = write_evidence(req, match, result,
                                      artifact_base=str(tmp_path))

        request_data = json.loads(
            (artifact_dir / "request.json").read_text()
        )
        assert request_data["parameter_name"] == "Mark"
        assert request_data["value"] == "AX-001"
        assert request_data["category"] == "Doors"
        assert request_data["element_count"] == 2
        assert request_data["mode"] == "preview"


# =========================================================================
# Registry JSONL loader tests
# =========================================================================


class TestRegistryLoader:
    """Load registry from JSONL files."""

    def test_load_valid_jsonl(self, tmp_path):
        jsonl_path = tmp_path / "registry.jsonl"
        lines = [
            json.dumps({"ObjectCategory": "Walls", "ParameterName": "Comments"}),
            json.dumps({"ObjectCategory": "Doors", "ParameterName": "Mark"}),
        ]
        jsonl_path.write_text("\n".join(lines), encoding="utf-8")

        entries = load_registry_jsonl(str(jsonl_path))
        assert len(entries) == 2

    def test_load_missing_file(self):
        entries = load_registry_jsonl("/nonexistent/path.jsonl")
        assert entries == []

    def test_load_bom_encoded_jsonl(self, tmp_path):
        jsonl_path = tmp_path / "registry.jsonl"
        content = json.dumps({"ObjectCategory": "Walls", "ParameterName": "X"})
        jsonl_path.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))

        entries = load_registry_jsonl(str(jsonl_path))
        assert len(entries) == 1
        assert entries[0]["ObjectCategory"] == "Walls"


# =========================================================================
# No external network dependency
# =========================================================================


class TestNoNetworkDependency:
    """Verify no external network calls are needed."""

    def test_full_workflow_offline(self, tmp_path):
        """Complete preview workflow with no network calls."""
        # Create a local registry
        jsonl_path = tmp_path / "registry.jsonl"
        registry = _make_registry()
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for entry in registry:
                f.write(json.dumps(entry) + "\n")

        # Load registry
        entries = load_registry_jsonl(str(jsonl_path))
        assert len(entries) == len(registry)

        # Parse prompt
        req = parse_set_parameter_prompt(
            'Set Comments to "offline test" for 3 Walls'
        )
        assert not req.parse_errors

        # Validate
        match = validate_against_registry(req, entries)
        assert match.found

        # Execute preview
        result = run_set_parameter_preview(req, match)
        assert result.status == "success"
        assert not result.model_modified

        # Write evidence
        artifact_dir = write_evidence(
            req, match, result,
            artifact_base=str(tmp_path / "artifacts")
        )
        assert (artifact_dir / "request.json").exists()
        assert (artifact_dir / "preview.json").exists()
        assert (artifact_dir / "result_summary.md").exists()
