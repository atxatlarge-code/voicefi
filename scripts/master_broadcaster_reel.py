#!/usr/bin/env python3
"""
Master Audio & Video Assembly Engine for VoiceFi Reel (v7).
- 48-Pass Attenborough Neural Clone delivers both key lines:
  1. Opening tag-team (3.76s - 10.17s):
     User: "All right y'all, look how easy I made it to..."
     Attenborough: "...have a broadcaster voice. Quite remarkable, really. A single command... and the machine speaks."
     User: "It's a one-line command, so you just call vifi reel --doc --script..."
  2. Late feature tag (62.12s - 63.54s):
     User: "...and have refined..."
     Attenborough: "...this broadcaster voice..."
     User: "...as the first main one to roll out, and of course this is all open source."
- Continuous instrumental 85 BPM beat with zero vocal intros/restarts.
- Sharp cutoff right after "Out here we in outlaw country, just for outlaw sake. End."
"""

import os
import sys
import subprocess
import numpy as np
import scipy.signal as signal
import soundfile as sf

# Paths
VIDEO_INPUT = "/Users/jaketrigg/Downloads/PXL_20260916_160530265.mp4"
VIDEO_OUTPUT = "/Users/jaketrigg/Downloads/voicefi_broadcaster_reel_master.mp4"

SPICEWOOD_MASTER = "/Users/jaketrigg/Projects/VoiceFi/src/voicefi/companion/static/downloads/spicewood_outlaws_full_master_audio.mp3"
SPICEWOOD_BEAT = "/Users/jaketrigg/Projects/VoiceFi/src/voicefi/companion/static/downloads/spicewood_texas_beat_85bpm.mp3"

ATTENBOROUGH_INTRO = "/tmp/intro_66s.wav"
ATTENBOROUGH_TAKE2 = "/tmp/attenborough_take2_48.wav"

TEMP_DIR = "/tmp/voicefi_reel_build"
os.makedirs(TEMP_DIR, exist_ok=True)

SAMPLE_RATE = 48000


def run(cmd):
    subprocess.run(cmd, shell=True, check=True)


def extract_original_audio(video_path, out_wav):
    print("▶️ Extracting original audio from video...")
    cmd = f'ffmpeg -y -i "{video_path}" -vn -acodec pcm_s16le -ar {SAMPLE_RATE} -ac 2 "{out_wav}"'
    run(cmd)


def trim_speech(audio, sr, threshold=0.015, pad_start=0.04, pad_end=0.06):
    """Trims leading and trailing silence from recorded audio."""
    energy = np.abs(audio)
    if audio.ndim == 2:
        energy = np.max(energy, axis=1)
    voiced = np.where(energy > threshold)[0]
    if len(voiced) > 0:
        start_idx = max(0, voiced[0] - int(pad_start * sr))
        end_idx = min(len(audio), voiced[-1] + int(pad_end * sr))
        return audio[start_idx:end_idx]
    return audio


