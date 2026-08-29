# Contributing Custom Sound Effects & Procedural Audio Packs

VoiceFi features a hybrid acoustic cues architecture combining **real-time procedural waveform synthesis** (via NumPy) and **native macOS system chimes** (via `afplay`). This enables instantaneous comedy sound effects (rimshots, horn honks, sad trombones, applauses, boings, crickets) and subtle UI interaction chimes without heavy external audio asset downloads.

This guide details how the SFX engine works, how to synthesize new procedural audio waveforms with NumPy, how to register custom sound effects and aliases, how to integrate system chimes, and how to write rigorous unit tests.

---

## 1. Architectural Overview

The sound effects subsystem is located in `src/voicefi/audio/sfx.py` and `src/voicefi/audio/chimes.py`.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           VoiceFi SFX Architecture                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   CLI (`vifi sfx`) / MCP (`voicefi_sfx`) / Agent Inline (`[sfx:rimshot]`)   │
│                                  │                                          │
│                                  ▼                                          │
│                        `play_sfx(name, volume)`                             │
│                                  │                                          │
│                                  ▼                                          │
│                        `get_sfx_path(name)`                                 │
│                                  │                                          │
│                 ┌────────────────┴────────────────┐                         │
│                 ▼                                 ▼                         │
│       Is `.wav` in cache?               Generate via NumPy                  │
│       `~/.voicefi/sfx/<name>.wav`       `_generate_<name>(44100)`           │
│                 │                                 │                         │
│                 │ (Cached hit)                    │ (Writes 16-bit PCM WAV) │
│                 │                                 ▼                         │
│                 └────────────────► Play via `afplay`                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Core Characteristics:
- **Zero Asset Bloat**: Procedural sound generators produce studio-quality acoustic cues on demand using pure mathematical equations.
- **Dynamic Caching**: The first time an effect is requested, its waveform is generated and saved as a 16-bit signed PCM `.wav` in `~/.voicefi/sfx/`. Subsequent calls load instantly from disk with 0ms synthesis overhead.
- **Inline Tag Stripping**: When AI agents produce responses containing inline sound tags (e.g. `[sfx:rimshot]` or `[honk]`), `strip_inline_sfx_tags()` removes the tag from the text sent to TTS engines while triggering the sound effect independently.
- **System Audio Chimes**: `src/voicefi/audio/chimes.py` maps macOS native alert tones (`Tink.aiff`, `Mail Sent.aiff`, `Basso.aiff`, `Glass.aiff`) for turn transitions and notifications.

---

## 2. Mathematics & Physics of Procedural Audio Synthesis

All procedural sound generators in `src/voicefi/audio/sfx.py` return a NumPy array of signed 16-bit integers (`np.int16`) at a standard sample rate of **44,100 Hz**.

### 2.1 Generating Time Vectors

```python
import numpy as np

sample_rate = 44100
duration = 1.0  # seconds
t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
```

### 2.2 Waveform Synthesis Primitives

#### 1. Pure Tones & Harmonics
A fundamental tone with harmonic overtones:
$$\text{signal}(t) = \sum_{k=1}^{N} A_k \sin(2\pi \cdot (k \cdot f_0) \cdot t)$$

```python
f0 = 440.0  # A4
harmonics = (
    0.60 * np.sin(2 * np.pi * f0 * t) +       # Fundamental
    0.30 * np.sin(2 * np.pi * (2 * f0) * t) + # 2nd Harmonic (Octave)
    0.10 * np.sin(2 * np.pi * (3 * f0) * t)   # 3rd Harmonic (Fifth)
)
```

#### 2. Frequency Modulation & Pitch Sweeps (Chirps)
For cartoon spring "boings" or laser swooshes, integrate the instantaneous frequency using cumulative summation:
$$\phi(t) = 2\pi \int f(t) \, dt \approx 2\pi \frac{\sum f(t)}{f_s}$$

```python
# Upward frequency sweep from 150 Hz to 600 Hz
freq_curve = 150.0 + 450.0 * (1.0 - np.exp(-t / 0.15))
phase = 2 * np.pi * np.cumsum(freq_curve) / sample_rate
wave = np.sin(phase)
```

#### 3. Noise Generators (Transients & Applause)
- **White Noise**: `np.random.uniform(-1.0, 1.0, len(t))`
- **Envelope Shaping**: Exponential decay for percussive hits $\exp(-t / \tau)$ or sinusoidal bell curves $\sin(\pi \frac{t}{\text{dur}})^\gamma$.

### 2.3 Quantization & 16-bit Clipping
Audio arrays must be bounded to $[-1.0, 1.0]$ and converted to 16-bit signed PCM integers:
```python
pcm_audio = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
```

