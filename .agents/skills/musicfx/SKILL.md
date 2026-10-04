---
name: musicfx
description: Directs, prompts, automates, and masters high-fidelity AI music generation using Google MusicFX and MusicLM. Features prompt tokenization, chip/slider weighting, DJ mode loop stacking, negative instrumental safeguards against phantom vocals, and automated audio post-processing (loop alignment, -16 LUFS broadcast mastering, and sidechain ducking under VoiceFi voice acting).
---

# 🎵 MusicFX Skill — VoiceFi™

The definitive engineering and operational guide for directing, prompting, automating, and mastering AI-generated instrumental audio with **Google MusicFX** (powered by MusicLM).

Use this skill whenever generating musical beds, commercial bumpers, parody jingles, procedural background beats for social reels, or podcast stingers.

---

## 🎯 What is Google MusicFX?

Google MusicFX is a generative music sandbox developed by Google Labs and Google DeepMind, powered by **MusicLM** and discrete neural audio diffusion. 

Unlike traditional static audio libraries, MusicFX generates continuous, high-fidelity (44.1kHz/48kHz) stereo music conditioned on natural language prompts, tempo, and interactive semantic "chips" (prompt pills).

### Core Capabilities:
1. **Interactive Chip Tokenization**: Prompts are parsed into interactive pill tags with intensity sliders (`0%` to `100%`).
2. **DJ Mode / Infinite Loop Stacking**: Allows continuous real-time crossfading between musical genres, moods, and instrumental layers.
3. **Tempo & Pitch Consistency**: Maintains steady rhythmic tempo suitable for grid-aligned video editing and voiceover ducking.

---

## 🎛️ The Anatomy of a High-Yield MusicFX Prompt

To achieve professional broadcast quality, every prompt must combine **5 acoustic pillars**:

```
[Era & Broadcast Genre] + [Core Lead Instrument] + [Rhythm & Low-End Bass] + [Cadence & Melodic Hook] + [Strict Instrumental Guardrail]
```

### The 5 Pillars Explained:

| Pillar | Purpose | Example Terms |
| :--- | :--- | :--- |
| **1. Era & Broadcast Genre** | Establishes the production era and mixing aesthetic. | `Early 1990s television commercial jingle`, `1980s synthwave`, `Modern luxury perfume bumper` |
| **2. Core Lead Instrument** | Dictates harmonic timbre and chord warmth. | `Fender Rhodes Mark II electric piano with chorus`, `Yamaha DX7 bell keys`, `Warm analog Oberheim pad` |
| **3. Rhythm & Low-End** | Defines the tempo, swing, and percussion weight. | `85 BPM`, `Soft R&B finger snaps`, `Smooth fretless bassline`, `Brush snare`, `Tight 90s kick` |
| **4. Cadence & Melodic Hook** | Directs how phrases resolve. | `Two-phrase commercial hook`, `Crystalline glass chimes on turnaround`, `Glockenspiel resolve` |
| **5. Strict Instrumental Guardrail** | **CRITICAL:** Suppresses AI vocal chops and phantom hums. | `Strictly instrumental, wordless backing track, zero vocals, no singing, no choir, no human voice` |

---

## 🚫 The Ghost Vocal Rule (Negative Prompting)

MusicFX is trained on vast multi-genre audio corpora. If a prompt includes evocative words like *"sensual"*, *"pop"*, *"soulful"*, or *"catchy"*, the model will frequently synthesize alien vocal chops, muffled humming, or synthetic choir artifacts.

### 🛡️ The Mandatory Guardrail Formula
Always append this exact phrase to the end of any instrumental prompt:
```text
Strictly instrumental, wordless backing track, zero vocals, no singing, no choir, no human voice.
```

---

## 🎹 Production Recipes Library

### 1. 1990s Cosmetics Commercial Jingle (The Maybelline Recipe)
* **Target:** 82–85 BPM, 10–15s loop, Rhodes electric piano, glass chime resolve.
```text
Early 1990s luxury cosmetics television commercial jingle bumper, Fender Rhodes electric piano with warm stereo chorus and gentle tremolo, sparkling FM synthesizer bells, crystalline glass chimes on the turnaround resolve, smooth fretless bassline, soft R&B finger snaps, lush warm analog synth pad swells, daytime television glamour, sensual slow-motion fashion aesthetic, pristine studio master, 85 BPM, strictly instrumental, wordless backing track, zero vocals, no singing.
```

