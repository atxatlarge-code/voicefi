---
name: local-content
description: Edge creative engine, conversational scriptwriter, and autonomous Content Factory. Generates social reel scripts, comedy dialogue, AI rap battle lyrics, and character banter locally on Apple Silicon Metal GPU with zero API latency and native JSON mode, guarded by ThermalSupervisor and feeding directly into VoiceFi's neural TTS pipelines.
---

# 🎨 Local-Content: Edge Creative Engine & Autonomous Content Factory

The **`local-content`** skill leverages local models (Gemma 2, Llama 3.2, Qwen 2.5, Tev1, Nimble) on Apple Silicon Metal GPU to draft high-turn conversational scripts, social media reels, lyrics, and comedic dialogue with **zero cloud API costs** and **sub-second latency**. The output directly hooks into VoiceFi's **Autonomous Content Creation Factory** (`scripts/run_content_factory.py`), discrete codec MLX engine (Qwen3-TTS), F5-TTS neural cloning, and procedural beats.

Use this skill whenever:
- You want to draft 10–50 variations of social reel hooks, comedic skits, or podcast dialogue offline without paying cloud per-token fees.
- You want to run an autonomous background worker processing a continuous queue of video scripts and reel manifests.
- You need rhythmically calibrated rap lyrics, rhyming brag verses, or chorus hooks.
- You want real-time agent-to-agent banter between Antigravity (`Viv`) and Claude Code (`Stefan`) with synchronized spoken audio delivery.
- You are generating declarative reel manifests for automated video rendering (`social-reel-producer`).

---

## ⚡ Architecture: The Autonomous Edge Content Factory

```
Content Job Queue (SQLite WAL Mode with Backoff Jitter)
         │
         ▼ (<0.2 ms Unified Memory Ingress)
┌────────────────────────────────────────────────────────┐
│  ThermalSupervisor Telemetry Check                     │  --> Ensures macOS thermals (pmset -g therm)
│  (wait_if_throttled: poll=3.0s, max=30s)               │      are normal and free unified RAM >= 4.0 GB
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│  LocalContentGenerator (`src/voicefi/factory/`)        │  --> Auto-discovers installed creative models:
│  • Dynamic Model Selection: gemma2:2b, llama3.2:1b,    │      gemma2, llama3.2, qwen2.5-coder, tev1, nimble
│    qwen2.5-coder:1.5b, tev1:latest, nimble:latest      │  --> Native JSON mode (format: "json")
│  • LiteRT Apple Silicon Metal GPU Fallback             │  --> Emits validated ContentManifest
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼ (Declarative Dialogue Manifest | 350-1,200 Tokens Saved)
┌────────────────────────────────────────────────────────┐
│  Stage 2: VoiceFi MLX Neural TTS & Video Pipeline       │  --> Multi-speaker neural audio (Viv, Stefan)
│  • Edge TTS / F5-TTS / Qwen3-TTS                       │  --> Playwright active-word caption rendering
│  • Procedural Beats & Dynamic Volume Ducking           │  --> Apple Silicon VideoToolbox FFmpeg encode
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│  Output: Ready-to-Publish 9:16 / 1:1 Social Reel       │  --> Generated in seconds with $0 cloud API cost
└────────────────────────────────────────────────────────┘
```

---

## 🛠️ How to Trigger

### 1. Autonomous Content Factory Runner (`scripts/run_content_factory.py`)
Run the autonomous background worker loop:

```bash
# 🏭 Start worker polling the ContentFactoryQueue
uv run python scripts/run_content_factory.py --worker-id worker_local_01 --poll-interval 2.0

# 🧪 Run with sample job enqueueing and bounded execution (e.g. 3 jobs)
uv run python scripts/run_content_factory.py --enqueue-samples 3 --max-jobs 3

# 🗄️ Point to a specific SQLite queue database
uv run python scripts/run_content_factory.py --db ~/.voicefi/factory.db --worker-id worker_02
```

### 2. High-Level CLI & VoiceFi Integrations
```bash
# 🎙️ Generate spoken dialogue directly via local Gemini Spark runner
vifi spark -p "Give me a quick 10-second roast of cloud latency"

# 🎬 Produce and compile a social reel locally
vifi reel compile --topic "Local vs Cloud"

# 🔊 Audition a local voice persona
vifi persona Viv -s "Testing local creative audio generation on Apple Silicon."
```

