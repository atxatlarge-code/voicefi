# AI Agent Developer & Troubleshooting Guide — VoiceFi™

Universal Voice Layer for Knowledge Vaults, MCP, and Autonomous AI Coding Agents.

---

## 🛠️ Essential Commands & Diagnostic Tools

| Command | Purpose |
| :--- | :--- |
| `vifi status` / `vifi server status` | **Server & Port Status**: Shows running server, LaunchAgent state, Port 5141 listener, and PID details. |
| `vifi stop` / `vifi server stop` | **Server Terminator**: Safely unloads LaunchAgent, terminates VoiceFi processes, and frees Port 5141. |
| `vifi restart` / `vifi server restart` | **Server Reloader**: Gracefully restarts the background VoiceFi server and reloads configuration. |
| `vifi clean` | **Cache & State Purge**: Cleans all `__pycache__`, stale locks, and temporary session files. |
| `vifi clean --all` | **Complete Reset**: Stops background servers, frees Port 5141, and cleans all caches and locks. |
| `vifi clean --dev` | **Dev Reset & Link**: Cleans caches, stops servers, and links hooks to local repository `.venv`. |
| `vifi dev` | **Live Dev Mode**: Auto-takes over background servers, cleans caches, and streams live console logs. |
| `vifi setup --dev` | **Link Dev Hooks & MCP**: Points Antigravity and Claude Code hooks & MCP servers directly to local `.venv`. |
| `vifi mcp` | **Model Context Protocol Server**: Starts native Stdio JSON-RPC 2.0 MCP server exposing voice tools to AI agents. |
| `vifi update` | Self-updater: pulls latest GitHub release, upgrades `~/.voicefi/venv`, and reloads hooks. |
| `vifi update --check` | Check if a newer version is available without installing. |
| `vifi voice download-ava` | **Instant 0ms Offline Speech Setup**: Guides downloading Apple's **Ava (Premium)** neural voice and auto-configures 0ms offline synthesis. |
| `vifi troubleshoot` | Comprehensive automated diagnostic suite (devices, TTS latency, VAD). |
| `vifi troubleshoot --json` | Machine-readable hardware and diagnostic profile (great for agent inspection). |
| `vifi troubleshoot -i` | Interactive mic loopback recording & instant playback. |
| `vifi ping [voice]` | **Silent Voice Connection & Speed Test**: Measures TTFB latency, throughput (chars/s), payload size, and rate limits silently without audio output. |
| `vifi ping --all` | **Silent Multi-Voice Benchmark**: Runs silent connection and speed tests across all curated neural and local voices. |
| `vifi feedback-loop` | **Simultaneous Speak + Listen Test**: Speaks over speakers while monitoring microphone. |
| `vifi hearing-test` | **Acoustic Verification**: Plays phrase over speakers and tests room microphone STT match %. |
| `vifi feedback submit "<title>"` | Logs sanitized zero-PII diagnostic report and dispatches to telemetry. |
| `vifi panel` | Launch interactive web control panel (`http://localhost:5141`). |
| `vifi hud debug` | Interactive terminal Dynamic Island HUD Debug Studio. |
| `python scripts/sync_hud_assets.py` | **HUD & Web Asset Synchronizer**: Captures AppKit HUD screenshots and syncs shared JS/CSS/SVGs to `voicefi.org`. |
| `vifi autostart` / `vifi start` | Enable background LaunchAgent server (`vifi tray`) for persistent Dynamic Island HUD & menu bar companion. |
| `vifi stop-autostart` | Unload and remove background LaunchAgent server. |

---

## 🔍 Troubleshooting Guide

### 1. Active Voice Barge-In & Acoustic Safe Mode
* **How It Works:** Allows interrupting AI agent speech simply by speaking over it.
  - **Headphones / AirPods / Headsets:** Instantaneous full-duplex interruption (~150ms). Enabled in `auto` mode.
  - **Speakers (Laptop / Monitor / External):** In `auto` mode (default), barge-in is disabled during agent speech to completely avoid speaker bleed and premature cutoffs; once the agent finishes speaking, the mic automatically opens for your turn. If forced ON (`vad.barge_in: true`), it operates with adaptive acoustic safe mode.

* **Testing Barge-In Aloud:**
  ```bash
  vifi voice test "Viv" -t "This is a full test of laptop active voice barge-in. I will keep speaking aloud for several seconds so you can hear that I do not cut off automatically. If you want to interrupt me, speak firmly into your microphone."
  ```
* **Resolution if Premature Cutoffs Occur:**
  1. Check hardware profile: `vifi troubleshoot --json`
  2. Set `vad.barge_in` to `"auto"` (which safely adapts thresholding to connected devices):
     ```bash
     vifi troubleshoot --fix auto_barge_in
     ```
  3. Or run the auto-fix:
     ```bash
     python3 -c "from voicefi.config import load_config, save_config; c = load_config(); c.vad.barge_in = 'auto'; save_config(c)"
     ```

---

