# VoiceFi™ Configuration & Conversational Flow Guide

This document describes all configuration settings in `~/.voicefi/config.yaml` (or `./config.yaml`), including pre-built workflow presets, VAD tuning, global hotkeys, and agent voice personas.

---

## 🚀 Quick-Start Presets

### 1. 🌟 The Hands-Free Conversational Loop (Recommended)
This is the default, seamless pair-programming preset. When an agent turn finishes, VoiceFi speaks a concise soundbite aloud and immediately opens the microphone for your spoken response without touching any keys.

```yaml
# ~/.voicefi/config.yaml
antigravity:
  read_summary_aloud: true     # Speak agent turn summary
  auto_listen: true            # Open mic automatically after speaking
  max_spoken_words: 45         # Keep soundbite concise (under 15 seconds)
  inject_to_active_window: true

vad:
  engine: "auto"               # Silero Neural VAD with Energy fallback
  mode: "hybrid"               # Tap = auto-listen, Hold = Push-to-Talk
  silence_duration: 1.4        # Natural pause window before auto-submitting
  barge_in: "auto"             # Full duplex on headphones; acoustic safe-mode on speakers

audio_cues:
  enabled: true                # Plays subtle "Tink" chime when mic opens for auto-listen

global_hotkey:
  talk_to_agent_hotkey: "<alt>+v"     # Option+V / Alt+V to prompt on-demand
  focus_and_talk_hotkey: "<ctrl>+r"   # Ctrl+R to focus and respond
```

---

### 2. 🤫 Push-to-Talk / Focused Silent Mode
Best for shared offices, coffee shops, or when you prefer reading text on screen and only speaking on demand.

```yaml
antigravity:
  read_summary_aloud: false    # Do not speak turns aloud automatically
  auto_listen: false           # Mic stays closed until explicitly invoked

vad:
  mode: "ptt"                  # Strict push-to-talk mode
  barge_in: false

global_hotkey:
  talk_to_agent_hotkey: "<alt>+v"     # Option+V to prompt active agent
  dictate_hotkey: "<ctrl>+t"          # Ctrl+T for universal dictation anywhere
```

---

### 3. ⚡ Speed Talking / Turbo Productivity
Accelerates spoken feedback up to 1.5x–2.0x with pause compression, dynamic velocity ramping, and zero latency.

```yaml
tts:
  provider: "edge_tts"
  voice: "en-US-AvaNeural"
  speed_talk: true             # Enable Speed Talking acceleration
  speed: "1.5x"                # 1.25x to 3.0x speed multiplier
  pause_compression: true      # Shortens punctuation pauses by 40%

vad:
  silence_duration: 1.0        # Rapid 1.0s silence handoff for lightning turnarounds
```

---

## ⚙️ Configuration Reference

### 🎙️ Text-to-Speech (`tts`)
| Key | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `provider` | `string` | `"edge_tts"` | TTS engine: `"edge_tts"`, `"mac_say"`, `"elevenlabs"`, `"gemini"`. |
| `voice` | `string` | `"en-US-AvaNeural"` | Voice persona (e.g. `Viv`, `Ava (Premium)`, `Christopher`, `Guy`). |
| `rate` | `int` / `str` | `200` | Words-per-minute (mac_say) or speed percentage (edge_tts). |
| `volume` | `float` | `1.0` | Playback volume multiplier (`0.0` to `1.0`). |
| `streaming` | `bool` | `true` | Stream sentence chunks with `< 200ms` time-to-first-byte latency. |
| `speed_talk` | `bool` | `false` | Enable speed talking velocity engine. |
| `speed` | `string` | `"1.25x"` | Velocity rate (`1.25x`, `1.5x`, `1.75x`, `2.0x`). |

---

