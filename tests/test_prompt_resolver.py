"""Tests for the prompt resolver — grid use case only."""


from axiom_core.prompt_resolver import resolve_prompt


class TestPromptResolver:
    def test_basic_grid_prompt(self):
        result = resolve_prompt("Create 10 vertical gridlines, 50' long, spaced 10' apart")
        assert result is not None
        assert result.capability_name == "CreateGrids"
        # "vertical" → HorizontalCount (creates vertical lines in C#)
        assert result.params["HorizontalCount"] == 10
        assert result.params["VerticalCount"] == 0
        assert result.params["Length"] == 50.0
        assert result.params["SpacingFeet"] == 10.0

    def test_horizontal_grids(self):
        result = resolve_prompt("Create 5 horizontal grids spaced 30 ft apart")
        assert result is not None
        # "horizontal" → VerticalCount (creates horizontal lines in C#)
        assert result.params["HorizontalCount"] == 0
        assert result.params["VerticalCount"] == 5
        assert result.params["SpacingFeet"] == 30.0

    def test_both_orientations(self):
        result = resolve_prompt("Create 8 horizontal and 6 vertical grids spaced 25' apart")
        assert result is not None
        # "8 horizontal" → VerticalCount=8, "6 vertical" → HorizontalCount=6
        assert result.params["HorizontalCount"] == 6
        assert result.params["VerticalCount"] == 8
        assert result.params["SpacingFeet"] == 25.0

    def test_defaults_filled(self):
        result = resolve_prompt("Create 3 vertical grids")
        assert result is not None
        # "vertical" → HorizontalCount
        assert result.params["HorizontalCount"] == 3
        assert result.params["VerticalCount"] == 0
        assert result.params["SpacingFeet"] == 30.0  # default
        assert len(result.assumptions) > 0

    def test_unresolvable_prompt(self):
        result = resolve_prompt("What is the meaning of life?")
        assert result is None

    def test_generic_grid_count(self):
        result = resolve_prompt("Create 10 grids")
        assert result is not None
        assert result.params["HorizontalCount"] == 10
        assert result.params["VerticalCount"] == 10

    def test_spacing_with_feet_keyword(self):
        result = resolve_prompt("Create 5 vertical gridlines with spacing of 15 feet")
        assert result is not None
        assert result.params["SpacingFeet"] == 15.0

    def test_length_extraction(self):
        result = resolve_prompt("Create 4 vertical grids 100 ft long")
        assert result is not None
        assert result.params["Length"] == 100.0

    def test_assumptions_tracked(self):
        result = resolve_prompt("Create 5 vertical grids")
        assert result is not None
        assert any("SpacingFeet" in a for a in result.assumptions)
        assert any("Length" in a for a in result.assumptions)


