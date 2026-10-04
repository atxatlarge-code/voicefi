#!/usr/bin/env python3
"""
Audition true neural reference clones for Christopher Walken - The Continental character.
Synthesizes and plays takes aloud through MacBook speakers via macOS CoreAudio
under the exclusive_audio output mutex with zero audience laughter.
"""

import os
import sys
import time
from pathlib import Path

# Add project src to path
sys.path.insert(0, "/Users/jaketrigg/Projects/VoiceFi/src")

from voicefi.audio.output_lock import exclusive_audio
from voicefi.tts.voice_acting import VoiceActingTTS
from voicefi.tts.director import TheatricalDirector

CANDIDATES = [
    {
        "id": "take_01_continental_bubble",
        "name": "The Continental (Bubble Monologue - SNL Authentic)",
        "ref_audio": "/Users/jaketrigg/.voicefi/cloned_voices/christopher_walken/continental/ref_continental_bubble.wav",
        "ref_text": "Each bubble like the story of one life. Would you like to hear my story?",
        "line": "Wow... look at you. Champagne... and a clean build. Does it get any better? I don't think so.",
        "speed": 0.92,
        "description": "Authentic SNL sketch seed: velvet robe, intimate breathy rasp, low-energy suave absurdity.",
    },
    {
        "id": "take_02_continental_flyer",
        "name": "The Continental (Kinko's Flyer - SNL Authentic)",
        "ref_audio": "/Users/jaketrigg/.voicefi/cloned_voices/christopher_walken/continental/ref_continental_flyer.wav",
        "ref_text": "Oh, you got my flyer. I made them myself at Kinko's.",
        "line": "Wow... look at you. Champagne... and a clean build. Does it get any better? I don't think so.",
        "speed": 0.92,
        "description": "Authentic SNL sketch seed: conversational rasp and hushed comedic confidence.",
    },
    {
        "id": "take_03_walken_punchy_24k",
        "name": "Walken Punchy 24k (Continental Directing)",
        "ref_audio": "/Users/jaketrigg/.voicefi/cloned_voices/christopher_walken/samples/sample_walken_punchy_24k.wav",
        "ref_text": "Look, why would you pay for voice when you can have it for free?",
        "line": "Wow... look at you. Champagne... and a clean build. Does it get any better? I don't think so.",
        "speed": 0.92,
        "description": "High-clarity 24kHz studio seed: crisp consonants, directed with Continental pauses.",
    },
    {
        "id": "take_04_walken_baritone_s2",
        "name": "Walken Deep Baritone S2 (Continental Directing)",
        "ref_audio": "/Users/jaketrigg/.voicefi/cloned_voices/christopher_walken/samples/sample_s2_clean.wav",
        "ref_text": "And so it makes sense that you get hired because you have demonstrated that whatever it is you do.",
        "line": "Wow... look at you. Champagne... and a clean build. Does it get any better? I don't think so.",
        "speed": 0.92,
        "description": "Deep warm baritone seed: resonant chest tones with theatrical Walken cadences.",
    },
    {
        "id": "take_05_snl_cowbell",
        "name": "Bruce Dickinson / SNL Cowbell (High Energy Contrast)",
        "ref_audio": "/Users/jaketrigg/.voicefi/cloned_voices/christopher_walken/samples/sample_cowbell_snl.wav",
        "ref_text": "Guess what? I got a fever, and the only prescription is more cowbell.",
        "line": "Guess what? I got a fever! And the only prescription... is merging this branch right now!",
        "speed": 0.98,
        "description": "Iconic high-energy SNL reference for acoustic contrast against The Continental.",
    },
]

out_dir = Path("/Users/jaketrigg/.voicefi/cloned_voices/christopher_walken/auditions")
out_dir.mkdir(parents=True, exist_ok=True)


def run_audition(interactive: bool = False):
    print("=" * 70)
    print("🎭 VOICEFI VOICE AUDITION: CHRISTOPHER WALKEN (THE CONTINENTAL)")
    print("⚡ Engine: MLX Qwen3-TTS Base 0.6B (Metal GPU • Apache 2.0)")
    print("🔇 SFX Mode: Zero audience laughter (100% dry acoustic voice)")
    print("🔊 Output: macOS CoreAudio via exclusive_audio output mutex")
    print("=" * 70)

    for i, c in enumerate(CANDIDATES, 1):
        print(f"\n[{i}/{len(CANDIDATES)}] 🎙️  Candidate: {c['name']}")
        print(f"       Description: {c['description']}")
        print(f"       Reference WAV: {Path(c['ref_audio']).name}")
        print(f"       Spoken Line: \"{c['line']}\"")

        wav_path = out_dir / f"{c['id']}.wav"
        t0 = time.time()

        tts = VoiceActingTTS(
            ref_audio=c["ref_audio"],
            ref_text=c["ref_text"],
            speed=c["speed"],
            intro_sfx=None,  # Guarantee NO audience laughter
            intro_sfx_volume=0.0,
            apply_silk_mastering=True,
        )

        ok = tts.speak_to_file(c["line"], wav_path)
        synth_elapsed = time.time() - t0

        if not ok or not wav_path.exists():
            print("       ❌ Synthesis failed!")
            continue

        import soundfile as sf
        data, sr = sf.read(str(wav_path))
        audio_dur = len(data) / sr
        rtf = synth_elapsed / audio_dur if audio_dur > 0 else 0.0

        print(f"       ✅ Synthesized in {synth_elapsed:.2f}s (Duration: {audio_dur:.2f}s • RTF: {rtf:.2f}x)")
        print("       🔊 Playing aloud through MacBook speakers...")

        # Play aloud under cross-process exclusive_audio lock
        with exclusive_audio(timeout=15.0, owner=f"audition_{c['id']}"):
            import subprocess
            subprocess.run(["afplay", str(wav_path)], check=False)

        # Brief intermission between audition takes
        time.sleep(1.2)

    print("\n" + "=" * 70)
    print("🎉 All Christopher Walken auditions completed successfully!")
    print(f"📂 Audition files saved to: {out_dir}")
    print("=" * 70)


if __name__ == "__main__":
    run_audition()
