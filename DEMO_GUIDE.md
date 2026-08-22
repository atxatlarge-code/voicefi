# 🎙️ Voicegency Demo Guide: Agent-First Voice Layer

Follow this 5-minute interactive walkthrough to showcase the complete **Agent-First Voice Layer** for Voicegency.

---

## 🎬 Act 1: The 1-Line Setup & Discovery
Showcase how easily an agent or developer can bootstrap Voicegency and inspect system tools:

```bash
# 1. Check system detection and active audio engines:
vg info

# 2. View curated agent personas:
vg voice list
```

---

## 🎭 Act 2: Live Multi-Voice Audition Showcase
Let the audience hear the distinct acoustic personas directly over the speakers:

```bash
# Play the 4-persona live audition showcase:
vg voice audition
```
> *Hear **Christopher** (Deep/Calm), **Aria** (Crisp/Energetic), **Sonia** (British/Analytical), and **Guy** (Warm/Conversational).*

You can also test individual personas with custom lines:
```bash
vg voice test "Christopher" --text "Hey Jake, I'm ready to begin refactoring the database layer."
vg voice test "Aria" --text "All 49 unit tests passed with zero errors!"
vg voice test "Sonia" --text "Codebase research complete. Three performance bottlenecks were identified."
```

---

## ⚙️ Act 3: Multi-Agent Persona Allocation
Assign acoustic identities to your main agent and background subagents:

```bash
# Assign signature voices:
vg voice set antigravity Christopher
vg voice set researcher Sonia
vg voice set debugger Aria

# Inspect active voice mappings:
vg voice get
```

---

## 🚀 Act 4: Live Multi-Agent Swarm Turn-Taking
Demonstrate seamless, sequential turn-taking across multiple agents in parallel without overlapping or cutting off:

```bash
uv run python scripts/demo_multi_agent_flow.py
```
> *Watch and listen as the **Main Planner** initiates the task $\rightarrow$ **Researcher** reports on API contracts $\rightarrow$ **Debugger** announces passing test suites $\rightarrow$ **Main Planner** asks for deployment confirmation.*

---

## 📬 Act 5: Agent-First Bug & Feedback Channel
Showcase how agents and developers can autonomously submit bug reports and telemetry:

```bash
# Submit a feedback ticket with environment diagnostics:
vg feedback submit "Audio level calibrated" \
  -d "EdgeTTS neural voices verified with cross-process turn locking." \
  -c voice_quality \
  --agent-id antigravity

# View submitted tickets:
vg feedback list
```

---

## ⌨️ Act 6: Hands-Free Desktop Dictation & IDE Pairing
Showcase universal desktop dictation:
1. Hit `Control + T` anywhere on macOS to dictate directly into Slack, Cursor, Terminal, or Chrome.
2. In Antigravity, give any coding task—when the turn finishes, Voicegency automatically announces the result aloud and opens the mic for your voice response!

---

## 🧠 Act 7: The Voice Memo Buffer (Stream of Consciousness to Code)
Showcase capturing 2–5 minutes of unstructured developer thoughts and synthesizing into plans:

```bash
# 1. Start a 3-minute pacing/brain dump session with elegant timer:
vg memo record -d 3m

# 2. Or instantly synthesize raw developer rambles:
vg memo synth --text "So I'm thinking we need a background worker for video processing. It should pull tasks from Redis. Actually wait, let's use SQLite queues first to keep it self-contained for local dev. The worker should decode video, extract frames with ffmpeg, and write thumbnail images. We need an API endpoint POST /jobs and GET /jobs/:id. If ffmpeg fails, retry 3 times. We need unit tests for retry logic."

# 3. View stored brain dumps:
vg memo list
```
> *Watch as Voicegency parses pivots ("actually wait... SQLite instead of Redis"), generates a Mermaid.js diagram, builds a step-by-step implementation plan, and compiles a complete PR checklist.*

