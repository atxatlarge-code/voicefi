"""
Troubleshooting, diagnostic suite, barge-in, loopback, and voice ping subcommands.
"""

import json
import os
import sys
import threading
import time
from typing import Any

from voicefi.config import load_config, save_config


def cmd_troubleshoot(args):
    """Run interactive or automated Voice & Audio troubleshooting and test suite."""
    import time
    from voicefi.troubleshoot import AudioTroubleshooter, TEST_PHRASES

    config = load_config(getattr(args, "config", None))
    troubleshooter = AudioTroubleshooter(config)

    # 1. Check if quick fix requested
    fix_type = getattr(args, "fix", None)
    if fix_type:
        print(f"\n🔧 Applying auto-fix: '{fix_type}'...")
        res = troubleshooter.apply_fix(fix_type)
        if res.get("success"):
            print(f"✅ {res['message']}\n")
        else:
            print(f"❌ {res['message']}\n")
        return

    # 2. Check if JSON requested
    if getattr(args, "json", False):
        report = troubleshooter.run_full_troubleshoot()
        print(json.dumps(report, indent=2))
        return

    # 3. Check if Mic Loopback only
    if getattr(args, "mic", False) or getattr(args, "loopback", False):
        print("\n🎙️ Starting 3-Second Microphone Loopback Test...")
        print("🔔 Ready... Recording in 1 second!")
        time.sleep(1.0)
        print("🔴 RECORDING (3.0s) — Speak a sentence into your microphone!")
        res = troubleshooter.test_microphone_loopback(duration_seconds=3.0, play_back=True)
        if res.success:
            print(f"✅ Captured {res.duration_s}s audio at {res.sample_rate}Hz.")
            print(
                f"📊 RMS Energy: {res.rms_energy:.4f}, Peak: {res.peak_amplitude:.3f}, SNR: {res.snr_db:.1f} dB"
            )
            status = "Speech detected ✅" if res.speech_detected else "Quiet / Low audio ⚠️"
            print(f"🎙️ Detection: {status}")
            print("🔊 Playing back over speakers now...")
            time.sleep(3.2)
            print("✨ Test complete.\n")
        else:
            print(f"❌ Mic test failed: {res.error}\n")
        return

    # 4. Check if Benchmark only
    if getattr(args, "benchmark", False):
        print("\n⚡ Benchmarking Voice Personas Latency...")
        benchmarks = troubleshooter.benchmark_all_curated_voices()
        for b in benchmarks:
            status_icon = "🟢" if b["status"] == "online" else "🔴"
            lat_str = f"{b['latency_ms']} ms" if b["status"] == "online" else "Error"
            print(
                f"  • {status_icon} {b['name']:<12} [{b['provider']}]: {lat_str} ({b['recommended_role']})"
            )
        print()
        return

    # 5. Full automated diagnostics & interactive walkthrough
    print("\n🔍 VoiceFi Audio & Voice Diagnostic Suite")
    print("=" * 60)

    # Hardware Check
    hw = troubleshooter.get_hardware_diagnostics()
    vad_res = troubleshooter.test_vad()
    vad_detail = ""
    if vad_res.get("status") == "ready":
        d = vad_res.get("details", {})
        vad_detail = f" (latency: {d.get('avg_latency_ms', 0.1):.3f}ms, ~{d.get('throughput_frames_per_sec', 0):.0f} fps)"
    print("\n🖥️  [1/4] Audio Hardware & System:")
    print(f"  • Platform:      {hw['os_platform']} {hw['os_release']} ({hw['machine_arch']})")
    print(f"  • Default Mic:   {hw['default_input'] or 'None'}")
    print(f"  • Default Spkr:  {hw['default_output'] or 'None'}")
    print(f"  • VAD Engine:    {vad_res.get('engine', 'silero').upper()}{vad_detail}")
    print(
        f"  • Active Engine: {hw['tts_provider']} ({hw['tts_voice']}) at {hw['tts_rate']} WPM ({hw['tts_rate_pct']})"
    )

    # Speaker Output Chime Test
    print("\n🔔 [2/4] Speaker Output & Alert System:")
    print("  Playing test chime over default output device...")
    spk_res = troubleshooter.test_speaker_output("start", block=True)
    if spk_res["success"]:
        print(f"  ✅ Speaker chime played successfully ({spk_res['latency_ms']} ms latency).")
    else:
        print(f"  ⚠️ Speaker chime failed: {spk_res['error']}")

    # Active Voice Test
    print("\n🔊 [3/4] Active Voice Persona Audition:")
    v_res = troubleshooter.test_voice(
        voice_name_or_id=hw["tts_voice"],
        text="Voice test nominal. Audio output and latency are healthy.",
        provider=hw["tts_provider"],
        rate=hw["tts_rate"],
        block=True,
        show_hud=getattr(args, "hud", False),
    )
    if v_res.success:
        print("  ✅ Active voice synthesized and played aloud.")
        print(f"  ⚡ Latency (TTFB): {v_res.latency_ms} ms (Duration: {v_res.duration_s}s)")
    else:
        print(f"  ⚠️ Voice playback error: {v_res.error}")

    # Interactive Mic Test if requested
    if getattr(args, "interactive", False):
        print("\n🎙️ [4/4] Interactive Microphone Test:")
        try:
            input("  Press Enter to begin 3-second mic recording (or Ctrl+C to skip)... ")
            print("  🔴 RECORDING NOW (3s) — Speak a sentence clearly!")
            mic_res = troubleshooter.test_microphone_loopback(duration_seconds=3.0, play_back=True)
            if mic_res.success:
                print(
                    f"  ✅ Recorded {mic_res.duration_s}s. RMS Energy: {mic_res.rms_energy:.4f}, SNR: {mic_res.snr_db:.1f} dB"
                )
                print("  🔊 Playing back your voice over speakers...")
                time.sleep(3.2)
            else:
                print(f"  ⚠️ Microphone loopback failed: {mic_res.error}")
        except (KeyboardInterrupt, EOFError):
            print("\n  Skipped mic loopback.")
    else:
        print("\n🎙️ [4/4] Microphone Diagnostics:")
        print("  Tip: Run 'vg feedback-loop' or 'vg hearing-test' to test full roundtrip audio.")

    # Summary Recommendations
    full_report = troubleshooter.run_full_troubleshoot()
    recs = full_report.get("recommendations", [])
    print("\n📋 Troubleshooting Summary & Recommendations:")
    if recs:
        for r in recs:
            print(f"  💡 {r}")
    else:
        print("  ✨ All voice, audio, and hardware subsystems are running at peak performance!")

    print(
        "\n🌐 Web Control Panel with live interactive tester: 'vg panel' (http://localhost:5141)\n"
    )


