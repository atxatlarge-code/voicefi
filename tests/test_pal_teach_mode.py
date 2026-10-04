"""
Unit and integration tests for Pal Teach Mode (Demonstration Learning) and Training Lifecycle.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from voicefi.integrations.pal_harness import PalHarness
from voicefi.integrations.pal_trainer import PalTeachRawStep, PalTrainer
from voicefi.integrations.pal_workflow import PalWorkflowRegistry


class TestPalTeachModeLifecycle:
    """Test start, observe, denoise, and finish in PalTrainer."""

    def test_trainer_session_compilation(self, tmp_path):
        trainer = PalTrainer("Test Morning Setup")

        # Mock the recorder's steps directly to test synthesizer
        with patch.object(trainer.recorder, "start"), patch.object(trainer.recorder, "stop") as mock_stop:
            mock_stop.return_value = [
                PalTeachRawStep(
                    step_number=1,
                    action="switch_app",
                    app_name="GarageBand",
                    window_title="My Project",
                    params={"app_name": "GarageBand", "bundle_id": "com.apple.garageband10"},
                    spoken_summary="Switched to GarageBand",
                    voice_note="Focusing main DAW",
                ),
                PalTeachRawStep(
                    step_number=2,
                    action="hotkey",
                    app_name="GarageBand",
                    window_title="My Project",
                    params={"combo": "Cmd+R", "key": "R", "modifiers": ["Cmd"]},
                    spoken_summary="Pressed Cmd+R",
                    voice_note="Start recording",
                ),
                PalTeachRawStep(
                    step_number=3,
                    action="type_text",
                    app_name="GarageBand",
                    window_title="Save As",
                    params={"text": "Vocal_Take_1"},
                    spoken_summary="Typed 'Vocal_Take_1'",
                ),
            ]

            recipe = trainer.finish(save_dir=tmp_path)

            assert recipe.id == "test_morning_setup"
            assert recipe.name == "Test Morning Setup"
            assert len(recipe.steps) == 3
            assert recipe.steps[0].action.value == "activate_app"
            assert recipe.steps[0].app_name == "GarageBand"
            assert recipe.steps[0].description == "Focusing main DAW"
            assert recipe.steps[1].action.value == "hotkey"
            assert recipe.steps[1].combo == "Cmd+R"
            assert recipe.steps[2].action.value == "keystroke"
            assert recipe.steps[2].text == "Vocal_Take_1"

            # Verify saved YAML
            saved_file = tmp_path / "test_morning_setup.yaml"
            assert saved_file.exists()

            # Verify registered in registry
            matched = PalWorkflowRegistry.match_recipe("test morning setup")
            assert matched is not None
            assert matched[0].id == "test_morning_setup"


class TestPalHarnessTrainingCommands:
    """Test voice intent commands for training mode."""

    def test_start_and_stop_training_commands(self, tmp_path):
        with patch("voicefi.integrations.pal_trainer.PalTeachRecorder.start"), \
             patch("voicefi.integrations.pal_trainer.PalTeachRecorder.stop", return_value=[]):

            # 1. Start training via natural voice command
            res_start = PalHarness.execute_command("start training podcast export")
            assert res_start.success is True
            assert res_start.action_type == "training_start"
            assert PalHarness.is_training_active() is True
            assert "podcast export" in res_start.spoken_summary

            # 2. Prevent concurrent training sessions
            res_dup = PalHarness.execute_command("watch me do export")
            assert res_dup.success is False

            # 3. Stop training
            with patch("pathlib.Path.home", return_value=tmp_path):
                res_stop = PalHarness.execute_command("stop training")
                assert res_stop.success is True
                assert res_stop.action_type == "training_stop"
                assert PalHarness.is_training_active() is False

    def test_cancel_training_command(self):
        with patch("voicefi.integrations.pal_trainer.PalTeachRecorder.start"), \
             patch("voicefi.integrations.pal_trainer.PalTeachRecorder.stop", return_value=[]):

            PalHarness.execute_command("watch me do clean caches")
            assert PalHarness.is_training_active() is True

            res_cancel = PalHarness.execute_command("cancel training")
            assert res_cancel.success is True
            assert res_cancel.action_type == "training_cancel"
            assert PalHarness.is_training_active() is False

    def test_execute_dynamically_registered_workflow(self):
        from voicefi.integrations.pal_workflow import PalWorkflowRecipe, WorkflowStep, ActionType

        test_recipe = PalWorkflowRecipe(
            id="deploy_staging_macro",
            name="Deploy Staging",
            triggers=["deploy staging", "push to staging"],
            steps=[
                WorkflowStep(
                    name="Echo Test",
                    action=ActionType.NOTIFY,
                    message="Deploying to staging",
                )
            ],
        )
        PalWorkflowRegistry.register_recipe(test_recipe)

        res = PalHarness.execute_command("deploy staging")
        assert res.success is True
        assert res.action_type == "workflow"
        assert res.command == "deploy_staging_macro"
