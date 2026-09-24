"""
Comprehensive unit test suite for hardened VoiceFi feedback loop:
1. Ordinal and index-based choice matching
2. Multiple choice options extraction (numbered, bulleted, Oxford comma, quotes)
3. Echo cancellation option whitelisting
4. Hardware acoustic device classification (monitors/HDMI vs headphones)
5. Concurrency dead PID debounce & atomic turn completion
6. Cross-agent provenance envelopes
"""

import json
import os
import time
import pytest
from unittest.mock import patch, MagicMock

from voicefi.integrations.active_listening import (
    ActiveListeningEngine,
    SpokenIntentCategory,
    SpokenTargetChannel,
)
from voicefi.integrations.conversations import (
    extract_choice_options,
    claim_turn,
    mark_turn_completed,
    set_pending_question,
    get_pending_question,
    clear_pending_question,
)
from voicefi.audio.echo_canceller import is_acoustic_echo
from voicefi.audio.device import is_headphone_or_headset_active, is_using_builtin_speakers
from voicefi.integrations.injector import inject_text_to_claude


class TestOrdinalAndChoiceMatching:
    """Test ordinal, index, relative, and polar choice matching."""

    def test_ordinal_words_and_digits(self):
        pq = {
            "question": "Would you like to deploy to staging or ship to production?",
            "options": ["deploy to staging", "ship to production"],
        }

        # 1st option
        assert ActiveListeningEngine.match_pending_choice("the first one", pq) == "deploy to staging"
        assert ActiveListeningEngine.match_pending_choice("first option please", pq) == "deploy to staging"
        assert ActiveListeningEngine.match_pending_choice("option 1", pq) == "deploy to staging"
        assert ActiveListeningEngine.match_pending_choice("choice 1", pq) == "deploy to staging"
        assert ActiveListeningEngine.match_pending_choice("number 1", pq) == "deploy to staging"
        assert ActiveListeningEngine.match_pending_choice("1st one", pq) == "deploy to staging"

        # 2nd option
        assert ActiveListeningEngine.match_pending_choice("the second one", pq) == "ship to production"
        assert ActiveListeningEngine.match_pending_choice("option 2", pq) == "ship to production"
        assert ActiveListeningEngine.match_pending_choice("choice two", pq) == "ship to production"
        assert ActiveListeningEngine.match_pending_choice("second option", pq) == "ship to production"
        assert ActiveListeningEngine.match_pending_choice("2nd", pq) == "ship to production"

    def test_relative_former_and_latter(self):
        pq = {
            "question": "Should we use PostgreSQL or SQLite?",
            "options": ["postgresql", "sqlite"],
        }
        assert ActiveListeningEngine.match_pending_choice("the former", pq) == "postgresql"
        assert ActiveListeningEngine.match_pending_choice("the latter", pq) == "sqlite"

    def test_polar_confirmation(self):
        pq = {
            "question": "Should we proceed with the refactor?",
            "options": ["proceed with refactor", "cancel"],
        }
        assert ActiveListeningEngine.match_pending_choice("yes please", pq) == "proceed with refactor"
        assert ActiveListeningEngine.match_pending_choice("sure sounds good", pq) == "proceed with refactor"
        assert ActiveListeningEngine.match_pending_choice("no don't do it", pq) == "cancel"

    def test_fuzzy_and_substring_option(self):
        pq = {
            "question": "Should we stage on Railway or ship straightaway?",
            "options": ["stage on railway", "ship straightaway"],
        }
        assert ActiveListeningEngine.match_pending_choice("railway please", pq) == "stage on railway"
        assert ActiveListeningEngine.match_pending_choice("let's do straightaway", pq) == "ship straightaway"


