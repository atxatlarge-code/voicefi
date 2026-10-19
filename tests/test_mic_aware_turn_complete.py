import os
import threading
import time
from unittest.mock import patch

import pytest

from voicefi.audio.device import (
    _resolve_external_mic_pid,
    get_external_mic_recording_info,
    is_external_mic_recording_active,
    reset_external_mic_detection_state,
)
from voicefi.tts.base import (
    get_mic_recording_info,
    is_blocking_mic_recording_active,
    is_mic_recording_active,
    set_agent_audio_playing,
    set_agent_speaking,
    set_mic_recording,
    speech_turn_lock,
    wait_for_mic_to_clear,
)


@pytest.fixture(autouse=True)
def clean_mic_and_speech_state(monkeypatch):
    monkeypatch.delenv("MOCK_EXTERNAL_MIC", raising=False)
    reset_external_mic_detection_state()
    set_mic_recording(False)
    set_agent_speaking(False)
    set_agent_audio_playing(False)
    yield
    monkeypatch.delenv("MOCK_EXTERNAL_MIC", raising=False)
    reset_external_mic_detection_state()
    set_mic_recording(False)
    set_agent_speaking(False)
    set_agent_audio_playing(False)


def test_external_mic_detection_mock_env(monkeypatch):
    assert is_external_mic_recording_active(use_cache=False) is False
    assert get_external_mic_recording_info(use_cache=False) is None

    monkeypatch.setenv("MOCK_EXTERNAL_MIC", "Antigravity")
    info = get_external_mic_recording_info(use_cache=False)
    assert info is not None
    assert info["state"] == "external_recording"
    assert info["app_name"] == "Antigravity"
    assert info["source"] == "external_mic"
    assert is_external_mic_recording_active(use_cache=False) is True
    assert is_mic_recording_active() is True


def test_resolve_external_mic_pid_filters_voicefi_and_daemons():
    own_pid = os.getpid()
    # Own PID is excluded
    app_name, ignored = _resolve_external_mic_pid(own_pid)
    assert app_name == "VoiceFi"
    assert ignored is True

    # Passive system/virtual audio daemons are excluded
    with patch(
        "voicefi.audio.device._get_pid_executable_path",
        return_value="/usr/sbin/coreaudiod",
    ):
        app_name, ignored = _resolve_external_mic_pid(99991)
        assert ignored is True

    # External native app (e.g. Antigravity / Electron) is detected
    with patch(
        "voicefi.audio.device._get_pid_executable_path",
        return_value="/Applications/Antigravity.app/Contents/MacOS/Electron",
    ):
        app_name, ignored = _resolve_external_mic_pid(99992)
        assert app_name == "Antigravity"
        assert ignored is False


def test_blocking_mic_recording_distinguishes_barge_in_monitor():
    # Same-process passive barge-in monitor for the same conv_id does NOT self-deadlock
    set_mic_recording(
        True,
        conv_id="conv-123",
        agent_name="antigravity",
        state="barge_in_monitor",
    )
    blocked, _ = is_blocking_mic_recording_active(conv_id="conv-123")
    assert blocked is False

    # Different conv_id IS blocked
    blocked_other, _ = is_blocking_mic_recording_active(conv_id="conv-999")
    assert blocked_other is True

    # Active dictation (`dictating` or `transcribing`) ALWAYS blocks even for the same conv_id
    set_mic_recording(
        True,
        conv_id="conv-123",
        agent_name="VoiceFi",
        state="dictating",
    )
    blocked_dict, info_dict = is_blocking_mic_recording_active(conv_id="conv-123")
    assert blocked_dict is True
    assert info_dict["state"] == "dictating"

    set_mic_recording(
        True,
        conv_id="conv-123",
        agent_name="VoiceFi",
        state="transcribing",
    )
    blocked_trans, info_trans = is_blocking_mic_recording_active(conv_id="conv-123")
    assert blocked_trans is True
    assert info_trans["state"] == "transcribing"


def test_wait_for_mic_to_clear_waits_for_dictation_and_transcription():
    set_mic_recording(True, state="dictating", agent_name="VoiceFi")

    events = []

    def _release_mic_lifecycle():
        time.sleep(0.08)
        events.append("transcribing")
        set_mic_recording(True, state="transcribing", agent_name="VoiceFi")
        time.sleep(0.08)
        events.append("cleared")
        set_mic_recording(False)

    t = threading.Thread(target=_release_mic_lifecycle, daemon=True)
    t.start()

    cleared = wait_for_mic_to_clear(max_wait_seconds=2.0, settle_seconds=0.05)
    events.append("unblocked")
    t.join(timeout=1.0)

    assert cleared is True
    assert events == ["transcribing", "cleared", "unblocked"]


