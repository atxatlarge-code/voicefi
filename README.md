# 🎙️ Talk 2 Me

<div align="center">

**A hands-free, two-way voice layer for AI coding agents & macOS desktop computing.**

[![Status: Patent Pending](https://img.shields.io/badge/Status-Patent%20Pending%20(64%2F137%2C300)-blue.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB.svg?logo=python&logoColor=white)](https://python.org)
[![Platform: macOS](https://img.shields.io/badge/Platform-macOS-lightgrey.svg?logo=apple&logoColor=white)](https://apple.com)
[![Engine: Antigravity](https://img.shields.io/badge/Engine-Antigravity%20Ready-purple.svg)]()

*U.S. Patent Application No. 64/137,300 — LienLogic Data LLC*

</div>

---

## ⚡ The Problem & Vision

When pair-programming with autonomous AI agents like **Antigravity**, developers spend hours staring at progress logs, waiting for agent turns to finish, reading markdown summaries, clicking confirmation buttons, and typing prompt replies.

**Talk 2 Me** closes this gap by transforming your AI agent into a natural, conversational voice partner:

```
                  ┌─────────────────────────────────────────┐
                  │       Antigravity Finishes Turn         │
                  └────────────────────┬────────────────────┘
                                       │ (Stop Hook)
                                       ▼
                  ┌─────────────────────────────────────────┐
                  │   Talk 2 Me Summarizes & Speaks Aloud   │
                  │   "Tests passed! Ready to deploy?"      │
                  └────────────────────┬────────────────────┘
                                       │
                                       ▼
                  ┌─────────────────────────────────────────┐
                  │   Auto-Opens Mic with VAD & Listens     │
                  │   (No clicking buttons, hands-free)     │
                  └────────────────────┬────────────────────┘
                                       │
                                       ▼
                  ┌─────────────────────────────────────────┐
                  │   Whisper Transcribes & Injects Text    │
                  │   Submits prompt back to Antigravity    │
                  └─────────────────────────────────────────┘
```

---

## ✨ Features

- 🔄 **Hands-Free Agent Turn-Handoff**: Directly integrates into Antigravity lifecycle hooks (`hooks.json`). Announces agent status and listens for your voice command automatically.
- 🎯 **Smart Conversational Summarizer**: Cleanses raw markdown, code snippets, and logs to deliver brief, audible voice soundbites.
- 🎙️ **Voice Activity Detection (VAD)**: Real-time energy detection that knows when you start speaking and stops listening when you pause.
- 🔊 **Multi-Provider TTS (Text-to-Speech)**:
  - **Native macOS `say`** (Instant, zero latency, offline, supports Siri & system voices).
  - **Microsoft Edge Neural TTS** (Natural AI voices, free, no API key).
  - **ElevenLabs** (Pro tier / ultra-realistic cloned voices).
- 🧠 **Multi-Provider STT (Speech-to-Text)**:
  - **`faster-whisper`** (Runs 100% locally and offline on Apple Silicon / CPU).
  - **Groq Cloud Whisper** (~150ms instant cloud transcription).
  - **Apple Speech Framework** (macOS native speech recognition).
- 🖥️ **macOS Menu Bar Companion (`talk2me tray`)**: Lightweight menu bar item displaying live listening/speaking status and instant controls.
- ⌨️ **Global Desktop Voice Hotkey**: Press `<cmd>+<alt>+space` anywhere on macOS to dictate directly into any application.

---

## 🚀 Quickstart

### 1. Installation

Clone and install using `uv` (recommended) or standard `pip`:

```bash
git clone https://github.com/jaketrigg/talk-2-me.git
cd talk-2-me

# Install in virtual environment
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e .
```

### 2. Connect with Antigravity (1-Command Setup)

Run the automated setup to register the Talk 2 Me hook in `~/.gemini/config/hooks.json`:

```bash
talk2me setup
```

Now, whenever Antigravity completes a task or asks a question, **Talk 2 Me** will speak the update, listen for your voice response, and paste it right back to the agent!

---

## 💻 CLI Usage

| Command | Description |
| :--- | :--- |
| `talk2me setup` | Auto-registers Talk 2 Me lifecycle hook with Antigravity |
| `talk2me hook` | Executes Antigravity hook handler (called by `hooks.json`) |
| `talk2me listen` | One-shot voice dictation (records, transcribes, pastes to active app) |
| `talk2me speak "Hello world"` | Speaks text aloud using configured TTS provider |
| `talk2me loop` | Starts continuous hands-free voice loop in the terminal |
| `talk2me tray` | Launches the macOS Menu Bar companion app |
| `talk2me info` | Displays active tier, audio devices, and voice models |

---

## ⚙️ Configuration

Configuration is stored at `~/.talk2me/config.yaml`. Customize your voices, models, and sensitivities:

```yaml
version: 1
tier: "community" # or "pro"

# Text-to-Speech
tts:
  provider: "mac_say" # "mac_say" | "edge_tts" | "elevenlabs"
  voice: "Samantha"   # e.g., "Samantha", "Alex", "en-US-ChristopherNeural"
  rate: 200

# Speech-to-Text
stt:
  provider: "whisper_local" # "whisper_local" | "groq" | "apple_speech"
  model_size: "base.en"     # "tiny.en" | "base.en" | "small.en"
  groq_api_key: ""

# Voice Activity Detection (VAD)
vad:
  silence_duration: 1.5    # Seconds of silence to finish listening
  energy_threshold: 0.015  # Mic sensitivity
  max_record_seconds: 45

# Antigravity Behavior
antigravity:
  auto_listen: true            # Automatically open mic after agent speaks
  read_summary_aloud: true     # Speak agent turn summary
  max_spoken_words: 60         # Soundbite word limit
  inject_to_active_window: true
```

---

## 💎 Community vs Pro Edition

| Feature | Community (MIT Open Source) | Pro Edition |
| :--- | :---: | :---: |
| **macOS Native `say` TTS** | ✅ | ✅ |
| **Microsoft Edge Neural TTS** | ✅ | ✅ |
| **Local Faster-Whisper (Offline)** | ✅ | ✅ |
| **Antigravity `Stop` Hook Integration** | ✅ | ✅ |
| **macOS Menu Bar Companion** | ✅ | ✅ |
| **Global Voice Dictation Hotkey** | ✅ | ✅ |
| **ElevenLabs High-Def Neural Voices** | — | ✅ |
| **Custom Wake Words ("Hey Antigravity")** | — | ✅ |
| **Multi-Agent Voice Dispatcher** | — | ✅ |
| **Commercial License & Support** | — | ✅ |

---

## 🧪 Testing

Run the automated test suite:

```bash
uv run pytest
```

Run the interactive hardware test (mic + speakers):

```bash
uv run python scripts/test_loop.py
```

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