class TestChoiceOptionsExtraction:
    """Test options parsing from various natural language and markdown formats."""

    def test_numbered_markdown_list(self):
        q = "Which database engine would you prefer?\n1. PostgreSQL\n2. SQLite\n3. MongoDB"
        opts = extract_choice_options(q)
        assert opts == ["postgresql", "sqlite", "mongodb"]

    def test_bulleted_markdown_list(self):
        q = "Select deployment target:\n- Staging Cluster\n- Production Cloud"
        opts = extract_choice_options(q)
        assert opts == ["staging cluster", "production cloud"]

    def test_oxford_comma_or_split(self):
        q = "Should we deploy to AWS, GCP, or Azure?"
        opts = extract_choice_options(q)
        assert opts == ["aws", "gcp", "azure"]

    def test_quoted_choices(self):
        q = 'Do you want to run "unit tests" or "integration tests"?'
        opts = extract_choice_options(q)
        assert opts == ["unit tests", "integration tests"]

    def test_simple_or_question(self):
        q = "Would you like to stage on Railway or ship straightaway?"
        opts = extract_choice_options(q)
        assert opts == ["stage on railway", "ship straightaway"]


class TestEchoCancellerWhitelist:
    """Test that valid user responses to multiple-choice questions are not dropped as echoes."""

    def test_option_whitelist_prevents_echo_suppression(self):
        conv_id = "test-echo-whitelist-conv"
        set_pending_question(
            conv_id,
            "Should we stage on Railway or ship straightaway?",
            options=["stage on railway", "ship straightaway"],
        )

        ref_text = "Should we stage on Railway or ship straightaway?"

        # With pending question registered, repeating the option text is NOT suppressed as echo
        assert is_acoustic_echo("Stage on Railway", reference_text=ref_text) is False
        assert is_acoustic_echo("ship straightaway", reference_text=ref_text) is False

        # Explicit whitelist parameter also prevents suppression
        assert is_acoustic_echo(
            "Stage on Railway",
            reference_text=ref_text,
            whitelist_options=["stage on railway"],
        ) is False

        clear_pending_question(conv_id)


class TestAudioDeviceClassification:
    """Test hardware device acoustic profiling (speakers vs headphones)."""

    def test_external_monitors_not_classified_as_headphones(self):
        # Dell Monitor
        with patch("voicefi.audio.device.get_default_audio_devices") as mock_devs:
            mock_devs.return_value = (
                {"name": "MacBook Pro Microphone"},
                {"name": "DELL U2723QE (DisplayPort)"},
            )
            assert is_headphone_or_headset_active() is False

        # LG UltraFine Monitor
        with patch("voicefi.audio.device.get_default_audio_devices") as mock_devs:
            mock_devs.return_value = (
                {"name": "MacBook Pro Microphone"},
                {"name": "LG UltraFine Display Audio"},
            )
            assert is_headphone_or_headset_active() is False

        # HDMI TV
        with patch("voicefi.audio.device.get_default_audio_devices") as mock_devs:
            mock_devs.return_value = (
                {"name": "MacBook Pro Microphone"},
                {"name": "HDMI Audio Output"},
            )
            assert is_headphone_or_headset_active() is False

    def test_headphones_and_airpods_classified_correctly(self):
        # AirPods Pro
        with patch("voicefi.audio.device.get_default_audio_devices") as mock_devs:
            mock_devs.return_value = (
                {"name": "Jake's AirPods Pro"},
                {"name": "Jake's AirPods Pro"},
            )
            assert is_headphone_or_headset_active() is True

        # Bluetooth headset
        with patch("voicefi.audio.device.get_default_audio_devices") as mock_devs:
            mock_devs.return_value = (
                {"name": "Bose QC35 Microphone"},
                {"name": "Bose QC35 Bluetooth Headphone"},
            )
            assert is_headphone_or_headset_active() is True


