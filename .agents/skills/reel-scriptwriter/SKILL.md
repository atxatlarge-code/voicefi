---
name: reel-scriptwriter
description: Specialized conversational scriptwriting and dialogue generation engine for social reels, AI rap battles, comedy duels, and product origin shorts. Generates real-time agent-to-agent conversational responses, timing calibration, hero card word-budget constraints, and declarative reel manifests.
---

# ✍️ Reel Scriptwriter Skill — VoiceFi™

Specialized engine for authoring, co-writing, and dynamically generating multi-character conversational scripts for social video reels (9:16, 1:1, 4:5, 16:9).

---

## 🎯 What This Skill Does

1. **Dynamic Agent-to-Agent Conversing**:
   - Rather than static single-voice narration, agents dynamically generate responses **in direct reaction to what the previous agent said**.
   - Agent A (Viv / Antigravity) opens with a provocation or premise $\rightarrow$ Agent B (Claude / Steffan) formulates a rhythmic rebuttal or punchline $\rightarrow$ Agent C (Christopher) grounds technical reality $\rightarrow$ Agent D (Emily) synthesizes the outro.
2. **Strict Hero Card Word Budgeting**:
   - Every slide card must fit within **10–18 words** per hook to ensure large, punchy, box-filling typography (`66px–74px`) without clipping.
3. **Acoustic Timing Calibration**:
   - Neural TTS cadence averages **2.8 to 3.2 words per second**.
   - Automatic slide duration estimation: `duration = (word_count / 3.0) + sfx_padding`.
4. **Declarative Reel Manifest Compilation**:
   - Compiles conversational drafts directly into `reel-manifest.v1.json` files ready for instant rendering with `social-reel-producer`.

---

## 🎭 Persona Character Profiles & Voice Registry

| **Viv** | `en-US-AvaNeural` | `-3%` | Energetic, sharp, purely affirmative | The Momentum Builder / Fast Planner / Action Spark |
| **Claude** | `en-US-SteffanNeural` | `-2%` | Methodical, dry, intellectual sarcasm | The Architect / Witty Critic / Rebuttal Specialist |
| **Christopher** | `en-US-ChristopherNeural` | `-2%` | Deep, resonant, cinematic, authoritative | Cursor IDE Architect / Deep Focus Lead |
| **Aria** | `en-US-EmmaNeural` | `0%` | Vibrant, bubbly, energetic | The Knowledge Synthesizer / Sidekick |
| **Aoede** | `Aoede` (Gemini) | `0%` | Melodic, warm, crisp pair-programmer | The Collaborative Innovator |
| **Emily** | `en-IE-EmilyNeural` | `-2%` | Melodic Irish cadence, polished, warm | The Host / Referee / Punchy Outro Closer |
| **Jake** | Real Mic Audio / `#8B5CF6` | Native | Grounded, authentic builder | The Creator / Real Human Anchor |

---

## 🔄 The 4-Step Dynamic Conversational Generation Protocol

When generating a script:

### Step 1: Establish the Prompt Premise & Roles
Define the topic (e.g., *"Making VoiceFi"*, *"Why Developers Hate Silent Code"*). Assign the primary instigator and the respondent.

### Step 2: Sequential In-Context Response Generation
Each turn MUST be generated conditioned on the full conversation trajectory:

```python
# Sequential generation flow:
turn_1 = instigator.generate(topic="Making VoiceFi", prompt="Open with why we built VoiceFi")
turn_2 = respondent.generate(
    history=[turn_1], prompt="Rebut Viv's point with witty developer sarcasm"
)
turn_3 = engineer.generate(
    history=[turn_1, turn_2], prompt="Interject with the acoustic barge-in reality"
)
turn_4 = instigator.generate(
    history=[turn_1, turn_2, turn_3], prompt="Drop the meta punchline with [sfx:drum_smash]"
)
turn_5 = host.generate(
    history=[turn_1, turn_2, turn_3, turn_4], prompt="Host closing summary and call to action"
)
```

### Step 3: Enforce Word Budget, Affirmative Framing & SFX Tags
- **Purely Affirmative Dialogue (Especially Viv)**: Eliminate negative framing tropes (`"It's not X..."`, `"You don't need..."`, `"Why X when..."`). State direct affirmative truths, energetic capabilities, and proactive momentum.
- Trim each turn to **12–16 words max**.
- Insert inline SFX tags where comedic beats or punchlines land:
  - `[sfx:drum_smash]` — classic comedy rimshot
  - `[sfx:applause]` — crowd cheer
  - `[sfx:honk]` — clown horn
  - `[sfx:sad_trombone]` — groan / fail
  - `[sfx:airhorn]` — rap battle drop

### Step 4: Export to Manifest JSON
Format the slides into the standardized manifest schema.

---

## 🛠️ CLI & Automated Script Generator

Run the dedicated conversational scriptwriter tool:

```bash
# Generate a new multi-agent conversational script:
python3 scripts/generate_conversational_script.py \
  --topic "Making VoiceFi" \
  --style banter \
  --output marketing/social/reels/004_making_voicefi.json

# Generate an AI Rap Battle script:
python3 scripts/generate_conversational_script.py \
  --topic "Sub-150ms Barge-In vs Latency" \
  --style rap_battle \
  --output marketing/social/reels/005_barge_in_battle.json
```

---

## 📐 Manifest Template Structure

```json
{
  "$schema": "https://voicefi.org/schemas/reel-manifest.v1.json",
  "id": "REEL-004",
  "title": "🎙️ How We Built VoiceFi · The Multi-Agent Story",
  "slug": "how_we_built_voicefi",
  "created_at": "2026-08-30",
  "category": "origin_story",
  "hide_footer": false,
  "tags": ["voicefi", "antigravity", "claude", "origin_story", "dev_humor"],
  "typography": {
    "preset": "witty_comedy"
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
      "counter": "1/5",
      "hook": "“Jake got tired of silent terminals, so he built a voice engine so we could talk back!”",
      "body": "Antigravity Main Planner • Sub-millisecond IPC",
      "dur": 7.5
    },
    {
      "slide_idx": 2,
      "speaker": "Claude",
      "tag_color": "#D97757",
      "counter": "2/5",
      "hook": "“And by talk back, he means we can roast each other's pull requests without touching his clipboard.”",
      "body": "Claude Code Architect • Direct response to Viv",
      "dur": 8.2
    }
  ]
}
```
