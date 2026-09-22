---
name: voice-cloning
description: Guides the creation, calibration, neural diffusion cloning (F5-TTS), broadcast mastering, and fine-tuning of custom voice personas in VoiceFi, including the complete documentary broadcaster nature documentary voice recipe.
---

# 🧬 Voice Cloning & Persona Crafting Studio — VoiceFi™

Universal Voice Cloning Engine for AI Agents, Social Reels, and macOS.

Use this skill whenever the user asks to clone a voice, create a new vocal persona, synthesize speech with a custom clone (such as a documentary broadcaster, Morgan Freeman, or personal recordings), or optimize neural voice cloning fidelity and broadcast mastering.

---

## 🏗️ Architecture & Engine Overview

VoiceFi's voice cloning engine operates on **zero-shot neural diffusion** powered by **F5-TTS** (`F5TTS_v1_Base` / `E2-TTS`), running completely locally and privately on Apple Silicon Metal Performance Shaders (`device="mps"`).

```
[Reference Audio (10-15s clean WAV)] + [Reference Transcript]
                              │
                              ▼
        [F5-TTS Neural Diffusion Model (Apple Silicon MPS)]
                              │
                              ▼
            [Raw Neural Diffusion Synthesis (24kHz)]
                              │
                              ▼
        [BBC Natural History Unit Broadcast Mastering Chain]
     (70Hz Rumble Cut → 125Hz Warmth → 5.6kHz De-Esser → 11.5kHz Air)
                              │
                              ▼
       [Multi-Take Stitching & Natural Breath Insertion (0.4s)]
                              │
                              ▼
           [Final Studio Broadcast Master Audio / Video]
```

### Key Technical Safeguards:
1. **MPS Metal Threading Safety**: PyTorch MPS Metal command queues on macOS are **not thread-safe**. VoiceFi patches `f5_tts.infer.utils_infer.ThreadPoolExecutor` to enforce `max_workers=1`, preventing hard `SIGSEGV` crashes.
2. **Batch-Seam Glitch Prevention**: Feeding long paragraphs (>25 words) to neural diffusion models causes drift, unnatural pitch warping, or abrupt batch-boundary clicks. Scripts must be broken into natural thought clauses and stitched with 350ms–500ms room-tone pauses.
3. **Environment Requirement**: Requires `DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib"` on macOS for `torchcodec` and FFmpeg shared libraries.

---

## 🎙️ The Documentary Broadcaster Voice Recipe

This is the exact, production-validated blueprint for the authentic BBC documentary broadcaster voice:

### 1. Curating the Reference Sample
- **Reference WAV**: `~/.voicefi/cloned_voices/documentary_broadcaster/samples/sample_01_clean.wav`
- **Duration**: Exactly 10.0 to 14.0 seconds (optimal diffusion conditioning window).
- **Acoustics**: 100% dry studio voice. Zero background music, zero birdsong, zero room reverb.
- **Delivery**: Intimate, measured, contemplative cadence with characteristic British received pronunciation.

### 2. Script Chunking & Thought Pacing
The documentary broadcaster's signature cadence relies on **the dramatic pause**. Never synthesize an entire act in a single take. Split by dramatic thought:

| Act | Spoken Thought | Typical Duration |
| :--- | :--- | :--- |
| **Act 1** | *"Carved over millennia... this limestone artery sustains life across the Texas hill country."* | 8.5s |
| **Act 2** | *"Following the current... we arrive at the great watering hole... where the pack prepares for the ritual plunge."* | 9.6s |
| **Act 3a**| *"Sixty-eight degrees of shock to the system... With primal courage... they leap."* | 6.8s |
| **Splash**| *[Zero voiceover — 3.0s live acoustic splash sound]* | 3.0s |
| **Act 3b**| *"Extraordinary... The alpha possesses no claws, no venom, and very little dignity left in those soaked swim trunks."* | 10.2s |
| **Breath**| *[0.45s natural inhalation silence]* | 0.45s |
| **Act 3c**| *"And yet... to these two juveniles... he remains the undisputed hero of the watering hole."* | 8.6s |
| **Outro** | *[2.0s ambient water pad before fade]* | 2.0s |

### 3. BBC Broadcast Silk Mastering Profile (Eliminating Static & Hiss)
Raw neural diffusion output (F5-TTS with Vocos vocoder) produces high-frequency flow-matching hash and vocoder floor hiss above 10.5 kHz. The **Broadcast Silk** pipeline drops the background noise floor by **20 dB** (from `0.0019` to `0.0002`) while preserving the narrator's intimate chest warmth:

```bash
ffmpeg -y -i raw_diffusion_take.wav \
  -af "afftdn=nr=10:nf=-35,lowpass=f=10500,equalizer=f=6000:width_type=q:width=2.0:g=-2.0,equalizer=f=125:width_type=q:width=1.0:g=2.5,volume=-0.5dB" \
  silk_mastered_take.wav
```
- **`afftdn=nr=10:nf=-35`**: Fast FFT spectral de-noiser targeting stationary diffusion vocoder noise floor.
- **`lowpass=f=10500`**: Rolls off ultrasonic digital vocoder hash above 10.5 kHz (inaudible human speech range).
- **`equalizer=f=6000:width_type=q:width=2.0:g=-2.0`**: De-esser notch taming sharp digital sibilance.
- **`equalizer=f=125:width_type=q:width=1.0:g=2.5`**: Restores intimate chest tone proximity effect.
- **`volume=-0.5dB`**: Safe true-peak headroom preventing CoreAudio clipping.

