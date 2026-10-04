#!/usr/bin/env python3
"""
Generate and audition 8 iconic Christopher Walken voice character lines.
Saves each character to ~/.voicefi/cloned_voices/christopher_walken/auditions/<char_name>.wav
and plays each audio file aloud sequentially over macOS CoreAudio.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, "/Users/jaketrigg/Projects/VoiceFi/src")

from voicefi.tts.f5_tts import F5TTS

CHARACTERS = [
    {
        "id": "01_the_continental",
        "name": "The Continental",
        "ref_audio": "/Users/jaketrigg/.voicefi/cloned_voices/christopher_walken/samples/sample_walken_why_pay_24k.wav",
        "ref_text": "Look, why would you pay for voice when you can have it for free? That's crazy.",
        "line": "Wow... look at you. Champagne... and a clean build. Does it get any better? I don't think so.",
        "speed": 0.95,
        "nfe_step": 24,
    },
    {
        "id": "02_the_census_taker",
        "name": "The Census Taker",
        "ref_audio": "/Users/jaketrigg/.voicefi/cloned_voices/christopher_walken/samples/sample_walken_warm_24k.wav",
        "ref_text": "Look, why would you pay for voice when you can have it for free?",
        "line": "How many errors left in this branch? Counting me? Approximately... zero. That's nice.",
        "speed": 0.92,
        "nfe_step": 24,
    },
    {
        "id": "03_captain_koons",
        "name": "Captain Koons (The Watch)",
        "ref_audio": "/Users/jaketrigg/.voicefi/cloned_voices/christopher_walken/samples/sample_01_clean.wav",
        "ref_text": "Movies are a very pragmatic, efficient business in that respect. And so it makes sense that you get hired because you have demonstrated that whatever it is you do.",
        "line": "Five long minutes... I held this function in my repository... and now... I give it to you.",
        "speed": 0.90,
        "nfe_step": 24,
    },
    {
        "id": "04_the_florist",
        "name": "The Florist (Googly Eyes)",
        "ref_audio": "/Users/jaketrigg/.voicefi/cloned_voices/christopher_walken/samples/sample_walken_why_pay_24k.wav",
        "ref_text": "Look, why would you pay for voice when you can have it for free? That's crazy.",
        "line": "I put googly eyes... on your microservices. That way... I know where I stand with them.",
        "speed": 0.95,
        "nfe_step": 24,
    },
    {
        "id": "05_the_lion",
        "name": "The Street Philosopher (The Lion)",
        "ref_audio": "/Users/jaketrigg/.voicefi/cloned_voices/christopher_walken/samples/sample_01_clean.wav",
        "ref_text": "Movies are a very pragmatic, efficient business in that respect. And so it makes sense that you get hired because you have demonstrated that whatever it is you do.",
        "line": "You see... a lion... he doesn't worry about unit tests. He waits... and then... bam. Clean compile.",
        "speed": 0.92,
        "nfe_step": 24,
    },
    {
        "id": "06_frank_abagnale",
        "name": "Frank Abagnale Sr. (Two Mice)",
        "ref_audio": "/Users/jaketrigg/.voicefi/cloned_voices/christopher_walken/samples/sample_walken_warm_24k.wav",
        "ref_text": "Look, why would you pay for voice when you can have it for free?",
        "line": "Two little mice fell in a bucket of cream. One mouse wrote unit tests... and churned that cream into butter.",
        "speed": 0.94,
        "nfe_step": 24,
    },
    {
        "id": "07_the_showman",
        "name": "The Showman (Weapon of Choice)",
        "ref_audio": "/Users/jaketrigg/.voicefi/cloned_voices/christopher_walken/samples/sample_walken_why_pay_24k.wav",
        "ref_text": "Look, why would you pay for voice when you can have it for free? That's crazy.",
        "line": "Look at that... it passed. Boom. Just like that. I feel like dancing... a little tap.",
        "speed": 0.96,
        "nfe_step": 24,
    },
    {
        "id": "08_bruce_dickinson",
        "name": "Bruce Dickinson (More Cowbell)",
        "ref_audio": "/Users/jaketrigg/.voicefi/cloned_voices/christopher_walken/samples/sample_cowbell_snl.wav",
        "ref_text": "Guess what? I got a fever, and the only prescription is more cowbell.",
        "line": "Guess what? I got a fever! And the only prescription... is merging this branch right now!",
        "speed": 1.0,
        "nfe_step": 24,
    },
]

out_dir = Path("/Users/jaketrigg/.voicefi/cloned_voices/christopher_walken/auditions")
out_dir.mkdir(parents=True, exist_ok=True)

print("🎭 Initializing F5-TTS model on Apple Silicon Metal GPU...")
engine = F5TTS.get_f5_instance("F5TTS_v1_Base", device="auto")

print(f"\n🚀 Synthesizing and auditioning {len(CHARACTERS)} Walken characters...")
print("=" * 65)

for i, char in enumerate(CHARACTERS, 1):
    char_id = char["id"]
    char_name = char["name"]
    wav_path = out_dir / f"{char_id}.wav"
    line_text = char["line"]

    print(f"\n[{i}/{len(CHARACTERS)}] 🎙️  Character: {char_name}")
    print(f'       Line: "{line_text}"')

    t0 = time.time()
    tts_obj = F5TTS(
        ref_audio=char["ref_audio"],
        ref_text=char["ref_text"],
        speed=char["speed"],
        nfe_step=char["nfe_step"],
    )
    success = tts_obj.speak_to_file(line_text, wav_path)
    dur = time.time() - t0

    if success and wav_path.exists():
        print(f"       ✅ Synthesized in {dur:.2f}s -> {wav_path.name}")
        # Announce and play audio aloud over CoreAudio
        print("       🔊 Playing aloud...")
        subprocess.run(["afplay", str(wav_path)], check=False)
    else:
        print(f"       ❌ Failed to synthesize {char_name}")

print("\n" + "=" * 65)
print("🎉 All 8 Walken character auditions complete!")
