"""Tests for input normalization."""


from axiom_core.input_normalization import InputNormalizer


def test_normalize_dict_success():
    """Test normalizing a dictionary input."""
    normalizer = InputNormalizer()

    data = {
        "Project Number": "2024-001",
        "Project Name": "Test Project",
        "Project Revit Version": 2023,
        "Is this an ACC project?": "No",
        "Indicate what views will be needed": "E - General;M - HVAC",
    }

    report = normalizer.normalize_dict(data, "test_firm")

    assert report.success is True
    assert report.normalized_job is not None
    assert report.normalized_job.project_number == "2024-001"
    assert report.normalized_job.project_name == "Test Project"
    assert report.normalized_job.revit_version == 2023
    assert report.normalized_job.is_acc_project is False
    assert len(report.normalized_job.views_required) == 2


def test_normalize_dict_missing_required():
    """Test normalization fails with missing required fields."""
    normalizer = InputNormalizer()

    data = {
        "Project Name": "Test Project",
    }

    report = normalizer.normalize_dict(data, "test_firm")

    assert report.success is False
    assert len(report.errors) > 0


def test_normalize_dict_with_scope_boxes():
    """Test parsing scope boxes from description."""
    normalizer = InputNormalizer()

    data = {
        "Project Number": "2024-001",
        "Project Name": "Test Project",
        "Project Revit Version": 2023,
        "Indicate what views will be needed": "E - General",
        "Will the footprint of the project be divided by areas": "Yes, 3 scope boxes for: Building A, Building B, Building C",
    }

    report = normalizer.normalize_dict(data, "test_firm")

    assert report.success is True
    assert report.normalized_job is not None
    assert len(report.normalized_job.scope_boxes) == 3


def test_parse_boolean_variations():
    """Test parsing boolean from various formats."""
    normalizer = InputNormalizer()

    data_yes = {
        "Project Number": "2024-001",
        "Project Name": "Test",
        "Project Revit Version": 2023,
        "Indicate what views will be needed": "E - General",
        "Is this an ACC project?": "Yes",
    }

    report = normalizer.normalize_dict(data_yes, "test_firm")
    assert report.normalized_job is not None
    assert report.normalized_job.is_acc_project is True

    data_no = {
        "Project Number": "2024-002",
        "Project Name": "Test",
        "Project Revit Version": 2023,
        "Indicate what views will be needed": "E - General",
        "Is this an ACC project?": "No",
    }

    report = normalizer.normalize_dict(data_no, "test_firm")
    assert report.normalized_job is not None
    assert report.normalized_job.is_acc_project is False
