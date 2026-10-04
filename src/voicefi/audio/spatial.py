"""
Spatial audio engine and multi-agent stereo panning for VoiceFi.
Provides constant-power stereo positioning across headphones, AirPods, and Pixel Buds Pro 2.
"""

import math
from typing import Optional, Union, Tuple, Any
import numpy as np

# Spatial stereo panning assignments (-1.0 = hard left, 0.0 = center, +1.0 = hard right)
AGENT_PAN_PRESETS = {
    "antigravity": -0.55,       # Left ear: Primary pair programmer & orchestrator
    "claude": 0.55,            # Right ear: Strategic verifier & challenger
    "scout": -0.70,            # Far left: Reconnaissance / context extraction
    "verifier": 0.70,          # Far right: Verification & lint audit
    "qa": 0.65,                # Right: User acceptance & QA
    "cursor": -0.40,           # Mid-left: Inline code suggestions
    "windsurf": 0.40,          # Mid-right: Cascade operations
    "system": 0.0,             # Center: Platform notifications & chimes
    "musicfx": 0.0,            # Center: Ambient procedural lo-fi beats
}


def get_agent_pan(
    agent_name: Optional[str] = None,
    role: Optional[str] = None,
    adapt_for_device: bool = True,
) -> float:
    """
    Resolve the stereo pan (-1.0 to +1.0) for a given agent persona or role.
    If adapt_for_device is True and laptop speakers are active, narrows pan to maintain acoustic balance.
    """
    target_pan = 0.0
    key = (agent_name or role or "").lower().strip()

    for preset_key, pan_val in AGENT_PAN_PRESETS.items():
        if preset_key in key:
            target_pan = pan_val
            break

    if adapt_for_device:
        return adapt_pan_for_active_device(target_pan)
    return target_pan


def adapt_pan_for_active_device(pan: float) -> float:
    """
    Adapt the stereo pan value according to the physical audio output hardware.
    - Headphones / Pixel Buds Pro 2: 100% full stereo separation.
    - Built-in Laptop Speakers: Narrow stereo spread (40%) to prevent acoustically unbalanced playback.
    """
    try:
        from voicefi.audio.device import is_headphone_or_headset_active

        if is_headphone_or_headset_active():
            return float(np.clip(pan, -1.0, 1.0))
        # Narrows stereo field when listening in open air on MacBook speakers
        return float(np.clip(pan * 0.4, -0.4, 0.4))
    except Exception:
        return pan


def pan_audio(
    audio: np.ndarray,
    pan: float = 0.0,
    sample_rate: int = 24000,
) -> np.ndarray:
    """
    Apply constant-power stereo panning law to audio data.

    Panning Law:
      theta = (pan + 1) * pi / 4
      Left  = cos(theta)
      Right = sin(theta)
      Left^2 + Right^2 = 1.0 (constant acoustic power)

    Parameters:
      audio: 1D (mono) or 2D (mono/stereo) numpy array (float32 or int16)
      pan: -1.0 (full left) to +1.0 (full right). 0.0 is center.
      sample_rate: Sampling frequency

    Returns:
      2D numpy array of shape (N, 2) with dtype float32
    """
    # Sanitize and clamp pan parameter against NaN / Inf / non-numeric
    try:
        if pan is None or math.isnan(pan) or math.isinf(pan):
            safe_pan = 0.0
        else:
            safe_pan = float(np.clip(float(pan), -1.0, 1.0))
    except (TypeError, ValueError):
        safe_pan = 0.0

    # Ensure audio is numpy array
    if not isinstance(audio, np.ndarray):
        audio = np.asarray(audio, dtype=np.float32)

    # Convert to float32 normalized in [-1.0, 1.0] if necessary
    if audio.dtype == np.int16:
        float_audio = (audio.astype(np.float32)) / 32768.0
    elif audio.dtype == np.int32:
        float_audio = (audio.astype(np.float32)) / 2147483648.0
    else:
        float_audio = audio.astype(np.float32)

    # Clean out NaN / Inf samples to protect CoreAudio hardware drivers
    if np.isnan(float_audio).any() or np.isinf(float_audio).any():
        float_audio = np.nan_to_num(float_audio, nan=0.0, posinf=1.0, neginf=-1.0)

    # Calculate constant-power gain coefficients
    angle = (safe_pan + 1.0) * (math.pi / 4.0)
    left_gain = math.cos(angle)
    right_gain = math.sin(angle)

    # Flatten if mono
    if float_audio.ndim == 1:
        mono_signal = float_audio
    elif float_audio.ndim == 2:
        if float_audio.shape[1] == 1:
            mono_signal = float_audio[:, 0]
        else:
            # Downmix stereo to mono before applying new spatial pan
            mono_signal = (float_audio[:, 0] + float_audio[:, 1]) * 0.5
    else:
        raise ValueError(f"Unsupported audio dimension: {float_audio.ndim}")

    num_samples = len(mono_signal)
    stereo_out = np.empty((num_samples, 2), dtype=np.float32)
    stereo_out[:, 0] = mono_signal * left_gain
    stereo_out[:, 1] = mono_signal * right_gain

    return stereo_out