### 👂 Voice Activity Detection (`vad`)
| Key | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `engine` | `string` | `"auto"` | VAD engine: `"auto"` (Silero ONNX), `"silero"`, `"energy"`. |
| `speech_threshold` | `float` | `0.5` | Neural speech probability threshold (`0.0` to `1.0`). |
| `mode` | `string` | `"hybrid"` | Interaction mode: `"hybrid"`, `"auto"`, `"ptt"`. |
| `silence_duration` | `float` | `1.4` | Seconds of trailing silence before auto-submitting prompt. |
| `energy_threshold` | `float` | `0.004` | Baseline RMS audio energy floor (calibrated via `vifi troubleshoot --fix calibrate`). |
| `barge_in` | `string`/`bool`| `"auto"` | Interruption mode: `"auto"` adapts based on headphones vs built-in speakers. |
| `barge_in_sensitivity`| `float` | `1.0` | Multiplier for voice barge-in sensitivity. |

---

### 🔔 Audio Cues (`audio_cues`)
| Key | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `enabled` | `bool` | `true` | Enable lightweight system audio cues for state transitions. |
| `start_chime` | `string` | `"/System/Library/Sounds/Tink.aiff"` | Played when the microphone opens for auto-listen. |
| `done_chime` | `string` | `".../Mail Sent.aiff"` | Played when recording completes and dispatches to agent. |
| `error_chime` | `string` | `"/System/Library/Sounds/Basso.aiff"` | Played on recording or synthesis failure. |

---

### 🤖 Antigravity Integration (`antigravity`)
| Key | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `read_summary_aloud` | `bool` | `true` | Speak turn summary aloud upon agent turn completion. |
| `auto_listen` | `bool` | `true` | Automatically open microphone after speaking finishes. |
| `max_spoken_words` | `int` | `60` | Maximum soundbite word limit for turn summarization. |
| `inject_to_active_window`| `bool` | `true` | Submit transcribed prompt directly to active agent window via native IPC. |
| `auto_send` | `bool` | `true` | Automatically submit prompt without requiring review modal. |
| `show_speech_popup` | `bool` | `true` | Display floating speech card in Dynamic Island HUD. |

---

### ⌨️ Global Hotkeys (`global_hotkey`)
| Key | Default | Function |
| :--- | :--- | :--- |
| `talk_to_agent_hotkey` | `"<alt>+v"` | **Prompt Active Agent** (`Option+V` / `⌥V`) — opens mic and dispatches prompt. |
| `focus_and_talk_hotkey` | `"<ctrl>+r"` | **Respond to Active Agent** (`Ctrl+R`) — focuses agent window and starts listening. |
| `jump_to_agent_hotkey` | `"<ctrl>+j"` | **Switch to Agent Window** (`Ctrl+J`) — brings Antigravity to foreground. |
| `hub_hotkey` | `"<ctrl>+<shift>+j"` | **Activity Hub Window** (`Ctrl+Shift+J`) — toggles floating history hub. |
| `dictate_hotkey` | `"<ctrl>+t"` | **Universal Dictation** (`Ctrl+T`) — transcribes anywhere into active text box. |
| `new_conversation_hotkey` | `"<cmd>+<shift>+n"` | **New Conversation** (`Cmd+Shift+N`) — starts fresh agent thread. |
| `Esc` | *(Universal)* | **Instant Silence / Cancel** — halts TTS audio and closes microphone. |

---

### 🎭 Per-Agent & Subagent Personas (`agents` / `subagents`)
Assign distinct neural voices to primary agents and specialized subagents:

```yaml
agents:
  antigravity:
    provider: "edge_tts"
    voice: "en-US-AvaNeural"      # Viv (Warm, expressive, natural)
  claude:
    provider: "edge_tts"
    voice: "en-US-GuyNeural"      # Guy (Calm, articulate, analytical)
  cursor:
    provider: "edge_tts"
    voice: "en-US-JennyNeural"

subagents:
  researcher:
    provider: "edge_tts"
    voice: "en-GB-SoniaNeural"    # Sonia (British, polished researcher)
  debugger:
    provider: "edge_tts"
    voice: "en-US-EmmaNeural"     # Emma (Focused debugger)
  architect:
    provider: "edge_tts"
    voice: "en-AU-WilliamNeural"  # William (Australian senior architect)
```
