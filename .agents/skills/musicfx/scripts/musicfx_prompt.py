#!/usr/bin/env python3
"""
MusicFX Prompt Generator & Chip Optimizer.
Generates structured, tokenized MusicFX prompts with anti-vocal guardrails and BPM targeting.
"""

import argparse
import sys

PRESETS = {
    "maybelline_90s": {
        "title": "1990s Maybelline Commercial Jingle",
        "bpm": 85,
        "chips": [
            "Early 1990s luxury cosmetics television commercial jingle bumper",
            "Fender Rhodes electric piano with warm stereo chorus and gentle tremolo",
            "Sparkling FM synthesizer bells",
            "Crystalline glass chimes on turnaround resolve",
            "Smooth fretless bassline",
            "Soft R&B finger snaps",
            "Lush warm analog synth pad swells",
            "Daytime television glamour",
            "Sensual slow-motion fashion aesthetic",
            "Pristine studio master",
            "85 BPM"
        ],
        "guardrail": "Strictly instrumental, wordless backing track, zero vocals, no singing, no choir, no human voice."
    },
    "upbeat_97": {
        "title": "Late-90s Upbeat TV Commercial Bed",
        "bpm": 96,
        "chips": [
            "Late 1990s daytime television beauty commercial bumper",
            "Bright FM synthesizer piano",
            "Crisp 90s pop drum groove with tight snare rimshot",
            "Punchy melodic bassline",
            "Shimmering wind chimes",
            "Uplifting two-chord melodic rise and sparkling glockenspiel resolve",
            "Polished broadcast audio",
            "Glossy radiant high-energy fashion aesthetic",
            "96 BPM"
        ],
        "guardrail": "Strictly instrumental, no singing, no vocals, no choir, wordless commercial jingle bed."
    },
    "luxury_minimalist": {
        "title": "High-End Luxury Editorial Minimalist",
        "bpm": 75,
        "chips": [
            "High-fashion luxury cosmetics editorial bumper",
            "Lush solo Rhodes chords drenched in warm hall reverb",
            "Deep gentle sub-bass pulse",
            "Airy ambient textures",
            "Single crystalline glass chime accent on turnaround",
            "Minimalist elegant mysterious",
            "Slow tempo unhurried pacing",
            "Audiophile studio master"
        ],
        "guardrail": "Instrumental only, completely wordless, zero vocals, no singing, no humming."
    },
    "quiet_storm": {
        "title": "1992 Quiet Storm R&B Groove",
        "bpm": 84,
        "chips": [
            "1992 smooth R&B commercial jingle instrumental",
            "Silky Yamaha DX7 electric piano bell tones",
            "Warm vintage synth pad",
            "Delicate tambourine",
            "Soft kick and finger snaps",
            "Smooth walking bassline",
            "Catchy two-phrase commercial hook structure",
            "Twinkling bell tree chime at cadence",
            "84 BPM",
            "Vintage broadcast aesthetic"
        ],
        "guardrail": "100% instrumental, no human voices, no vocal chops, wordless backing track."
    }
}

def main():
    parser = argparse.ArgumentParser(description="Generate and format MusicFX prompts with optimal token chips.")
    parser.add_argument("preset", nargs="?", default="maybelline_90s", choices=list(PRESETS.keys()) + ["all"],
                        help="Preset name (default: maybelline_90s) or 'all'")
    args = parser.parse_args()

    selected = PRESETS.keys() if args.preset == "all" else [args.preset]

    print("\n" + "="*70)
    print("🎵 MusicFX Prompt Generator — VoiceFi™")
    print("="*70)

    for key in selected:
        data = PRESETS[key]
        full_prompt = ", ".join(data["chips"]) + ". " + data["guardrail"]
        print(f"\n📌 Preset: {data['title']} ({key})")
        print(f"⏱️  BPM: {data['bpm']}")
        print(f"🎛️  Interactive Chips ({len(data['chips'])} pills to circle in DJ Mode):")
        for chip in data["chips"]:
            print(f"   • [{chip}]")
        print(f"\n📋 Full Copy-Paste Prompt:")
        print(f"   \"{full_prompt}\"")
        print("-" * 70)

if __name__ == "__main__":
    main()