### 2. Simultaneous Speak & Listen (Acoustic Loopback Debugging)
To debug how VoiceFi handles simultaneous speech output and microphone capture:
* **Audition & Test Mid-Speech Interruption:**
  ```bash
  vifi voice test "Viv" -t "<long sample phrase>"
  ```
* **Test Full Roundtrip:**
  ```bash
  vifi feedback-loop
  ```
  Speaks test phrase aloud, simultaneously captures audio on the mic, transcribes the output, and computes RMS energy and loopback latency.
* **Test Acoustic Reception Match:**
  ```bash
  vifi hearing-test
  ```
  Plays a phrase and validates the room STT accuracy percentage.
* **Monitor Live Energy & Barge-In Events in Foreground:**
  ```bash
  vifi dev
  ```
  Prints real-time logs:
  ```
  [VAD] Agent is speaking aloud -> barge-in monitoring (acoustic safe-mode)...
  [VAD] ⚡ Barge-In detected (energy=0.0850, thresh=0.0650) -> stopping agent speech
  ```

---

### 3. Microphone Sensitivity / High Noise Floor
* **Symptom:** Microphone triggers continuously or fails to detect end of speech.
* **Calibration:**
  ```bash
  vifi troubleshoot --fix calibrate
  ```
  Samples ambient room noise for 1.5 seconds and dynamically calibrates `vad.energy_threshold`.

---

### 4. Audio Playback or TTS Latency Issues
* **Fastest 0ms Offline Neural Voice (Instant Apple Silicon Synthesis):**
  ```bash
  vifi voice download-ava
  # or
  vifi voice set antigravity "Ava (Premium)"
  ```
  Uses Apple's native local neural engine for zero-latency, 100% private offline speech.
* **Classic Offline Fallback:**
  ```bash
  vifi voice set antigravity Samantha
  # or
  vifi troubleshoot --fix offline_say
  ```
* **Audition Persona:**
  ```bash
  vifi voice test "Ava (Premium)" -t "Hello! Checking instant offline latency."
  ```

---

### 5. Hands-Free Feedback Loop (Conversational Voice Loop)
* **How It Works:** Autonomous turn handoff between developer and AI agents (Antigravity & Claude Code).
  - **Spoken Persona Feedback:** Agent turn completes -> VoiceFi speaks a concise soundbite in the agent's persona.
  - **Microphone Handoff:** AudioRecorder opens mic, streams live waveforms (`on_listening_tick`) and dictation previews (`on_live_transcript`) to the Dynamic Island HUD.
  - **Smart Injection Dispatch:**
    - **Antigravity:** Native `agentapi` background IPC (0 screen flicker, 0 clipboard hijacking).
    - **Claude Code & Desktop:** `inject_text_to_claude()` automatically handles terminal CLI focus and Claude Desktop (`Claude.app`) prompt textarea focus clicks before pasting and submitting.

---

### 6. Cross-Agent Dispatch & Return Routing (Antigravity ↔ Claude Code)
When Antigravity agents collaborate with Claude Code across projects:
* **Sending Task from Antigravity to Claude:**
  ```bash
  vifi send "Refactor the authentication middleware and test all endpoints." --to claude
  # or via REST API:
  curl -s -X POST http://localhost:5141/api/send -H "Content-Type: application/json" -d '{"text": "Refactor auth middleware", "engine": "claude"}'
  ```
  Automatically wraps the prompt in a provenance envelope containing the originating Antigravity conversation ID and executable return instructions.

* **Sending Findings from Claude Code back to Antigravity:**
  ```bash
  vifi send "Refactoring complete! All 14 tests passing." --to antigravity --reply
  # or via REST API:
  curl -s -X POST http://localhost:5141/api/send -H "Content-Type: application/json" -d '{"text": "Refactoring complete!", "engine": "antigravity", "conv_id": "reply", "sender_name": "Claude"}'
  ```
  Automatically resolves the originating Antigravity conversation ID, dispatches via native `agentapi` IPC, and reactively wakes up the Antigravity agent without screen flicker.

---

## 🏗️ Architecture & Conventions

* **Source Code**: Located in `src/voicefi/`
* **Configuration**: `~/.voicefi/config.yaml` (managed via Pydantic in `src/voicefi/config.py`)
* **Hardware Sensing**: `src/voicefi/audio/device.py` (detects built-in speakers vs. AirPods / headphones)
* **VAD & Audio Recorder**: `src/voicefi/audio/recorder.py` (`resolve_barge_in_mode()`)
* **Self-Updater Engine**: `src/voicefi/updater.py` (24h cached GitHub check, `vifi update`)
* **Agent Hooks & Injector**: `src/voicefi/integrations/antigravity.py`, `claude.py`, and `injector.py`
* **Floating Cocoa HUD**: `src/voicefi/ui/unified_hud.py`
* **Telemetry & Feedback**: `src/voicefi/telemetry.py` & `src/voicefi/feedback.py`
* **3D Voice Carousel (Web)**: `docs/3D_CAROUSEL_ARCHITECTURE.md` on `voicefi.org` (covers 3D cylinder orbit geometry, looking-down camera elevation, and responsive radii)