class TestVariableSpacing:
    """Tests for variable per-bay spacing support."""

    def test_comma_separated_vertical(self):
        result = resolve_prompt(
            "Create vertical grids with spacings 10, 5, 20, 10"
        )
        assert result is not None
        assert result.params["HorizontalSpacingsFeet"] == [10.0, 5.0, 20.0, 10.0]
        assert result.params["HorizontalCount"] == 5  # 4 spacings + 1
        assert result.params["VerticalCount"] == 0

    def test_comma_separated_horizontal(self):
        result = resolve_prompt(
            "Create horizontal grids with spacings 15, 12, 18"
        )
        assert result is not None
        assert result.params["VerticalSpacingsFeet"] == [15.0, 12.0, 18.0]
        assert result.params["VerticalCount"] == 4  # 3 spacings + 1
        assert result.params["HorizontalCount"] == 0

    def test_table_format_vertical_only(self):
        prompt = (
            "Create grids:\n"
            "Vertical:\n"
            "1-2 = 10'\n"
            "2-3 = 5'\n"
            "3-4 = 20'\n"
            "4-5 = 10'"
        )
        result = resolve_prompt(prompt)
        assert result is not None
        assert result.params["HorizontalSpacingsFeet"] == [10.0, 5.0, 20.0, 10.0]
        assert result.params["HorizontalCount"] == 5
        assert result.params["VerticalCount"] == 0

    def test_table_format_horizontal_only(self):
        prompt = (
            "Create grids:\n"
            "Horizontal:\n"
            "A-B = 15'\n"
            "B-C = 12'"
        )
        result = resolve_prompt(prompt)
        assert result is not None
        assert result.params["VerticalSpacingsFeet"] == [15.0, 12.0]
        assert result.params["VerticalCount"] == 3
        assert result.params["HorizontalCount"] == 0

    def test_table_format_both_orientations(self):
        prompt = (
            "Create grids:\n"
            "Vertical:\n"
            "1-2 = 10'\n"
            "2-3 = 5'\n"
            "3-4 = 20'\n"
            "Horizontal:\n"
            "A-B = 15'\n"
            "B-C = 12'"
        )
        result = resolve_prompt(prompt)
        assert result is not None
        assert result.params["HorizontalSpacingsFeet"] == [10.0, 5.0, 20.0]
        assert result.params["HorizontalCount"] == 4
        assert result.params["VerticalSpacingsFeet"] == [15.0, 12.0]
        assert result.params["VerticalCount"] == 3

    def test_table_format_with_feet_suffix(self):
        prompt = (
            "Create grids:\n"
            "Vertical:\n"
            "1-2 = 10 ft\n"
            "2-3 = 5 feet\n"
            "3-4 = 20'"
        )
        result = resolve_prompt(prompt)
        assert result is not None
        assert result.params["HorizontalSpacingsFeet"] == [10.0, 5.0, 20.0]

    def test_uniform_spacing_still_works(self):
        result = resolve_prompt(
            "Create 10 vertical gridlines, 50' long, spaced 10' apart"
        )
        assert result is not None
        assert result.params["SpacingFeet"] == 10.0
        assert "HorizontalSpacingsFeet" not in result.params

    def test_variable_spacing_overrides_uniform(self):
        result = resolve_prompt(
            "Create vertical grids with spacings 10, 5, 20"
        )
        assert result is not None
        assert result.params["HorizontalSpacingsFeet"] == [10.0, 5.0, 20.0]
        # SpacingFeet keeps its default but variable spacing takes precedence
        assert "SpacingFeet" in result.params

    def test_variable_spacing_assumptions(self):
        result = resolve_prompt(
            "Create vertical grids with spacings 10, 5, 20"
        )
        assert result is not None
        assert any("Variable vertical" in a for a in result.assumptions)

    def test_table_with_5_vertical_gridlines(self):
        prompt = (
            "Create 5 vertical gridlines with spacing table:\n"
            "1-2 = 10'\n"
            "2-3 = 5'\n"
            "3-4 = 20'\n"
            "4-5 = 10'"
        )
        result = resolve_prompt(prompt)
        assert result is not None
        assert result.params["HorizontalSpacingsFeet"] == [10.0, 5.0, 20.0, 10.0]
        assert result.params["HorizontalCount"] == 5


class TestPromptResolverEdgeCases:
    def test_case_insensitive(self):
        result = resolve_prompt("CREATE 5 VERTICAL GRIDS SPACED 20' APART")
        assert result is not None
        # "vertical" → HorizontalCount
        assert result.params["HorizontalCount"] == 5

    def test_gridline_keyword(self):
        result = resolve_prompt("Add 3 gridlines")
        assert result is not None

    def test_empty_prompt(self):
        result = resolve_prompt("")
        assert result is None


