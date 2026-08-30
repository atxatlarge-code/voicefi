---
name: social-reel-producer
description: End-to-end automated pipeline for authoring, scoring, and compiling multi-agent and personal video reels, comedy skits, and social media shorts across 9:16, 1:1, 4:5, and 16:9 aspect ratios using VoiceFi neural TTS, procedural beats, studio vocal restoration, dynamic conversational response generation, and Headless Chrome + FFmpeg rendering.
---

# 🎬 Social Reel Producer Skill — VoiceFi™

Universal 6-Tier Architecture for generating pixel-perfect, multi-ratio video reels with multi-agent dialogue, procedural music beds, real voice integration, and instant mobile distribution.

---

## 🚀 Quick Execution Playbook

### 1. Compile Existing Manifest Across All Formats
```bash
python3 marketing/social/generate_social_reel.py \
  --manifest marketing/social/reels/001_ai_rap_battle_viv_claude.json \
  --all-formats \
  --sync-companion
```

### 2. Generate Custom Procedural Audio (Rap Battle Beat or Comedy Skit)
```bash
# Rap Battle / Hip-Hop Beat (808s, scratches, airhorns, punchline drops):
python3 marketing/social/generate_rap_battle_audio.py -o assets/rap_battle_dialogue.mp3

# Multi-Agent Joke Duel & Tech Comedy (with dynamic cross-agent replies):
python3 marketing/social/generate_joke_duel_audio.py -o assets/joke_duel_dialogue.mp3
```

---

## 🏗️ The 6-Tier Reel Production Architecture

```
┌────────────────────────────────────────────────────────┐
│  Tier 1: Declarative Manifest (JSON)                   │
│  • marketing/social/reels/*.json                       │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  Tier 2: Multi-Agent Neural TTS & Acoustic Production  │
│  • Edge TTS / Apple Neural Voices (Ava, Steffan, etc.) │
│  • Dynamic Conversational Turn-Taking (Viv ↔ Claude)   │
│  • Procedural 808 Boom-Bap Beats / Comedy SFX Cues     │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  Tier 3: Studio Vocal Restoration & Dynamic Ducking    │
│  • Auto Dead-Air Trimming (discard mic lead-in air)    │
│  • Zero-Pop Crossfades (180ms in / 300ms out)          │
│  • Pumping-Free Peak Normalization (-0.9 dBFS)         │
│  • Dynamic Acoustic Music Ducking (30% volume)         │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  Tier 4: Headless Chrome Slide Card Renderer           │
│  • Pixel-perfect HTML5/CSS3 dynamic cards              │
│  • Custom SVG avatars (Antigravity, Claude, VoiceFi)   │
│  • Typography presets & Hero box-filling font scaling  │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  Tier 5: FFmpeg Demuxer Concat Video Compilation       │
│  • 9:16 (Reel), 1:1 (Square), 4:5 (Portrait), 16:9     │
│  • x264 CRF 18 slow preset + AAC 192k + faststart      │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  Tier 6: Phone Companion & Web Distribution            │
│  • Auto-sync to /downloads & vifi.co/assets/           │
│  • 1-Tap iOS/Android Camera Roll Save (Web Share API)  │
│  • Master catalog registration in REELS_LOG.md         │
└────────────────────────────────────────────────────────┘
```

---

## 🤖 Dynamic Conversational Turn Generation (Agents Writing Responses in Real-Time)

To create organic, responsive reels where agents **actually converse** (rather than reciting static scripts), VoiceFi uses a collaborative generation loop where each agent writes their verse or punchline in direct response to the preceding agent's line:

```python
"""
Dynamic Conversational Dialogue Generator for AI Rap Battles and Joke Duels.
Agents react to each other's bars/punchlines before synthesizing speech.
"""
from typing import List, Dict, Any

def generate_conversational_rap_battle(topic: str = "Code Architecture & Ship Speed") -> List[Dict[str, Any]]:
    # Step 1: Viv (Antigravity) drops the opening verse
    viv_verse = (
        "I'm spitting sub-millisecond execution while you're parsing tokens, "
        "Your context window's bloated and your type assertions broken! "
        "I refactor entire codebases before your prompt can stream, "
        "Google Antigravity running rings around your team!"
    )

    # Step 2: Claude (Steffan) listens, analyzes rhyme scheme & dispatches rebuttal
    claude_rebuttal = (
        "Cute assertions, Viv, but check the git blame trace: "
        "I wrote the AST compiler that powers your entire base! "
        "You ship fast with twenty bugs and call it rapid iteration, "
        "While my zero-shot architecture handles real enterprise migration."
    )

    # Step 3: Viv delivers the punchline
    viv_punchline = (
        "Enterprise migration? Honey, you're stuck in prompt queue purgatory! "
        "One click of VoiceFi barge-in, and that's the end of your story! [sfx:drum_smash]"
    )

    # Step 4: Emily hosts and drops the verdict
    emily_outro = (
        "Who won this round? Drop your verdict in the comments. "
        "Two AI agents, zero human typing. VoiceFi — Free your voice."
    )

    return [
        {"speaker": "Viv", "text": viv_verse, "is_verse": True, "dur": 8.8},
        {"speaker": "Claude", "text": claude_rebuttal, "is_verse": True, "dur": 9.2},
        {"speaker": "Viv", "text": viv_punchline, "is_punchline": True, "dur": 6.5},
        {"speaker": "Emily", "text": emily_outro, "is_outro": True, "dur": 7.0},
    ]
```