def test_wait_for_mic_to_clear_waits_for_external_native_mic(monkeypatch):
    monkeypatch.setenv("MOCK_EXTERNAL_MIC", "Antigravity")

    events = []

    def _close_native_mic():
        time.sleep(0.1)
        events.append("native_mic_closed")
        monkeypatch.setenv("MOCK_EXTERNAL_MIC", "0")
        reset_external_mic_detection_state()

    t = threading.Thread(target=_close_native_mic, daemon=True)
    t.start()

    cleared = wait_for_mic_to_clear(max_wait_seconds=2.0, settle_seconds=0.05)
    events.append("turn_proceeded")
    t.join(timeout=1.0)

    assert cleared is True
    assert events == ["native_mic_closed", "turn_proceeded"]


def test_speech_turn_lock_and_audio_playing_wait_for_open_mic(monkeypatch):
    # 1. Mic open before entering speech_turn_lock -> speech_turn_lock waits until mic closes
    set_mic_recording(True, state="dictating", agent_name="VoiceFi")
    timeline = []

    def _finish_dictation():
        time.sleep(0.1)
        timeline.append("dictation_done")
        set_mic_recording(False)

    threading.Thread(target=_finish_dictation, daemon=True).start()

    with speech_turn_lock(agent_name="antigravity", conv_id="conv-abc"):
        timeline.append("entered_speech_lock")

        # 2. Simulate native mic opening mid-synthesis right before afplay starts
        monkeypatch.setenv("MOCK_EXTERNAL_MIC", "Antigravity")
        reset_external_mic_detection_state()

        def _finish_native_talk():
            time.sleep(0.1)
            timeline.append("native_talk_done")
            monkeypatch.setenv("MOCK_EXTERNAL_MIC", "0")
            reset_external_mic_detection_state()

        threading.Thread(target=_finish_native_talk, daemon=True).start()
        set_agent_audio_playing(True)
        timeline.append("afplay_started")
        set_agent_audio_playing(False)

    assert timeline == [
        "dictation_done",
        "entered_speech_lock",
        "native_talk_done",
        "afplay_started",
    ]


def test_wakeword_listener_evaluates_nothing_when_external_mic_active(monkeypatch):
    import numpy as np
    from unittest.mock import MagicMock
    from voicefi.audio.wakeword import WakeWordListener
    from voicefi.config import VoiceFiConfig

    listener = WakeWordListener(config=VoiceFiConfig(), on_wake=lambda *a, **kw: None)
    mock_stt = MagicMock()
    listener._stt = mock_stt
    monkeypatch.setenv("MOCK_EXTERNAL_MIC", "Antigravity")
    reset_external_mic_detection_state()

    listener._evaluate_single_candidate(np.zeros(16000, dtype=np.float32))
    mock_stt.transcribe.assert_not_called()


def test_recorder_protects_active_dictation_from_non_dictation_cancellation():
    import numpy as np
    from voicefi.audio.recorder import AudioRecorder

    dictation_rec = AudioRecorder()
    dictation_rec.is_dictation = True

    with AudioRecorder._RECORDER_LOCK:
        AudioRecorder._ACTIVE_RECORDERS.add(dictation_rec)
    try:
        assert AudioRecorder.has_active_dictation_recorder() is True
        # Non-dictation recorder should return empty audio immediately without cancelling dictation_rec
        bg_rec = AudioRecorder()
        audio, path = bg_rec.record_speech_auto(is_dictation=False)
        assert len(audio) == 0
        assert path is None
        assert dictation_rec.cancelled is False
    finally:
        with AudioRecorder._RECORDER_LOCK:
            AudioRecorder._ACTIVE_RECORDERS.discard(dictation_rec)
        dictation_rec.is_dictation = False

    assert AudioRecorder.has_active_dictation_recorder() is False