class TestClarificationNeeded:
    """BUG-001: rows/columns without 'grid' keyword trigger clarification."""

    def test_rows_without_grid_triggers_clarification(self):
        result = resolve_prompt("Create 4 rows spaced 15 ft apart")
        assert result is not None
        assert result.status == "clarification_needed"
        assert result.capability_name == "CreateGrids"
        assert "gridlines" in result.clarification_message.lower()

    def test_columns_without_grid_triggers_clarification(self):
        result = resolve_prompt("Create 6 columns spaced 10 ft apart")
        assert result is not None
        assert result.status == "clarification_needed"
        assert "6 vertical column" in result.clarification_message

    def test_rows_and_columns_without_grid_triggers_clarification(self):
        result = resolve_prompt("Create 8 columns and 4 rows spaced 12 ft apart")
        assert result is not None
        assert result.status == "clarification_needed"
        assert "4 horizontal row" in result.clarification_message
        assert "8 vertical column" in result.clarification_message

    def test_explicit_grid_rows_executes_normally(self):
        result = resolve_prompt("Create 5 grid rows spaced 15 ft apart")
        assert result is not None
        assert result.status == "resolved"
        assert result.params["VerticalCount"] == 5

    def test_explicit_gridlines_executes_normally(self):
        result = resolve_prompt(
            "Create 5 horizontal gridlines and 10 vertical gridlines spaced 10 ft apart"
        )
        assert result is not None
        assert result.status == "resolved"
        assert result.params["VerticalCount"] == 5
        assert result.params["HorizontalCount"] == 10

    def test_unrelated_prompt_still_returns_none(self):
        result = resolve_prompt("Place diffusers in every room")
        assert result is None


class TestLevelPromptResolver:
    """Tests for CreateLevels prompt resolution."""

    def test_basic_level_prompt(self):
        result = resolve_prompt("Create 5 levels starting at 0 feet, spaced 12 feet apart")
        assert result is not None
        assert result.capability_name == "CreateLevels"
        assert result.params["LevelCount"] == 5
        assert result.params["FloorToFloorFeet"] == 12.0
        assert result.params["StartElevationFeet"] == 0.0

    def test_level_count_extraction(self):
        result = resolve_prompt("Create 3 levels spaced 10 ft apart")
        assert result is not None
        assert result.params["LevelCount"] == 3
        assert result.params["FloorToFloorFeet"] == 10.0

    def test_variable_elevations(self):
        result = resolve_prompt("Create 3 levels at 0, 12, and 24 feet")
        assert result is not None
        assert result.params["LevelCount"] == 3
        assert result.params["VariableElevationsFeet"] == [0.0, 12.0, 24.0]

    def test_named_levels(self):
        result = resolve_prompt(
            "Create levels named Level 1, Level 2, Level 3 spaced 10 feet apart"
        )
        assert result is not None
        assert result.params["LevelCount"] == 3
        assert result.params["LevelNames"] == ["level 1", "level 2", "level 3"]
        assert result.params["FloorToFloorFeet"] == 10.0

    def test_named_level_table(self):
        prompt = (
            "Create levels:\n"
            "Basement = -10'\n"
            "Ground = 0'\n"
            "Level 2 = 12'"
        )
        result = resolve_prompt(prompt)
        assert result is not None
        assert result.params["LevelCount"] == 3
        assert result.params["LevelNames"] == ["Basement", "Ground", "Level 2"]
        assert result.params["VariableElevationsFeet"] == [-10.0, 0.0, 12.0]

    def test_start_elevation(self):
        result = resolve_prompt("Create 4 levels starting at 10 feet spaced 12 ft apart")
        assert result is not None
        assert result.params["StartElevationFeet"] == 10.0

    def test_defaults(self):
        result = resolve_prompt("Create 2 levels")
        assert result is not None
        assert result.params["LevelCount"] == 2
        assert result.params["StartElevationFeet"] == 0.0
        assert len(result.assumptions) > 0

    def test_single_level(self):
        result = resolve_prompt("Create 1 level spaced 12 feet apart")
        assert result is not None
        assert result.params["LevelCount"] == 1

    def test_add_keyword(self):
        result = resolve_prompt("Add 3 levels spaced 12 ft apart")
        assert result is not None
        assert result.capability_name == "CreateLevels"
        assert result.params["LevelCount"] == 3

    def test_grid_prompt_not_affected(self):
        result = resolve_prompt("Create 10 vertical gridlines, 50' long, spaced 10' apart")
        assert result is not None
        assert result.capability_name == "CreateGrids"

    def test_unrelated_prompt_returns_none(self):
        result = resolve_prompt("What is the meaning of life?")
        assert result is None


