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

    def test_talk_now_wake_word_extraction(self):
        cases = [
            ("Talk now", "talk now", ""),
            ("talk now", "talk now", ""),
            ("Talk now.", "talk now", ""),
            ("Talk now!", "talk now", ""),
            ("Talk now, transcribe this document", "talk now", "transcribe this document"),
            ("talk now write a poem about rust", "talk now", "write a poem about rust"),
            ("Um, talk now, what's my status?", "talk now", "what's my status?"),
            ("Hey talk now, type this out", "talk now", "type this out"),
            ("tock now, let's start dictation", "talk now", "let's start dictation"),
        ]
        for phrase, expected_match, expected_prompt in cases:
            matched, prompt = ActiveListeningEngine.extract_wakeword_and_prompt(phrase)
            assert matched is not None, f"Failed on: {phrase}"
            assert matched.lower() == expected_match
            assert prompt == expected_prompt


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
        assert "talk now" in [a.lower() for a in cfg.wakeword.aliases]
        assert "VoiceFi" in cfg.wakeword.alert_words
        assert "Vi-Fi" in cfg.wakeword.alert_words
        assert "Viv" in cfg.wakeword.alert_words
        assert "Talk now" in cfg.wakeword.alert_words
        assert cfg.wakeword.talk_now_target == "dictate"
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

    def test_handoff_audio_buffer_consume(self):
        cfg = VoiceFiConfig()
        listener = WakeWordListener(config=cfg)
        import numpy as np

        sample = np.ones(1600, dtype=np.float32) * 0.1
        listener._last_handoff_audio = sample

        audio = listener.consume_handoff_audio()
        assert audio is not None
        assert len(audio) == 1600

        # Subsequent consume should be empty
        audio2 = listener.consume_handoff_audio()
        assert audio2 is None