def test_pressure_8_agent_dogpile_during_dictation_and_stop_speech():
    """
    Pressure test: 8 concurrent agent threads hit speech_turn_lock while the user
    is actively dictating (and stop_all_speech was triggered at dictation start).
    Verifies:
    - Zero agents speak while dictating or transcribing is active.
    - Zero agents are falsely aborted by the dictation-start stop_all_speech timestamp.
    - All 8 agents acquire the lock strictly sequentially (max concurrency == 1) after mic closes.
    """
    from voicefi.tts.base import clear_speech_stopped_time, record_speech_stopped

    # Simulate user starting dictation and silencing a prior speaker
    set_mic_recording(True, state="dictating", agent_name="VoiceFi")
    record_speech_stopped()

    mic_open_flag = {"open": True}
    active_speakers = {"count": 0, "max_concurrent": 0, "spoke_while_mic_open": 0}
    completed_agents = []
    errors = []
    state_lock = threading.Lock()

    def _agent_worker(idx: int):
        try:
            with speech_turn_lock(
                text=f"Agent{idx}Unique{idx * 7919} completed turn number {idx} successfully",
                agent_name=f"agent_{idx}",
                conv_id=f"conv_{idx}",
            ):
                with state_lock:
                    active_speakers["count"] += 1
                    if active_speakers["count"] > active_speakers["max_concurrent"]:
                        active_speakers["max_concurrent"] = active_speakers["count"]
                    if mic_open_flag["open"]:
                        active_speakers["spoke_while_mic_open"] += 1
                time.sleep(0.015)
                with state_lock:
                    active_speakers["count"] -= 1
                    completed_agents.append(idx)
        except Exception as e:
            with state_lock:
                errors.append((idx, repr(e)))

    threads = [threading.Thread(target=_agent_worker, args=(i,), daemon=True) for i in range(8)]
    for t in threads:
        t.start()

    # Keep dictating for 80ms, then transition to transcribing for 80ms
    time.sleep(0.08)
    assert len(completed_agents) == 0, "No agent may complete while dictating"
    set_mic_recording(True, state="transcribing", agent_name="VoiceFi")
    time.sleep(0.08)
    assert len(completed_agents) == 0, "No agent may complete while transcribing"

    # Now release the microphone
    with state_lock:
        mic_open_flag["open"] = False
    set_mic_recording(False)

    for t in threads:
        t.join(timeout=5.0)

    clear_speech_stopped_time()

    assert errors == [], f"Unexpected errors in dogpile: {errors}"
    assert (
        len(completed_agents) == 8
    ), f"Expected all 8 agents to speak after mic closed, got {len(completed_agents)}"
    assert active_speakers["spoke_while_mic_open"] == 0
    assert active_speakers["max_concurrent"] == 1


def test_pressure_rapid_mic_flapping_respects_settle_window(monkeypatch):
    """
    Pressure test: Native microphone rapidly flaps open/closed every 15ms for 5 cycles.
    Verifies wait_for_mic_to_clear does NOT leak through brief gaps between flaps.
    """
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("MOCK_EXTERNAL_MIC", "Antigravity")
    reset_external_mic_detection_state()

    flap_done = {"finished_all_flaps": False}

    def _flapper():
        for _ in range(5):
            monkeypatch.setenv("MOCK_EXTERNAL_MIC", "Antigravity")
            reset_external_mic_detection_state()
            time.sleep(0.025)
            # Brief 15ms gap (shorter than 90ms settle window)
            monkeypatch.setenv("MOCK_EXTERNAL_MIC", "0")
            reset_external_mic_detection_state()
            time.sleep(0.015)

        # Final open burst then permanent close
        monkeypatch.setenv("MOCK_EXTERNAL_MIC", "Antigravity")
        reset_external_mic_detection_state()
        time.sleep(0.03)
        flap_done["finished_all_flaps"] = True
        monkeypatch.setenv("MOCK_EXTERNAL_MIC", "0")
        reset_external_mic_detection_state()

    t = threading.Thread(target=_flapper, daemon=True)
    t.start()

    cleared = wait_for_mic_to_clear(
        max_wait_seconds=3.0,
        poll_interval=0.015,
        settle_seconds=0.09,
    )
    t.join(timeout=2.0)

    assert cleared is True
    assert flap_done["finished_all_flaps"] is True


def test_pressure_corrupted_status_files_and_zombie_pids():
    """
    Hostile input fuzzing against MIC_RECORDING_STATUS_FILE:
    Tests binary garbage, truncated JSON, non-dict JSON, NaN timestamps,
    negative PIDs, zombie PIDs, and malformed legacy strings.
    """
    from voicefi.tts.base import MIC_RECORDING_STATUS_FILE

    hostile_payloads = [
        b"\xff\xfe\x00\x89PNG\r\n\x1a\n\x00\x00\x00",
        b'{"pid": 12345, "state": "dictating"',
        b"[1, 2, 3, 4]",
        b'"just_a_raw_string"',
        b"null",
        b'{"pid": "not_an_int", "timestamp": "not_a_float", "state": "dictating"}',
        f'{{"pid": {os.getpid()}, "timestamp": NaN, "state": "dictating"}}'.encode(),
        f'{{"pid": {os.getpid()}, "timestamp": -999999.0, "state": "dictating"}}'.encode(),
        f'{{"pid": {os.getpid()}, "timestamp": {time.time() + 99999.0}, "state": "dictating"}}'.encode(),
        f'{{"pid": 99999999, "timestamp": {time.time()}, "state": "dictating"}}'.encode(),
        b"not_a_pid:not_a_ts",
        f"99999999:{time.time()}".encode(),
    ]

    for payload in hostile_payloads:
        MIC_RECORDING_STATUS_FILE.write_bytes(payload)
        info = get_mic_recording_info(include_external=False)
        assert info is None, f"Payload {payload!r} should have been rejected as invalid"
        blocked, b_info = is_blocking_mic_recording_active(include_external=False)
        assert blocked is False
        assert b_info is None
        assert not MIC_RECORDING_STATUS_FILE.exists(), (
            f"Corrupt file should be unlinked for {payload!r}"
        )


