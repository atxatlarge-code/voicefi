---
name: speed-talking
description: Enables AI agents to discover, configure, test, and operate VoiceFi Speed Talking acceleration (1.25x to 3.0x velocity) with pause compression, dynamic ramping, and developer time-saved analytics.
---

# ⚡ Speed Talking & High-Velocity Voice Productivity Skill

Use this skill when the user asks to speed up speech, enable fast audio responses, listen to summaries at 1.5x-3.0x velocity, configure speech rate presets, or check how much time they've saved.

---

## 🏎️ Available Presets & Multipliers

| Preset | Multiplier | Words/Min | Offset | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Normal** | `1.0x` | 200 WPM | `+0%` | Baseline natural conversational speed. |
| **Breezy** | `1.25x` | 250 WPM | `+25%` | Effortless listening with zero cognitive fatigue. |
| **Fast** | `1.5x` | 300 WPM | `+50%` | **Developer sweet spot** — saves 33% time with 100% consonant clarity. |
| **Turbo** | `1.75x` | 350 WPM | `+75%` | High velocity for rapid turn notifications and quick summaries. |
| **Sonic / Auctioneer** | `2.0x` | 400 WPM | `+100%` | Double speed — strictly cuts listening duration in half. |
| **Warp / Ludicrous** | `2.5x` | 500 WPM | `+150%` | Ultra-fast soundbite stream for speed listening power users. |
| **Supersonic** | `3.0x` | 600 WPM | `+200%` | Maximum velocity with aggressive high-frequency presence boost. |

---

## 🛠️ CLI Quick Commands

### 1. Toggle & Configure Speed Talking
```bash
# Check current Speed Talking status, multiplier, and time saved:
vifi speed-talk

# Enable Speed Talking:
vifi speed-talk on

# Set specific preset:
vifi speed-talk set turbo
vifi speed-talk set fast
vifi speed-talk set sonic
vifi speed-talk set warp

# Set exact multiplier:
vifi speed-talk 1.75x
vifi speed-talk 2.0x

# Disable and return to 1.0x normal baseline:
vifi speed-talk off
```

### 2. Audition & Test Speed Talking
```bash
# Test playback at current speed talking configuration:
vifi speed-talk test

# Test at a specific speed:
vifi speed-talk test turbo -t "Refactoring complete! All 24 test suites passed with zero regressions."

# Audition Dynamic Speed Ramping (starts at 1.0x and escalates to 1.75x over 2.5s):
vifi speed-talk ramp

# Play escalating multi-speed showcase (1.0x -> 1.25x -> 1.5x -> 2.0x -> 2.5x):
vifi speed-talk demo
```

### 3. Check Observability & Time-Saved Metrics
```bash
# Display 30-day cumulative listening minutes/hours saved:
vifi speed-talk stats
```

---

## 🔌 MCP Tool Usage

AI agents can interact directly with Speed Talking via MCP:

### Tool: `voicefi_speed_talk`
```json
// Query active status & time saved
{
  "name": "voicefi_speed_talk",
  "arguments": { "action": "status" }
}

// Enable Speed Talking with preset
{
  "name": "voicefi_speed_talk",
  "arguments": { "action": "enable", "preset": "turbo" }
}

// Set exact multiplier
{
  "name": "voicefi_speed_talk",
  "arguments": { "action": "set", "preset": "1.75x" }
}

// Audition a test phrase
{
  "name": "voicefi_speed_talk",
  "arguments": {
    "action": "test",
    "preset": "fast",
    "text": "Checking fast audio speed."
  }
}
```

### Tool: `voicefi_speak` with Speed Override
```json
{
  "name": "voicefi_speak",
  "arguments": {
    "text": "Build succeeded in 320 milliseconds.",
    "speed": "turbo"
  }
}
```