### 2. Late-90s Upbeat TV Commercial Bed
* **Target:** 96–100 BPM, bright, punchy, optimistic broadcast energy.
```text
Late 1990s daytime television beauty commercial bumper, bright FM synthesizer piano, crisp 90s pop drum groove with tight snare rimshot, punchy melodic bassline, shimmering wind chimes, uplifting two-chord melodic rise and sparkling glockenspiel resolve, polished broadcast audio, glossy, radiant, high-energy fashion aesthetic, 96 BPM, strictly instrumental, no singing, no vocals, no choir, wordless commercial jingle bed.
```

### 3. High-End Editorial Luxury Minimalist
* **Target:** 75 BPM, spacious, reverb-drenched, cinematic breath.
```text
High-fashion luxury cosmetics editorial bumper, lush solo Rhodes chords drenched in warm hall reverb, deep gentle sub-bass pulse, airy ambient textures, single crystalline glass chime accent on the turnaround, minimalist, elegant, mysterious, slow tempo, unhurried pacing, audiophile studio master, high dynamic range, instrumental only, completely wordless, zero vocals, no singing, no humming.
```

### 4. 90s "Quiet Storm" R&B Groove
* **Target:** 84 BPM, silky vintage R&B slow jam with tape warmth.
```text
1992 smooth R&B commercial jingle instrumental, silky Yamaha DX7 electric piano bell tones, warm vintage synth pad, delicate tambourine, soft kick and finger snaps, smooth walking bassline, catchy two-phrase commercial hook structure with a twinkling bell tree chime at the cadence, 84 BPM, vintage broadcast aesthetic, 100% instrumental, no human voices, no vocal chops, wordless backing track.
```

### 5. Tech Startup Product Origin Stinger
* **Target:** 115 BPM, modern, rhythmic, forward-momentum synthesizer.
```text
Modern tech keynote launch teaser bumper, clean plucked synth arpeggio, punchy electronic kick, warm analog Moog bassline, subtle white noise risers, polished modular synthesizer groove, crisp hi-hat tick, 115 BPM, pristine stereo imaging, forward momentum, completely instrumental, zero vocals.
```

---

## 🔄 DJ Mode & The "Circle Them All" Strategy

In Google MusicFX's **DJ Mode**:
1. Paste your prompt into the main bar.
2. MusicFX will parse the text into interactive token chips (e.g. `[Fender Rhodes]`, `[Glass Chimes]`, `[85 BPM]`, `[Luxury Cosmetics]`).
3. **Circle / Activate all chips**: Rather than isolating a single genre, activating all chips produces a layered, full-frequency broadcast texture without dead frequency pockets.
4. Adjust the **Density / Intensity** slider to ~`70-85%` for warm analog balance without digital clipping.

---

## 🎚️ Audio Post-Processing & Mastering Pipeline

Once a MusicFX `.wav` or `.mp3` is generated:

### 1. Grid Alignment & Trimming (ffmpeg)
Trim the track to exact musical beats (e.g., 8 bars at 85 BPM = 22.588s, or a 4-bar stinger = 5.647s):
```bash
# Trim exact 8.0s commercial bumper with clean micro-fade:
ffmpeg -y -i input_musicfx.mp3 \
  -t 8.0 \
  -af "afade=t=in:ss=0:d=0.04,afade=t=out:st=7.6:d=0.4" \
  -b:a 192k trimmed_bumper.mp3
```

### 2. Broadcast Loudness Normalization (-16 LUFS)
Match streaming and podcast broadcast loudness standards:
```bash
ffmpeg -y -i trimmed_bumper.mp3 \
  -af "loudnorm=I=-16:TP=-1.5:LRA=11" \
  mastered_music.mp3
```

### 3. Voiceover Sidechain Ducking
To seat VoiceFi voice acting cleanly over the MusicFX instrumental, duck the music track by `-12dB` whenever the voice speaks:
```bash
ffmpeg -y -i voice_track.wav -i mastered_music.mp3 \
  -filter_complex "[1:a]volume=0.85[music]; [music][0:a]sidechaincompress=threshold=0.08:ratio=4:attack=20:release=250[ducked]; [ducked][0:a]amix=inputs=2:duration=longest" \
  final_mix.mp3
```

---

## 🛠️ Included Automation & Helper Scripts

* **`scripts/musicfx_prompt.py`**: Formats, validates, and optimizes prompt chips for any era or style.
* **`scripts/musicfx_master.py`**: Trims, normalizes, and mixes MusicFX backing tracks with VoiceFi voice acting.