class TestLevelClarification:
    """Tests for floors/stories clarification (same pattern as BUG-001)."""

    def test_floors_triggers_clarification(self):
        result = resolve_prompt("Create 5 floors spaced 12 ft apart")
        assert result is not None
        assert result.status == "clarification_needed"
        assert result.capability_name == "CreateLevels"
        assert "levels" in result.clarification_message.lower()

    def test_stories_triggers_clarification(self):
        result = resolve_prompt("Create 3 stories")
        assert result is not None
        assert result.status == "clarification_needed"
        assert "levels" in result.clarification_message.lower()

    def test_explicit_level_executes(self):
        result = resolve_prompt("Create 5 levels spaced 12 ft apart")
        assert result is not None
        assert result.status == "resolved"
        assert result.capability_name == "CreateLevels"

    def test_diffuser_prompt_still_none(self):
        result = resolve_prompt("Place diffusers in every room")
        assert result is None


class TestGridLevelPriority:
    """Grid keywords should take priority over 'level' in mixed prompts."""

    def test_create_grids_at_level_resolves_to_grids(self):
        result = resolve_prompt("Create grids at level 2")
        assert result is not None
        assert result.capability_name == "CreateGrids"

    def test_create_gridlines_on_level_resolves_to_grids(self):
        result = resolve_prompt("Create 5 gridlines on level 1")
        assert result is not None
        assert result.capability_name == "CreateGrids"

    def test_pure_level_prompt_still_resolves_to_levels(self):
        result = resolve_prompt("Create 3 levels spaced 10 ft apart")
        assert result is not None
        assert result.capability_name == "CreateLevels"

    def test_grid_level_mixed_resolves_to_grids(self):
        result = resolve_prompt("Add grid lines at level 1 spaced 20 ft apart")
        assert result is not None
        assert result.capability_name == "CreateGrids"

    def test_grid_with_floors_resolves_to_grids_not_clarification(self):
        result = resolve_prompt("Create a grid layout for all 3 floors, 10 ft spacing")
        assert result is not None
        assert result.capability_name == "CreateGrids"
        assert result.status == "resolved"


