#!/usr/bin/env python3
"""
scripts/generate_audio_comparison.py
Generates side-by-side audio comparison files:
1. Baseline: Flat single-voice TTS reading the entire script as a single monologue.
2. Stage 2: Multi-speaker dialogue (Viv & Jake) with calibrated turn pauses and ducked backing music.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from voicefi.factory.audio_synth import ContentAudioSynthesizer
from voicefi.factory.generator import LocalContentGenerator
from voicefi.factory.models import ContentJob

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("voicefi.comparison")


def main():
    out_dir = Path("build/comparison")
    out_dir.mkdir(parents=True, exist_ok=True)

    generator = LocalContentGenerator()
    synth = ContentAudioSynthesizer()

    # Backing track
    backing_track = Path("build/companion_static/downloads/spicewood_texas_beat_85bpm.mp3")
    if not backing_track.exists():
        backing_track = Path(
            "/Users/jaketrigg/Projects/vifi.co/marketing/social/assets/spicewood_texas_beat_85bpm.mp3"
        )

    logger.info("Generating punchy on-device vs cloud debate dialogue using local Ollama model...")
    job = ContentJob(
        id="comp_01",
        title="Local vs Cloud Showdown",
        prompt="Viv and Jake have a quick, lively debate on why running AI models locally on Apple Silicon beats cloud APIs for overnight tests.",
        characters=["Viv", "Jake"],
        target_duration_s=25,
    )

    manifest, tokens_saved, gen_sec = generator.generate_manifest(job)
    logger.info(f"Script ready in {gen_sec:.2f}s: '{manifest.title}' ({len(manifest.turns)} turns)")
    for idx, t in enumerate(manifest.turns):
        logger.info(f"  Turn {idx + 1} [{t.speaker}] ({t.emotion}): {t.text}")

    # =========================================================================
    # 1. Generate Baseline (Flat Single-Voice Monologue)
    # =========================================================================
    logger.info("\n--- Generating Baseline File (Flat Single-Voice Monologue) ---")
    t0 = time.time()
    baseline_mp3 = out_dir / "baseline_monotone_raw.mp3"
    ok_base = synth.synthesize_baseline_monotone(
        manifest, baseline_mp3, single_voice="en-US-JennyNeural"
    )
    base_sec = time.time() - t0
    logger.info(
        f"Baseline generated in {base_sec:.2f}s -> {baseline_mp3} ({baseline_mp3.stat().st_size} bytes)"
    )

    # =========================================================================
    # 2. Generate Stage 2 (Multi-Speaker Turn Synthesis + Conversational Pauses + Ducking)
    # =========================================================================
    logger.info(
        "\n--- Generating Stage 2 Mastered Audio (Multi-Speaker + Pauses + Ducked Beat) ---"
    )
    t0 = time.time()
    stage2_res = synth.synthesize_manifest(
        manifest=manifest,
        output_dir=out_dir / "stage2",
        backing_track_path=backing_track if backing_track.exists() else None,
    )
    stage2_sec = time.time() - t0
    logger.info(f"Stage 2 generated in {stage2_sec:.2f}s -> {stage2_res.get('master_mix_mp3')}")

    # Copy the final stage 2 master mp3 to out_dir for easy access
    final_stage2_mp3 = out_dir / "stage2_multispeaker_mastered.mp3"
    if stage2_res.get("master_mix_mp3"):
        import shutil

        shutil.copy2(stage2_res["master_mix_mp3"], final_stage2_mp3)

    print("\n" + "=" * 70)
    print("🎧 VOICEFI A/B AUDIO COMPARISON READY")
    print("=" * 70)
    print(f"Script Title: {manifest.title}")
    print(f"Turns:        {len(manifest.turns)} dialogue turns")
    print("-" * 70)
    print("1️⃣  BASELINE (Raw Generic Monologue):")
    print(f"    Path:     {baseline_mp3.resolve()}")
    print("    Voice:    Single voice (Jenny), no character chemistry, zero music, flat pace.")
    print(f"    Size:     {baseline_mp3.stat().st_size} bytes")
    print("")
    print("2️⃣  STAGE 2 (VoiceFi Multi-Speaker Mastered Mix):")
    print(f"    Path:     {final_stage2_mp3.resolve()}")
    print("    Voices:   Viv (AvaNeural) + Jake (AndrewNeural)")
    print("    Features: Individual character formants, 140ms conversational gaps,")
    print("              and sidechain ducking over 85 BPM Spicewood Texas beat.")
    print(f"    Size:     {final_stage2_mp3.stat().st_size} bytes")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