def create_spatial_tone(
    freq: float = 440.0,
    duration: float = 0.5,
    sample_rate: int = 44100,
    pan: float = 0.0,
) -> np.ndarray:
    """Generate a pure tone with spatial stereo panning and smooth windowed envelope."""
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False, dtype=np.float32)
    tone = np.sin(2 * np.pi * freq * t)

    # 15ms raised cosine fade in / fade out to avoid clicks
    fade_len = int(sample_rate * 0.015)
    if len(tone) > fade_len * 2:
        fade_in = 0.5 * (1 - np.cos(np.linspace(0, np.pi, fade_len, dtype=np.float32)))
        fade_out = 0.5 * (1 + np.cos(np.linspace(0, np.pi, fade_len, dtype=np.float32)))
        tone[:fade_len] *= fade_in
        tone[-fade_len:] *= fade_out

    return pan_audio(tone * 0.4, pan=pan, sample_rate=sample_rate)


def create_orbit_sweep(duration: float = 4.0, sample_rate: int = 44100) -> np.ndarray:
    """
    Generate a 360-degree acoustic panning sweep that smoothly orbits around the listener's head.
    Pan trajectory moves: Left (-1.0) -> Center (0.0) -> Right (+1.0) -> Center (0.0) -> Left (-1.0).
    """
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False, dtype=np.float32)
    # Warm major third harmonic chord: 440Hz (A4) + 554.37Hz (C#5) + 659.25Hz (E5)
    carrier = (
        0.25 * np.sin(2 * np.pi * 440.0 * t)
        + 0.20 * np.sin(2 * np.pi * 554.37 * t)
        + 0.15 * np.sin(2 * np.pi * 659.25 * t)
    )

    fade_len = int(sample_rate * 0.05)
    if len(carrier) > fade_len * 2:
        fade_in = 0.5 * (1 - np.cos(np.linspace(0, np.pi, fade_len, dtype=np.float32)))
        fade_out = 0.5 * (1 + np.cos(np.linspace(0, np.pi, fade_len, dtype=np.float32)))
        carrier[:fade_len] *= fade_in
        carrier[-fade_len:] *= fade_out

    # Continuous sine pan trajectory from -1.0 to +1.0 and back
    pan_trajectory = np.sin(2 * np.pi * (1.0 / duration) * t - (np.pi / 2.0))
    angle = (pan_trajectory + 1.0) * (np.pi / 4.0)

    stereo_out = np.empty((len(carrier), 2), dtype=np.float32)
    stereo_out[:, 0] = carrier * np.cos(angle)
    stereo_out[:, 1] = carrier * np.sin(angle)
    return stereo_out