def cmd_hearing_test(args):
    """Run acoustic hearing test (speak aloud -> listen via mic -> STT verification)."""
    args.voice_action = "test"
    args.hearing = True
    cmd_voice(args)


def cmd_feedback_loop(args):
    """Manage ProActive Feedback Loop setting (on/off/status) or run acoustic loop test."""
    voice_arg = getattr(args, "voice", None)
    action_arg = getattr(args, "action", None)
    target = (action_arg or voice_arg or "").lower()

    if target in ("on", "enable", "true", "1"):
        cfg = load_config(getattr(args, "config", None))
        cfg.proactive.feedback_loop.enabled = True
        cfg.antigravity.auto_listen = True
        save_config(cfg)
        print("\n⚡ ProActive Feedback Loop: 🟢 ENABLED")
        print(
            "💡 The microphone will automatically open for your conversational turn after the agent speaks.\n"
        )
        return
    elif target in ("off", "disable", "false", "0"):
        cfg = load_config(getattr(args, "config", None))
        cfg.proactive.feedback_loop.enabled = False
        cfg.antigravity.auto_listen = False
        save_config(cfg)
        print("\n⚡ ProActive Feedback Loop: ⚪ DISABLED")
        print("💡 Speech synthesis only. Use Ctrl+R or Ctrl+T to speak on-demand.\n")
        return
    elif target == "status":
        cfg = load_config(getattr(args, "config", None))
        status_str = "🟢 ENABLED" if cfg.proactive.feedback_loop.enabled else "⚪ DISABLED"
        print(f"\n⚡ ProActive Feedback Loop Status: {status_str}")
        print(
            f"  • Turn Handoff: {'✅ Active' if cfg.proactive.feedback_loop.enabled else '⚪ Inactive'}"
        )
        print(f"  • Chime Cue: {'✅ On' if cfg.proactive.feedback_loop.chime_cue else '❌ Off'}")
        print(f"  • Turn Timeout: {cfg.proactive.feedback_loop.timeout_seconds}s")
        print(
            f"  • Typing Guard: {'✅ Active' if cfg.proactive.feedback_loop.cancel_on_typing else '❌ Inactive'}"
        )
        print(
            f"  • Multi-Channel Routing: {'✅ Active (Claude, Slack, Linear)' if cfg.proactive.intent_routing.enabled else '❌ Inactive'}\n"
        )
        return

    # Otherwise run acoustic roundtrip verification test
    args.voice_action = "test"
    args.feedback_loop = True
    cmd_voice(args)


