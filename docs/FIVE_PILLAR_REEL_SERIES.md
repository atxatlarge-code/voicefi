# 🎬 VoiceFi™ 5-Pillar Social Reel Series: Production Bible & Manifests

> **Series Theme:** *"The Universal Serial Voice (USV) & The Return of Joy to Computing"*  
> **Format:** 9:16 Vertical Video (1080x1920) for TikTok, Reels, YouTube Shorts, and X  
> **Production Standard:** 10–16 words max per hero card, sub-10ms word-level kinetic alignment, procedural lo-fi groove, dynamic -75% RMS speech ducking.

---

## 🗺️ The 5-Pillar Series Overview

| # | Pillar & Topic | Reel ID | Slug | Primary Characters | Key Hook / Premise | Status |
|---|---|---|---|---|---|---|
| **1** | **The Silent Screen Epidemic** | `REEL-005` | `the_glass_wall` | Jake, Viv, Steffan, Christopher, Emily | *"Your brain thinks at 400 WPM. Why choke it through a 60 WPM keyboard?"* | 🟢 Mastered (`.mp4`) |
| **2** | **The Pacing Coder & Remote Companion** | `REEL-009` | `coffee_walk_refactor` | Jake, Viv, Steffan | *"Refactor an entire service from across the room without touching your computer."* | 🟡 Script / Manifest Ready |
| **3** | **0ms On-Device Apple Silicon** | `REEL-014` | `0ms_apple_silicon` | Jake, Steffan, Viv, Christopher | *"Cloud roundtrips take 600ms. Human conversation happens in 200ms."* | 🟡 Script / Manifest Ready |
| **4** | **Cross-Agent Banter & Swarm** | `REEL-011` | `cross_agent_ping_pong` | Jake, Viv, Steffan, Emily | *"Stop copying and pasting between Claude Code and Antigravity like an unpaid intern."* | 🟡 Script / Manifest Ready |
| **5** | **Agent-First USV & WebMCP** | `REEL-015` | `the_usv_standard` | Jake, Viv, Steffan, Emily | *"In 1996, USB unified hardware. In 2026, USV unifies AI voice."* | 🟡 Script / Manifest Ready |

---

## 🎭 Cast & Voice Registry

| Character | Real Persona / Engine | Voice Model | Rate / Pitch | Brand Color | Signature Vibe |
|---|---|---|---|---|---|
| **Jake** | Human Creator | Native 48kHz Studio Mic | 1.0x / Native | `#8B9A46` *(Olive)* | Authentic, relatable builder |
| **Viv** | Antigravity Main Planner | `en-US-AvaNeural` | `-2%` / `+0Hz` | `#3186FF` *(Electric Blue)* | Energetic, fast planner, affirmative |
| **Steffan** | Claude Code Architect | `en-US-SteffanNeural` | `-2%` / `-1Hz` | `#D97757` *(Terra Cotta)* | Methodical, dry wit, precision |
| **Christopher** | Cursor IDE Architect | `en-US-ChristopherNeural` | `-2%` / `-1Hz` | `#00E5FF` *(Cyan)* | Deep, resonant, authoritative |
| **Emily** | VoiceFi Host & Outro | `en-IE-EmilyNeural` | `-2%` / `+0Hz` | `#10B981` *(Emerald)* | Melodic Irish cadence, crisp closer |

---

# 🎬 Detailed Reel Production Blueprints

---

### 1️⃣ REEL-005: The Silent Screen Epidemic (Breaking The Glass Wall)
* **Objective:** Ignite sensory empathy; challenge the assumption that coding must be a solitary, silent text slog.
* **Duration:** ~31 seconds
* **Assets:** `assets/reels/reel_005/` (`clip_0_jake.mp4` through `clip_4_emily.mp4`, `jake_intro.wav`)
* **Compiled Master:** `assets/reels/reel_005_the_glass_wall_9_16.mp4`