def create_binaural_360_orbit(
    duration: float = 7.0,
    sample_rate: int = 44100,
) -> np.ndarray:
    """
    Generate a true 360-degree binaural spatial orbit moving in a full circle around the head:
    Trajectory: Front (0°) -> Right Ear (90°) -> Behind Neck (180°) -> Left Ear (270°) -> Front (360°).

    Uses true binaural HRTF acoustic cues:
      1. ITD (Interaural Time Delay): ~0.55ms time delay across ears.
      2. Pinna Occlusion: Dynamic 1-pole low-pass filtering simulating outer-ear shielding when sound is behind.
      3. Contralateral Head Shadowing: Attenuates high frequencies on the obstructed ear.
      4. ILD (Interaural Level Difference): Equal-power lateral gain.
      5. Rear Attenuation: -2.5dB level dip for rear trajectory.
    """
    N = int(sample_rate * duration)
    t = np.linspace(0, duration, N, endpoint=False, dtype=np.float32)

    # 1. Rhythmic crystalline harmonic chime (sparkling transients for crisp localization)
    pulse = (0.5 * (1.0 + np.sin(2 * np.pi * 5.0 * t))) ** 3
    carrier = (
        0.35 * np.sin(2 * np.pi * 440.0 * t)
        + 0.25 * np.sin(2 * np.pi * 554.37 * t)
        + 0.20 * np.sin(2 * np.pi * 659.25 * t)
        + 0.15 * np.sin(2 * np.pi * 1108.73 * t)
        + 0.12 * np.sin(2 * np.pi * 2217.46 * t)
        + 0.10 * np.sin(2 * np.pi * 4434.92 * t)
        + 0.08 * np.sin(2 * np.pi * 6652.38 * t)
    ).astype(np.float32) * pulse

    # Smooth 80ms window
    fade_n = int(sample_rate * 0.08)
    if len(carrier) > fade_n * 2:
        w = 0.5 * (1.0 - np.cos(np.linspace(0, np.pi, fade_n, dtype=np.float32)))
        carrier[:fade_n] *= w
        carrier[-fade_n:] *= w[::-1]

    # 2. Continuous 360-degree Azimuth: 0 (front) -> pi/2 (right) -> pi (rear) -> 3pi/2 (left) -> 2pi (front)
    phi = (2.0 * np.pi * (t / duration)).astype(np.float32)

    # 3. ITD (Interaural Time Delay) ~0.55ms max (24 samples at 44.1kHz)
    max_itd = 24.0
    d_L = np.maximum(0.0, np.sin(phi) * max_itd).astype(np.int32)
    d_R = np.maximum(0.0, -np.sin(phi) * max_itd).astype(np.int32)

    idx_L = np.clip(np.arange(N) - d_L, 0, N - 1)
    idx_R = np.clip(np.arange(N) - d_R, 0, N - 1)
    x_L = carrier[idx_L]
    x_R = carrier[idx_R]

    # 4. Front-to-Back Pinna Occlusion (Cutoff Freq)
    # Front (cos=1): 18,000 Hz. Rear (cos=-1): 2,200 Hz.
    u = (1.0 + np.cos(phi)) * 0.5
    fc_base = 2200.0 + 15800.0 * (u ** 1.8)

    # Head shadowing on contralateral ear
    fc_L = np.clip(fc_base * (1.0 - 0.55 * np.maximum(0.0, np.sin(phi))), 1200.0, 20000.0)
    fc_R = np.clip(fc_base * (1.0 - 0.55 * np.maximum(0.0, -np.sin(phi))), 1200.0, 20000.0)

    # Calculate discrete IIR alpha per sample
    w_L = 2.0 * np.pi * fc_L / sample_rate
    alpha_L = (w_L / (w_L + 1.0)).astype(np.float32)
    w_R = 2.0 * np.pi * fc_R / sample_rate
    alpha_R = (w_R / (w_R + 1.0)).astype(np.float32)

    # Run 1-pole filter
    y_L = np.empty(N, dtype=np.float32)
    y_R = np.empty(N, dtype=np.float32)
    cur_L, cur_R = 0.0, 0.0
    for i in range(N):
        cur_L = alpha_L[i] * x_L[i] + (1.0 - alpha_L[i]) * cur_L
        y_L[i] = cur_L
        cur_R = alpha_R[i] * x_R[i] + (1.0 - alpha_R[i]) * cur_R
        y_R[i] = cur_R

    # 5. Interaural Level Difference (ILD) & Rear Attenuation
    lat = np.sin(phi)
    gain_L = np.cos((lat + 1.0) * (np.pi / 4.0))
    gain_R = np.sin((lat + 1.0) * (np.pi / 4.0))

    # Rear volume dip (-2.5dB when sound is behind ears)
    rear_att = 1.0 - 0.28 * np.maximum(0.0, -np.cos(phi))

    out_L = y_L * gain_L * rear_att
    out_R = y_R * gain_R * rear_att

    return np.column_stack([out_L, out_R]).astype(np.float32)


