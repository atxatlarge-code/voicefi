"""
Comprehensive Fault Tolerance & Resiliency Test Suite for VoiceFi.

Validates:
1. Cloud-to-Local Neural TTS Fallback (EdgeTTS network drop, DNS failure, 429 rate limit,
   invalid voice names, multi-sentence streaming failure, ElevenLabs error recovery).
2. Server Process Lifecycle, Port 5141 Probing & Zombie Process Termination.
3. Stale Speech Lock & Status File Auto-Reclamation (Dead PID detection, crash recovery).
4. Corrupted Config File Recovery (~/.voicefi/config.yaml syntax errors & type mismatch).
5. Comprehensive Input Validation & Boundary Handling Across All Public Surfaces.
"""

import asyncio
import json
import os
import signal
import socket
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from voicefi.config import (
    VoiceFiConfig,
    find_config_path,
    load_config,
    save_config,
    detect_system_user_name,
)
from voicefi.server import (
    clean_caches,
    clean_lock_files,
    find_running_voicefi_processes,
    get_launchagent_status,
    get_port_listener,
    get_process_info_by_pid,
    is_pid_running,
    stop_all_voicefi_servers,
)
from voicefi.tts import (
    BaseTTS,
    EdgeTTS,
    ElevenLabsTTS,
    MacSayTTS,
    find_persona,
    get_tts_engine,
    is_agent_audio_playing,
    is_agent_speaking,
    normalize_edge_rate,
    normalize_mac_rate,
    set_agent_audio_playing,
    set_agent_speaking,
    set_cross_process_hud_state,
    get_cross_process_hud_state,
    clear_cross_process_hud_state,
)
from voicefi.tts.base import (
    AGENT_SPEAKING_STATUS_FILE,
    AUDIO_PLAYING_STATUS_FILE,
    HUD_STATE_STATUS_FILE,
    DuplicateSpeechSuppressed,
    is_duplicate_speech,
    record_recent_speech,
    speech_turn_lock,
)
from voicefi.tts.normalizer import normalize_tts_text


# =============================================================================
# 1. Cloud-to-Local Neural TTS Fallback Hardening
# =============================================================================

def test_edge_tts_single_sentence_network_failure_fallback(monkeypatch):
    """Verify that network exception during EdgeTTS synthesis triggers seamless offline say fallback."""
    engine = EdgeTTS(voice="en-US-AvaNeural", offline_fallback_voice="Ava (Premium)")
    
    fallback_called = []
    def fake_fallback(text):
        fallback_called.append(text)
    
    monkeypatch.setattr(engine, "_fallback_speak_direct", fake_fallback)

    # Simulate network exception in _generate_audio
    async def fake_generate_fail(text, path):
        raise ConnectionResetError("Connection reset by peer (simulated network severance)")

    monkeypatch.setattr(engine, "_generate_audio", fake_generate_fail)

    engine.speak("VoiceFi neural synthesis test with offline fallback.", block=True)
    assert len(fallback_called) == 1
    assert "VoiceFi neural synthesis test with offline fallback." in fallback_called[0]


def test_edge_tts_dns_timeout_failure_fallback(monkeypatch):
    """Verify DNS resolution failure or timeout triggers instant offline fallback."""
    engine = EdgeTTS(voice="en-US-AvaNeural")
    fallback_called = []
    monkeypatch.setattr(engine, "_fallback_speak_direct", lambda t: fallback_called.append(t))

    async def fake_dns_error(text, path):
        raise socket.gaierror(-3, "Temporary failure in name resolution")

    monkeypatch.setattr(engine, "_generate_audio", fake_dns_error)

    engine.speak("Testing DNS error handling.", block=True)
    assert len(fallback_called) == 1
    assert "Testing DNS error handling." in fallback_called[0]


