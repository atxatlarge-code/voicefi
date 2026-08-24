# AI Agent Developer & Troubleshooting Guide — VoiceFi™

Universal Voice Layer for Knowledge Vaults, MCP, and Autonomous AI Coding Agents.

---

## 🛠️ Essential Commands & Diagnostic Tools

| Command | Purpose |
| :--- | :--- |
| `vifi update` | Self-updater: pulls latest GitHub release, upgrades `~/.voicefi/venv`, and reloads hooks. |
| `vifi update --check` | Check if a newer version is available without installing. |
| `vifi troubleshoot` | Comprehensive automated diagnostic suite (devices, TTS latency, VAD). |
| `vifi troubleshoot --json` | Machine-readable hardware and diagnostic profile (great for agent inspection). |
| `vifi troubleshoot -i` | Interactive mic loopback recording & instant playback. |
| `vifi feedback-loop` | **Simultaneous Speak + Listen Test**: Speaks over speakers while monitoring microphone. |
| `vifi hearing-test` | **Acoustic Verification**: Plays phrase over speakers and tests room microphone STT match %. |
| `vifi dev` | **Live Real-Time Console Dev Mode**: Streams real-time VAD energy levels and barge-in events. |
| `vifi feedback submit "<title>"` | Logs sanitized zero-PII diagnostic report and dispatches to telemetry. |
| `vifi panel` | Launch interactive web control panel (`http://localhost:8765`). |
| `vifi hud debug` | Interactive terminal Dynamic Island HUD Debug Studio. |

---

## 🔍 Troubleshooting Guide

### 1. Agent Voice Cuts Off After 1–2 Seconds (Acoustic Bleed)
* **Symptom:** When Antigravity or Claude finishes a turn, the speaker starts talking, speaks a few words, and abruptly stops.
* **Root Cause:** The laptop is using **built-in MacBook speakers** without headphones. Sound from the speakers physically leaks into the adjacent microphone, causing VAD barge-in to mistake the speaker's own output for user speech interruption.
* **Resolution:**
  1. Check hardware profile: `vifi troubleshoot --json`
  2. Set `vad.barge_in` to `"auto"` (which safely disables barge-in on built-in speakers and enables it on headphones):
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
  [VAD] ⚡ Barge-In detected (headphones, energy=0.0450, thresh=0.0320) -> stopping agent speech
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
* **Fastest Offline Fallback (Zero Latency):**
  ```bash
  vifi voice set antigravity Samantha
  # or
  vifi troubleshoot --fix offline_say
  ```
  Switches to macOS native offline speech synthesis (`mac_say`), removing cloud roundtrip latencies.
* **Audition Persona:**
  ```bash
  vifi voice test "Christopher" -t "Hello! Checking audio output latency."
  ```

---

## 🏗️ Architecture & Conventions

* **Source Code**: Located in `src/voicefi/`
* **Configuration**: `~/.voicefi/config.yaml` (managed via Pydantic in `src/voicefi/config.py`)
* **Hardware Sensing**: `src/voicefi/audio/device.py` (detects built-in speakers vs. AirPods / headphones)
* **VAD & Audio Recorder**: `src/voicefi/audio/recorder.py` (`resolve_barge_in_mode()`)
* **Self-Updater Engine**: `src/voicefi/updater.py` (24h cached GitHub check, `vifi update`)
* **Agent Hooks**: `src/voicefi/integrations/antigravity.py` and `claude.py`
* **Floating Cocoa HUD**: `src/voicefi/ui/unified_hud.py`
* **Telemetry & Feedback**: `src/voicefi/telemetry.py` & `src/voicefi/feedback.py`