---

## 3. Step-by-Step: Adding a Custom Sound Generator

Let's build and register a new procedural sound effect: **`fanfare`** (a triumph / level-up 8-bit brass arpeggio: C4 -> E4 -> G4 -> C5).

### Step 1: Implement the Generator Function in `src/voicefi/audio/sfx.py`

```python
def _generate_fanfare(sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Triumphant level-up fanfare arpeggio (C4 -> E4 -> G4 -> C5)."""
    dur = 1.2
    t = np.linspace(0, dur, int(sample_rate * dur), False)
    audio = np.zeros_like(t)

    # Arpeggio notes: (start_time, end_time, frequency_hz)
    notes = [
        (0.00, 0.15, 261.63),  # C4
        (0.15, 0.30, 329.63),  # E4
        (0.30, 0.45, 392.00),  # G4
        (0.45, 1.15, 523.25),  # C5 (held with shimmer)
    ]

    for start, end, freq in notes:
        mask = (t >= start) & (t < end)
        if not np.any(mask):
            continue
        t_sub = t[mask] - start
        seg_dur = end - start

        # Rich brass harmonic composition
        harmonics = (
            np.sin(2 * np.pi * freq * t_sub) * 0.60 +
            np.sin(2 * np.pi * freq * 2 * t_sub) * 0.30 +
            np.sin(2 * np.pi * freq * 3 * t_sub) * 0.15
        )

        # ADSR Envelope: Fast attack, sustained body, exponential release
        if start >= 0.45:
            # Final held note: vibrato + gentle decay
            vibrato = np.sin(2 * np.pi * 5.0 * t_sub) * 3.0
            harmonics = np.sin(2 * np.pi * (freq + vibrato) * t_sub) * 0.70
            env = np.exp(-t_sub / 0.35)
        else:
            env = np.sin(np.pi * (t_sub / seg_dur)) ** 0.7

        audio[mask] = harmonics * env * 0.85

    return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
```

---

### Step 2: Register in `GENERATORS` and `ALIASES`

Add the generator and aliases in `src/voicefi/audio/sfx.py`:

```python
GENERATORS: Dict[str, Callable[[int], np.ndarray]] = {
    "drum_smash": _generate_rimshot,
    "honk": _generate_honk,
    "sad_trombone": _generate_sad_trombone,
    "applause": _generate_applause,
    "boing": _generate_boing,
    "crickets": _generate_crickets,
    
    # --- Add your new generator ---
    "fanfare": _generate_fanfare,
    "level_up": _generate_fanfare,
    "victory": _generate_fanfare,
}

ALIASES: Dict[str, str] = {
    "drum-smash": "drum_smash",
    "horn-honk": "honk",
    "sad-trombone": "sad_trombone",
    "claps": "applause",
    "awkward": "crickets",
    
    # --- Add aliases ---
    "tada": "fanfare",
    "triumph": "fanfare",
    "levelup": "fanfare",
    "success-chime": "fanfare",
}
```

---

### Step 3: Update Available SFX List

Ensure `list_available_sfx()` includes the new primary effect name:

```python
def list_available_sfx() -> List[str]:
    """List distinct available sound effect names."""
    return sorted(list(set([
        "drum_smash",
        "honk",
        "sad_trombone",
        "applause",
        "boing",
        "crickets",
        "fanfare",
    ])))
```

---

### Step 4: Verify Inline Tag Stripping

`strip_inline_sfx_tags(text)` dynamically parses `list_available_sfx()` and `ALIASES`. When an agent emits:
```
All 42 tests passing! [sfx:fanfare] Ready for PR review.
```
The function cleans it into:
```
All 42 tests passing! Ready for PR review.
```
So TTS speaks the clean sentence while the orchestration hook executes `play_sfx("fanfare")`.

---

## 4. System Chimes Integration (`src/voicefi/audio/chimes.py`)

VoiceFi triggers system chimes during voice turn transitions (e.g. mic activation, message sent, error).

```python
# In src/voicefi/audio/chimes.py

SYSTEM_SOUNDS = {
    "start": "/System/Library/Sounds/Tink.aiff",
    "done": DEFAULT_SENT_SOUND,
    "sent": DEFAULT_SENT_SOUND,
    "mail_sent": DEFAULT_SENT_SOUND,
    "swoosh": DEFAULT_SENT_SOUND,
    "error": "/System/Library/Sounds/Basso.aiff",
    "alert": "/System/Library/Sounds/Glass.aiff",
}

def play_chime(sound_key_or_path: str, block: bool = False) -> None:
    """Play a system audio cue using macOS afplay."""
    # Resolves from SYSTEM_SOUNDS or accepts explicit file path
    sound_path = SYSTEM_SOUNDS.get(sound_key_or_path, sound_key_or_path)
    ...
```