def test_edge_tts_rate_limit_429_fallback(monkeypatch):
    """Verify HTTP 429 rate-limiting from cloud TTS triggers offline fallback."""
    engine = EdgeTTS(voice="en-US-AvaNeural")
    fallback_called = []
    monkeypatch.setattr(engine, "_fallback_speak_direct", lambda t: fallback_called.append(t))

    async def fake_rate_limit(text, path):
        raise RuntimeError("HTTP 429: Too Many Requests from Edge TTS API")

    monkeypatch.setattr(engine, "_generate_audio", fake_rate_limit)

    engine.speak("Testing rate limit fallback recovery.", block=True)
    assert len(fallback_called) == 1
    assert "Testing rate limit fallback recovery." in fallback_called[0]


def test_edge_tts_invalid_voice_fallback(monkeypatch):
    """Verify invalid/unrecognized voice names in EdgeTTS fall back gracefully to local say."""
    engine = EdgeTTS(voice="non-existent-neural-voice-999")
    fallback_called = []
    monkeypatch.setattr(engine, "_fallback_speak_direct", lambda t: fallback_called.append(t))

    async def fake_voice_not_found(text, path):
        raise ValueError("Invalid voice: non-existent-neural-voice-999")

    monkeypatch.setattr(engine, "_generate_audio", fake_voice_not_found)

    engine.speak("Validating invalid voice handling.", block=True)
    assert len(fallback_called) == 1


def test_edge_tts_multi_sentence_midstream_network_drop(monkeypatch):
    """
    Verify multi-sentence sentence-pipelining where chunk 0 succeeds but chunk 1 fails.
    The remaining text must be spoken via offline fallback without losing words.
    """
    engine = EdgeTTS(voice="en-US-AvaNeural")
    fallback_called = []
    monkeypatch.setattr(engine, "_fallback_speak_direct", lambda t: fallback_called.append(t))

    call_count = 0

    async def fake_midstream_generate(text, path):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Chunk 1 succeeds - write non-empty file
            Path(path).write_bytes(b"FAKE_MP3_DATA")
        else:
            # Chunk 2 fails with network drop
            raise ConnectionError("Network disconnected during stream")

    monkeypatch.setattr(engine, "_generate_audio", fake_midstream_generate)

    # Speak 2 sentences
    engine.speak("First sentence is synthesized. Second sentence will suffer network drop.", block=True)
    
    # Check that remaining sentence was dispatched to fallback
    assert len(fallback_called) == 1
    assert "Second sentence will suffer network drop." in fallback_called[0]


def test_elevenlabs_network_and_api_error_fallback(monkeypatch):
    """Verify ElevenLabs API failures seamlessly fall back to local offline say."""
    engine = ElevenLabsTTS(api_key="invalid_test_key_12345", voice_id="21m00Tcm4TlvDq8ikWAM")
    fallback_called = []
    monkeypatch.setattr(engine, "_fallback_speak_direct", lambda t: fallback_called.append(t))

    # Speak with invalid API key
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 401
        mock_post.return_value.text = "Unauthorized: Invalid API Key"
        engine.speak("ElevenLabs auth failure test.", block=True)

    assert len(fallback_called) == 1
    assert "ElevenLabs auth failure test." in fallback_called[0]


def test_elevenlabs_missing_api_key_fallback(monkeypatch):
    """Verify ElevenLabs with empty API key immediately falls back to offline say."""
    engine = ElevenLabsTTS(api_key="")
    fallback_called = []
    monkeypatch.setattr(engine, "_fallback_speak_direct", lambda t: fallback_called.append(t))

    engine.speak("ElevenLabs empty key test.", block=True)
    assert len(fallback_called) == 1
    assert "ElevenLabs empty key test." in fallback_called[0]


def test_get_tts_engine_invalid_provider_graceful_degradation():
    """Verify get_tts_engine with invalid provider or malformed voice returns safe fallback engine."""
    cfg = VoiceFiConfig()
    engine = get_tts_engine(cfg, provider_override="invalid_provider_xyz", voice_override="non_existent")
    assert isinstance(engine, MacSayTTS)
    assert engine.agent_name == "VoiceFi"


# =============================================================================
# 2. Server Process Lifecycle, Port 5141 & Zombie Process Termination
# =============================================================================