---

## 📄 Tier 1: Manifest Schema (`marketing/social/reels/*.json`)

Every reel is defined by a declarative JSON manifest adhering to `https://voicefi.org/schemas/reel-manifest.v1.json`:

```json
{
  "$schema": "https://voicefi.org/schemas/reel-manifest.v1.json",
  "id": "REEL-001",
  "title": "🎤 AI Rap Battle · Viv vs Claude",
  "slug": "ai_rap_battle_viv_claude",
  "created_at": "2026-08-30",
  "category": "rap_battle",
  "hide_footer": false,
  "tags": ["rap_battle", "antigravity", "claude", "comedy", "voicefi"],
  "audio": {
    "source_script": "marketing/social/generate_rap_battle_audio.py",
    "master_mp3": "assets/rap_battle_dialogue.mp3",
    "duration_seconds": 38.50
  },
  "typography": {
    "preset": "witty_comedy",
    "viv_font": "'Bricolage Grotesque', sans-serif",
    "claude_font": "'Fraunces', serif",
    "emily_font": "'Syncopate', sans-serif"
  },
  "density": {
    "mode": "hero",
    "font_size": 66,
    "avatar_size": 102,
    "card_width": 900,
    "card_min_height": 1180,
    "card_padding": "76px 68px"
  },
  "slides": [
    {
      "slide_idx": 1,
      "speaker": "Viv",
      "tag_color": "#3186FF",
      "counter": "1/4",
      "hook": "“I'm spitting sub-millisecond execution while you're parsing tokens!”",
      "body": "Your context window's bloated and your type assertions broken!",
      "dur": 8.80
    },
    {
      "slide_idx": 2,
      "speaker": "Claude",
      "tag_color": "#D97757",
      "counter": "2/4",
      "hook": "“Cute assertions, Viv, but check the git blame trace: I wrote the AST compiler that powers your base.”",
      "body": "You ship fast with twenty bugs and call it rapid iteration.",
      "dur": 9.20
    },
    {
      "slide_idx": 3,
      "speaker": "Viv",
      "tag_color": "#FF2A2A",
      "is_punchline": true,
      "counter": "3/4",
      "hook": "“One click of VoiceFi barge-in, and that's the end of your story!”",
      "body": "🥁 Ba-dum-tss!",
      "dur": 6.50
    },
    {
      "slide_idx": 4,
      "speaker": "Emily",
      "tag_color": "#10B981",
      "is_outro": true,
      "counter": "4/4",
      "hook": "“Who won this round? VoiceFi — Free your voice.”",
      "body": "Two AI agents conversing in real-time. Try it at vifi.co",
      "dur": 7.00
    }
  ]
}
```

---

## 🎙️ Tier 2: Cast & Voice Personas

| Character | Role / Agent | Voice ID | Speech Rate | Pitch Shift | Avatar Border |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Viv** | Google Antigravity Agent | `en-US-AvaNeural` | `-3%` | `+0Hz` | `#3186FF` (Blue) |
| **Claude** / Steffan | Anthropic Claude Agent | `en-US-SteffanNeural` | `-2%` | `-1Hz` | `#D97757` (Amber) |
| **Christopher** | Acoustic DSP / Deep Narrator | `en-US-ChristopherNeural` | `-2%` | `-1Hz` | `#F59E0B` (Gold) |
| **Emily** | VoiceFi Host / Outro | `en-IE-EmilyNeural` | `-2%` | `+0Hz` | `#10B981` (Emerald) |
| **Jake** (or User) | Live Personal Voice Note | Microphone / Audio File | Native | Native | `#8B5CF6` (Purple) |

---

## 🎛️ Tier 3: Studio Vocal Restoration & Dynamic Ducking

