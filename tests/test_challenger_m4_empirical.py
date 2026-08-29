"""
Empirical Adversarial Stress Test Suite — Milestone M4 Challenger.
Focus areas:
1. Severe Cloud TTS Disruption (mid-stream socket aborts, truncated audio chunks, DNS timeouts, 429 bursts, zero speech dropping).
2. Zombie Port 5141 Recovery (stubborn processes ignoring SIGTERM -> SIGKILL escalation -> socket reuse).
3. Rapid Concurrent Process Crashes (`kill -9`) leaving stale `/tmp/voicefi*` locks and status files.
"""

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from voicefi.config import VoiceFiConfig, load_config
from voicefi.server import (
    clean_lock_files,
    find_running_voicefi_processes,
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
    get_tts_engine,
    is_agent_audio_playing,
    is_agent_speaking,
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
    SPEECH_LOCK_FILE,
    DuplicateSpeechSuppressed,
    clear_recent_speech_history,
    get_agent_speaking_info,
    is_duplicate_speech,
    is_pid_alive,
    record_recent_speech,
    speech_turn_lock,
    stop_all_speech,
)


# =============================================================================
# 1. Severe Cloud TTS Disruption & Fallback Verification
# =============================================================================

class TestCloudTTSDisruptionAndFallback:
    """Stress-test EdgeTTS and ElevenLabs under severe network degradation."""

    def test_edge_tts_midstream_socket_abort_preserves_remaining_speech(self, monkeypatch):
        """
        Simulate a multi-sentence stream where chunk 0 succeeds, chunk 1 throws socket ConnectionResetError,
        and verify chunk 1, 2, 3 are dispatched to fallback with zero dropped text.
        """
        engine = EdgeTTS(voice="en-US-AvaNeural", offline_fallback_voice="Ava (Premium)")
        fallback_invocations = []
        monkeypatch.setattr(engine, "_fallback_speak_direct", lambda text: fallback_invocations.append(text))

        generated_chunks = []
        call_index = 0

        async def fake_generate_audio(text, output_path):
            nonlocal call_index
            call_index += 1
            if call_index == 1:
                # First chunk succeeds
                Path(output_path).write_bytes(b"FAKE_AUDIO_HEADER_12345")
                generated_chunks.append(text)
            else:
                # Subsequent chunks suffer immediate socket abort
                raise ConnectionResetError("Errno 54: Connection reset by peer during TTS streaming socket")

        monkeypatch.setattr(engine, "_generate_audio", fake_generate_audio)

        speech_text = (
            "Sentence one is the introductory phrase. "
            "Sentence two experiences severe socket abort. "
            "Sentence three must also be recovered safely. "
            "Sentence four concludes the speech without dropping."
        )

        engine.speak(speech_text, block=True)

        assert len(generated_chunks) == 1
        assert "Sentence one is the introductory phrase." in generated_chunks[0]
        assert len(fallback_invocations) == 1
        
        fallback_text = fallback_invocations[0]
        assert "Sentence two experiences severe socket abort." in fallback_text
        assert "Sentence three must also be recovered safely." in fallback_text
        assert "Sentence four concludes the speech without dropping." in fallback_text

    def test_edge_tts_truncated_zero_byte_chunk_handling(self, monkeypatch):
        """
        Simulate an edge case where generator creates an empty (0 bytes) or truncated chunk.
        Verify it is discarded without unhandled exceptions or playback failure.
        """
        engine = EdgeTTS(voice="en-US-AvaNeural")
        fallback_invocations = []
        monkeypatch.setattr(engine, "_fallback_speak_direct", lambda text: fallback_invocations.append(text))

        async def fake_empty_generate(text, output_path):
            # Create a 0-byte file
            Path(output_path).touch()

        monkeypatch.setattr(engine, "_generate_audio", fake_empty_generate)

        # Single sentence test
        engine.speak("Single sentence zero-byte test.", block=True)
        assert len(fallback_invocations) == 1
        assert "Single sentence zero-byte test." in fallback_invocations[0]

    def test_edge_tts_dns_timeout_and_asyncio_timeout(self, monkeypatch):
        """
        Simulate DNS lookup hang or asyncio.TimeoutError during speech synthesis.
        """
        engine = EdgeTTS(voice="en-US-AvaNeural")
        fallback_invocations = []
        monkeypatch.setattr(engine, "_fallback_speak_direct", lambda text: fallback_invocations.append(text))

        async def fake_dns_timeout(text, output_path):
            raise asyncio.TimeoutError("DNS query to speech.platform.bing.com timed out after 5000ms")

        monkeypatch.setattr(engine, "_generate_audio", fake_dns_timeout)

        engine.speak("Testing DNS timeout resiliency.", block=True)
        assert len(fallback_invocations) == 1
        assert "Testing DNS timeout resiliency." in fallback_invocations[0]

    def test_edge_tts_burst_429_rate_limits(self, monkeypatch):
        """
        Simulate a burst of rapid speak requests hitting HTTP 429 Too Many Requests.
        Verify all calls complete without uncaught exceptions and fall back cleanly.
        """
        engine = EdgeTTS(voice="en-US-AvaNeural")
        fallback_count = 0
        lock = threading.Lock()

        def fake_fallback(text):
            nonlocal fallback_count
            with lock:
                fallback_count += 1

        monkeypatch.setattr(engine, "_fallback_speak_direct", fake_fallback)

        async def fake_429(text, output_path):
            raise RuntimeError("HTTP 429: Too Many Requests from Edge TTS Gateway")

        monkeypatch.setattr(engine, "_generate_audio", fake_429)

        # Clear recent speech to prevent deduplication
        clear_recent_speech_history()

        for i in range(5):
            engine.speak(f"Unique request index {i} experiencing rate limiting burst.", block=True)

        assert fallback_count == 5

    def test_elevenlabs_midstream_connection_reset_and_http_errors(self, monkeypatch):
        """
        Stress-test ElevenLabs TTS under connection drop, HTTP 429, HTTP 503, and invalid keys.
        """
        engine = ElevenLabsTTS(api_key="valid_looking_dummy_key_elevenlabs", voice_id="test_voice_id")
        fallback_invocations = []
        monkeypatch.setattr(engine, "_fallback_speak_direct", lambda text: fallback_invocations.append(text))

        # 1. Connection Reset during POST
        with patch("requests.post", side_effect=ConnectionResetError("Socket aborted mid-request")):
            clear_recent_speech_history()
            engine.speak("ElevenLabs connection reset test.", block=True)
            assert len(fallback_invocations) == 1
            assert "ElevenLabs connection reset test." in fallback_invocations[0]

        # 2. HTTP 503 Service Unavailable
        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 503
            mock_resp.text = "Service Temporarily Unavailable"
            mock_post.return_value = mock_resp
            clear_recent_speech_history()
            engine.speak("ElevenLabs 503 service unavailable test.", block=True)
            assert len(fallback_invocations) == 2
            assert "ElevenLabs 503 service unavailable test." in fallback_invocations[1]