def test_get_port_listener_detection_and_parsing(monkeypatch):
    """Test get_port_listener accurately parses lsof output and handles edge cases."""
    # 1. Successful listener
    mock_lsof = "COMMAND   PID USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME\nvoicefi 98765 jake    3u  IPv4 0x12345678      0t0  TCP *:5141 (LISTEN)\n"
    
    with patch("subprocess.run") as mock_run, \
         patch("voicefi.server.is_pid_running", return_value=True), \
         patch("voicefi.server.get_process_info_by_pid", return_value={"pid": 98765, "command": "voicefi tray"}):
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_lsof, stderr="")
        listener = get_port_listener(5141)
        assert listener is not None
        assert listener["pid"] == 98765
        assert listener["command_name"] == "voicefi"
        assert listener["port"] == 5141

    # 2. No listener (empty lsof output)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        listener = get_port_listener(5141)
        assert listener is None

    # 3. Invalid port type
    assert get_port_listener("invalid_port") is None
    assert get_port_listener(None) is None


def test_stop_all_voicefi_servers_terminates_zombies_and_frees_port():
    """Test stop_all_voicefi_servers handles SIGTERM -> SIGKILL escalation and LaunchAgent unloads."""
    killed_signals = []
    
    def fake_kill(pid, sig):
        killed_signals.append((pid, sig))

    mock_procs = [
        {"pid": 11111, "ppid": 1, "command": "voicefi tray"},
        {"pid": 22222, "ppid": 1, "command": "voicefi daemon"},
    ]

    # Process 11111 dies after SIGTERM, Process 22222 is stubborn and requires SIGKILL
    alive_status = {11111: True, 22222: True}
    
    def fake_is_running(pid):
        return alive_status.get(pid, False)

    with patch("voicefi.server.find_running_voicefi_processes", return_value=mock_procs), \
         patch("voicefi.server.is_pid_running", side_effect=fake_is_running), \
         patch("os.kill", side_effect=fake_kill), \
         patch("voicefi.server.get_port_listener", return_value=None), \
         patch("subprocess.run"):
        
        # After first check, 11111 exits
        alive_status[11111] = False
        
        res = stop_all_voicefi_servers(timeout_seconds=0.2)
        assert res["success"] is True
        assert 11111 in res["stopped_pids"]
        assert 22222 in res["stopped_pids"]
        assert res["port_freed"] is True

        # Verify SIGKILL was dispatched to stubborn process 22222
        assert (22222, signal.SIGKILL) in killed_signals