def cmd_loopback(args):
    """Alias for cmd_feedback_loop."""
    cmd_feedback_loop(args)


def cmd_barge_in(args):
    """Run live interactive barge-in & Silero VAD interruption test."""
    from voicefi.config import load_config
    from voicefi.audio.recorder import AudioRecorder
    from voicefi.tts import get_tts_engine, stop_all_speech, find_persona
    from voicefi.audio.device import get_audio_device_profile
    from voicefi.stt.whisper_local import WhisperLocalSTT
    import threading

    config = load_config()
    prof = get_audio_device_profile()

    target_voice = getattr(args, "voice", None) or config.tts.voice
    persona = find_persona(target_voice)
    resolved_voice = persona.id if persona else target_voice

    default_test_phrase = (
        "This is a live acoustic barge-in test with Silero VAD. "
        "I will keep speaking aloud for several seconds so you can test interrupting me. "
        "Whenever you are ready, speak firmly into your microphone now to cut me off!"
    )
    test_phrase = getattr(args, "text", None) or default_test_phrase

    print("\n" + "=" * 65)
    print("⚡ VoiceFi Active Voice Barge-In & Silero VAD Live Test")
    print("=" * 65)
    print(f"🎙️  Microphone:      {prof.get('default_input') or 'Default'}")
    print(f"🔊 Output Device:   {prof.get('default_output') or 'Default'}")
    print(
        f"🎧 Device Profile:  {'Headphones / AirPods ✅' if prof.get('is_headphones_active') else 'Built-in Laptop Speakers (Acoustic Safe Mode)'}"
    )
    print(
        f"🧠 VAD Engine:      {getattr(config.vad, 'engine', 'silero').upper()} (Threshold: {getattr(config.vad, 'speech_threshold', 0.5)})"
    )
    print("-" * 65)
    print("👉 HOW THIS TEST WORKS:")
    print("   1. VoiceFi will speak aloud through your speakers/headphones.")
    print("   2. While it speaks, Silero VAD actively monitors your microphone.")
    print("   3. Speak firmly into your microphone (e.g. 'Wait, stop right now!').")
    print("   4. Agent speech will INSTANTLY cut off and transcribe your interruption.")
    print("-" * 65)

    recorder = AudioRecorder(
        sample_rate=16000,
        energy_threshold=config.vad.energy_threshold,
        silence_duration=0.8,
        max_record_seconds=15.0,
        barge_in=True,
        barge_in_sensitivity=config.vad.barge_in_sensitivity,
        vad_engine=getattr(config.vad, "engine", "auto"),
        speech_threshold=getattr(config.vad, "speech_threshold", 0.5),
    )

    barge_in_triggered = False
    speech_detected = False

    def on_barge():
        nonlocal barge_in_triggered
        barge_in_triggered = True
        print(
            "\n⚡ [BARGE-IN TRIGGERED] Silero neural VAD confirmed user speech -> Audio playback terminated!"
        )

    def on_speech_start():
        nonlocal speech_detected
        speech_detected = True
        print("🎙️ [SPEECH ONSET] Recording user interruption prompt...")

    def speak_in_background():
        try:
            tts = get_tts_engine(config, agent_name="BargeInTest", voice_override=resolved_voice)
            tts.speak(test_phrase, block=True)
        except Exception as e:
            print(f"[TTS] Playback notice: {e}")

    print("\n🔊 Starting agent speech playback...")
    tts_thread = threading.Thread(target=speak_in_background, daemon=True)
    tts_thread.start()

    time.sleep(0.3)
    print("🔴 Live mic monitoring active with Silero VAD (speak now to interrupt)...\n")

    audio_data, wav_path = recorder.record_speech_auto(
        on_barge_in=on_barge,
        on_speech_start=on_speech_start,
    )

    stop_all_speech()

    print("\n" + "=" * 65)
    print("📊 Test Summary:")
    if barge_in_triggered:
        print("✅ Barge-In Status:   SUCCESSFULLY TRIGGERED & INTERRUPTED")
    else:
        print("ℹ️  Barge-In Status:   Not triggered (agent completed phrase without interruption)")

    dur = len(audio_data) / 16000.0
    print(f"⏱️  Captured Audio:   {dur:.2f} seconds")

    if dur > 0.3 and speech_detected:
        print("📝 Transcribing user speech with Whisper...")
        try:
            stt = WhisperLocalSTT()
            transcript = stt.transcribe(wav_path)
            if transcript:
                print(f'💬 You said:         "{transcript}"')
        except Exception as ex:
            print(f"⚠️  Transcription note: {ex}")

    if wav_path.exists():
        wav_path.unlink(missing_ok=True)

    print("=" * 65 + "\n")