```json
{
  "slides": [
    {
      "slide_idx": 1,
      "speaker": "Jake",
      "tag_color": "#8B9A46",
      "hook": "Your brain thinks at 400 words a minute. Why are you choking it through a 60 word per minute keyboard?",
      "sfx": "harsh_keyboard_clacking"
    },
    {
      "slide_idx": 2,
      "speaker": "Viv",
      "tag_color": "#3186FF",
      "hook": "Your whole dev team lives in your pocket now! Talk to us on your phone from anywhere!",
      "sfx": "positive_whoosh"
    },
    {
      "slide_idx": 3,
      "speaker": "Steffan",
      "tag_color": "#D97757",
      "hook": "The QWERTY keyboard is 150 years old. Spoken voice has been in your DNA for 200,000 years.",
      "sfx": "subtle_gong"
    },
    {
      "slide_idx": 4,
      "speaker": "Christopher",
      "tag_color": "#00E5FF",
      "hook": "Stand up. Pace the room. Speak your thoughts into the air—we'll handle the git commits.",
      "sfx": "sub_bass_drop"
    },
    {
      "slide_idx": 5,
      "speaker": "Emily",
      "tag_color": "#10B981",
      "hook": "Break through the glass wall. Free your voice at voicefi dot org.",
      "sfx": "affirmative_bell_chime"
    }
  ]
}
```

---

### 2️⃣ REEL-009: The Pacing Coder & The Remote Companion
* **Objective:** Demonstrate hands-free roaming with `vifi rc` (PWA WebSocket relay) and the 10-word micro-steering habit.
* **Duration:** ~35 seconds
* **Visual Style:** Split-screen or live phone camera walking outside while Mac terminal executes in PIP.

```json
{
  "slides": [
    {
      "slide_idx": 1,
      "speaker": "Jake",
      "tag_color": "#F59E0B",
      "hook": "The best coding epiphanies happen when you’re pacing, not sitting hunched at a desk.",
      "sfx": "outdoor_footsteps"
    },
    {
      "slide_idx": 2,
      "speaker": "Viv",
      "tag_color": "#3186FF",
      "hook": "Run vifi rc on your Mac, pocket your phone, and walk out the front door.",
      "sfx": "phone_pairing_chime"
    },
    {
      "slide_idx": 3,
      "speaker": "Jake",
      "tag_color": "#10B981",
      "hook": "Viv, migrate session tokens to Redis and ping my AirPods when smoke tests pass.",
      "sfx": "mic_active_beep"
    },
    {
      "slide_idx": 4,
      "speaker": "Viv",
      "tag_color": "#3186FF",
      "hook": "Session tokens migrated. 18 concurrency tests passing in 420 milliseconds.",
      "sfx": "pass_fanfare"
    },
    {
      "slide_idx": 5,
      "speaker": "Steffan",
      "tag_color": "#8B5CF6",
      "hook": "3,300 turns of data proved it: 52% of your instructions become 10 words or fewer.",
      "sfx": "drum_smash"
    }
  ]
}
```

---

### 3️⃣ REEL-014: 0ms Apple Silicon vs. The Cloud Lag Trap
* **Objective:** Explain why cloud voice fails for coding (600ms lag + privacy risk) vs. instant offline Apple Silicon synthesis.
* **Duration:** ~30 seconds
* **Visual Style:** Speed race between a buffering cloud spinner and instantaneous Apple Silicon waveform bursts.

