#!/usr/bin/env python3
"""
Interactive test script for Voicegency TTS, VAD, and STT pipelines.
"""

import sys
from pathlib import Path

# Add src to sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir / "src"))

from voicegency.config import load_config
from voicegency.tts import get_tts_engine
from voicegency.stt import get_stt_engine
from voicegency.audio.recorder import AudioRecorder
from voicegency.audio.chimes import play_chime


def run_interactive_test():
    config = load_config()
    print("\n--- Voicegency Interactive Test Suite ---")
    print(f"Active TTS: {config.tts.provider} ({config.tts.voice})")
    print(f"Active STT: {config.stt.provider} ({config.stt.model_size})")

    # 1. Test TTS
    print("\n[1/3] Testing Text-to-Speech...")
    tts = get_tts_engine(config)
    tts.speak("Hello! Voicegency is initialized and ready.", block=True)
    print("✓ TTS playback finished.")

    # 2. Test Chimes
    print("\n[2/3] Testing Audio Feedback Chimes...")
    play_chime("start", block=True)
    play_chime("done", block=True)
    print("✓ Audio chimes played.")

    # 3. Test Mic & STT
    print("\n[3/3] Testing Microphone & Speech Recognition...")
    print("👉 Please speak a sentence into your microphone now...")
    play_chime("start", block=False)

    recorder = AudioRecorder(
        sample_rate=config.vad.sample_rate,
        energy_threshold=config.vad.energy_threshold,
        silence_duration=config.vad.silence_duration,
    )
    audio_data, temp_wav = recorder.record_speech_auto(
        on_speech_start=lambda: print("🗣️ Speech detected...")
    )

    print("Transcribing with Whisper...")
    stt = get_stt_engine(config)
    try:
        text = stt.transcribe(temp_wav)
        play_chime("done", block=False)
        print(f"\n🎉 Successfully Transcribed: '{text}'")
    finally:
        temp_wav.unlink(missing_ok=True)

    print("\n--- Test Completed Successfully! ---")


if __name__ == "__main__":
    run_interactive_test()