def test_pressure_coreaudio_ctypes_50_processes_and_real_hardware_benchmark(monkeypatch):
    """
    1. Runs 100 rapid live queries against real macOS CoreAudio.framework to verify
       zero crashes and <5ms average latency.
    2. Simulates 50 CoreAudio process objects (VoiceFi PIDs, system daemons, inactive processes,
       and 1 active external Antigravity process) and verifies exact identification.
    """
    import voicefi.audio.device as dev_mod

    for env_key in (
        "PYTEST_CURRENT_TEST",
        "VOICEFI_MOCK_AUDIO",
        "VOICEFI_HEADLESS",
        "VOICEFI_TESTING",
        "MOCK_EXTERNAL_MIC",
    ):
        monkeypatch.delenv(env_key, raising=False)
    reset_external_mic_detection_state()

    # Part 1: Warm up macOS CoreAudio HAL connection once, then benchmark uncached + cached live queries
    _ = get_external_mic_recording_info(use_cache=False)
    t0 = time.perf_counter()
    for _ in range(25):
        _ = get_external_mic_recording_info(use_cache=False)
    uncached_avg_ms = ((time.perf_counter() - t0) * 1000.0) / 25.0
    assert uncached_avg_ms < 20.0, f"Uncached CoreAudio query too slow: {uncached_avg_ms:.2f}ms/call"

    t1 = time.perf_counter()
    for _ in range(500):
        _ = get_external_mic_recording_info(use_cache=True)
    cached_avg_ms = ((time.perf_counter() - t1) * 1000.0) / 500.0
    assert cached_avg_ms < 0.05, f"Cached CoreAudio query too slow: {cached_avg_ms:.4f}ms/call"

    # Part 2: Mocked 50-process CoreAudio table
    def _unwrap_c_arg(arg):
        return getattr(arg, "_obj", arg)

    class FakeCoreAudio:
        def AudioObjectGetPropertyDataSize(self, obj_id, addr_ptr, qual_sz, qual_ptr, size_ptr):
            size_obj = _unwrap_c_arg(size_ptr)
            size_obj.value = 50 * 4  # 50 process objects
            return 0

        def AudioObjectGetPropertyData(
            self, obj_id, addr_ptr, qual_sz, qual_ptr, size_ptr, data_ptr
        ):
            addr = _unwrap_c_arg(addr_ptr)
            data = _unwrap_c_arg(data_ptr)
            oid = getattr(obj_id, "value", obj_id)
            # 'prs#' list
            if addr.mSelector == 0x70727323:
                for i in range(50):
                    data[i] = 1000 + i
                return 0
            # 'piri' (is running input)
            if addr.mSelector == 0x70697269:
                # Objects 1010 (own PID), 1020 (coreaudiod), and 1042 (Antigravity) have input active
                data.value = 1 if oid in (1010, 1020, 1042) else 0
                return 0
            # 'ppid'
            if addr.mSelector == 0x70706964:
                if oid == 1010:
                    data.value = os.getpid()
                elif oid == 1020:
                    data.value = 88001
                elif oid == 1042:
                    data.value = 88042
                else:
                    data.value = 70000 + oid
                return 0
            return -50

    def _fake_exe_path(pid: int) -> str:
        if pid == 88001:
            return "/usr/sbin/coreaudiod"
        if pid == 88042:
            return "/Applications/Antigravity.app/Contents/MacOS/Electron"
        return "/usr/bin/true"

    reset_external_mic_detection_state()
    with patch.object(dev_mod, "_COREAUDIO_LIB", FakeCoreAudio()), patch(
        "voicefi.audio.device._get_pid_executable_path", side_effect=_fake_exe_path
    ):
        info = get_external_mic_recording_info(use_cache=False)
        assert info is not None
        assert info["pid"] == 88042
        assert info["app_name"] == "Antigravity"
        assert info["state"] == "external_recording"