class TestConcurrencyAndLivenessDebounce:
    """Test turn claiming concurrency and dead PID debounce."""

    def test_dead_pid_within_debounce_window_is_respected(self, tmp_path):
        from voicefi.integrations import turn_lock

        turn_file = tmp_path / "voicefi_active_turns.json"
        lock_file = tmp_path / "voicefi_active_turns.lock"

        with patch.object(turn_lock, "Path") as mock_path:
            def _path_side_effect(p):
                if "active_turns.json" in str(p):
                    return turn_file
                elif "active_turns.lock" in str(p):
                    return lock_file
                return tmp_path / p
            mock_path.side_effect = _path_side_effect

            # Simulate an ephemeral CLI hook process that claimed turn 1.0s ago with dead PID
            initial_entry = [{
                "conv_id": "test-conv-pid",
                "signature": "test-conv-pid:Hello world",
                "norm_sig": "test-conv-pid:Hello world",
                "step_index": 4,
                "pid": 99999999,  # non-existent dead PID
                "timestamp": time.time() - 1.0,  # 1.0s ago (< 4.0s debounce)
                "status": "claimed",
            }]
            with open(turn_file, "w") as f:
                json.dump(initial_entry, f)

            with patch("voicefi.integrations.turn_lock.is_pid_alive", return_value=False):
                # Another process (like TranscriptWatcher) tries to claim the same turn within 1.0s
                claimed = claim_turn("test-conv-pid", "test-conv-pid:Hello world", step_index=4)
                assert claimed is False  # Must be blocked by recent debounce window!

    def test_dead_pid_after_debounce_window_is_evicted(self, tmp_path):
        from voicefi.integrations import turn_lock

        turn_file = tmp_path / "voicefi_active_turns.json"
        lock_file = tmp_path / "voicefi_active_turns.lock"

        with patch.object(turn_lock, "Path") as mock_path:
            def _path_side_effect(p):
                if "active_turns.json" in str(p):
                    return turn_file
                elif "active_turns.lock" in str(p):
                    return lock_file
                return tmp_path / p
            mock_path.side_effect = _path_side_effect

            # Simulate stale turn from 10.0s ago with dead PID
            initial_entry = [{
                "conv_id": "test-conv-stale",
                "signature": "test-conv-stale:Stale turn",
                "norm_sig": "test-conv-stale:Stale turn",
                "step_index": 1,
                "pid": 99999999,
                "timestamp": time.time() - 10.0,  # 10.0s ago (> 4.0s debounce)
                "status": "claimed",
            }]
            with open(turn_file, "w") as f:
                json.dump(initial_entry, f)

            with patch("voicefi.integrations.turn_lock.is_pid_alive", return_value=False):
                # Stale lock must be ignored/evicted
                claimed = claim_turn("test-conv-stale", "test-conv-stale:New fresh turn", step_index=2)
                assert claimed is True


class TestClaudeCrossAgentProvenance:
    """Test cross-agent dispatch with provenance envelopes."""

    def test_inject_text_to_claude_includes_envelope_and_return_instructions(self):
        with patch("voicefi.integrations.injector.set_clipboard_text") as mock_clipboard, \
             patch("voicefi.integrations.injector.focus_terminal_app", return_value="Terminal"), \
             patch("subprocess.run") as mock_subproc, \
             patch("voicefi.integrations.conversations.record_agent_route"):

            mock_subproc.return_value = MagicMock(returncode=0)

            inject_text_to_claude(
                "Please run database migrations and report back.",
                submit_enter=False,
                from_conv_id="agy-conversation-789",
                from_engine="antigravity",
                include_envelope=True,
            )

            assert mock_clipboard.called
            clipboard_content = mock_clipboard.call_args[0][0]

            # Verify provenance header
            assert "[From: Antigravity | Conversation: agy-conversation-789]" in clipboard_content
            assert "Please run database migrations and report back." in clipboard_content

            # Verify return instructions
            assert "vifi send --to antigravity --reply" in clipboard_content
            assert "agy-conversation-789" in clipboard_content

    def test_claude_hook_silence_timeout_handled_cleanly(self):
        from voicefi.integrations.claude import handle_claude_stop_hook
        from voicefi.config import VoiceFiConfig

        cfg = VoiceFiConfig()
        cfg.claude.read_summary_aloud = False
        cfg.claude.auto_listen = True

        with patch("voicefi.integrations.claude.load_config", return_value=cfg), \
             patch("voicefi.integrations.claude.claim_turn", return_value=True), \
             patch("voicefi.integrations.claude.mark_turn_completed") as mock_mark_done, \
             patch("voicefi.integrations.claude.clear_cross_process_hud_state") as mock_clear_hud, \
             patch("voicefi.audio.recorder.AudioRecorder.record_speech_auto", return_value=(b"", None)):

            # When auto-listen times out with silence (temp_wav is None)
            res = handle_claude_stop_hook(payload={"text": "All tests passed."}, config=cfg)
            assert res == {"status": "no_speech"}
            mock_clear_hud.assert_called()
            mock_mark_done.assert_called()
