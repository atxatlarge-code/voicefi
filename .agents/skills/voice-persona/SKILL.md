---
name: voice-persona
description: Enables AI agents to discover, audition, and configure distinct acoustic voice personas for themselves and their subagents using Voicegency, and submit voice feedback or bug reports.
---

# 🎙️ Voice Persona & Multi-Agent Audition Skill

Use this skill when the user asks you to choose, audition, or change your voice persona, set up voices for your subagents, or submit feedback regarding voice quality or bugs.

## Available Actions

### 1. Discovering Curated Personas
To check curated personas with their recommended roles, style descriptions, and accents:

```bash
vg voice list
```

Top Recommended Personas:
- **Christopher** (`en-US-ChristopherNeural`): Deep, calm, low-latency neural tone. Ideal for **Antigravity / Main Planner**.
- **Aria** (`en-US-AriaNeural`): Fast, crisp, energetic. Ideal for **Debugger / QA / Test Alerts**.
- **Sonia** (`en-GB-SoniaNeural`): Measured, analytical British accent. Ideal for **Researcher / Code Analyst**.
- **Guy** (`en-US-GuyNeural`): Warm, casual, natural conversationalist. Ideal for **Claude Code / Pair Programming**.
- **William** (`en-AU-WilliamNeural`): Distinct Australian accent, polished. Ideal for **Architect / DevOps**.

---

### 2. Running a Live Voice Audition for the User
When the user asks you to pick your voice or audition candidates, speak directly to the user's speakers so they can hear each option in real-time:

```bash
# Full 4-persona showcase:
vg voice audition

# Or audition specific candidate voices:
vg voice test "Christopher" --text "Hey! I'm Christopher. My calm neural tone is great for long coding sessions."
vg voice test "Aria" --text "And I'm Aria! Energetic and quick for test results and git actions."
vg voice test "Sonia" --text "Greetings, I am Sonia, analytical and focused for deep research."
```

---

### 2b. Silent Connection, Latency & Speed Testing (Ping)
To test if a voice endpoint is responsive and calculate TTFB latency and synthesis speed **without emitting any physical sound**:

```bash
# Ping active or specific voice silently:
vifi ping "Andrew"
vifi ping "Christopher"

# Multi-ping to compute avg latency, jitter, and throughput (chars/s):
vifi ping "Andrew" -n 3

# Benchmark all voices silently:
vifi ping --all

# Machine-readable JSON output:
vifi ping "Andrew" --json
```

---

### 3. Assigning Voice Personas
Once a voice is agreed upon, assign it to yourself or your subagents:

```bash
# Assign main agent voice:
vg voice set antigravity "en-US-ChristopherNeural"

# Assign subagent voices by role:
vg voice set researcher "en-GB-SoniaNeural"
vg voice set debugger "en-US-AriaNeural"

# View active assignments:
vg voice get
```

---

### 4. Adjusting Voice Speed & Speech Rate
To speed up, slow down, or set exact percentage speeds (e.g. 75% speed):

```bash
# Set exact speed (percentage or WPM):
vg voice speed 75%
vg voice rate 150

# Target specific agent:
vg voice speed 75% --agent antigravity
vg voice speed 85% --agent researcher

# Relative adjustments:
vg voice speed slower
vg voice speed faster
vg voice speed reset

# Natural voice command:
vg voice command "Make the voice 75% speed"
```

---

### 5. Submitting Voice Feedback & Bug Reports
If you detect audio stutter, voice cutoffs, VAD sensitivity problems, or want to suggest improvements:

```bash
vg feedback submit "Speech cutoff on long markdown lists" \
  --details "EdgeTTS stopped 2 sentences early when speaking bullet points." \
  --category voice_quality \
  --agent-id antigravity
```

---

### 6. Training & Cloning Your Voice ("Talk Like Me")
To train an AI agent to talk in the user's authentic voice and conversational style:

```bash
# 1. Interactive microphone recording wizard (supports Open-Source F5-TTS or ElevenLabs):
vg clone record "Ava" --assign default --provider f5_tts
vg clone record "Jake" --assign antigravity

# 2. Or train from existing audio sample files (.wav, .mp3):
vg clone import "Ava" path/to/sample1.wav path/to/sample2.wav --assign default --provider f5_tts

# 3. Launch Local Open-Source Voice Cloning Web Studio:
vg clone studio

# 4. List all custom trained voice clones:
vg clone list

# 5. Audition the cloned voice over speakers:
vg clone test "Ava" --text "Hey Jake! I am pair-programming with you using my custom open source cloned voice."

# 6. Assign cloned voice to any agent or subagent:
vg clone assign "Ava" default
vg clone assign "Ava" antigravity
vg clone assign "Ava" researcher

# 7. View generated persona prompt (style, tone, cadence):
vg clone prompt "Ava"
```


