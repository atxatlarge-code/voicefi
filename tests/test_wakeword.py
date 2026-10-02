"""
Unit tests for 'Hey Viv' Wake Word Detection, Alias Extraction, and Config Lifecycle.
"""

import pytest
from voicefi.config import VoiceFiConfig, WakeWordConfig, load_config
from voicefi.integrations.active_listening import ActiveListeningEngine
from voicefi.audio.wakeword import WakeWordListener


class TestWakeWordExtraction:
    """Tests for extracting wake phrases and isolating user prompts."""

    def test_single_shot_hey_viv_prompt(self):
        matched, prompt = ActiveListeningEngine.extract_wakeword_and_prompt("Hey Viv, refactor the authentication middleware.")
        assert matched is not None
        assert matched.lower() == "hey viv"
        assert prompt == "refactor the authentication middleware."

    def test_conversational_cue_hey_viv_only(self):
        matched, prompt = ActiveListeningEngine.extract_wakeword_and_prompt("Hey Viv")
        assert matched is not None
        assert matched.lower() == "hey viv"
        assert prompt == ""

    def test_viv_alias_with_question(self):
        matched, prompt = ActiveListeningEngine.extract_wakeword_and_prompt("Viv, what is the status of the build?")
        assert matched is not None
        assert matched.lower() == "viv"
        assert prompt == "what is the status of the build?"

    def test_vifi_alias(self):
        matched, prompt = ActiveListeningEngine.extract_wakeword_and_prompt("Hey ViFi, check the server logs")
        assert matched is not None
        assert matched.lower() == "hey vifi"
        assert prompt == "check the server logs"

    def test_antigravity_alias(self):
        matched, prompt = ActiveListeningEngine.extract_wakeword_and_prompt("Hey Antigravity review my pull request")
        assert matched is not None
        assert matched.lower() == "hey antigravity"
        assert prompt == "review my pull request"

    def test_non_wake_utterance(self):
        matched, prompt = ActiveListeningEngine.extract_wakeword_and_prompt("This is a normal sentence about python.")
        assert matched is None
        assert prompt == "This is a normal sentence about python."

    def test_empty_string(self):
        matched, prompt = ActiveListeningEngine.extract_wakeword_and_prompt("")
        assert matched is None
        assert prompt == ""

    def test_punctuated_whisper_variants(self):
        cases = [
            ("Hey, Viv.", "hey viv", ""),
            ("Hey, Viv", "hey viv", ""),
            ("Hey, Viv!", "hey viv", ""),
            ("Hey, Viv, check status", "hey viv", "check status"),
            ("Hey, Viv. What is the error?", "hey viv", "What is the error?"),
            ("Hey, ViFi.", "hey vifi", ""),
            ("Hey, Vive, run tests", "hey vive", "run tests"),
            ("Hey, Wi-Fi, explain this code", "hey wi-fi", "explain this code"),
            ("VoiceFi, create a meeting note", "voicefi", "create a meeting note"),
            ("Vi-Fi, track this action item", "vi-fi", "track this action item"),
            ("Hey VoiceFi, dispatch a test run", "hey voicefi", "dispatch a test run"),
            ("Hey Vi-Fi, file an issue", "hey vi-fi", "file an issue"),
            ("Voice Fi, summarize the standup", "voicefi", "summarize the standup"),
        ]
        for phrase, expected_match, expected_prompt in cases:
            matched, prompt = ActiveListeningEngine.extract_wakeword_and_prompt(phrase)
            assert matched is not None, f"Failed on: {phrase}"
            assert matched.lower() == expected_match
            assert prompt == expected_prompt

    def test_custom_user_alert_words_via_settings(self):
        # User adds custom alert words in settings
        custom_aliases = ["computer", "hey computer"]
        matched, prompt = ActiveListeningEngine.extract_wakeword_and_prompt(
            "Computer, file a Linear ticket on the audio latency",
            aliases=custom_aliases,
        )
        assert matched is not None
        assert matched.lower() == "computer"
        assert prompt == "file a Linear ticket on the audio latency"


class TestWakeWordConfig:
    """Tests for WakeWordConfig schema and defaults."""

    def test_default_wakeword_config(self):
        cfg = VoiceFiConfig()
        assert cfg.wakeword.enabled is True
        assert cfg.wakeword.phrase == "Hey Viv"
        assert "hey viv" in [a.lower() for a in cfg.wakeword.aliases]
        assert "viv" in [a.lower() for a in cfg.wakeword.aliases]
        assert "voicefi" in [a.lower() for a in cfg.wakeword.aliases]
        assert "vi-fi" in [a.lower() for a in cfg.wakeword.aliases]
        assert "VoiceFi" in cfg.wakeword.alert_words
        assert "Vi-Fi" in cfg.wakeword.alert_words
        assert "Viv" in cfg.wakeword.alert_words
        assert cfg.obsidian.meetings_folder == "Meetings"
        assert cfg.wakeword.chime is True
        assert cfg.wakeword.target_engine == "antigravity"

    def test_custom_wakeword_phrase_and_alert_words(self):
        custom_cfg = WakeWordConfig(
            phrase="VoiceFi",
            alert_words=["VoiceFi", "Vi-Fi", "Echo"],
            sensitivity=0.8,
        )
        assert custom_cfg.phrase == "VoiceFi"
        assert custom_cfg.sensitivity == 0.8
        assert "Echo" in custom_cfg.alert_words


class TestWakeWordListenerLifecycle:
    """Tests for starting, pausing, resuming, and stopping WakeWordListener."""

    def test_listener_instantiation_and_callbacks(self):
        events = []

        def on_wake(phrase, prompt):
            events.append((phrase, prompt))

        cfg = VoiceFiConfig()
        listener = WakeWordListener(config=cfg, on_wake=on_wake)
        assert listener._running is False
        assert listener._paused is False

        listener.pause()
        assert listener._paused is True

        listener.resume()
        assert listener._paused is False
