"""
Unit and integration tests for Pal macOS Computer-Use Harness & 'Hey Pal' Wake Word Routing.
"""

from unittest.mock import MagicMock, patch
import pytest

from voicefi.config import VoiceFiConfig, WakeWordConfig
from voicefi.integrations.active_listening import ActiveListeningEngine
from voicefi.integrations.pal_harness import PalHarness, PalCommandResult
from voicefi.stt.biasing import PhoneticNormalizer


class TestHeyPalWakeWordExtraction:
    """Test recognition and normalization of 'Hey Pal' and its acoustic variants."""

    def test_direct_hey_pal_open_garageband(self):
        matched, prompt = ActiveListeningEngine.extract_wakeword_and_prompt("Hey Pal, open GarageBand")
        assert matched is not None
        assert matched.lower() == "hey pal"
        assert prompt == "open GarageBand"

    def test_pal_alias_short(self):
        matched, prompt = ActiveListeningEngine.extract_wakeword_and_prompt("Pal, mute system volume")
        assert matched is not None
        assert matched.lower() == "pal"
        assert prompt == "mute system volume"

    def test_paypal_phonetic_stt_transcription(self):
        # When Whisper hears 'PayPal' instead of 'Hey Pal'
        normalized = PhoneticNormalizer.normalize("PayPal open GarageBand")
        matched, prompt = ActiveListeningEngine.extract_wakeword_and_prompt(normalized)
        assert matched is not None
        assert matched.lower() == "hey pal"
        assert "open GarageBand" in prompt

    def test_pay_pal_split_transcription(self):
        normalized = PhoneticNormalizer.normalize("Pay pal set volume to 50")
        matched, prompt = ActiveListeningEngine.extract_wakeword_and_prompt(normalized)
        assert matched is not None
        assert matched.lower() == "hey pal"
        assert "set volume to 50" in prompt

    def test_hey_pow_transcription(self):
        normalized = PhoneticNormalizer.normalize("hey pow bring up terminal")
        matched, prompt = ActiveListeningEngine.extract_wakeword_and_prompt(normalized)
        assert matched is not None
        assert matched.lower() == "hey pal"
        assert "bring up terminal" in prompt

    def test_hey_paul_transcription(self):
        normalized = PhoneticNormalizer.normalize("hey paul open finder")
        matched, prompt = ActiveListeningEngine.extract_wakeword_and_prompt(normalized)
        assert matched is not None
        assert matched.lower() == "hey pal"
        assert "open finder" in prompt

    def test_hey_pal_conversational_cue_only(self):
        matched, prompt = ActiveListeningEngine.extract_wakeword_and_prompt("Hey Pal")
        assert matched is not None
        assert matched.lower() == "hey pal"
        assert prompt == ""


class TestPalHarnessExecution:
    """Test deterministic execution of macOS computer use commands."""

    @patch("subprocess.run")
    def test_launch_app_garageband(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        res = PalHarness.execute_command("open GarageBand")
        assert res.success is True
        assert res.action_type == "launch_app"
        assert "GarageBand" in res.spoken_summary
        mock_run.assert_called_with(["open", "-a", "GarageBand"], capture_output=True, text=True, timeout=3.0)

    @patch("voicefi.integrations.pal_harness.PalHarness.run_applescript")
    def test_garageband_record(self, mock_as):
        mock_as.return_value = (True, "")
        res = PalHarness.execute_command("garageband record")
        assert res.success is True
        assert res.action_type == "garageband"
        assert "Recording started" in res.spoken_summary
        assert 'keystroke "r"' in mock_as.call_args[0][0]

    @patch("voicefi.integrations.pal_harness.PalHarness.run_applescript")
    def test_garageband_settings(self, mock_as):
        mock_as.return_value = (True, "")
        res = PalHarness.execute_command("garageband settings")
        assert res.success is True
        assert res.action_type == "garageband"
        assert 'keystroke "," using command down' in mock_as.call_args[0][0]

    @patch("voicefi.integrations.pal_harness.PalHarness.run_applescript")
    def test_volume_mute(self, mock_as):
        mock_as.return_value = (True, "")
        res = PalHarness.execute_command("mute")
        assert res.success is True
        assert res.action_type == "volume"
        assert "output muted" in mock_as.call_args[0][0]

    @patch("voicefi.integrations.pal_harness.PalHarness.run_applescript")
    def test_volume_unmute(self, mock_as):
        mock_as.return_value = (True, "")
        res = PalHarness.execute_command("unmute")
        assert res.success is True
        assert res.action_type == "volume"
        assert "without output muted" in mock_as.call_args[0][0]

    @patch("voicefi.integrations.pal_harness.PalHarness.run_applescript")
    def test_volume_set_percentage(self, mock_as):
        mock_as.return_value = (True, "")
        res = PalHarness.execute_command("set volume to 75")
        assert res.success is True
        assert res.action_type == "volume"
        assert "output volume 75" in mock_as.call_args[0][0]

    @patch("subprocess.run")
    def test_open_folder_downloads(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        res = PalHarness.execute_command("open downloads folder")
        assert res.success is True
        assert res.action_type == "open_folder"
        assert "Downloads" in res.details

    @patch("voicefi.integrations.pal_harness.PalHarness.run_applescript")
    def test_quit_app(self, mock_as):
        mock_as.return_value = (True, "")
        res = PalHarness.execute_command("quit GarageBand")
        assert res.success is True
        assert res.action_type == "quit_app"
        assert 'tell application "GarageBand" to quit' in mock_as.call_args[0][0]


class TestConfigPalSupport:
    """Verify WakeWordConfig includes Hey Pal defaults."""

    def test_wakeword_config_has_pal(self):
        cfg = WakeWordConfig()
        assert "hey pal" in cfg.aliases
        assert "pal" in cfg.aliases
        assert "Hey Pal" in cfg.alert_words
        assert cfg.pal_computer_use is True