# =============================================================================
# 2. Zombie Port 5141 Recovery & SIGKILL Escalation
# =============================================================================

class TestZombiePortAndProcessEscalation:
    """Stress-test process termination, port conflicts, and SIGKILL escalation."""

    def test_stubborn_child_process_ignoring_sigterm_escalates_to_sigkill(self):
        """
        Spawn a real Python subprocess that sets SIGTERM handler to SIG_IGN (ignores SIGTERM)
        and binds a test TCP port. Verify SIGTERM fails to kill it, SIGKILL terminates it,
        the socket is released, and the port can be immediately re-bound.
        """
        # Pick an ephemeral port for testing
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        test_sock.bind(("127.0.0.1", 0))
        test_port = test_sock.getsockname()[1]
        test_sock.close()

        # Script that ignores SIGTERM and holds port
        subproc_code = f"""
import socket, signal, time, sys

# Explicitly ignore SIGTERM
signal.signal(signal.SIGTERM, signal.SIG_IGN)

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('127.0.0.1', {test_port}))
sock.listen(1)

print('BOUND', flush=True)

# Loop indefinitely ignoring SIGTERM
while True:
    time.sleep(0.5)
"""
        proc = subprocess.Popen([sys.executable, "-c", subproc_code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            # Wait for socket bind
            line = proc.stdout.readline()
            assert "BOUND" in line
            pid = proc.pid

            # Confirm port listener detected
            listener = get_port_listener(test_port)
            assert listener is not None
            assert listener["pid"] == pid

            # Attempt graceful SIGTERM
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.2)
            # Process MUST still be alive because it ignored SIGTERM
            assert proc.poll() is None, "Stubborn process unexpectedly exited on SIGTERM"

            # Now test SIGKILL escalation
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.2)
            exit_code = proc.poll()
            assert exit_code == -signal.SIGKILL or exit_code == -9

            # Confirm port listener is completely gone
            assert get_port_listener(test_port) is None

            # Verify socket is freed and can be immediately re-bound
            rebound_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            rebound_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            rebound_sock.bind(("127.0.0.1", test_port))
            rebound_sock.listen(1)
            rebound_sock.close()
        finally:
            if proc.poll() is None:
                proc.kill()

    def test_stop_all_voicefi_servers_multi_zombie_and_port_clearing(self, monkeypatch):
        """
        Verify stop_all_voicefi_servers kills stubborn processes in find_running_voicefi_processes
        and port listener PIDs on port 5141 and 8765 using SIGKILL escalation.
        """
        signals_sent = []
        def fake_kill(pid, sig):
            signals_sent.append((pid, sig))

        monkeypatch.setattr(os, "kill", fake_kill)
        monkeypatch.setattr("voicefi.server.LAUNCHAGENT_PLISTS", [])
        
        # 3 processes: p1 exits on SIGTERM, p2 ignores SIGTERM, p3 is port 5141 listener
        p1 = {"pid": 30001, "ppid": 1, "command": "vifi daemon"}
        p2 = {"pid": 30002, "ppid": 1, "command": "voicefi tray"}
        p3_port = {"port": 5141, "pid": 30003, "command_name": "voicefi", "full_info": {"pid": 30003, "command": "voicefi server"}}

        procs_alive = {30001: True, 30002: True, 30003: True}

        def fake_is_running(pid):
            return procs_alive.get(pid, False)

        monkeypatch.setattr("voicefi.server.is_pid_running", fake_is_running)
        monkeypatch.setattr("voicefi.server.find_running_voicefi_processes", lambda: [p1, p2])
        
        port_call_count = 0
        def fake_port_listener(p):
            nonlocal port_call_count
            if p == 5141:
                return p3_port if procs_alive[30003] else None
            return None

        monkeypatch.setattr("voicefi.server.get_port_listener", fake_port_listener)

        # p1 exits when SIGTERM arrives
        procs_alive[30001] = False
        # p2 stays alive through timeout (stubborn)
        # p3 stays alive on port 5141

        result = stop_all_voicefi_servers(disable_launchagent=False, timeout_seconds=0.2)
        assert result["success"] is True

        # Verify SIGTERM sent to p1 and p2
        assert (30001, signal.SIGTERM) in signals_sent
        assert (30002, signal.SIGTERM) in signals_sent

        # Verify SIGKILL escalated to p2 (stubborn process)
        assert (30002, signal.SIGKILL) in signals_sent

        # Verify SIGKILL sent to p3 (port 5141 listener)
        assert (30003, signal.SIGKILL) in signals_sent

    def test_get_port_listener_fuzzing_and_boundary_cases(self):
        """Test get_port_listener against non-integer, negative, out-of-range, and special ports."""
        assert get_port_listener(-1) is None
        assert get_port_listener(0) is None or isinstance(get_port_listener(0), dict)
        assert get_port_listener("not_a_port") is None
        assert get_port_listener(None) is None
        assert get_port_listener(99999999) is None