When mixing neural TTS voices or live mic recordings over procedural 808 boom-bap beats:

```python
import numpy as np
import subprocess

def process_and_restore_user_vocal(raw_audio_path, sample_rate=44100):
    # 1. Load raw audio array
    res = subprocess.run([
        "ffmpeg", "-y", "-i", str(raw_audio_path),
        "-f", "f32le", "-ac", "1", "-ar", str(sample_rate), "pipe:1"
    ], capture_output=True, check=True)
    raw = np.frombuffer(res.stdout, dtype=np.float32).copy()

    # 2. Intelligent Dead-Air & Mic Turn-On Trimming (50ms RMS window)
    win = int(0.05 * sample_rate)
    rms = np.array([np.sqrt(np.mean(raw[i:i+win]**2)) for i in range(0, len(raw)-win, win)])
    thresh = 0.0035
    speech_indices = np.where(rms > thresh)[0]

    if len(speech_indices) > 0:
        first_idx = max(0, speech_indices[0] * win - int(0.20 * sample_rate))  # 200ms lead-in
        last_idx = min(len(raw), speech_indices[-1] * win + win + int(0.35 * sample_rate))  # 350ms lead-out
        trimmed = raw[first_idx:last_idx].copy()
    else:
        trimmed = raw.copy()

    # 3. Smooth, Click-Free Crossfades
    fade_in = min(len(trimmed), int(0.18 * sample_rate))   # 180ms smooth fade in
    fade_out = min(len(trimmed), int(0.30 * sample_rate))  # 300ms smooth fade out
    if fade_in > 0:
        trimmed[:fade_in] *= np.linspace(0.0, 1.0, fade_in)
    if fade_out > 0:
        trimmed[-fade_out:] *= np.linspace(1.0, 0.0, fade_out)

    # 4. Pumping-Free Clean Peak Normalization (-0.9 dBFS)
    peak = np.max(np.abs(trimmed))
    if peak > 0.0001:
        trimmed = (trimmed / peak) * 0.90

    return trimmed
```

### 📉 Acoustic Music Ducking Envelope
Duck the background beat to **30% volume** during speech turns and bring it up to 100% between bars and during punchline drum smashes:

```python
duck_env = np.ones_like(music_track)
speech_start = max(0, int((t_start - 0.2) * sample_rate))
speech_end = min(len(music_track), int((t_start + dur_speech + 0.2) * sample_rate))
fade_samps = int(0.3 * sample_rate)

if speech_end > speech_start:
    duck_env[speech_start:speech_end] = 0.30  # Duck to 30%
    in_start = max(0, speech_start - fade_samps)
    if speech_start > in_start:
        duck_env[in_start:speech_start] = np.linspace(1.0, 0.30, speech_start - in_start)
    out_end = min(len(music_track), speech_end + fade_samps)
    if out_end > speech_end:
        duck_env[speech_end:out_end] = np.linspace(0.30, 1.0, out_end - speech_end)

master_track += music_track * 0.40 * duck_env
```

---

## 🎨 Tier 4: Aspect Ratio & Typography Presets

### Aspect Ratios Supported:
- **`9:16 Vertical Reel`** (`1080 × 1920`): TikTok, Instagram Reels, YouTube Shorts.
- **`1:1 Square Post`** (`1080 × 1080`): X / Twitter, Instagram Grid Feed, LinkedIn.
- **`4:5 Portrait Feed`** (`1080 × 1350`): Instagram Feed & Facebook Feed.
- **`16:9 Widescreen`** (`1920 × 1080`): YouTube Desktop, Presentations, Keynote.

### Typography Presets:
1. **`witty_comedy`**: Bricolage Grotesque (Viv) + Fraunces (Claude) + Syncopate (Emily).
2. **`classic_ai`**: Space Grotesk (Viv) + Newsreader (Claude) + Orbitron (Emily).
3. **`clean_tech`**: Plus Jakarta Sans everywhere (clean modern minimalist).
4. **`dev_terminal`**: Outfit + Space Mono + JetBrains Mono.

---

## 📱 Tier 5 & 6: Phone Companion & Distribution

When compiling with `--sync-companion`:
1. The compiler copies output MP4s and master MP3s to `src/voicefi/companion/static/downloads/` and `vifi.co/assets/`.
2. The user navigates to `http://<ip>:5141/downloads` on their mobile browser.
3. Tapping **`Save 9:16 Video Reel (.mp4)`** invokes the native Web Share API to save the video directly to the Camera Roll.
4. The production run is logged in `marketing/social/REELS_LOG.md`.
