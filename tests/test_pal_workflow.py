"""
Unit and integration tests for Pal Workflow Recipe Schema, Registry, and Deterministic Replay Engine.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from voicefi.integrations.pal_workflow import (
    ActionType,
    ClickTarget,
    PalWorkflowRecipe,
    PalWorkflowRegistry,
    PalWorkflowRunner,
    ParameterDefinition,
    WorkflowStep,
)


class TestPalWorkflowSchema:
    """Test serialization, validation, and parameter definition."""

    def test_create_valid_recipe(self):
        step1 = WorkflowStep(
            name="Open GarageBand",
            action=ActionType.ACTIVATE_APP,
            app_name="GarageBand",
        )
        step2 = WorkflowStep(
            name="Export Stems Hotkey",
            action=ActionType.HOTKEY,
            combo="Cmd+Shift+E",
        )
        recipe = PalWorkflowRecipe(
            id="test_stem_export",
            name="Stem Export",
            triggers=["export stems", "bounce tracks"],
            steps=[step1, step2],
        )

        assert recipe.id == "test_stem_export"
        assert len(recipe.steps) == 2
        assert recipe.steps[0].action == ActionType.ACTIVATE_APP
        assert recipe.steps[1].combo == "Cmd+Shift+E"

    def test_parameter_regex_binding(self):
        param = ParameterDefinition(
            type="string",
            default="My_Session",
            extract_patterns=[r"(?:named|as)\s+['\"](?P<value>[^'\"]+)['\"]"],
        )
        recipe = PalWorkflowRecipe(
            id="test_param",
            name="Param Test",
            parameters={"project_name": param},
            steps=[
                WorkflowStep(
                    name="Type Name",
                    action=ActionType.KEYSTROKE,
                    text="${project_name}",
                )
            ],
        )

        vars_bound = PalWorkflowRunner._bind_parameters(
            recipe.parameters,
            "bounce stems as 'Album_Master'",
            explicit_args={},
        )
        assert vars_bound["project_name"] == "Album_Master"

        # Fallback to default when no match
        vars_default = PalWorkflowRunner._bind_parameters(
            recipe.parameters,
            "bounce stems",
            explicit_args={},
        )
        assert vars_default["project_name"] == "My_Session"


class TestPalWorkflowRunner:
    """Test deterministic step execution and safety circuit breakers."""

    @patch("voicefi.integrations.pal_harness.PalHarness.launch_app")
    def test_execute_activate_app(self, mock_launch):
        from voicefi.integrations.pal_harness import PalCommandResult

        mock_launch.return_value = PalCommandResult(
            success=True,
            command="open -a 'GarageBand'",
            action_type="launch_app",
            details="Launched GarageBand",
            spoken_summary="Opened GarageBand",
        )

        recipe = PalWorkflowRecipe(
            id="launch_gb",
            name="Launch GB",
            steps=[
                WorkflowStep(
                    name="Launch",
                    action=ActionType.ACTIVATE_APP,
                    app_name="GarageBand",
                )
            ],
        )

        res = PalWorkflowRunner.execute_recipe(recipe)
        assert res.success is True
        mock_launch.assert_called_with("GarageBand")

    @patch("voicefi.integrations.pal_harness.PalHarness.run_applescript")
    def test_execute_hotkey_combo(self, mock_as):
        mock_as.return_value = (True, "")

        recipe = PalWorkflowRecipe(
            id="hotkey_test",
            name="Hotkey Test",
            steps=[
                WorkflowStep(
                    name="Save",
                    action=ActionType.HOTKEY,
                    combo="Cmd+S",
                )
            ],
        )

        res = PalWorkflowRunner.execute_recipe(recipe)
        assert res.success is True
        assert 'keystroke "s" using {command down}' in mock_as.call_args[0][0]

    @patch("voicefi.integrations.pal_harness.PalHarness.run_applescript")
    def test_execute_keystroke_with_interpolation(self, mock_as):
        mock_as.return_value = (True, "")

        recipe = PalWorkflowRecipe(
            id="type_test",
            name="Type Test",
            steps=[
                WorkflowStep(
                    name="Type Track",
                    action=ActionType.KEYSTROKE,
                    text="Vocal_Lead_24bit",
                    press_enter=True,
                )
            ],
        )

        res = PalWorkflowRunner.execute_recipe(recipe)
        assert res.success is True
        # First call: keystroke text, second call: key code 36 (Enter)
        assert any('keystroke "Vocal_Lead_24bit"' in call[0][0] for call in mock_as.call_args_list)

    @patch("voicefi.integrations.pal_harness.PalHarness.run_applescript")
    def test_step_failure_triggers_unwind(self, mock_as):
        # Step fails
        mock_as.return_value = (False, "UI element not found")

        recipe = PalWorkflowRecipe(
            id="fail_test",
            name="Fail Test",
            steps=[
                WorkflowStep(
                    name="Broken Step",
                    action=ActionType.APPLESCRIPT,
                    script="tell application 'Unknown' to activate",
                    on_failure="abort",
                )
            ],
        )

        res = PalWorkflowRunner.execute_recipe(recipe)
        assert res.success is False
        assert "Broken Step" in res.spoken_summary
        # Verify Escape key unwinding was triggered (key code 53)
        assert any("key code 53" in call[0][0] for call in mock_as.call_args_list)


class TestPalWorkflowRegistry:
    """Test in-memory registration and trigger lookup."""

    def test_register_and_match_recipe(self):
        recipe = PalWorkflowRecipe(
            id="morning_setup_test",
            name="Morning Setup",
            triggers=["morning setup", "wake up studio"],
            steps=[],
        )
        PalWorkflowRegistry.register_recipe(recipe)

        # Match exact trigger
        matched = PalWorkflowRegistry.match_recipe("morning setup")
        assert matched is not None
        assert matched[0].id == "morning_setup_test"

        # Match with prefix verb
        matched_verb = PalWorkflowRegistry.match_recipe("run morning setup")
        assert matched_verb is not None
        assert matched_verb[0].id == "morning_setup_test"

        # Match alternate trigger
        matched_alt = PalWorkflowRegistry.match_recipe("wake up studio")
        assert matched_alt is not None
        assert matched_alt[0].id == "morning_setup_test"