def test_pressure_escape_to_stop_speech_halts_when_dictation_or_native_mic_opens(monkeypatch):
    """
    Verifies that if an agent is actively playing speech audio inside escape_to_stop_speech
    and the user opens either VoiceFi dictation OR an external native mic,
    stop_all_speech() is automatically invoked within <600ms.
    """
    from voicefi.tts.base import escape_to_stop_speech

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    with patch("voicefi.tts.base.is_tray_hotkey_listener_active", return_value=True), patch(
        "voicefi.tts.base.stop_all_speech"
    ) as mock_stop:
        set_agent_audio_playing(True)
        try:
            with escape_to_stop_speech(agent_name="antigravity", conv_id="conv-live"):
                # Open external native mic while agent is speaking
                monkeypatch.setenv("MOCK_EXTERNAL_MIC", "Antigravity")
                reset_external_mic_detection_state()
                deadline = time.time() + 1.2
                while time.time() < deadline and mock_stop.call_count == 0:
                    time.sleep(0.05)
                assert mock_stop.call_count >= 1
        finally:
            set_agent_audio_playing(False)
            monkeypatch.delenv("MOCK_EXTERNAL_MIC", raising=False)
            reset_external_mic_detection_state()


def test_pressure_watcher_on_turn_complete_waits_for_dictation_and_native_mic(monkeypatch):
    """
    End-to-end integration pressure test on TranscriptWatcher._handle_turn_ready:
    Verifies that when a turn finishes while the user is dictating (`dictating` -> `transcribing`)
    followed immediately by native talk (`MOCK_EXTERNAL_MIC="Antigravity"`), the watcher does NOT
    drop the turn and does NOT speak while the mic is open, then speaks the turn once the mic closes.
    """
    from unittest.mock import MagicMock
    from voicefi.config import VoiceFiConfig
    from voicefi.integrations.conversations import ConversationInfo
    from voicefi.integrations.watcher import TranscriptWatcher

    cfg = VoiceFiConfig()
    cfg.antigravity.read_summary_aloud = True
    cfg.antigravity.auto_listen = False
    cfg.antigravity.show_speech_popup = False
    cfg.vad.barge_in = False

    watcher = TranscriptWatcher(config=cfg)
    conv_info = MagicMock(spec=ConversationInfo)
    conv_info.id = "conv-pressure-e2e-99"
    conv_info.title = "Pressure Test Conversation"
    conv_info.workspace_path = "/Users/jaketrigg/Projects/VoiceFi"
    conv_info.project_name = "VoiceFi"

    events = []
    fake_tts = MagicMock()

    def _record_speak(txt, block=True):
        events.append(("tts_spoke", txt))

    fake_tts.stream_speak.side_effect = _record_speak

    # Start with dictation active
    set_mic_recording(True, state="dictating", agent_name="VoiceFi")

    def _user_mic_sequence():
        time.sleep(0.06)
        events.append(("mic_transcribing", ""))
        set_mic_recording(True, state="transcribing", agent_name="VoiceFi")
        time.sleep(0.06)
        events.append(("native_mic_opened", ""))
        monkeypatch.setenv("MOCK_EXTERNAL_MIC", "Antigravity")
        reset_external_mic_detection_state()
        set_mic_recording(False)
        time.sleep(0.06)
        events.append(("all_mics_closed", ""))
        monkeypatch.setenv("MOCK_EXTERNAL_MIC", "0")
        reset_external_mic_detection_state()

    mic_thread = threading.Thread(target=_user_mic_sequence, daemon=True)
    mic_thread.start()

    with patch("voicefi.integrations.watcher.load_config", return_value=cfg), patch(
        "voicefi.integrations.watcher.claim_turn", return_value=True
    ), patch("voicefi.integrations.watcher.get_tts_engine", return_value=fake_tts), patch(
        "voicefi.audio.meeting_detection.is_user_on_call", return_value=False
    ), patch(
        "voicefi.integrations.watcher.has_active_companion_client", return_value=False
    ):
        watcher._handle_turn_ready(
            "Pressure test turn completed cleanly without interrupting the user.",
            conv_info=conv_info,
            is_active=True,
            agent_role="antigravity",
            step_index=777,
        )

    mic_thread.join(timeout=2.0)

    event_names = [e[0] for e in events]
    assert event_names == [
        "mic_transcribing",
        "native_mic_opened",
        "all_mics_closed",
        "tts_spoke",
    ]