class TestWakeWordUXEnhancements:
    """Tests for wake-word phonetic normalization, TopBarMicIndicatorPill, and turn detector false-start guard."""

    def test_hyphenated_and_filler_wakeword_variants(self):
        cases = [
            ("Hey anti-gravity, run the tests", "hey antigravity", "run the tests"),
            ("Um, hey Brok, what's on my screen?", "hey brok", "what's on my screen?"),
            ("Hey Paul, click the submit button", "hey pal", "click the submit button"),
            ("Okay, hey Viv, summarize this file", "hey viv", "summarize this file"),
        ]
        for phrase, expected_match, expected_prompt in cases:
            matched, prompt = ActiveListeningEngine.extract_wakeword_and_prompt(phrase)
            assert matched is not None, f"Failed on: {phrase}"
            assert matched.lower() == expected_match
            assert prompt == expected_prompt

    def test_top_bar_mic_indicator_pill_labels_and_lifecycle(self):
        from voicefi.ui.mic_pill import TopBarMicIndicatorPill

        assert TopBarMicIndicatorPill.resolve_display_label(app_name="VoiceFi", agent_name="VoiceFi", source="voicefi") == "VoiceFi"
        assert TopBarMicIndicatorPill.resolve_display_label(app_name="Brok (Live Mac)", agent_name="Brok", source="voicefi") == "Brok"
        assert TopBarMicIndicatorPill.resolve_display_label(app_name="Pal (Mac OS)", agent_name="Pal", source="voicefi") == "Pal"
        assert TopBarMicIndicatorPill.resolve_display_label(app_name="Antigravity", agent_name="Antigravity", source="antigravity") == "Antigravity"
        assert TopBarMicIndicatorPill.resolve_display_label(app_name="Claude Code", agent_name="Claude", source="claude") == "Claude"

        pill = TopBarMicIndicatorPill.get_instance()
        pill.show(state="listening", app_name="Brok (Live Mac)", agent_name="Brok", source="voicefi")
        assert pill._current_label == "Brok"
        assert pill._is_visible is False
        pill.update_audio_level(0.45)
        pill.hide()
        assert pill._is_visible is False

    def test_untranscribed_short_burst_does_not_trigger_premature_done(self):
        import numpy as np
        from voicefi.audio.turn_detector import CueTurnCascade

        cascade = CueTurnCascade(mode="auto", smart_turn_enabled=True)
        # 0.16s untranscribed burst (e.g. post-wakeword breath) even if SmartTurnONNX p_voice=0.99
        short_burst = np.zeros(int(16000 * 0.16), dtype=np.float32)
        assert CueTurnCascade.is_false_start(speech_duration_s=0.16, partial_text="", p_voice=0.99) is True
        res = cascade.evaluate_turn(audio=short_burst, partial_text="", baseline_silence_s=1.4)
        assert res.state != "DONE"
        assert res.wait_seconds >= 0.80

    def test_tray_handle_wakeword_trigger_routes_talk_now_to_dictate(self):
        from unittest.mock import MagicMock
        from voicefi.ui.tray import VoiceFiTrayApp

        app = MagicMock(spec=VoiceFiTrayApp)
        app.config = VoiceFiConfig()
        app.wakeword_listener = MagicMock()
        app.wakeword_listener.consume_handoff_audio.return_value = None
        app.watcher = None
        app.finish_active_recording = MagicMock()
        app.trigger_manual_listen = MagicMock()

        VoiceFiTrayApp._handle_wakeword_trigger(app, "talk now", "here is what I want to transcribe")
        app.trigger_manual_listen.assert_called_once_with(
            from_wakeword=True,
            wake_phrase="talk now",
            initial_prompt="here is what I want to transcribe",
            initial_audio=None,
        )

    def test_wakeword_viv_and_brok_normalize_display_label_to_voicefi(self):
        from unittest.mock import MagicMock
        from voicefi.ui.tray import VoiceFiTrayApp
        from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD

        app = MagicMock(spec=VoiceFiTrayApp)
        app.config = VoiceFiConfig()
        app.wakeword_listener = MagicMock()
        app.wakeword_listener.consume_handoff_audio.return_value = None
        app.watcher = None
        app._parse_channel_voice_intent.return_value = (None, None)
        app.finish_active_recording = MagicMock()
        app.trigger_talk_to_antigravity = MagicMock()

        VoiceFiTrayApp._handle_wakeword_trigger(app, "hey viv", "status check")
        app.trigger_talk_to_antigravity.assert_called_once_with(
            target_engine="antigravity",
            from_wakeword=True,
            wake_phrase="hey viv",
            initial_prompt="status check",
            initial_audio=None,
            display_app="VoiceFi",
        )

        hud = UnifiedDynamicIslandHUD.get_instance()
        hud.set_listening(
            user_name="Brok (Live Mac)",
            app_name="Brok (Live Mac)",
            agent_name="Brok Live",
            source="Wake Word ('hey brok')",
        )
        assert hud._active_app_name == "Brok"
        assert hud._active_agent_name == "Brok"
        assert hud._active_is_live is False
        hud.set_idle()

    def test_stop_speaking_now_cancels_active_recorder_and_hides_highlight(self):
        import threading
        from unittest.mock import MagicMock
        from voicefi.audio.recorder import AudioRecorder
        from voicefi.ui.screen_highlight import PalHighlightOverlay
        from voicefi.ui.tray import VoiceFiTrayApp

        recorder = AudioRecorder()
        assert recorder.cancelled is False
        recorder.cancel()
        assert recorder.cancelled is True

        overlay = PalHighlightOverlay.get_instance()
        overlay.show_screen_perimeter(color_type="voicefi", max_duration_s=5.0)
        assert overlay._want_visible is True

        app = MagicMock(spec=VoiceFiTrayApp)
        app.watcher = None
        app._current_status = "listening"
        app._ptt_stop_event = threading.Event()
        app.active_recorder = AudioRecorder()

        VoiceFiTrayApp.stop_speaking_now(app, None)
        assert app._recording_cancelled is True
        assert app.active_recorder.cancelled is True
        assert app._ptt_stop_event.is_set() is True
        assert overlay._want_visible is False

    def test_extract_wakeword_transcribe_and_tray_routing(self):
        from unittest.mock import MagicMock
        from voicefi.integrations.active_listening import ActiveListeningEngine
        from voicefi.ui.tray import VoiceFiTrayApp

        # Test extraction
        mw, prompt = ActiveListeningEngine.extract_wakeword_and_prompt("Transcribe this is a live test")
        assert mw == "transcribe"
        assert prompt == "this is a live test"

        mw2, prompt2 = ActiveListeningEngine.extract_wakeword_and_prompt("Transcribe.")
        assert mw2 == "transcribe"
        assert prompt2 == ""

        # Test tray routing
        app = MagicMock(spec=VoiceFiTrayApp)
        app.config = VoiceFiConfig()
        app.wakeword_listener = MagicMock()
        app.wakeword_listener.consume_handoff_audio.return_value = None
        app.watcher = None
        app.finish_active_recording = MagicMock()
        app.trigger_manual_listen = MagicMock()

        VoiceFiTrayApp._handle_wakeword_trigger(app, "transcribe", "send this into the window")
        app.trigger_manual_listen.assert_called_once_with(
            from_wakeword=True,
            wake_phrase="transcribe",
            initial_prompt="send this into the window",
            initial_audio=None,
        )

    def test_pal_channel_intents_and_brok_persona_separation(self):
        from unittest.mock import MagicMock, patch
        from voicefi.ui.tray import VoiceFiTrayApp

        app = MagicMock(spec=VoiceFiTrayApp)
        app.config = VoiceFiConfig()
        app._parse_channel_voice_intent = lambda txt: VoiceFiTrayApp._parse_channel_voice_intent(app, txt)

        assert app._parse_channel_voice_intent("take a note") == ("open_session", "")
        assert app._parse_channel_voice_intent("start a brain dump") == ("open_session", "")
        assert app._parse_channel_voice_intent(
            "take a note: we need to separate Brok and Pal into distinct personalities"
        ) == (
            "direct_channel",
            "we need to separate Brok and Pal into distinct personalities",
        )

        with patch("voicefi.integrations.pal_harness.PalHarness.execute_command") as mock_exec, patch(
            "voicefi.local.intent.LocalIntentRouter"
        ) as mock_router:
            mock_exec.return_value = MagicMock(
                success=True,
                action_type="smart_roast",
                spoken_summary="That tab layout is pure chaos.",
                should_speak=False,
            )
            hud = MagicMock()
            overlay = MagicMock()
            VoiceFiTrayApp._dispatch_pal_intent(
                app,
                "what do you think of this?",
                persona_tag="brok",
                label_tag="VoiceFi",
                hud=hud,
                overlay=overlay,
            )
            # Brok bypasses LocalIntentRouter so it stays 100% in its Grok-style persona
            mock_router.assert_not_called()
            mock_exec.assert_called_once_with("what do you think of this?", persona="brok")

    def test_hey_pal_fast_path_bypasses_recorder_when_prompt_present(self):
        """When prompt is already present from candidate STT, trigger_talk_to_pal executes instantly without recording delay."""
        import time
        import threading
        from unittest.mock import MagicMock, patch
        from voicefi.ui.tray import VoiceFiTrayApp

        app = MagicMock(spec=VoiceFiTrayApp)
        app.config = VoiceFiConfig()
        app._listen_lock = threading.Lock()
        app._current_status = "idle"
        app.active_recorder = None
        app.watcher = None
        app._dispatch_pal_intent = MagicMock()
        app.wakeword_listener = MagicMock()

        # Turn 1: Spoken command with prompt
        VoiceFiTrayApp.trigger_talk_to_pal(
            app,
            persona_tag="pal",
            from_wakeword=True,
            wake_phrase="hey pal",
            initial_prompt="open Chrome",
            is_streaming_prefix=False,
        )

        # Allow fast worker thread to execute
        time.sleep(0.05)
        app._dispatch_pal_intent.assert_called_once()
        args, kwargs = app._dispatch_pal_intent.call_args
        assert args[0] == "open Chrome"
        assert kwargs["persona_tag"] == "pal"
        assert kwargs["label_tag"] == "Pal"
        assert app.active_recorder is None

    def test_hey_pal_and_hey_brock_back_to_back_to_back(self):
        """Extensive QA: Three rapid back-to-back triggers (Hey Pal -> Hey Brock -> Hey Pal) succeed without drops or lockouts."""
        import time
        import threading
        from unittest.mock import MagicMock, patch
        from voicefi.ui.tray import VoiceFiTrayApp

        app = MagicMock(spec=VoiceFiTrayApp)
        app.config = VoiceFiConfig()
        app._listen_lock = threading.Lock()
        app._current_status = "idle"
        app.active_recorder = None
        app.watcher = None
        app._parse_channel_voice_intent.return_value = (None, None)
        app.trigger_talk_to_pal = lambda **kwargs: VoiceFiTrayApp.trigger_talk_to_pal(app, **kwargs)
        dispatched_turns = []

        def _mock_dispatch(cmd, persona_tag, label_tag, hud=None, overlay=None):
            dispatched_turns.append((persona_tag, label_tag, cmd))

        app._dispatch_pal_intent = _mock_dispatch
        app.wakeword_listener = MagicMock()

        # Turn 1: "Hey Pal, open Chrome"
        VoiceFiTrayApp._handle_wakeword_trigger(app, "hey pal", "open Chrome", is_streaming_prefix=False)
        time.sleep(0.06)

        # Turn 2: "Hey Brock, what's on my screen?" (rapid succession)
        VoiceFiTrayApp._handle_wakeword_trigger(app, "hey brok", "what's on my screen?", is_streaming_prefix=False)
        time.sleep(0.06)

        # Turn 3: "Hey Pal, mute" (back to back)
        VoiceFiTrayApp._handle_wakeword_trigger(app, "hey pal", "mute", is_streaming_prefix=False)
        time.sleep(0.06)

        assert len(dispatched_turns) == 3
        assert dispatched_turns[0] == ("pal", "Pal", "open Chrome")
        assert dispatched_turns[1] == ("brok", "Brok", "what's on my screen?")
        assert dispatched_turns[2] == ("pal", "Pal", "mute")

    def test_wakeword_listener_pause_resume_clears_stuck_signals(self):
        """Ensure pause() and resume() reset prefix signals so state never leaks across turns."""
        import numpy as np

        listener = WakeWordListener()
        listener._prefix_wake_signal = ("hey pal", "open", 12)
        listener._latest_pending_candidate = np.zeros(160, dtype=np.float32)

        listener.pause()
        assert listener._prefix_wake_signal is None
        assert listener._latest_pending_candidate is None

        listener._prefix_wake_signal = ("hey brok", "roast", 8)
        listener.resume()
        assert listener._prefix_wake_signal is None
        assert listener._latest_pending_candidate is None
        assert listener._prefix_check_inflight is False

    def test_phonetic_normalization_extensive_brock_and_pal(self):
        """Extensive phonetic normalization for Hey Brock, Hey Pal, and acoustic variants."""
        from voicefi.stt.biasing import PhoneticNormalizer

        cases = [
            ("hey brock open Chrome", "Hey Brok open Chrome"),
            ("hay brock what is on my screen", "Hey Brok what is on my screen"),
            ("hey brook roast this", "Hey Brok roast this"),
            ("hey grok test", "Hey Brok test"),
            ("brock what time is it", "Brok what time is it"),
            ("brook what time is it", "Brok what time is it"),
            ("paypal open GarageBand", "Hey Pal open GarageBand"),
            ("pay pal mute", "Hey Pal mute"),
            ("hey paul volume 50", "Hey Pal volume 50"),
            ("for a brock", "Hey Brok"),
            ("or a brock", "Hey Brok"),
            ("for a pal", "Hey Pal"),
            ("a brock", "Hey Brok"),
            ("hey rock", "Hey Brok"),
            ("hey barack roast screen", "Hey Brok roast screen"),
            ("paul mute", "Pal mute"),
            ("hey pow quiet", "Hey Pal quiet"),
        ]
        for inp, expected in cases:
            norm = PhoneticNormalizer.normalize(inp)
            assert norm == expected, f"Failed for '{inp}': got '{norm}', expected '{expected}'"

    def test_pal_brok_lifecycle_invariants_no_regression(self):
        """
        Regression lock for the 4 critical Pal/Brok UX & audio invariants:
        1. watcher.interrupt(notify_idle=False) must NOT overwrite _current_status='listening' back to 'idle'.
        2. Top-right menu bar _active_listen_label must be 'Brok' or 'Pal' (never 'VoiceFi').
        3. Screen perimeter highlight must remain visible during STT & _dispatch_pal_intent execution,
           only hiding when the turn finishes.
        """
        import threading
        from unittest.mock import MagicMock
        from voicefi.integrations.watcher import TranscriptWatcher
        from voicefi.ui.screen_highlight import PalHighlightOverlay
        from voicefi.ui.tray import VoiceFiTrayApp

        status_log = []
        watcher = TranscriptWatcher(on_state_change=lambda s, **kw: status_log.append(s))
        watcher.interrupt(notify_idle=False)
        assert "idle" not in status_log, "watcher.interrupt(notify_idle=False) must not emit 'idle'"

        overlay = PalHighlightOverlay.get_instance()
        overlay.hide()
        assert overlay._want_visible is False

        app = MagicMock(spec=VoiceFiTrayApp)
        app.config = VoiceFiConfig()
        app._listen_lock = threading.Lock()
        app._current_status = "idle"
        app.active_recorder = None
        app.watcher = watcher
        app.wakeword_listener = MagicMock()

        overlay_visible_during_dispatch = []

        def _fake_dispatch(cmd, persona_tag="pal", label_tag="Pal", hud=None, overlay=None):
            overlay_visible_during_dispatch.append(
                (persona_tag, label_tag, app._active_listen_label, bool(overlay and overlay._want_visible))
            )

        app._dispatch_pal_intent = _fake_dispatch

        VoiceFiTrayApp.trigger_talk_to_pal(
            app,
            persona_tag="brok",
            from_wakeword=True,
            wake_phrase="hey brok",
            initial_prompt="open Spotify",
            is_streaming_prefix=False,
        )
        import time

        time.sleep(0.08)
        assert len(overlay_visible_during_dispatch) == 1
        p_tag, l_tag, active_lbl, was_vis = overlay_visible_during_dispatch[0]
        assert p_tag == "brok"
        assert l_tag == "Brok"
        assert active_lbl == "Brok"
        assert was_vis is True, "Screen perimeter highlight must still be visible during _dispatch_pal_intent"
        assert overlay._want_visible is False, "Screen perimeter highlight must hide after _dispatch_pal_intent completes"