def cmd_ping(args):
    """Silently test voice connection, latency, speed, and health."""
    args.voice_action = "ping"
    cmd_voice(args)


def run_silent_voice_ping(args, config):
    """Execute silent voice connection, latency, speed, and health diagnostics."""
    import json
    from voicefi.troubleshoot import AudioTroubleshooter, TEST_PHRASES
    from voicefi.tts import CURATED_PERSONAS, find_persona

    troubleshooter = AudioTroubleshooter(config)
    as_json = getattr(args, "json", False)
    all_personas = getattr(args, "all", False)
    sample_text = (
        getattr(args, "text", None) or "VoiceFi silent neural voice connection and speed test."
    )
    count = getattr(args, "count", 1) or 1
    provider = getattr(args, "provider", None)
    rate = getattr(args, "rate", None)

    if all_personas:
        if not as_json:
            print("\n🌐 VoiceFi Neural Voice Connection & Speed Benchmark (Silent)\n")
            print(
                f"{'Persona':<14} {'ID / Voice':<28} {'Provider':<10} {'Status':<18} {'Latency':<10} {'Speed':<16} {'Payload'}"
            )
            print("-" * 108)

        results = []
        for p in CURATED_PERSONAS:
            res = troubleshooter.ping_voice_silently(
                voice_name_or_id=p.id,
                text=sample_text,
                provider=p.provider,
            )
            results.append(res.to_dict())
            if not as_json:
                status_icon = "🟢" if res.success else "🔴"
                if res.status == "online":
                    status_desc = "Online (200)"
                elif res.status == "offline_native":
                    status_desc = "Offline Native"
                elif res.status == "rate_limited":
                    status_desc = "Throttled (429)"
                else:
                    status_desc = "Error"
                status_col = f"{status_icon} {status_desc}"
                lat_str = f"{res.latency_ms:.1f} ms" if res.success else "Failed"
                speed_str = f"{res.chars_per_sec:.1f} chars/s" if res.success else "N/A"
                size_str = f"{res.audio_bytes / 1024.0:.1f} KB" if res.success else "0 KB"
                print(
                    f"{p.name:<14} {p.id:<28} {p.provider:<10} {status_col:<18} {lat_str:<10} {speed_str:<16} {size_str}"
                )

        if as_json:
            print(json.dumps({"status": "success", "benchmark": results}, indent=2))
        else:
            print("-" * 108)
            successful_lats = [r["latency_ms"] for r in results if r["success"]]
            avg_lat = sum(successful_lats) / max(len(successful_lats), 1)
            print(
                f"✨ Benchmark complete. Curated voices tested: {len(results)} | Avg Latency: {avg_lat:.1f} ms | Zero audio emitted.\n"
            )
        return

    # Single voice or target voice
    target_voice = getattr(args, "voice", None) or config.tts.voice
    persona = find_persona(target_voice)
    resolved_voice = persona.id if persona else target_voice
    resolved_name = persona.name if persona else target_voice
    resolved_provider = provider or (persona.provider if persona else config.tts.provider)

    if count > 1:
        stats = troubleshooter.ping_multiple_silently(
            voice_name_or_id=resolved_voice,
            count=count,
            text=sample_text,
            provider=resolved_provider,
            rate=rate,
        )
        if as_json:
            print(json.dumps(stats, indent=2))
            return

        print("\n🌐 VoiceFi Silent Connection & Speed Test")
        print(f"🎙️ Target: {resolved_name} (`{resolved_voice}`) | Provider: {resolved_provider}\n")
        for idx, p in enumerate(stats["pings"], start=1):
            s_icon = "🟢" if p["success"] else "🔴"
            s_desc = (
                "200 OK"
                if p["status"] == "online"
                else (
                    "Offline Native"
                    if p["status"] == "offline_native"
                    else ("429 Rate Limit" if p["status"] == "rate_limited" else "Error")
                )
            )
            size_kb = p["audio_bytes"] / 1024.0
            print(
                f"  • Ping {idx}: {s_icon} {s_desc:<14} — Latency: {p['latency_ms']:>6.1f} ms | Speed: {p['chars_per_sec']:>6.1f} chars/s ({p['words_per_min']:>5.0f} WPM) | Size: {size_kb:.1f} KB"
            )

        print(f"\n📊 Summary Statistics ({count} pings):")
        print(
            f"  • Success Rate:    {stats['success_rate_pct']}% ({stats['success_count']}/{count})"
        )
        if stats["success_count"] > 0:
            print(
                f"  • Latency (TTFB):  min = {stats['min_latency_ms']} ms | avg = {stats['avg_latency_ms']} ms | max = {stats['max_latency_ms']} ms (jitter: ±{stats['jitter_ms']} ms)"
            )
            print(f"  • Avg Throughput:  {stats['avg_chars_per_sec']} chars/s")
            print("  • Connection:      🟢 Operational & responsive (zero speaker sound)\n")
        else:
            print(f"  • Errors:          {stats.get('errors')}\n")
        return

    # Single ping
    res = troubleshooter.ping_voice_silently(
        voice_name_or_id=resolved_voice,
        text=sample_text,
        provider=resolved_provider,
        rate=rate,
    )
    if as_json:
        print(json.dumps(res.to_dict(), indent=2))
        return

    print("\n🌐 VoiceFi Silent Connection & Speed Test")
    print(f"🎙️ Voice: {resolved_name} (`{resolved_voice}`) | Provider: {resolved_provider}")
    if res.success:
        status_icon = "🟢"
        status_label = (
            "200 OK (Online)" if res.status == "online" else "Offline Native (macOS Apple Silicon)"
        )
        size_kb = res.audio_bytes / 1024.0
        print(f"  • Status:      {status_icon} {status_label}")
        print(f"  • Latency:     {res.latency_ms:.1f} ms roundtrip synthesis")
        print(
            f"  • Speed:       {res.chars_per_sec:.1f} chars/sec (~{res.words_per_min:.0f} WPM equivalent)"
        )
        print(f"  • Audio Size:  {size_kb:.1f} KB ({res.audio_bytes} bytes)")
        print("  • Audio Check: ✅ Silent synthesis verified (no speaker playback)\n")
    else:
        status_label = (
            "429 Too Many Requests (Rate Limited)"
            if res.status == "rate_limited"
            else f"Failed ({res.error})"
        )
        print(f"  • Status:      🔴 {status_label}")
        print(f"  • Latency:     {res.latency_ms:.1f} ms")
        print(f"  • Error:       {res.error}\n")


