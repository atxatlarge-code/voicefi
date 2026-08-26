#!/usr/bin/env python3
"""
Live Interactive Active Barge-In & Silero VAD Test Studio.
Speaks aloud through speakers / headphones while actively monitoring the microphone with Silero VAD.
When you speak into the microphone, it instantly halts audio playback and transcribes what you said.
"""

import sys
import time
import threading
from pathlib import Path

# Add src to python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from voicefi.config import load_config
from voicefi.audio.recorder import AudioRecorder
from voicefi.tts import get_tts_engine, stop_all_speech
from voicefi.tts.base import is_agent_speaking, set_agent_speaking, set_agent_audio_playing
from voicefi.audio.device import get_audio_device_profile
from voicefi.stt.whisper_local import WhisperLocalSTT


def main():
    config = load_config()
    prof = get_audio_device_profile()

    print("\n" + "=" * 65)
    print("⚡ VoiceFi Active Voice Barge-In & Silero VAD Live Test")
    print("=" * 65)
    print(f"🎙️  Microphone:      {prof.get('default_input') or 'Default'}")
    print(f"🔊 Output:          {prof.get('default_output') or 'Default'}")
    print(f"🎧 Device Type:     {'Headphones / AirPods ✅' if prof.get('is_headphones_active') else 'Built-in Laptop Speakers (Acoustic Safe Mode)'}")
    print(f"🧠 VAD Engine:      {getattr(config.vad, 'engine', 'silero').upper()} (Threshold: {getattr(config.vad, 'speech_threshold', 0.5)})")
    print("-" * 65)
    print("👉 HOW THIS TEST WORKS:")
    print("   1. VoiceFi will speak a long phrase aloud through your speakers/headphones.")
    print("   2. While it speaks, Silero VAD is actively listening on your microphone.")
    print("   3. Speak firmly into your microphone (e.g. 'Hey VoiceFi, stop right now!').")
    print("   4. Agent speech will INSTANTLY cut off and transcribe your interruption.")
    print("-" * 65)

    test_phrase = (
        "This is a live acoustic barge-in test with Silero VAD. "
        "I am going to keep speaking aloud for several seconds about system architecture, "
        "recurrent neural networks, and real-time audio streams. "
        "Whenever you are ready, speak firmly into your microphone to interrupt me!"
    )

    recorder = AudioRecorder(
        sample_rate=16000,
        energy_threshold=config.vad.energy_threshold,
        silence_duration=0.8,
        max_record_seconds=15.0,
        barge_in=True,  # Test active barge in
        barge_in_sensitivity=config.vad.barge_in_sensitivity,
        vad_engine=getattr(config.vad, "engine", "auto"),
        speech_threshold=getattr(config.vad, "speech_threshold", 0.5),
    )

    tts = get_tts_engine(config, agent_name="BargeInTest")
    barge_in_triggered = False
    speech_detected = False

    def on_barge():
        nonlocal barge_in_triggered
        barge_in_triggered = True
        print("\n⚡ [BARGE-IN TRIGGERED] Silero neural VAD confirmed user speech -> Audio playback terminated!")
        tts.stop()
        stop_all_speech()

    def on_speech_start():
        nonlocal speech_detected
        speech_detected = True
        print("🎙️ [SPEECH ONSET] Recording user interruption prompt...")

    def speak_in_background():
        try:
            tts.speak(test_phrase, block=True)
        except Exception as e:
            print(f"[TTS] Error during playback: {e}")

    # Launch TTS in background thread
    print("\n🔊 Starting agent speech playback...")
    tts_thread = threading.Thread(target=speak_in_background, daemon=True)
    tts_thread.start()

    # Small delay to ensure audio stream is initialized
    time.sleep(0.3)

    def on_tick(energy: float, conf: float = 0.0, is_spk: bool = False):
        bars = int(min(energy * 350, 25))
        meter = "█" * bars + "░" * (25 - bars)
        state_str = "🔊 SPEAKING" if is_spk else "🎙️ LISTENING"
        sys.stdout.write(f"\r[{state_str}] Energy: {energy:.4f} | Conf: {conf:.2f} | [{meter}] ")
        sys.stdout.flush()

    audio_data, wav_path = recorder.record_speech_auto(
        on_barge_in=on_barge,
        on_speech_start=on_speech_start,
        on_listening_tick=on_tick,
    )

    # Ensure all speech is killed
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
            print(f"💬 You said:         \"{transcript}\"")
        except Exception as ex:
            print(f"⚠️  Transcription note: {ex}")

    # Cleanup temp wav
    if wav_path.exists():
        wav_path.unlink(missing_ok=True)

    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