### 4. Diffusion Steps (`nfe_step=32`)
The default `nfe_step=16` in fast inference produces noticeable diffusion grain. For broadcast and social reel exports, always set:
```python
nfe_step = 32  # Pristine flow-matching convergence on Apple Silicon MPS
```

### 5. Documentary Broadcaster Prosody & Phrasing Secrets
- **The Exclamation Mark Trap**: **Never** use exclamation marks (`!`) for dramatic realization, comedic triumph, or awe (e.g. *"How profound!"* or *"Yet triumph!"*). Exclamation marks force the neural model to spike pitch into a cheerful American game-show host tone.
- **The Ellipsis Awe Trigger**: Replace exclamation points with ellipses (`...`) or periods (`.`):
  - ❌ `"Yet... triumph! A brazen pelvic display."`
  - ✅ `"Yet... triumph. A brazen pelvic display."` (or `"And yet... triumph."`)
  - ❌ `"How profound!"`
  - ✅ `"How... profound."` (or `"How... quite profound."`)
- **Pacing & Speed**: The documentary broadcaster delivers punchlines and grand conclusions with deliberate, hushed gravitas. Set `speed=0.88` to `0.95` for punchlines to trigger low vocal fry and contemplative British RP wonder.

### 6. Pure NumPy Sample-Accurate Timeline Assembly vs. FFmpeg `amix`
- **Never use FFmpeg `amix=inputs=N` for multi-take stems**: `amix` sums background room noise across all inputs simultaneously, causing compound noise and eerie phasing feedback during speech pauses.
- **The NumPy Standard**: Load all stems into a single zeroed buffer (`np.zeros(total_samples, dtype=np.float32)`) at sample-accurate indices (`start_sample = int(round(target_start * sr))`).
- **Edge Micro-Fades**: Apply 20ms fade-in and 40ms fade-out to every vocal slice:
  ```python
  def apply_edge_fades(data: np.ndarray, sr: int, fade_in_ms: int = 20, fade_out_ms: int = 40):
      n_in, n_out = int(sr * fade_in_ms / 1000), int(sr * fade_out_ms / 1000)
      data[:n_in] *= np.linspace(0, 1, n_in, dtype=np.float32)
      data[-n_out:] *= np.linspace(1, 0, n_out, dtype=np.float32)
      return data
  ```
- Guarantees **100% true digital silence** during pauses, allowing background acoustic music and nature soundscapes to shine unimpeded.

### 7. Final Video Freeze-Frame Extension (`tpad=stop_mode=clone`)
When punchline narration outlasts the original camera clip, or to freeze on a hilarious final pose before awkward camera handling/reaching occurs:
```bash
ffmpeg -y -i original_video.mp4 \
  -filter_complex "[0:v]trim=end=43.83,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=2.67,scale=1080:1920,format=yuv420p[v]" \
  -map "[v]" ...
```
This cleanly locks the exact pristine frame for 2.67s, allowing the punchline and musical outro to land with cinematic timing.

### 8. Splicing Out Vocal Artifacts / Hesitations
Diffusion models occasionally hallucinate short vocal ticks (e.g. a rogue *"a"* or *"uh"* during an ellipsis pause).
To surgically excise artifacts without re-running diffusion:
```python
import numpy as np, wave

with wave.open("raw_stem.wav", "rb") as w:
    rate = w.getframerate()
    audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)

# Ex: Cut rogue sound between 1.45s and 1.95s with a 10ms micro-crossfade
fade = int(0.01 * rate)
p1 = audio[:int(1.45 * rate)].copy()
p1[-fade:] *= np.linspace(1, 0, fade)

p2 = audio[int(1.95 * rate):].copy()
p2[:fade] *= np.linspace(0, 1, fade)

clean_audio = np.concatenate([p1, p2]).astype(np.int16)
```

---

## 🛠️ Python SDK Usage

Synthesize speech using the VoiceFi F5-TTS engine directly:

```python
import os
from pathlib import Path

# Set dynamic library path for macOS torchcodec
os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = "/opt/homebrew/lib"

from voicefi.tts.f5_tts import F5TTS

# Initialize on Apple Silicon Metal (MPS)
tts = F5TTS(device="mps")
tts.persona_name = "documentary_broadcaster"

# Synthesize directly to broadcast WAV
out_path = Path("/tmp/documentary_broadcaster_take.wav")
ok = tts.speak_to_file(
    "Carved over millennia... this limestone artery sustains life across the Texas hill country.",
    out_path
)
```

---

## 🧑‍🔬 Cloning Any New Voice (Step-by-Step Guide)

1. **Obtain High-Quality Reference Audio**:
   - Find or record a **10 to 15 second** clean voice clip.
   - Remove background noise, hum, or music using RX Spectral De-noise or Audacity.
   - Save as a 24,000Hz or 48,000Hz mono 16-bit WAV.
2. **Transcribe Word-for-Word**:
   - Transcribe the exact words spoken in the reference clip with precise punctuation.
3. **Register Persona**:
   - Create folder: `~/.voicefi/cloned_voices/<persona_name>/`
   - Store sample as: `~/.voicefi/cloned_voices/<persona_name>/samples/sample_01.wav`
   - Store transcript as: `~/.voicefi/cloned_voices/<persona_name>/samples/sample_01.txt`
4. **Test Synthesis**:
   - Run a test phrase using the Python script or CLI to verify acoustic resemblance.