class TestLevelMockExecution:
    """Tests for CreateLevels mock/simulation execution."""

    def test_basic_level_simulation(self):
        from axiom_core.agents.execution_agent import ExecutionAgent
        from axiom_core.agents.orchestrator_agent import OrchestratorAgent
        from axiom_core.agents.telemetry_agent import TelemetryAgent
        from axiom_core.pipe_client import PipeClient

        pipe = PipeClient()
        exec_agent = ExecutionAgent(pipe_client=pipe)
        tel_agent = TelemetryAgent()
        orch = OrchestratorAgent(execution_agent=exec_agent, telemetry_agent=tel_agent)

        result = orch.handle_prompt(
            "Create 5 levels starting at 0 feet, spaced 12 feet apart",
            simulate=True,
        )
        assert result["status"] == "SUCCESS"
        assert len(result["results"]) > 0
        assert result["results"][0].created_ids == [
            "level_1", "level_2", "level_3", "level_4", "level_5"
        ]

    def test_variable_elevation_simulation(self):
        from axiom_core.agents.execution_agent import ExecutionAgent
        from axiom_core.agents.orchestrator_agent import OrchestratorAgent
        from axiom_core.agents.telemetry_agent import TelemetryAgent
        from axiom_core.pipe_client import PipeClient

        pipe = PipeClient()
        exec_agent = ExecutionAgent(pipe_client=pipe)
        tel_agent = TelemetryAgent()
        orch = OrchestratorAgent(execution_agent=exec_agent, telemetry_agent=tel_agent)

        result = orch.handle_prompt(
            "Create 3 levels at 0, 14, and 28 feet",
            simulate=True,
        )
        assert result["status"] == "SUCCESS"
        assert len(result["results"][0].created_ids) == 3

    def test_named_level_table_simulation(self):
        from axiom_core.agents.execution_agent import ExecutionAgent
        from axiom_core.agents.orchestrator_agent import OrchestratorAgent
        from axiom_core.agents.telemetry_agent import TelemetryAgent
        from axiom_core.pipe_client import PipeClient

        pipe = PipeClient()
        exec_agent = ExecutionAgent(pipe_client=pipe)
        tel_agent = TelemetryAgent()
        orch = OrchestratorAgent(execution_agent=exec_agent, telemetry_agent=tel_agent)

        result = orch.handle_prompt(
            "Create levels:\nBasement = -10'\nGround = 0'\nLevel 2 = 12'",
            simulate=True,
        )
        assert result["status"] == "SUCCESS"
        assert len(result["results"][0].created_ids) == 3
        assert "level_Basement" in result["results"][0].created_ids

    def test_level_count_zero_fails(self):
        from axiom_core.pipe_client import PipeClient
        from axiom_core.schemas import StepStatus

        pipe = PipeClient()
        result = pipe._mock_execute(
            request_id="00000000-0000-0000-0000-000000000001",
            tool_name="CreateLevels",
            args={"LevelCount": 0},
            simulate=True,
        )
        assert result.status == StepStatus.FAILED

    def test_missing_spacing_fails(self):
        from axiom_core.pipe_client import PipeClient
        from axiom_core.schemas import StepStatus

        pipe = PipeClient()
        result = pipe._mock_execute(
            request_id="00000000-0000-0000-0000-000000000001",
            tool_name="CreateLevels",
            args={"LevelCount": 3},
            simulate=True,
        )
        assert result.status == StepStatus.FAILED
        assert any("FloorToFloorFeet" in e for e in result.errors)

    def test_single_level_no_spacing_succeeds(self):
        from axiom_core.pipe_client import PipeClient
        from axiom_core.schemas import StepStatus

        pipe = PipeClient()
        result = pipe._mock_execute(
            request_id="00000000-0000-0000-0000-000000000001",
            tool_name="CreateLevels",
            args={"LevelCount": 1, "StartElevationFeet": 0.0},
            simulate=True,
        )
        assert result.status == StepStatus.SUCCESS
        assert len(result.created_ids) == 1

    def test_duplicate_elevations_fails(self):
        from axiom_core.pipe_client import PipeClient
        from axiom_core.schemas import StepStatus

        pipe = PipeClient()
        result = pipe._mock_execute(
            request_id="00000000-0000-0000-0000-000000000001",
            tool_name="CreateLevels",
            args={"LevelCount": 3, "VariableElevationsFeet": [0, 12, 12]},
            simulate=True,
        )
        assert result.status == StepStatus.FAILED
        assert any("Duplicate" in e for e in result.errors)

    def test_mismatched_elevations_count_fails(self):
        from axiom_core.pipe_client import PipeClient
        from axiom_core.schemas import StepStatus

        pipe = PipeClient()
        result = pipe._mock_execute(
            request_id="00000000-0000-0000-0000-000000000001",
            tool_name="CreateLevels",
            args={"LevelCount": 3, "VariableElevationsFeet": [0, 12]},
            simulate=True,
        )
        assert result.status == StepStatus.FAILED

    def test_duplicate_names_fails(self):
        from axiom_core.pipe_client import PipeClient
        from axiom_core.schemas import StepStatus

        pipe = PipeClient()
        result = pipe._mock_execute(
            request_id="00000000-0000-0000-0000-000000000001",
            tool_name="CreateLevels",
            args={
                "LevelCount": 3,
                "FloorToFloorFeet": 12,
                "LevelNames": ["Level 1", "Level 1", "Level 2"],
            },
            simulate=True,
        )
        assert result.status == StepStatus.FAILED
        assert any("Duplicate" in e for e in result.errors)

    def test_floors_clarification_no_execution(self):
        from axiom_core.agents.execution_agent import ExecutionAgent
        from axiom_core.agents.orchestrator_agent import OrchestratorAgent
        from axiom_core.agents.telemetry_agent import TelemetryAgent
        from axiom_core.pipe_client import PipeClient

        pipe = PipeClient()
        exec_agent = ExecutionAgent(pipe_client=pipe)
        tel_agent = TelemetryAgent()
        orch = OrchestratorAgent(execution_agent=exec_agent, telemetry_agent=tel_agent)

        result = orch.handle_prompt("Create 5 floors spaced 12 ft apart")
        assert result["status"] == "CLARIFICATION_NEEDED"
        assert result["results"] == []

    def test_grid_prompt_still_works(self):
        from axiom_core.agents.execution_agent import ExecutionAgent
        from axiom_core.agents.orchestrator_agent import OrchestratorAgent
        from axiom_core.agents.telemetry_agent import TelemetryAgent
        from axiom_core.pipe_client import PipeClient

        pipe = PipeClient()
        exec_agent = ExecutionAgent(pipe_client=pipe)
        tel_agent = TelemetryAgent()
        orch = OrchestratorAgent(execution_agent=exec_agent, telemetry_agent=tel_agent)

        result = orch.handle_prompt(
            "Create 10 vertical gridlines, 50' long, spaced 10' apart",
            simulate=True,
        )
        assert result["status"] == "SUCCESS"
        assert result["resolved"].capability_name == "CreateGrids"


