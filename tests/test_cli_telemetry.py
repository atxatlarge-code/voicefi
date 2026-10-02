"""
Unit tests for Granular Zero-PII CLI telemetry in VoiceFi.
Validates PostHog instrumentation properties, voice_interaction events, crash hashes, and strict zero-PII guarantees.
"""

import argparse
import json
import os
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

from voicefi.cli import extract_cli_metadata, cmd_hook
from voicefi.telemetry import (
    sanitize_telemetry_data,
    get_telemetry_id,
    get_machine_id,
    is_telemetry_enabled,
    capture_voice_interaction,
    compute_traceback_hash,
    capture_event,
    set_active_command,
    check_and_record_first_spoken_turn,
    check_daily_active_retention,
    get_tier_properties,
    invalidate_tier_cache,
    capture_license_activated,
)



def test_extract_cli_metadata_universal_properties():
    """Verify standard command, subcommand, agent, voice, args, and flags extraction."""
    parser_args = argparse.Namespace(
        command="voice",
        voice_action="set",
        agent="antigravity",
        voice="Ava (Premium)",
        provider="apple_speech",
        quiet=True,
        dev=True,
    )
    props = extract_cli_metadata(parser_args)
    assert props["command"] == "voice"
    assert props["subcommand"] == "set"
    assert props["agent"] == "antigravity"
    assert props["voice"] == "Ava (Premium)"
    assert props["provider"] == "apple_speech"
    assert props["$is_server"] is True
    assert "--quiet" in props["args"]
    assert "--dev" in props["args"]
    assert "--quiet" in props["flags"]
    assert "--dev" in props["flags"]


def test_extract_cli_metadata_hud_properties():
    """Verify HUD actions, state enums, and boolean flags."""
    parser_args = argparse.Namespace(
        command="hud",
        hud_action="show",
        state="speaking",
        text="This should not be in props",
    )
    props = extract_cli_metadata(parser_args)
    assert props["command"] == "hud"
    assert props["subcommand"] == "show"
    assert props["hud_state"] == "speaking"
    assert "text" not in props


def test_extract_cli_metadata_zero_pii_guarantee():
    """Verify that user prompts, memo recordings, and raw text are never extracted."""
    parser_args = argparse.Namespace(
        command="speak",
        text=["Deploy", "to", "production", "server", "at", "192.168.1.1"],
        agent="claude",
        voice="Viv",
        prompt="Secret user prompt that must not leak",
        files=["/Users/alice/SecretProject/data.csv"],
    )
    props = extract_cli_metadata(parser_args)
    assert props["command"] == "speak"
    assert props["agent"] == "claude"
    assert props["voice"] == "Viv"
    assert "text" not in props
    assert "prompt" not in props
    assert "files" not in props


def test_sanitize_telemetry_data_drops_user_content_and_keys():
    """Verify sanitize_telemetry_data redacts paths, keys, and drops content fields."""
    raw_event = {
        "command": "hook",
        "subcommand": "Stop",
        "hook_agent": "antigravity",
        "sk_secret_key": "sk-1234567890abcdef1234567890",
        "prompt": "Fix the authentication vulnerability in auth.py",
        "raw_text": "Sensitive developer stream",
        "user_path": "/Users/john_doe/Projects/VoiceFi/test.py",
    }
    sanitized = sanitize_telemetry_data(raw_event)
    assert "sk_secret_key" not in sanitized
    assert "prompt" not in sanitized
    assert "raw_text" not in sanitized
    assert sanitized["command"] == "hook"
    assert sanitized["subcommand"] == "Stop"
    assert sanitized["hook_agent"] == "antigravity"
    assert sanitized["user_path"] == "~/Projects/VoiceFi/test.py"