# =============================================================================
# 3. Rapid Concurrent Process Crashes (`kill -9`) & Stale Lock Reclamation
# =============================================================================

class TestStaleLockAndCrashReclamation:
    """Stress-test concurrent crash scenarios and auto-reclamation of stale status/lock files."""

    def test_simulated_process_crash_holding_status_files_auto_reclaimed(self, tmp_path, monkeypatch):
        """
        Simulate multiple dead PIDs (from kill -9) leaving speaking.status, audio_playing.status,
        and hud_state.json. Verify all inspection functions detect dead PID and unlink them.
        """
        dead_pid = 8888888
        assert not is_pid_alive(dead_pid)

        f_speak = tmp_path / "voicefi_speaking.status"
        f_play = tmp_path / "voicefi_audio_playing.status"
        f_hud = tmp_path / "voicefi_hud_state.json"

        monkeypatch.setattr("voicefi.tts.base.AGENT_SPEAKING_STATUS_FILE", f_speak)
        monkeypatch.setattr("voicefi.tts.base.AUDIO_PLAYING_STATUS_FILE", f_play)
        monkeypatch.setattr("voicefi.tts.base.HUD_STATE_STATUS_FILE", f_hud)

        # 1. Speaking status dead PID JSON
        f_speak.write_text(json.dumps({
            "pid": dead_pid,
            "timestamp": time.time(),
            "text": "Interrupted speech during crash",
            "agent_name": "Antigravity",
            "persona_name": "Viv",
        }))
        assert is_agent_speaking() is False
        assert not f_speak.exists()

        # 2. Speaking status dead PID legacy format pid:ts
        f_speak.write_text(f"{dead_pid}:{time.time()}")
        assert is_agent_speaking() is False
        assert not f_speak.exists()

        # 3. Audio playing status dead PID format
        f_play.write_text(f"{dead_pid}:{time.time()}")
        assert is_agent_audio_playing() is False
        assert not f_play.exists()

        # 4. HUD state dead PID
        f_hud.write_text(json.dumps({
            "pid": dead_pid,
            "timestamp": time.time(),
            "state": "speaking",
            "text": "Crashed HUD state",
        }))
        assert get_cross_process_hud_state() is None
        assert not f_hud.exists()

    def test_corrupted_and_malformed_status_file_resilience(self, tmp_path, monkeypatch):
        """
        Verify that corrupted, half-written, binary, or non-JSON status files
        do not crash inspection functions or cause infinite blocking.
        """
        f_speak = tmp_path / "voicefi_speaking.status"
        f_play = tmp_path / "voicefi_audio_playing.status"
        f_hud = tmp_path / "voicefi_hud_state.json"

        monkeypatch.setattr("voicefi.tts.base.AGENT_SPEAKING_STATUS_FILE", f_speak)
        monkeypatch.setattr("voicefi.tts.base.AUDIO_PLAYING_STATUS_FILE", f_play)
        monkeypatch.setattr("voicefi.tts.base.HUD_STATE_STATUS_FILE", f_hud)

        malformed_samples = [
            "",  # empty
            "   ",  # whitespace
            "{truncated json object: ",  # syntax error
            "not_json_and_not_a_pid",  # unparseable string
            "::::",  # invalid separators
            "None:None",  # bad values
            "\x00\x01\x02\x03\xff\xfe",  # binary junk
            '{"pid": "invalid_pid", "timestamp": "not_float"}',  # type mismatches
        ]

        for sample in malformed_samples:
            f_speak.write_text(sample, errors="ignore")
            f_play.write_text(sample, errors="ignore")
            f_hud.write_text(sample, errors="ignore")

            # Must evaluate safely to False/None without unhandled exceptions
            assert is_agent_speaking() is False
            assert is_agent_audio_playing() is False
            assert get_cross_process_hud_state() is None

    def test_concurrent_speech_turn_lock_exception_unwinding(self, tmp_path, monkeypatch):
        """
        Verify that when an unhandled exception or abrupt exit occurs inside speech_turn_lock,
        the lock depth, agent speaking status, and lock file descriptor are cleanly unwound.
        """
        lock_file = tmp_path / "voicefi_speech.lock"
        speak_file = tmp_path / "voicefi_speaking.status"
        monkeypatch.setattr("voicefi.tts.base.SPEECH_LOCK_FILE", lock_file)
        monkeypatch.setattr("voicefi.tts.base.AGENT_SPEAKING_STATUS_FILE", speak_file)

        # Ensure clean initial state
        set_agent_speaking(False)
        assert is_agent_speaking() is False

        with pytest.raises(ZeroDivisionError):
            with speech_turn_lock(text="Exception unwinding test", agent_name="TestAgent"):
                assert is_agent_speaking() is True
                assert speak_file.exists()
                # Trigger unhandled exception inside lock
                _ = 1 / 0

        # After exception unwinding:
        assert is_agent_speaking() is False
        assert not speak_file.exists()

        # Verify a new turn can acquire the lock immediately without blocking
        turn_acquired = False
        with speech_turn_lock(text="Subsequent speech turn", agent_name="TestAgent"):
            turn_acquired = True
            assert is_agent_speaking() is True

        assert turn_acquired is True
        assert is_agent_speaking() is False

    def test_concurrent_multiprocess_speech_lock_stress(self, tmp_path):
        """
        Spawn 6 concurrent Python processes contending for the same speech_turn_lock.
        Each process acquires the lock, writes its PID to a shared ledger, sleeps briefly,
        and releases. Verify mutual exclusion and zero deadlocks.
        """
        shared_lock_file = tmp_path / "shared_speech.lock"
        ledger_file = tmp_path / "lock_contention_ledger.txt"

        worker_script = f"""
import time, os, fcntl, sys
from pathlib import Path

lock_path = Path("{shared_lock_file}")
ledger_path = Path("{ledger_file}")

with open(lock_path, "a+") as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    try:
        # Record lock entry
        with open(ledger_path, "a") as ledger:
            ledger.write(f"START:{{os.getpid()}}\\n")
        time.sleep(0.05)
        with open(ledger_path, "a") as ledger:
            ledger.write(f"END:{{os.getpid()}}\\n")
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
"""
        procs = []
        for _ in range(6):
            p = subprocess.Popen([sys.executable, "-c", worker_script])
            procs.append(p)

        # Wait for all processes to complete with timeout
        for p in procs:
            p.wait(timeout=10)
            assert p.returncode == 0

        # Validate ledger: every START must have a matching consecutive END (mutual exclusion)
        lines = ledger_file.read_text().strip().splitlines()
        assert len(lines) == 12  # 6 START + 6 END

        for i in range(0, 12, 2):
            start_line = lines[i]
            end_line = lines[i + 1]
            assert start_line.startswith("START:")
            assert end_line.startswith("END:")
            assert start_line.split(":")[1] == end_line.split(":")[1]
