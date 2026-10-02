---
name: local-content
description: Edge creative engine and conversational scriptwriter. Generates social reel scripts, comedy dialogue, AI rap battle lyrics, and character banter locally on Apple Silicon Metal GPU with zero API latency, directly feeding into VoiceFi's on-device MLX neural TTS pipelines.
---

# 🎨 Local-Content: Edge Creative Engine & Audio/Dialogue Pipeline

The **`local-content`** skill leverages local models (Gemma 4, Qwen 2.5) on Apple Silicon Metal GPU to draft high-turn conversational scripts, social media reels, lyrics, and comedic dialogue with **zero cloud API costs** and **sub-second latency**. The output directly hooks into VoiceFi's discrete codec MLX engine (Qwen3-TTS), F5-TTS neural cloning, and procedural beats.

Use this skill whenever:
- You want to draft 10–20 variations of social reel hooks, comedic skits, or podcast dialogue offline.
- You need rhythmically calibrated rap lyrics, rhyming brag verses, or chorus hooks without paying cloud per-token fees.
- You want real-time agent-to-agent banter between Antigravity and Claude Code with spoken audio delivery.
- You are generating declarative reel manifests for automated video rendering (`social-reel-producer`).

---

## ⚡ Architecture: The Zero-Latency Edge Creative Pipeline

```
Prompt / Topic / Beat BPM
         │
         ▼ (Instant local generation; $0 cost)
┌───────────────────────────────────────┐
│  Tier 1: Local Creative LLM           │  --> Drafts verses, dialogue turns, and audio cue tags
└──────────────────┬────────────────────┘      (e.g., [honk], [drum_smash], [applause])
                   │
                   ▼ (Declarative Dialogue Manifest)
┌───────────────────────────────────────┐
│  Tier 2: VoiceFi MLX Neural TTS       │  --> Synthesizes multi-voice audio locally
└──────────────────┬────────────────────┘      (Qwen3-TTS / F5-TTS / Ava)
                   │
                   ▼ (Whisper Alignment & FFmpeg)
┌───────────────────────────────────────┐
│  Output: Ready-to-Publish Reel/Audio  │  --> Rendered on Apple Silicon VideoToolbox
└───────────────────────────────────────┘
```

---

## 🛠️ How to Trigger

### 1. In Antigravity & Claude Code
When orchestrating creative content, prompt the local engine with strict formatting constraints:

```markdown
Draft a 30-second AI rap duel between Antigravity (cerebral, calm) and Claude Code (staccato, pragmatic) on why local Metal GPU beats WAN latency. Include inline SFX tags like [drum_smash].
```

### 2. From CLI & VoiceFi Integrations
```bash
# 🎙️ Generate spoken dialogue directly via local Gemini Spark runner
vifi spark -p "Give me a quick 10-second roast of cloud latency"

# 🎬 Produce a social reel locally
vifi reel compile --topic "Local vs Cloud"

# 🔊 Audition a local voice persona
vifi persona Viv -s "Testing local creative audio generation on Apple Silicon."
```

### 3. Pairing with Sibling Skills
- **[`lyric-crafting`](file:///Users/jaketrigg/Projects/vifi.co/.agents/skills/lyric-crafting/SKILL.md)**: 6-stage iterative lyric-smithing pipeline for rap tracks.
- **[`reel-scriptwriter`](file:///Users/jaketrigg/Projects/VoiceFi/.agents/skills/reel-scriptwriter/SKILL.md)**: Dialogue timing calibration and hero-card word budgeting.
- **[`social-reel-producer`](file:///Users/jaketrigg/Projects/VoiceFi/.agents/skills/social-reel-producer/SKILL.md)**: End-to-end automated video compilation with Playwright active-word rendering and FFmpeg acceleration.
- **[`voice-acting`](file:///Users/jaketrigg/Projects/VoiceFi/.agents/skills/voice-acting/SKILL.md)**: Character performances and vocal formants via MLX.

---

## 🛡️ Guardrails

1. **Memory Arbitration**: Ensure large 26B coding models are unallocated before loading heavy MLX multi-speaker voice pipelines on systems with $\le$ 24GB Unified Memory.
2. **Word Budget Adherence**: Enforce strict per-turn word count limits ($\le$ 28 words per scene) when targeting 9:16 vertical video reels.