def play_spatial_speech(
    text: str,
    agent_name: str = "antigravity",
    pan: Optional[float] = None,
    voice_override: Optional[str] = None,
    provider_override: Optional[str] = None,
    rate_override: Optional[Any] = None,
    speed_override: Optional[str] = None,
    block: bool = True,
) -> bool:
    """
    Synthesize speech for a given agent persona and play it with spatial stereo positioning.
    """
    import tempfile
    from pathlib import Path
    import sounddevice as sd
    import soundfile as sf
    from voicefi.config import load_config
    from voicefi.tts import get_tts_engine

    cfg = load_config()
    target_pan = pan if pan is not None else get_agent_pan(agent_name=agent_name)
    tts = get_tts_engine(
        cfg,
        agent_name=agent_name,
        voice_override=voice_override,
        provider_override=provider_override,
        rate_override=rate_override,
        speed_override=speed_override,
    )

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        wav_path = Path(tf.name)

    try:
        success = tts.speak_to_file(text, wav_path)
        if not success or not wav_path.is_file() or wav_path.stat().st_size == 0:
            return False

        data, sr = sf.read(str(wav_path))

        # Dynamically query active device parameters (e.g. Pixel Buds in SCO 1-ch vs A2DP 2-ch)
        try:
            _, out_idx = sd.default.device
            dev_info = sd.query_devices(out_idx) if out_idx is not None else {}
            target_sr = int(dev_info.get("default_samplerate", sr))
            max_out_channels = int(dev_info.get("max_output_channels", 2))
        except Exception:
            target_sr = sr
            max_out_channels = 2

        # Resample if sample rate does not match device native rate
        if target_sr > 0 and sr != target_sr:
            num_samples = int(len(data) * target_sr / sr)
            target_times = np.linspace(0, 1, num_samples, endpoint=False)
            orig_times = np.linspace(0, 1, len(data), endpoint=False)
            data = np.interp(target_times, orig_times, data).astype(np.float32)
            sr = target_sr

        stereo_audio = pan_audio(data, pan=target_pan, sample_rate=sr)

        # Adapt output to hardware channel capacity
        if max_out_channels == 1:
            playback_audio = (stereo_audio[:, 0] + stereo_audio[:, 1]) * 0.5
        else:
            playback_audio = stereo_audio

        sd.play(playback_audio, samplerate=sr)
        if block:
            sd.wait()
        return True
    except Exception as e:
        print(f"Error in play_spatial_speech: {e}")
        return False
    finally:
        wav_path.unlink(missing_ok=True)


def run_spatial_multiagent_audition(block: bool = True, with_speech: bool = False) -> bool:
    """
    Play a live multi-agent spatial audition directly through the active audio output.
    Demonstrates:
      1. Antigravity staged in Left Ear (pan = -0.6)
      2. Claude Code staged in Right Ear (pan = +0.6)
      3. Centered chime / confirmation (pan = 0.0)
    """
    import sounddevice as sd
    import time

    sample_rate = 44100
    try:
        from voicefi.audio.device import get_audio_device_profile
        prof = get_audio_device_profile()
        device_label = prof.get("default_output", "Default Output")
    except Exception:
        device_label = "Active Device"

    print(f"🎧 Auditioning Spatial Multi-Agent Audio on: {device_label}")
    print("   • Left Channel  ──► Antigravity Orchestrator (pan = -0.6)")
    print("   • Right Channel ──► Claude Code Verifier (pan = +0.6)")
    print("   • Center Field  ──► Centered Ambience / Chimes (pan = 0.0)")

    if with_speech:
        print("\n🗣️ Synthesizing spatial multi-agent vocal responses...")
        ok_left = play_spatial_speech(
            "Antigravity standing by on your left channel.",
            agent_name="antigravity",
            pan=-0.65,
            block=True,
        )
        time.sleep(0.2)
        ok_right = play_spatial_speech(
            "Claude Code verified on your right channel.",
            agent_name="claude",
            pan=0.65,
            block=True,
        )
        time.sleep(0.2)
        center_cue = create_spatial_tone(freq=783.99, duration=0.5, sample_rate=sample_rate, pan=0.0)
        sd.play(center_cue, samplerate=sample_rate)
        if block:
            sd.wait()
        return bool(ok_left and ok_right)

    # 1. Left Ear Tone (Antigravity prompt cue - 523.25 Hz / C5)
    left_cue = create_spatial_tone(freq=523.25, duration=0.4, sample_rate=sample_rate, pan=-0.65)

    # 2. Right Ear Tone (Claude Code prompt cue - 659.25 Hz / E5)
    right_cue = create_spatial_tone(freq=659.25, duration=0.4, sample_rate=sample_rate, pan=0.65)

    # 3. Center Stereo Chord (Harmonic resolution - G5 783.99 Hz)
    center_cue = create_spatial_tone(freq=783.99, duration=0.6, sample_rate=sample_rate, pan=0.0)

    silence_gap = np.zeros((int(sample_rate * 0.25), 2), dtype=np.float32)

    demo_sequence = np.concatenate([left_cue, silence_gap, right_cue, silence_gap, center_cue])

    try:
        sd.play(demo_sequence, samplerate=sample_rate)
        if block:
            sd.wait()
        return True
    except Exception as e:
        print(f"Spatial audition playback error: {e}")
        return False