### 3. In Python Code (`LocalContentGenerator`)
```python
from voicefi.factory.generator import LocalContentGenerator
from voicefi.factory.models import ContentJob

generator = LocalContentGenerator()

job = ContentJob(
    title="Local AI vs Cloud Billing",
    prompt="Why developers are switching from cloud APIs to on-device models on Apple Silicon",
    characters=["Viv", "Stefan"],
    target_duration_s=30,
)

manifest, tokens_saved, elapsed = generator.generate_manifest(job)

print(f"Title:        {manifest.title}")
print(f"Generated In: {elapsed:.2f}s")
print(f"Tokens Saved: {tokens_saved}")
print(f"Total Words:  {manifest.total_words}")
for turn in manifest.turns:
    print(f"  [{turn.speaker} - {turn.emotion}]: {turn.text}")
```

---

## 🎭 Default Character Personas

The Content Generator automatically maps characters to calibrated neural voices, colors, and speeds:
* **Viv** (`en-US-AvaNeural`, `#3186FF`, Speed: `-2%`): Google Antigravity Planner — cerebral, architectural, authoritative.
* **Stefan** (`en-US-SteffanNeural`, `#D97757`, Speed: `0%`): Claude Code Architect — staccato, pragmatic, dry wit.
* **Christopher** (`en-US-ChristopherNeural`, `#00E5FF`, Speed: `+2%`): Cursor Engineer — fast-paced, enthusiastic pair programmer.
* **Jake** (`en-US-AndrewNeural`, `#10B981`, Speed: `-3%`): VoiceFi Founder — visionary, grounded, narrative anchor.

---

## 🔬 Model Discovery & Native JSON Mode

1. **Auto-Discovery Hierarchy**: `LocalContentGenerator` queries `/api/tags` on `OLLAMA_BASE_URL` (`http://127.0.0.1:11434`) and automatically selects the highest-priority installed creative model:
   - `gemma2:2b`
   - `llama3.2:1b`
   - `qwen2.5-coder:1.5b`
   - `tev1:latest`
   - `dolphin-llama3:latest`
   - `nimble:latest`
2. **Native JSON Output**: Uses Ollama's `format: "json"` parameter with an explicit system prompt contract, ensuring zero conversational conversational filler and 100% parseable manifests.
3. **Deterministic Fallback**: If the local LLM daemon is offline, the generator seamlessly falls back to a structured deterministic template, guaranteeing zero factory crashes.

---

## 🛡️ Guardrails & Best Practices

1. **Thermal Backoff Guard**: The worker loop calls `default_supervisor.wait_if_throttled(poll_interval=3.0, max_wait=30.0)` before claiming each job. During heavy thermal pressure (`pmset -g therm` reporting `SERIOUS`/`CRITICAL`) or low free unified RAM (<4.0 GB), the loop sleeps to protect system stability and avoid fan noise.
2. **Word Budget Adherence**: Enforces strict turn word count limits ($\le$ 28 words per scene, 50–90 words total) to guarantee crisp 25–35 second delivery for 9:16 vertical video shorts.
3. **Database Concurrency**: The underlying `ContentFactoryQueue` uses SQLite WAL mode with randomized exponential backoff retry jitter to support multiple parallel worker processes with 0 database deadlocks.

---

## ⚖️ Acoustic Speech Tiers: Factory Workhorse vs. Theatrical Multimodal Acting

VoiceFi provides two distinct speech production pipelines. It is essential to select the right tier based on volume, budget, and theatrical requirements:

| Dimension | Tier A: Local Stage 2 Workhorse (`audio_synth.py`) | Tier B: Theatrical Multimodal (`gemini-live-characters`) |
| :--- | :--- | :--- |
| **Model / Engine** | Local Edge-TTS / CoreAudio with 48kHz PCM Stitching | **Gemini 3.8 Live** (`gemini-3.8-live` Native Audio) |
| **Acoustic Archetype** | **Broadcast Announcers / Co-Hosts** (*"Viv & Jake"*) | **Theatrical Improv Troupe** (*"The Three Stooges"*) |
| **Acting Capability** | Clean, articulate, professional podcast reading. Calibrated pacing (+10% to +12%), 140ms conversational gaps, and ducked backing beats. | Full directable acting: comedic timing, throat resonance, laughing, shouting, whiny bickering, slapstick whoops, and gasps. |
| **Best For** | Autonomous overnight batch production (thousands of reels), technical change logs, briefings, offline mobile. | Viral comedy shorts, Three Stooges roasts, AI rap battles, interactive live theatrical roleplay. |
| **Economics & Latency**| **$0 cloud cost**, 100% reliable, runs completely offline on Apple Silicon. | Cloud API dependency, token metered billing, requires WAN connection. |