class TestGridVariableSpacingClarification:
    """Tests for variable spacing clarification and validation."""

    def test_arithmetic_spacing_and_so_on_triggers_clarification(self):
        result = resolve_prompt(
            "create 10 vertical grids spaced 5', 10', 15' and so on apart"
        )
        assert result is not None
        assert result.capability_name == "CreateGrids"
        assert result.status == "clarification_needed"
        assert "increases by" in result.clarification_message

    def test_arithmetic_spacing_etc_triggers_clarification(self):
        result = resolve_prompt(
            "create grids spaced 10, 20, 30 ft etc"
        )
        assert result is not None
        assert result.status == "clarification_needed"

    def test_arithmetic_spacing_ellipsis_triggers_clarification(self):
        result = resolve_prompt(
            "create 8 vertical grids spaced 5, 10, 15..."
        )
        assert result is not None
        assert result.status == "clarification_needed"

    def test_count_3_with_3_spacings_triggers_clarification(self):
        result = resolve_prompt(
            "create 3 vertical grids spaced 5, 6, and 20 feet apart"
        )
        assert result is not None
        assert result.capability_name == "CreateGrids"
        assert result.status == "clarification_needed"
        assert "3 grids" in result.clarification_message
        assert "3 spacing" in result.clarification_message

    def test_generic_grids_variable_spacing_no_orientation_clarification(self):
        result = resolve_prompt(
            "create 3 grids spaced 5, 6, and 20 feet apart"
        )
        assert result is not None
        assert result.capability_name == "CreateGrids"
        assert result.status == "clarification_needed"

    def test_explicit_4_vertical_grids_with_3_spacings_succeeds(self):
        result = resolve_prompt(
            "create 4 vertical grids with spacings 5, 6, and 20 feet"
        )
        assert result is not None
        assert result.capability_name == "CreateGrids"
        assert result.status == "resolved"
        assert result.params.get("HorizontalSpacingsFeet") == [5.0, 6.0, 20.0]
        assert result.params.get("HorizontalCount") == 4

    def test_explicit_3_vertical_grids_with_2_spacings_succeeds(self):
        result = resolve_prompt(
            "create 3 vertical grids spaced 5 and 6 feet apart"
        )
        assert result is not None
        assert result.capability_name == "CreateGrids"
        assert result.status == "resolved"

    def test_explicit_3_horizontal_grids_with_2_spacings_succeeds(self):
        result = resolve_prompt(
            "create 3 horizontal grids spaced 5 and 6 feet apart"
        )
        assert result is not None
        assert result.capability_name == "CreateGrids"
        assert result.status == "resolved"

    def test_uniform_spacing_still_works(self):
        result = resolve_prompt(
            "create 10 vertical grids spaced 10 ft apart"
        )
        assert result is not None
        assert result.capability_name == "CreateGrids"
        assert result.status == "resolved"
        assert result.params.get("SpacingFeet") == 10.0

    def test_uniform_spacing_with_both_orientations_still_works(self):
        result = resolve_prompt(
            "create a 5 by 5 grid layout spaced 20 ft apart"
        )
        assert result is not None
        assert result.capability_name == "CreateGrids"
        assert result.status == "resolved"

    def test_explicit_vertical_variable_spacing_no_count_mismatch(self):
        result = resolve_prompt(
            "create vertical grids with spacings 10, 15, 20"
        )
        assert result is not None
        assert result.capability_name == "CreateGrids"
        assert result.status == "resolved"
        assert result.params.get("HorizontalSpacingsFeet") == [10.0, 15.0, 20.0]
