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
| `vifi autostart` | Enable background LaunchAgent daemon (`vifi tray`) for persistent Dynamic Island HUD & menu bar companion. |
| `vifi stop-autostart` | Unload and remove background LaunchAgent daemon. |

---

## 🔍 Troubleshooting Guide

### 1. Active Voice Barge-In & Acoustic Safe Mode
* **How It Works:** Allows interrupting AI agent speech simply by speaking over it.
  - **Headphones / AirPods:** Instantaneous full-duplex interruption (~150ms).
  - **Built-in Laptop Speakers:** Operates with a **1.2s acoustic grace window** to let initial TTS bursts and room reverb settle, paired with **continuous adaptive speaker bleed tracking** so normal playback won't trigger false interruptions while direct human speech into the mic breaks through cleanly.
* **Testing Barge-In Aloud:**
  ```bash
  vifi voice test "Christopher" -t "This is a full test of laptop active voice barge-in. I will keep speaking aloud for several seconds so you can hear that I do not cut off automatically. If you want to interrupt me, speak firmly into your microphone."
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
  vifi voice test "Christopher" -t "<long sample phrase>"
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