```json
{
  "slides": [
    {
      "slide_idx": 1,
      "speaker": "Jake",
      "tag_color": "#EF4444",
      "hook": "Why does cloud voice AI feel so painfully awkward in developer workflows?",
      "sfx": "dialup_modem_glitch"
    },
    {
      "slide_idx": 2,
      "speaker": "Steffan",
      "tag_color": "#D97757",
      "hook": "Cloud roundtrips take 600 milliseconds. Human conversational turn-taking happens in 200.",
      "sfx": "ticking_clock"
    },
    {
      "slide_idx": 3,
      "speaker": "Viv",
      "tag_color": "#3186FF",
      "hook": "VoiceFi runs directly on Apple Silicon Neural Engine. 0ms offline first-chunk latency.",
      "sfx": "laser_zap"
    },
    {
      "slide_idx": 4,
      "speaker": "Jake",
      "tag_color": "#10B981",
      "hook": "Zero cloud network latency. Zero third-party audio logging. Zero monthly TTS bills.",
      "sfx": "vault_lock"
    },
    {
      "slide_idx": 5,
      "speaker": "Emily",
      "tag_color": "#8B5CF6",
      "hook": "Run vifi voice download-ava on your Mac. Experience 0ms today at voicefi dot org.",
      "sfx": "victory_chime"
    }
  ]
}
```

---

### 4️⃣ REEL-011: The Agent Swarm (Claude Code ↔ Antigravity)
* **Objective:** Showcase multi-agent acoustic delegation (`vifi send`), pair programming, and comedic developer banter.
* **Duration:** ~33 seconds
* **Visual Style:** Antigravity and Claude terminal panes ping-ponging back and forth with rimshot effects.

```json
{
  "slides": [
    {
      "slide_idx": 1,
      "speaker": "Jake",
      "tag_color": "#EF4444",
      "hook": "Stop copying and pasting between Claude Code and Antigravity like an unpaid intern.",
      "sfx": "paper_shuffle"
    },
    {
      "slide_idx": 2,
      "speaker": "Jake",
      "tag_color": "#8B9A46",
      "hook": "Viv, send this slow query to Claude and ask why Prisma is taking four seconds.",
      "sfx": "swoosh"
    },
    {
      "slide_idx": 3,
      "speaker": "Steffan",
      "tag_color": "#D97757",
      "hook": "You're running an N plus one query inside a loop. Added compound index and batched it.",
      "sfx": "drum_smash"
    },
    {
      "slide_idx": 4,
      "speaker": "Viv",
      "tag_color": "#3186FF",
      "hook": "Don't get cocky Claude, I already merged your PR and verified the test suite.",
      "sfx": "honk"
    },
    {
      "slide_idx": 5,
      "speaker": "Emily",
      "tag_color": "#8B5CF6",
      "hook": "Orchestrate your multi-agent fleet out loud. Free at voicefi dot org.",
      "sfx": "applause"
    }
  ]
}
```

---

### 5️⃣ REEL-015: The USV (Universal Serial Voice & WebMCP)
* **Objective:** Establish USV as the open standard for AI agent acoustics across Stdio MCP, WebMCP, Unix Sockets, and REST.
* **Duration:** ~29 seconds
* **Visual Style:** 1996 USB cable clutter transforming into sleek VoiceFi Dynamic Island HUD.

```json
{
  "slides": [
    {
      "slide_idx": 1,
      "speaker": "Jake",
      "tag_color": "#3B82F6",
      "hook": "In 1996, USB unified computer hardware. In 2026, USV unifies AI voice.",
      "sfx": "usb_plug_in"
    },
    {
      "slide_idx": 2,
      "speaker": "Viv",
      "tag_color": "#3186FF",
      "hook": "USV is Universal Serial Voice. We gave AI agents native vocal cords and auditory reflexes.",
      "sfx": "harmonic_ping"
    },
    {
      "slide_idx": 3,
      "speaker": "Steffan",
      "tag_color": "#D97757",
      "hook": "Zero-install WebMCP in browser, Stdio MCP in Cursor, and Unix sockets in terminal.",
      "sfx": "keyboard_click"
    },
    {
      "slide_idx": 4,
      "speaker": "Jake",
      "tag_color": "#10B981",
      "hook": "Acoustic air traffic control ensures agents take turns and never talk over each other.",
      "sfx": "atc_radio_tone"
    },
    {
      "slide_idx": 5,
      "speaker": "Emily",
      "tag_color": "#8B5CF6",
      "hook": "Plug into the open USV standard. Star VoiceFi on GitHub today.",
      "sfx": "electric_chime"
    }
  ]
}
```