def test_get_telemetry_id_persists(tmp_path):
    """Verify get_telemetry_id persists to ~/.voicefi/telemetry.json and reuses UUID."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    with patch("pathlib.Path.home", return_value=fake_home):
        tid1 = get_telemetry_id()
        assert tid1 is not None
        assert len(tid1) >= 32

        telemetry_file = fake_home / ".voicefi" / "telemetry.json"
        assert telemetry_file.is_file()
        stored = json.loads(telemetry_file.read_text())
        assert stored["id"] == tid1

        # Second call returns identical ID
        tid2 = get_telemetry_id()
        assert tid2 == tid1
        assert get_machine_id() == tid1


def test_telemetry_opt_out(monkeypatch):
    """Verify telemetry kill switch and opt-out environment variables."""
    monkeypatch.setenv("VOICEFI_TELEMETRY", "false")
    assert is_telemetry_enabled() is False

    monkeypatch.setenv("VOICEFI_TELEMETRY", "0")
    assert is_telemetry_enabled() is False

    monkeypatch.delenv("VOICEFI_TELEMETRY", raising=False)
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    assert is_telemetry_enabled() is False

    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    assert is_telemetry_enabled() is True


def test_capture_voice_interaction():
    """Verify capture_voice_interaction formats and dispatches zero-PII payload."""
    with patch("voicefi.telemetry.capture_event") as mock_capture:
        capture_voice_interaction(
            trigger="hook",
            duration_ms=450,
            success=True,
            agent="antigravity",
            voice="Ava (Premium)",
            provider="mac_say",
            chars_count=85,
            is_barge_in=True,
        )
        assert mock_capture.called
        event_name, props = mock_capture.call_args_list[0][0]
        assert event_name == "voice_interaction"
        assert props["trigger"] == "hook"
        assert props["duration_ms"] == 450
        assert props["success"] is True
        assert props["agent"] == "antigravity"
        assert props["voice"] == "Ava (Premium)"
        assert props["provider"] == "mac_say"
        assert props["chars_count"] == 85
        assert props["is_barge_in"] is True
        assert props["$is_server"] is True


def test_compute_traceback_hash():
    """Verify deterministic traceback hash computation."""
    tb = "Traceback (most recent call last):\n  File 'test.py', line 10, in <module>\nValueError: Test error"
    h1 = compute_traceback_hash(tb)
    h2 = compute_traceback_hash(tb)
    assert len(h1) == 16
    assert h1 == h2
    assert compute_traceback_hash("") == "empty"


def test_cmd_hook_telemetry_enrichment_server_forward():
    """Verify cmd_hook attaches ipc_forwarded=True when server handles the hook."""
    args = argparse.Namespace(
        command="hook",
        config=None,
        agent="antigravity",
    )
    with patch("voicefi.integrations.server_client.forward_hook_to_server") as mock_forward:
        mock_forward.return_value = {"status": "handled"}
        with patch("sys.stdin.isatty", return_value=True):
            cmd_hook(args)
            assert hasattr(args, "_telemetry_extra")
            assert args._telemetry_extra["hook_agent"] == "antigravity"
            assert args._telemetry_extra["ipc_forwarded"] is True


def test_cmd_hook_telemetry_enrichment_standalone():
    """Verify cmd_hook attaches ipc_forwarded=False when falling back to standalone."""
    args = argparse.Namespace(
        command="hook",
        config=None,
        agent="claude",
    )
    with patch("voicefi.integrations.server_client.forward_hook_to_server", return_value=None):
        with patch("voicefi.integrations.claude.handle_claude_stop_hook", return_value={}) as mock_claude:
            with patch("sys.stdin.isatty", return_value=True):
                cmd_hook(args)
                assert hasattr(args, "_telemetry_extra")
                assert args._telemetry_extra["hook_agent"] == "claude"
                assert args._telemetry_extra["ipc_forwarded"] is False
                assert mock_claude.called


def test_check_and_record_first_spoken_turn_idempotency(tmp_path):
    """Verify first_spoken_turn fires exactly once and creates marker file."""
    marker = tmp_path / ".voicefi" / ".first_turn_recorded"
    props = {"trigger": "hook", "agent": "antigravity", "voice": "Ava", "duration_ms": 150}

    with patch("voicefi.telemetry.Path.home", return_value=tmp_path):
        with patch("voicefi.telemetry.record_event") as mock_record:
            # First turn: should record milestone
            assert check_and_record_first_spoken_turn(props) is True
            assert marker.exists()
            mock_record.assert_called_once()
            assert mock_record.call_args[0][0] == "first_spoken_turn"
            assert mock_record.call_args[0][1]["milestone"] == "activation_first_turn"

        with patch("voicefi.telemetry.record_event") as mock_record2:
            # Second turn: should NOT record milestone
            assert check_and_record_first_spoken_turn(props) is False
            mock_record2.assert_not_called()


def test_check_daily_active_retention(tmp_path, monkeypatch):
    """Verify daily retention tracking computes days_since_install and handles Day-2+."""
    import voicefi.telemetry as tm
    monkeypatch.setenv("VOICEFI_TELEMETRY", "1")
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    monkeypatch.setattr("voicefi.telemetry.is_telemetry_enabled", lambda: True)

    tm._retention_checked_today = None
    retention_file = tmp_path / ".voicefi" / ".activity_dates.json"

    with patch("voicefi.telemetry.Path.home", return_value=tmp_path):
        with patch("voicefi.telemetry.record_event") as mock_record:
            # First day (Day 0)
            res = check_daily_active_retention()
            assert res is not None
            assert res["days_since_install"] == 0
            assert res["is_day_2_plus"] is False
            assert res["total_active_days"] == 1
            assert retention_file.exists()
            assert mock_record.call_args[0][0] == "daily_active_ping"

        # Same day: should return None (no dupes)
        with patch("voicefi.telemetry.record_event") as mock_record:
            res_same_day = check_daily_active_retention()
            assert res_same_day is None
            mock_record.assert_not_called()

        # Simulate subsequent day (Day 3)
        tm._retention_checked_today = None
        data = json.loads(retention_file.read_text())
        data["install_date"] = "2026-08-30"
        data["last_active_date"] = "2026-08-31"
        data["active_dates"] = ["2026-08-30", "2026-08-31"]
        retention_file.write_text(json.dumps(data))

        with patch("voicefi.telemetry.record_event") as mock_record:
            res_day_n = check_daily_active_retention()
            assert res_day_n is not None
            assert res_day_n["days_since_install"] >= 1
            assert res_day_n["is_day_2_plus"] is True
            assert res_day_n["total_active_days"] >= 2
            assert mock_record.call_args[0][0] == "daily_active_ping"


def test_get_tier_properties_and_caching():
    """Verify tier properties extraction and 30s TTL caching behavior."""
    from voicefi.telemetry import get_tier_properties, invalidate_tier_cache
    from voicefi.config import VoiceFiConfig
    invalidate_tier_cache()

    with patch("voicefi.telemetry.load_config") as mock_load:
        mock_cfg = VoiceFiConfig(tier="pro", license_key="VF1-PRO-PERP-TEST.SIG")
        mock_load.return_value = mock_cfg

        with patch("voicefi.license.FeatureGate.get_tier_summary") as mock_summary:
            mock_summary.return_value = {
                "tier": "Pro (Licensed · Perpetual)",
                "is_licensed": True,
                "is_pro": True,
                "is_trial": False,
                "license_info": {"tier": "pro"},
            }
            props = get_tier_properties()
            assert props["tier"] == "pro"
            assert props["is_licensed"] is True
            assert props["is_pro"] is True
            assert props["is_trial"] is False
            assert mock_summary.called

            # Call again: should hit cache
            mock_summary.reset_mock()
            props2 = get_tier_properties()
            assert props2["tier"] == "pro"
            assert not mock_summary.called

            # Invalidate cache
            invalidate_tier_cache()
            props3 = get_tier_properties()
            assert props3["tier"] == "pro"
            assert mock_summary.called


def test_feature_gate_activate_license_and_telemetry():
    """Verify FeatureGate.activate_license updates config and emits license_activated."""
    from voicefi.license import FeatureGate, generate_license_key
    from voicefi.config import VoiceFiConfig

    test_key = generate_license_key(
        tier="PRO",
        expires="PERP",
        tag="POLARTEST",
        private_key_hex="75517c236305fa2c92df89e5a10edd730baabe0f0e5e8333651633cd49f401ba",
    )
    cfg = VoiceFiConfig(tier="community")

    with patch("voicefi.telemetry.record_event") as mock_record:
        with patch("voicefi.config.save_config") as mock_save:
            res = FeatureGate.activate_license(test_key, config=cfg)
            assert res["success"] is True
            assert res["tier"] == "pro"
            assert res["tag"] == "POLARTEST"
            assert cfg.license_key == test_key
            assert cfg.tier == "pro"
            assert mock_save.called

            # Verify license_activated telemetry event
            mock_record.assert_called_once()
            call_event = mock_record.call_args[0][0]
            call_props = mock_record.call_args[0][1]
            assert call_event == "license_activated"
            assert call_props["tier"] == "pro"
            assert call_props["license_tag"] == "POLARTEST"
            assert call_props["success"] is True
            # Zero-PII check: raw key must never be in telemetry properties
            assert "license_key" not in call_props
            assert test_key not in str(call_props)


def test_feature_gate_activate_license_invalid_telemetry():
    """Verify invalid license key activation emits failed telemetry."""
    from voicefi.license import FeatureGate
    from voicefi.config import VoiceFiConfig

    cfg = VoiceFiConfig(tier="community")
    with patch("voicefi.telemetry.record_event") as mock_record:
        res = FeatureGate.activate_license("VF1-PRO-PERP-FAKE.invalid_signature", config=cfg)
        assert res["success"] is False
        assert cfg.tier == "community"

        mock_record.assert_called_once()
        call_event = mock_record.call_args[0][0]
        call_props = mock_record.call_args[0][1]
        assert call_event == "license_activated"
        assert call_props["success"] is False


def test_capture_exception_native_sdk(monkeypatch):
    """Verify capture_exception dispatches $exception with sanitized props and version metadata via PostHog SDK."""
    from voicefi.telemetry import capture_exception, flush_telemetry
    import voicefi.telemetry as tm

    monkeypatch.setenv("VOICEFI_TELEMETRY", "1")
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    monkeypatch.delenv("VOICEFI_TESTING", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("voicefi.telemetry.is_telemetry_enabled", lambda: True)

    mock_ph = MagicMock()
    monkeypatch.setattr(tm, "posthog", mock_ph)
    monkeypatch.setattr(tm, "_posthog_initialized", True)
    monkeypatch.setattr(tm, "_recent_exception_hashes", {})

    try:
        raise ValueError("Secret database failure in /Users/jake/app.py with key AIzaSyA12345678901234567890123456789012")
    except Exception as exc:
        res = capture_exception(
            exc,
            properties={"extra_info": "tts_failure", "user_key": "sk-1234567890abcdef1234567890"},
            command="speak",
        )
        assert res is True
        assert mock_ph.capture_exception.called
        call_args, call_kwargs = mock_ph.capture_exception.call_args
        assert call_args[0] == exc
        props = call_kwargs["properties"]
        assert props["command"] == "speak"
        assert props["extra_info"] == "tts_failure"
        assert "$app_version" in props
        assert "python_version" in props
        assert "user_key" not in props  # Zero-PII check
        assert not mock_ph.flush.called  # Non-blocking check: flush is NOT called mid-turn

        # Verify graceful flush on shutdown
        flush_telemetry()
        assert mock_ph.flush.called


def test_capture_exception_deduplication(monkeypatch):
    """Verify sliding-window deduplication throttles duplicate exceptions."""
    from voicefi.telemetry import capture_exception
    import voicefi.telemetry as tm

    monkeypatch.setenv("VOICEFI_TELEMETRY", "1")
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    monkeypatch.delenv("VOICEFI_TESTING", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("VOICEFI_TEST_SYNC", raising=False)
    monkeypatch.setattr("voicefi.telemetry.is_telemetry_enabled", lambda: True)

    mock_ph = MagicMock()
    monkeypatch.setattr(tm, "posthog", mock_ph)
    monkeypatch.setattr(tm, "_posthog_initialized", True)
    monkeypatch.setattr(tm, "_recent_exception_hashes", {})

    err = RuntimeError("Repeated audio underrun")
    # First call: dispatches
    assert capture_exception(err, properties={"component": "audio_out"}) is True
    assert mock_ph.capture_exception.call_count == 1

    # Immediate second call: throttled
    assert capture_exception(err, properties={"component": "audio_out"}) is True
    assert mock_ph.capture_exception.call_count == 1  # Not dispatched again


def test_capture_exception_https_fallback(monkeypatch):
    """Verify capture_exception dispatches $exception via direct HTTPS fallback when SDK missing."""
    from voicefi.telemetry import capture_exception
    import voicefi.telemetry as tm

    monkeypatch.setenv("VOICEFI_TELEMETRY", "1")
    monkeypatch.setenv("VOICEFI_TEST_SYNC", "1")
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    monkeypatch.delenv("VOICEFI_TESTING", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("voicefi.telemetry.is_telemetry_enabled", lambda: True)
    monkeypatch.setattr(tm, "posthog", None)
    monkeypatch.setattr(tm, "_posthog_initialized", False)
    monkeypatch.setattr(tm, "_recent_exception_hashes", {})

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = MagicMock()
        try:
            raise RuntimeError("Audio device underrun")
        except Exception as exc:
            res = capture_exception(exc, properties={"component": "audio_out"})
            assert res is True
            assert mock_urlopen.called
            req = mock_urlopen.call_args[0][0]
            payload = json.loads(req.data.decode("utf-8"))
            assert payload["event"] == "$exception"
            assert payload["properties"]["$exception_type"] == "RuntimeError"
            assert payload["properties"]["$exception_message"] == "Audio device underrun"
            assert payload["properties"]["component"] == "audio_out"
            assert "$exception_stack_trace_raw" in payload["properties"]
            assert "$app_version" in payload["properties"]


def test_init_telemetry_supports_posthog_project_token(monkeypatch):
    """Verify init_telemetry picks up POSTHOG_PROJECT_TOKEN from environment and sets sync_mode=False."""
    from voicefi.telemetry import init_telemetry
    import voicefi.telemetry as tm

    monkeypatch.delenv("POSTHOG_API_KEY", raising=False)
    monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_token_12345")
    monkeypatch.delenv("VOICEFI_TESTING", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("voicefi.telemetry.is_telemetry_enabled", lambda: True)

    mock_ph = MagicMock()
    monkeypatch.setattr(tm, "posthog", mock_ph)
    monkeypatch.setattr(tm, "_posthog_initialized", False)

    init_telemetry()
    assert mock_ph.project_api_key == "phc_token_12345"
    assert mock_ph.sync_mode is False
    assert mock_ph.enable_exception_autocapture is True


def test_is_offline_mode_enforcement(monkeypatch):
    """Verify is_offline_mode detects VOICEFI_OFFLINE, VOICEFI_AIRGAP, and cfg.offline."""
    from voicefi.telemetry import is_offline_mode, is_telemetry_enabled, capture_exception, capture_event
    import voicefi.telemetry as tm

    monkeypatch.delenv("VOICEFI_OFFLINE", raising=False)
    monkeypatch.delenv("VOICEFI_AIRGAP", raising=False)
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    monkeypatch.setenv("VOICEFI_TELEMETRY", "1")

    # Clean state
    assert is_offline_mode() is False
    assert is_telemetry_enabled() is True

    # VOICEFI_OFFLINE=1
    monkeypatch.setenv("VOICEFI_OFFLINE", "1")
    assert is_offline_mode() is True
    assert is_telemetry_enabled() is False

    mock_ph = MagicMock()
    monkeypatch.setattr(tm, "posthog", mock_ph)
    monkeypatch.setattr(tm, "_posthog_initialized", True)

    assert capture_exception(RuntimeError("Offline test")) is False
    assert mock_ph.capture_exception.called is False

    capture_event("test_event", {"some": "data"})
    assert mock_ph.capture.called is False

    # VOICEFI_AIRGAP=true
    monkeypatch.delenv("VOICEFI_OFFLINE", raising=False)
    monkeypatch.setenv("VOICEFI_AIRGAP", "true")
    assert is_offline_mode() is True
    assert is_telemetry_enabled() is False


def test_capture_exception_cross_component_deduplication(monkeypatch):
    """Verify exceptions in different components with the same message are NOT erroneously deduplicated."""
    from voicefi.telemetry import capture_exception
    import voicefi.telemetry as tm

    monkeypatch.setenv("VOICEFI_TELEMETRY", "1")
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    monkeypatch.delenv("VOICEFI_OFFLINE", raising=False)
    monkeypatch.delenv("VOICEFI_AIRGAP", raising=False)
    monkeypatch.delenv("VOICEFI_TESTING", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("VOICEFI_TEST_SYNC", raising=False)
    monkeypatch.setattr("voicefi.telemetry.is_telemetry_enabled", lambda: True)

    mock_ph = MagicMock()
    monkeypatch.setattr(tm, "posthog", mock_ph)
    monkeypatch.setattr(tm, "_posthog_initialized", True)
    monkeypatch.setattr(tm, "_recent_exception_hashes", {})

    err = TimeoutError("Connection timed out after 10s")

    # 1. Component 'tts.edge'
    res1 = capture_exception(err, properties={"component": "tts.edge"})
    assert res1 is True
    assert mock_ph.capture_exception.call_count == 1
    call_props1 = mock_ph.capture_exception.call_args[1]["properties"]
    assert call_props1["component"] == "tts.edge"
    assert call_props1["$exception_fingerprint"][0] == "tts.edge"

    # 2. Component 'stt.groq' with IDENTICAL error message - must NOT be throttled!
    res2 = capture_exception(err, properties={"component": "stt.groq"})
    assert res2 is True
    assert mock_ph.capture_exception.call_count == 2
    call_props2 = mock_ph.capture_exception.call_args[1]["properties"]
    assert call_props2["component"] == "stt.groq"
    assert call_props2["$exception_fingerprint"][0] == "stt.groq"

    # 3. Third call for same 'stt.groq' - SHOULD be throttled
    res3 = capture_exception(err, properties={"component": "stt.groq"})
    assert res3 is True
    assert mock_ph.capture_exception.call_count == 2