### Adding Custom System Chimes
You can map new sound keys or configure paths in `~/.voicefi/config.yaml`:
```yaml
audio_cues:
  enabled: true
  start_chime: "/System/Library/Sounds/Tink.aiff"
  sent_chime: "/System/Applications/Mail.app/Contents/Resources/Mail Sent.aiff"
  error_chime: "/System/Library/Sounds/Basso.aiff"
```

---

## 5. Adding Pre-Rendered Audio Asset Packs

If you have pre-recorded sound effects (WAV, MP3, CAF, AIFF):
1. Place audio files in `~/.voicefi/sfx/<name>.wav` (or configure a custom directory).
2. VoiceFi's `get_sfx_path(name)` will automatically discover existing `.wav` files before falling back to procedural generators:

```python
# get_sfx_path checks file existence first
target_file = SFX_CACHE_DIR / f"{clean_name}.wav"
if target_file.is_file() and target_file.stat().st_size > 0:
    return target_file
```

---

## 6. Unit Testing Procedural SFX Generators

Create `tests/test_custom_sfx.py` to validate your generator's waveform physics, bounds, and caching:

```python
"""
Unit tests for custom SFX generators and procedural synthesis.
"""

import numpy as np
import pytest
from pathlib import Path

from voicefi.audio.sfx import (
    _generate_fanfare,
    get_sfx_path,
    list_available_sfx,
    strip_inline_sfx_tags,
    play_sfx,
    SAMPLE_RATE,
)


def test_fanfare_waveform_properties():
    """Verify waveform shape, data type, amplitude bounds, and absence of NaNs."""
    data = _generate_fanfare(SAMPLE_RATE)
    
    assert isinstance(data, np.ndarray)
    assert data.dtype == np.int16
    assert len(data) == int(SAMPLE_RATE * 1.2)  # 1.2s duration
    
    # Must not contain NaNs or Infs
    assert not np.isnan(data).any()
    assert not np.isinf(data).any()
    
    # Amplitude bounds check (16-bit range: -32768 to 32767)
    assert np.max(data) <= 32767
    assert np.min(data) >= -32768
    
    # Verify non-trivial energy (not pure silence)
    rms = np.sqrt(np.mean(data.astype(np.float32) ** 2))
    assert rms > 500.0


def test_sfx_alias_resolution_and_cache(tmp_path, monkeypatch):
    """Verify get_sfx_path generates and caches file for primary name and aliases."""
    monkeypatch.setattr("voicefi.audio.sfx.SFX_CACHE_DIR", tmp_path)
    
    path_primary = get_sfx_path("fanfare")
    assert path_primary is not None
    assert path_primary.is_file()
    assert path_primary.suffix == ".wav"
    assert path_primary.stat().st_size > 0
    
    # Alias resolution should point to the exact same cached WAV
    path_alias = get_sfx_path("level_up")
    assert path_alias is not None
    assert path_alias.name == "fanfare.wav" or path_alias.name == "level_up.wav"


def test_strip_inline_sfx_tags():
    """Verify that inline sound tags are stripped from speech text."""
    test_cases = [
        ("Great job! [sfx:fanfare] All done.", "Great job! All done."),
        ("That was awful [sad_trombone] let's retry.", "That was awful let's retry."),
        ("Clown moment [honk] indeed.", "Clown moment indeed."),
        ("[sfx:rimshot] Badum tss!", "Badum tss!"),
        ("[level_up] Level unlocked.", "Level unlocked."),
    ]
    for raw, expected in test_cases:
        assert strip_inline_sfx_tags(raw) == expected


def test_play_sfx_headless_safe():
    """Verify play_sfx executes without exceptions in headless/testing mode."""
    # Under test runners (os.getenv("VOICEFI_TESTING") == "1"), playback returns True safely
    assert play_sfx("fanfare", block=True) is True
```

Run tests:
```bash
pytest tests/test_custom_sfx.py -v
```

---

## 7. CLI & Tool Usage

```bash
# Play procedural sound effect via CLI
vifi sfx fanfare --volume 1.0

# Play with alias
vifi sfx level_up

# Play in banter duel benchmark
vifi duel --turns 2 --topic "microservices"
```

In MCP JSON-RPC:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "voicefi_sfx",
    "arguments": {
      "name": "fanfare",
      "volume": 0.8
    }
  }
}
```