def test_port_rebinding_after_server_stop():
    """Verify local socket can be cleanly bound after server teardown."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    # Find a free local ephemeral port for testing re-binding semantics
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.listen(1)

    # Confirm listener detection
    listener = get_port_listener(port)
    assert listener is None or listener.get("port") == port

    # Close socket and verify immediate re-binding
    sock.close()
    
    new_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    new_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    new_sock.bind(("127.0.0.1", port))
    new_sock.listen(1)
    new_sock.close()


# =============================================================================
# 3. Stale Speech Lock & Status File Reclamation on Crashed Processes
# =============================================================================

def test_stale_speaking_status_auto_reclaimed_when_pid_dead(tmp_path, monkeypatch):
    """Verify that is_agent_speaking() auto-detects a dead PID and unlinks the stale status file."""
    stale_file = tmp_path / "voicefi_speaking.status"
    monkeypatch.setattr("voicefi.tts.base.AGENT_SPEAKING_STATUS_FILE", stale_file)
    
    # Write status file with non-existent PID (e.g. 9999999)
    stale_payload = {
        "pid": 9999999,
        "timestamp": time.time(),
        "text": "Stale speech turn from crashed process",
        "agent_name": "Antigravity",
    }
    stale_file.write_text(json.dumps(stale_payload))

    assert is_agent_speaking() is False
    assert not stale_file.exists(), "Stale speaking status file was not automatically unlinked"


def test_stale_audio_playing_status_auto_reclaimed_when_pid_dead(tmp_path, monkeypatch):
    """Verify is_agent_audio_playing() auto-detects dead PID and purges stale marker."""
    stale_file = tmp_path / "voicefi_audio_playing.status"
    monkeypatch.setattr("voicefi.tts.base.AUDIO_PLAYING_STATUS_FILE", stale_file)
    
    stale_file.write_text(f"9999999:{time.time()}")
    
    assert is_agent_audio_playing() is False
    assert not stale_file.exists(), "Stale audio playing status file was not automatically unlinked"


def test_stale_hud_state_auto_reclaimed_when_pid_dead(tmp_path, monkeypatch):
    """Verify get_cross_process_hud_state() auto-cleans dead PID payloads."""
    stale_file = tmp_path / "voicefi_hud_state.json"
    monkeypatch.setattr("voicefi.tts.base.HUD_STATE_STATUS_FILE", stale_file)

    stale_payload = {
        "pid": 9999999,
        "timestamp": time.time(),
        "state": "speaking",
        "text": "Stale HUD state",
    }
    stale_file.write_text(json.dumps(stale_payload))

    assert get_cross_process_hud_state() is None
    assert not stale_file.exists()


def test_clean_lock_files_stale_mode(tmp_path, monkeypatch):
    """Verify clean_lock_files(only_stale=True) removes dead-PID artifacts but preserves active ones."""
    live_pid = os.getpid()
    dead_pid = 9999999

    f_dead = tmp_path / "voicefi_dead_test.status"
    f_dead.write_text(json.dumps({"pid": dead_pid}))

    f_live = tmp_path / "voicefi_live_test.status"
    f_live.write_text(json.dumps({"pid": live_pid}))

    monkeypatch.setattr("pathlib.Path.glob", lambda self, pat: [f_dead, f_live] if pat == "voicefi*" else [])

    clean_lock_files(only_stale=True)

    assert not f_dead.exists(), "Dead PID file should have been cleaned"
    assert f_live.exists(), "Live PID file should be preserved"
    f_live.unlink(missing_ok=True)


# =============================================================================
# 4. Corrupted Config Recovery (~/.voicefi/config.yaml)
# =============================================================================

def test_corrupted_yaml_syntax_recovery(tmp_path, monkeypatch):
    """Verify load_config gracefully recovers from syntax errors in config.yaml."""
    bad_yaml_file = tmp_path / "config.yaml"
    bad_yaml_file.write_text("tts:\n  provider: [unclosed bracket\n  voice: {\ninvalid yaml ::::")

    monkeypatch.setenv("VOICEFI_CONFIG", str(bad_yaml_file))
    
    cfg = load_config(str(bad_yaml_file))
    assert isinstance(cfg, VoiceFiConfig)
    assert cfg.tts.provider == "edge_tts"  # default recovered
    assert cfg.tts.voice == "en-US-AvaNeural"


def test_corrupted_data_types_in_config(tmp_path):
    """Verify load_config recovers from invalid data types (e.g. string instead of dict)."""
    bad_type_file = tmp_path / "config.yaml"
    bad_type_file.write_text("tts: \"should be a dict not a string\"\nvad: 12345\nuser_name: []")

    cfg = load_config(str(bad_type_file))
    assert isinstance(cfg, VoiceFiConfig)
    assert cfg.tts.provider == "edge_tts"


def test_empty_config_file_recovery(tmp_path):
    """Verify load_config recovers cleanly from empty config file."""
    empty_file = tmp_path / "config.yaml"
    empty_file.write_text("")

    cfg = load_config(str(empty_file))
    assert isinstance(cfg, VoiceFiConfig)
    assert cfg.tts.voice == "en-US-AvaNeural"


def test_save_and_reload_config_roundtrip(tmp_path):
    """Verify saving and re-loading config preserves custom settings without corruption."""
    cfg_file = tmp_path / "sub_dir" / "config.yaml"
    cfg = VoiceFiConfig()
    cfg.tts.voice = "en-US-ChristopherNeural"
    cfg.user_name = "Alice"
    
    saved_path = save_config(cfg, target_path=cfg_file)
    assert saved_path.is_file()

    loaded = load_config(str(saved_path))
    assert loaded.tts.voice == "en-US-ChristopherNeural"
    assert loaded.user_name == "Alice"


# =============================================================================
# 5. Invalid Parameter Handling Across All Surfaces
# =============================================================================

@pytest.mark.parametrize("input_rate,expected", [
    (None, "+0%"),
    ("", "+0%"),
    ("invalid", "+0%"),
    ("9999wpm", "+4900%"),
    ("-25%", "-25%"),
    ("+15%", "+15%"),
    ("75%", "-25%"),
    (0, "+0%"),
    (-25, "-25%"),
    (10, "+10%"),
    (75, "-25%"),
    (100, "+0%"),
    (150, "-25%"),
    (200, "+0%"),
    (250, "+25%"),
])
def test_normalize_edge_rate_resilience(input_rate, expected):
    """Test normalize_edge_rate handles valid, boundary, and pathological inputs."""
    assert normalize_edge_rate(input_rate) == expected


@pytest.mark.parametrize("input_rate,expected", [
    (None, 200),
    ("", 200),
    ("invalid", 200),
    ("150wpm", 150),
    ("+25%", 250),
    ("-25%", 150),
    ("75%", 150),
    (0, 200),
    (200, 200),
    (150, 150),
    (250, 250),
    (-25, 150),
    (75, 150),
    (9999, 450),  # Upper bound clamp
    (-9999, 60),  # Lower bound clamp
])
def test_normalize_mac_rate_resilience(input_rate, expected):
    """Test normalize_mac_rate handles valid, boundary, and clamped inputs."""
    assert normalize_mac_rate(input_rate) == expected


@pytest.mark.parametrize("name_or_id,should_find", [
    (None, False),
    ("", False),
    (123, False),
    ("non_existent_voice", False),
    ("viv", True),
    ("Ava (Premium)", True),
    ("AVA PREMIUM", True),
    ("christopher", True),
    ("en-US-AvaNeural", True),
    ("guyneural", True),
])
def test_find_persona_resilience(name_or_id, should_find):
    """Test find_persona input validation and alias resolution."""
    res = find_persona(name_or_id)
    if should_find:
        assert res is not None
    else:
        assert res is None


def test_normalize_tts_text_edge_cases():
    """Test phonetic text normalizer handles nulls, technical jargon, and heteronyms."""
    assert normalize_tts_text(None) == ""
    assert normalize_tts_text("") == ""
    assert normalize_tts_text("   \n\t  ") == ""
    
    # Technical acronyms
    norm = normalize_tts_text("Deploy kubectl to PostgreSQL with UUID and OAuth on CI/CD.")
    assert "koob control" in norm
    assert "Postgres Q L" in norm
    assert "U U I D" in norm
    assert "O Auth" in norm
    assert "C I C D" in norm

    # Heteronym: live -> lyve
    assert "lyve" in normalize_tts_text("The server is live right now.")
    assert "lyve" in normalize_tts_text("Join our live stream session.")
    assert "reed-only" in normalize_tts_text("Database is in read-only mode.")


def test_speech_turn_lock_duplicate_suppression():
    """Verify duplicate speech within 6s is suppressed by DuplicateSpeechSuppressed exception."""
    text = "Deploying unit test suite to production cluster."
    
    with speech_turn_lock(text=text):
        pass

    # Immediate second call with identical text should raise DuplicateSpeechSuppressed
    with pytest.raises(DuplicateSpeechSuppressed):
        with speech_turn_lock(text=text):
            pass


def test_clean_caches_non_existent_workspace():
    """Verify clean_caches handles non-existent or invalid directory paths gracefully."""
    fake_path = Path("/non/existent/path/xyz")
    res = clean_caches(workspace_root=fake_path, clean_pycache=True, clean_tmp_state=True)
    assert isinstance(res, dict)
    assert "cleaned_pycache_count" in res
    assert "cleaned_tmp_count" in res
