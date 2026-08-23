"""
Guided Interactive Voice Training Wizard for VoiceFi.
Speaks each training prompt aloud, plays chime cues, captures audio samples with VAD,
trains the acoustic profile, and assigns it to Antigravity.
"""

import time
import sys
from pathlib import Path
from voicefi.config import load_config
from voicefi.tts import get_tts_engine
from voicefi.audio.recorder import AudioRecorder
from voicefi.audio.chimes import play_chime
from voicefi.tts.cloning import VoiceCloneManager, TRAINING_PROMPTS


def run_guided_training(name: str = "Jake", target_agent: str = "antigravity"):
    config = load_config()
    tts = get_tts_engine(config)
    manager = VoiceCloneManager()

    print(f"\n🎙️ Starting Guided Voice Training for: '{name}'")
    print("=" * 65)

    intro = f"Welcome to VoiceFi voice training. I will read each phrase aloud. When you hear the chime, repeat the phrase into your microphone."
    print(f"🔊 {intro}")
    tts.speak(intro, block=True)
    time.sleep(0.5)

    recorder = AudioRecorder(
        sample_rate=16000,
        energy_threshold=0.004,
        silence_duration=1.2,
        max_record_seconds=20.0,
        barge_in=False,
    )
    recorded_files = []

    for i, p in enumerate(TRAINING_PROMPTS):
        prompt_intro = f"Phrase {i+1} of {len(TRAINING_PROMPTS)}: {p['text']}"
        print(f"\n[{i+1}/{len(TRAINING_PROMPTS)}] {p['title']}")
        print(f"👉 \"{p['text']}\"")

        tts.speak(prompt_intro, block=True)
        time.sleep(0.3)

        if config.audio_cues.enabled:
            play_chime("start", block=True)

        print("🔴 Recording... (speak now)")
        _, wav_path = recorder.record_speech_auto(
            on_speech_start=lambda: print("🗣️ Speech detected..."),
        )
        recorded_files.append(wav_path)
        print(f"✅ Sample {i+1} captured.")
        time.sleep(0.5)

    print("\n🧠 Analyzing acoustic features (F0 pitch, cadence, formant profile)...")
    tts.speak("Analyzing your vocal profile and training your custom persona.", block=True)

    try:
        profile = manager.train_voice(
            name=name,
            sample_paths=recorded_files,
            api_key=config.tts.elevenlabs_api_key,
            description=f"Authentic voice of {name}",
        )
        print(f"\n✨ Voice Profile Calibrated!")
        print(f"  • Name:        {profile.name}")
        print(f"  • Vocal Range: {profile.acoustic_metrics.get('vocal_range', 'Natural')}")
        print(f"  • Avg Pitch:   {profile.acoustic_metrics.get('avg_pitch_hz')} Hz")
        print(f"  • Duration:    {profile.acoustic_metrics.get('total_duration_seconds')}s")

        manager.assign_to_agent(profile.name, target_agent, config)
        print(f"  • Assigned to: {target_agent}")

        # Audition newly calibrated voice
        test_speech = f"Hey {name}! Your voice profile is trained and active. I am now pair programming with your calibrated voice."
        print(f"\n🔊 Auditioning new voice for {name}...")
        new_engine = get_tts_engine(config, agent_name=target_agent)
        new_engine.speak(test_speech, block=True)
        print("🎉 Voice training session complete!\n")
    finally:
        for f in recorded_files:
            try:
                Path(f).unlink(missing_ok=True)
            except Exception:
                pass


if __name__ == "__main__":
    target_name = sys.argv[1] if len(sys.argv) > 1 else "Jake"
    run_guided_training(name=target_name)