def replace_dialogue_window(
    dialogue, replacement, room_tone, window_start_t, window_end_t, sr, fade_len=960
):
    """
    Completely wipes out original dialogue in [window_start_t, window_end_t] and fills it with:
    replacement vocal + ambient room tone for the rest of the window.
    """
    start_idx = int(window_start_t * sr)
    end_idx = int(window_end_t * sr)
    total_len = end_idx - start_idx

    rep_count = int(np.ceil(total_len / len(room_tone)))
    bg_tone = np.tile(room_tone, (rep_count, 1))[:total_len] * 0.90

    rep_len = min(len(replacement), total_len)
    splice = bg_tone.copy()
    splice[:rep_len] += replacement[:rep_len]

    fade_len = min(fade_len, total_len // 4)
    fade_in = np.linspace(0.0, 1.0, fade_len)[:, None]
    fade_out = np.linspace(1.0, 0.0, fade_len)[:, None]

    dialogue[start_idx : start_idx + fade_len] = (
        dialogue[start_idx : start_idx + fade_len] * (1.0 - fade_in) + splice[:fade_len] * fade_in
    )
    dialogue[start_idx + fade_len : end_idx - fade_len] = splice[fade_len : total_len - fade_len]
    dialogue[end_idx - fade_len : end_idx] = (
        dialogue[end_idx - fade_len : end_idx] * (1.0 - fade_out)
        + splice[total_len - fade_len : total_len] * fade_out
    )


def assemble():
    orig_wav = os.path.join(TEMP_DIR, "orig_audio.wav")
    extract_original_audio(VIDEO_INPUT, orig_wav)

    dialogue, sr = sf.read(orig_wav)
    if dialogue.ndim == 1:
        dialogue = np.column_stack([dialogue, dialogue])
    total_samples = len(dialogue)
    total_duration = total_samples / sr
    print(f"Original dialogue: {total_duration:.2f}s ({total_samples} samples)")

    # Extract clean room noise from video (6.6s to 7.3s)
    room_noise = dialogue[int(6.6 * sr) : int(7.3 * sr)].copy()

    fade_samples = int(0.020 * sr)  # 20ms crossfade

    # 1. Extended Attenborough Intro Hook (3.76s -> 10.17s):
    # User finishes "to" at 3.76s
    # Attenborough: "...have a broadcaster voice. Quite remarkable, really. A single command... and the machine speaks."
    # Window wiped: 3.76s -> 10.40s
    if os.path.exists(ATTENBOROUGH_INTRO):
        bc_raw, sr_bc = sf.read(ATTENBOROUGH_INTRO)
        if sr_bc != sr:
            tmp_bc = os.path.join(TEMP_DIR, "bc_resample.wav")
            run(f'ffmpeg -y -i "{ATTENBOROUGH_INTRO}" -ar {sr} "{tmp_bc}"')
            bc_raw, _ = sf.read(tmp_bc)

        bc_trimmed = trim_speech(bc_raw, sr, threshold=0.015, pad_start=0.03, pad_end=0.06)
        if bc_trimmed.ndim == 1:
            bc_trimmed = np.column_stack([bc_trimmed, bc_trimmed])

        bc_rms = np.sqrt(np.mean(bc_trimmed**2)) + 1e-9
        target_bc_rms = 0.055
        bc_trimmed = bc_trimmed * (target_bc_rms / bc_rms)

        print(f"🎙️ Splicing Attenborough Intro ({len(bc_trimmed) / sr:.2f}s) at 3.76s...")
        replace_dialogue_window(dialogue, bc_trimmed, room_noise, 3.76, 10.40, sr, fade_samples)

    # 2. Attenborough Take 2: "...this broadcaster voice..." (62.12s -> 63.54s)
    # User says: "...and have refined..." (ends at 62.12s)
    # Attenborough says: "...this broadcaster voice..." (62.12s -> 63.54s)
    # User resumes at 63.54s: "...as the first main one to roll out..."
    if os.path.exists(ATTENBOROUGH_TAKE2):
        t2_raw, sr_t2 = sf.read(ATTENBOROUGH_TAKE2)
        if sr_t2 != sr:
            tmp_t2 = os.path.join(TEMP_DIR, "t2_resample.wav")
            run(f'ffmpeg -y -i "{ATTENBOROUGH_TAKE2}" -ar {sr} "{tmp_t2}"')
            t2_raw, _ = sf.read(tmp_t2)

        t2_trimmed = trim_speech(t2_raw, sr, threshold=0.015, pad_start=0.03, pad_end=0.05)
        if t2_trimmed.ndim == 1:
            t2_trimmed = np.column_stack([t2_trimmed, t2_trimmed])

        # Fit into exact 1.42s window
        dur_t2 = len(t2_trimmed) / sr
        if dur_t2 > 1.44:
            tmp_in = os.path.join(TEMP_DIR, "t2_raw_cut.wav")
            tmp_out = os.path.join(TEMP_DIR, "t2_timed.wav")
            sf.write(tmp_in, t2_trimmed, sr)
            tempo = dur_t2 / 1.40
            run(f'ffmpeg -y -i "{tmp_in}" -filter:a "atempo={tempo:.3f}" "{tmp_out}"')
            t2_trimmed, _ = sf.read(tmp_out)
            if t2_trimmed.ndim == 1:
                t2_trimmed = np.column_stack([t2_trimmed, t2_trimmed])

        t2_rms = np.sqrt(np.mean(t2_trimmed**2)) + 1e-9
        target_t2_rms = 0.055
        t2_trimmed = t2_trimmed * (target_t2_rms / t2_rms)

        print(f"🎙️ Splicing Attenborough Take 2 ({len(t2_trimmed) / sr:.2f}s) at 62.12s...")
        replace_dialogue_window(dialogue, t2_trimmed, room_noise, 62.12, 63.54, sr, fade_samples)

    # 3. Transition to Outro at 72.8s ("And of course this is all open source.")
    outro_transition_t = 72.80
    outro_idx = int(outro_transition_t * sr)
    dialogue_fadeout_len = int(0.35 * sr)
    fadeout_curve = np.linspace(1.0, 0.0, dialogue_fadeout_len)[:, None]
    dialogue[outro_idx : outro_idx + dialogue_fadeout_len] *= fadeout_curve
    dialogue[outro_idx + dialogue_fadeout_len :] = 0.0
    print(f"✂️ Dialogue smoothly faded out at {outro_transition_t}s.")

    # 4. Prepare Pure Instrumental Music Bed (NO Jungle VIP / vocal intro)
    print("🎵 Building continuous instrumental beat layer...")
    music_bed = np.zeros_like(dialogue)

    beat_wav = os.path.join(TEMP_DIR, "continuous_beat.wav")
    run(
        f'ffmpeg -y -ss 00:00:00 -t {outro_transition_t:.2f} -i "{SPICEWOOD_BEAT}" -ar {sr} -ac 2 "{beat_wav}"'
    )
    beat_audio, _ = sf.read(beat_wav)

    beat_len = min(len(beat_audio), outro_idx)
    beat_slice = beat_audio[:beat_len].copy()

    # Dynamic ducking envelope: -21 dB under user speech
    beat_gain_envelope = np.ones(beat_len) * 10 ** (-21.0 / 20.0)

    # Duck slightly lower during Attenborough's opening hook (3.76s - 10.20s)
    bc_start_idx = int(3.76 * sr)
    bc_end_idx = int(10.20 * sr)
    beat_gain_envelope[bc_start_idx:bc_end_idx] = 10 ** (-26.0 / 20.0)

    # Total silence during AI documentary voice demo (35.8s to 43.5s)
    doc_start_idx = int(35.8 * sr)
    doc_end_idx = int(43.5 * sr)
    ramp_len = int(0.4 * sr)

    beat_gain_envelope[doc_start_idx - ramp_len : doc_start_idx] = np.linspace(
        10 ** (-21.0 / 20.0), 0.0, ramp_len
    )
    beat_gain_envelope[doc_start_idx:doc_end_idx] = 0.0
    beat_gain_envelope[doc_end_idx : doc_end_idx + ramp_len] = np.linspace(
        0.0, 10 ** (-21.0 / 20.0), ramp_len
    )

    beat_slice *= beat_gain_envelope[:, None]
    music_bed[:beat_len] += beat_slice

    # 5. Outro Chorus: "Out here we in outlaw country, just for outlaw sake."
    print("💥 Adding Hook: 'Out here we in outlaw country, just for outlaw sake'...")
    hook_wav = os.path.join(TEMP_DIR, "hook_exact.wav")
    run(
        f'ffmpeg -y -ss 00:00:55.50 -to 00:01:01.35 -i "{SPICEWOOD_MASTER}" -ar {sr} -ac 2 "{hook_wav}"'
    )
    hook_audio, _ = sf.read(hook_wav)
    hook_len = len(hook_audio)
    hook_dur = hook_len / sr

    hook_fadein_len = int(0.12 * sr)
    hook_audio[:hook_fadein_len] *= np.linspace(0.0, 1.0, hook_fadein_len)[:, None]

    hook_fadeout_len = int(0.20 * sr)
    hook_audio[-hook_fadeout_len:] *= np.linspace(1.0, 0.0, hook_fadeout_len)[:, None]

    hook_gain = 10 ** (-4.5 / 20.0)  # -4.5 dBFS: punchy & loud without overpowering (-3.3 dB trim)
    music_bed[outro_idx : outro_idx + hook_len] += hook_audio * hook_gain

    # Total master cut duration
    final_end_t = outro_transition_t + hook_dur
    final_samples = int(final_end_t * sr)
    print(f"⏱️ Reel cutting off at {final_end_t:.2f}s (End of 'just for outlaw sake').")

    master_audio = dialogue[:final_samples] + music_bed[:final_samples]

    max_peak = np.max(np.abs(master_audio))
    if max_peak > 0:
        target_peak = 10 ** (-0.3 / 20.0)
        master_audio = master_audio * (target_peak / max_peak)

    master_wav = os.path.join(TEMP_DIR, "master_soundtrack_v7.wav")
    sf.write(master_wav, master_audio, sr)
    print(f"✅ Master soundtrack written to {master_wav}")

    # 6. Mux into video and CUT video at final_end_t!
    print(f"🎬 Muxing mastered audio and cutting video at {final_end_t:.2f}s: {VIDEO_OUTPUT}...")
    mux_cmd = (
        f'ffmpeg -y -i "{VIDEO_INPUT}" -i "{master_wav}" '
        f"-t {final_end_t:.2f} -map 0:v:0 -map 1:a:0 "
        f"-c:v copy -c:a aac -b:a 256k "
        f'-movflags +faststart "{VIDEO_OUTPUT}"'
    )
    run(mux_cmd)
    print("\n" + "=" * 60)
    print(f"🚀 FINAL MASTER REEL (V7) READY: {VIDEO_OUTPUT}")
    print(f"   Duration: {final_end_t:.2f}s")
    print("=" * 60)


if __name__ == "__main__":
    assemble()
