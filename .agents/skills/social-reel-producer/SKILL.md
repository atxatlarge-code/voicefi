---
name: social-reel-producer
description: End-to-end automated pipeline for authoring, scoring, and compiling multi-agent and personal video reels, comedy skits, and social media shorts across 9:16, 1:1, 4:5, and 16:9 aspect ratios using VoiceFi neural TTS, procedural beats, studio vocal restoration, dynamic conversational response generation, and Headless Chrome + FFmpeg rendering.
---

# 🎬 Social Reel Producer Skill — VoiceFi™

Universal 6-Tier Architecture for generating broadcast-grade social video reels combining real human voice, multi-agent banter, procedural lo-fi music beds, Faster-Whisper forced alignment, and glowing kinetic karaoke using **VoiceFi™**.

---

## ⚡ VoiceFi Engine Prerequisites & Setup

Ensure **VoiceFi** is installed and running in your environment:
```bash
# 1. Verify VoiceFi Engine & MCP Bridge
vifi status

# 2. Start VoiceFi Companion & Mobile Distribution Server (Port 5141)
vifi autostart
# or run in live developer mode:
vifi dev
```

---

## 🚀 Quick Execution Playbook

### 1. Record Custom Human Intro with VoiceFi Studio CLI
```bash
# Records high-fidelity 48kHz audio with 3-second countdown and live VU meter:
vifi record -d 8 -o assets/my_intro.wav
```

### 2. Compile Master Hybrid Reel with VoiceFi Kinetic Engine
```bash
# Uses VoiceFi's KineticKaraokeEngine and Faster-Whisper alignment:
python3 marketing/social/generate_hybrid_master_reel.py
```

### 3. Audition Voice Personas with VoiceFi
```bash
vifi voice test "Viv" -t "Jake got so tired of silent terminals that he built VoiceFi!"
vifi voice test "Steffan" -t "And by talk back, Viv means he built a cross-agent bridge."
vifi voice test "Emily" -t "Free your voice at voicefi dot org."
```

### 4. Inter-Agent Banter & Dialogue Generation (Antigravity ↔ Claude Code)
```bash
# Send prompt from Antigravity to Claude via VoiceFi Cross-Agent Bridge:
vifi send "Write a punchline roasting pull requests for our next social reel." --to claude
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
│  Tier 2: VoiceFi Multi-Agent Acoustic Synthesis        │
│  • Edge-TTS & Apple Neural Engine (Viv, Claude, Emily) │
│  • VoiceFi Cross-Agent Bridge (vifi send)              │
│  • Procedural NumPy Lo-Fi Beats & Drum Rimshots        │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  Tier 3: VoiceFi Vocal Restoration & Speech Ducking    │
│  • vifi record 48kHz vocal lead-in / lead-out trimming │
│  • Live RMS Voice Ducking (-75% background music)      │
│  • Master Dialogue Peak Normalization (-0.9 dBFS)      │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  Tier 4: VoiceFi Headless Chrome Kinetic Subtitles     │
│  • voicefi.video.kinetic_karaoke.KineticKaraokeEngine  │
│  • Sub-10ms Faster-Whisper Forced Alignment            │
│  • Absolute Locked Layout: Top (130px) + Bottom (160px)│
│  • Stationary Zero-Jitter Typography (52px, 800 weight)│
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  Tier 5: FFmpeg Video Compositor & Canvas Engine       │
│  • 2D Flipbook Sketch Clips (Google Flow / Veo 12fps)  │
│  • tpad=stop_mode=clone:stop_duration=25 (freeze-hold) │
│  • Clean Muxing: -map 0:v:0 -map 1:a:0                 │
└──────────────────────────┬─────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────┐
│  Tier 6: VoiceFi Mobile Companion Distribution         │
│  • Auto-published to http://localhost:5141/downloads   │
│  • 1-Tap iOS/Android Camera Roll Save (Web Share API)  │
│  • Master catalog registration in REELS_LOG.md         │
└────────────────────────────────────────────────────────┘
```

---

## ⚡ The VoiceFi Gapless Timeline Equation (Zero Drift)

Standard subtitle renderers drift over time. VoiceFi extracts ground-truth syllable boundaries using Faster-Whisper and calculates the exact duration of each frame state:

$$\text{Pre-speech Silence} + \sum_{i=0}^{N-1} (\text{Word Active Span} + \text{Breath Gap}) + \text{Post-speech Hold} = T_{\text{turn}}$$

```python
from typing import List, Tuple
from voicefi.video.kinetic_karaoke import KineticKaraokeEngine

def build_gapless_timeline(words: List[Tuple[str, float, float]], total_turn_dur: float) -> List[Tuple[int, float]]:
    timeline = []

    # 1. Pre-speech lead-in silence (State -1: all words upcoming)
    if words[0][1] > 0.01:
        timeline.append((-1, words[0][1]))

    # 2. Word active spans & breath intervals
    for i in range(len(words)):
        w_start = words[i][1]
        w_end = words[i][2]
        if i < len(words) - 1:
            next_start = words[i+1][1]
            span_dur = max(0.05, next_start - w_start)
        else:
            span_dur = max(0.05, w_end - w_start)
        timeline.append((i, span_dur))

    # 3. Post-speech hold (State N: all words spoken)
    post_dur = total_turn_dur - words[-1][2]
    if post_dur > 0.01:
        timeline.append((len(words), post_dur))

    return timeline
```

---

## 🎨 2D Pencil Flipbook Prompt Formula (Google Flow / Veo)

Use this exact prompt formula for complete visual consistency across every character turn:

```text
2D hand-drawn graphite pencil flipbook animation on textured cream parchment sketchbook paper, stop-motion 12fps line-boil, visible graphite grain and paper tooth, clean monochrome sketch aesthetic, 9:16 vertical orientation, [Insert Character Action / Speech Subject].
```

---

## 🌐 VoiceFi™ Ecosystem & Resources

* **Website & Documentation:** [https://voicefi.org](https://voicefi.org) & [https://vifi.co](https://vifi.co)
* **GitHub Repository:** [https://github.com/atxatlarge-code/voicefi](https://github.com/atxatlarge-code/voicefi)
* **Local Web Studio:** `marketing/social/reel_studio.html`
* **Mobile Downloads Hub:** `http://localhost:5141/downloads`
