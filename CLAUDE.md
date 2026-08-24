# Claude Code Guide — VoiceFi™

Universal Voice Layer for AI Agents, MCP, and macOS.

## Build & Installation

When setting up or testing the repository in Claude Code:

```bash
# Automated local installation
./install.sh

# Or via virtual environment
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Running Tests

```bash
# Run full unit test suite
uv run pytest

# Run a specific test module
uv run pytest tests/test_panel.py
uv run pytest tests/test_tts_stt.py
```

## CLI Commands

CLI entry points: `vifi`, `vg`, `voicefi`

- `vifi setup` — Auto-configure lifecycle hooks for AI coding agents
- `vifi info` — Show detected agents, active tier, and audio status
- `vifi listen` — One-shot voice dictation with Whisper STT & macOS clipboard injection
- `vifi loop` — Continuous hands-free voice loop in the terminal
- `vifi tray` — Launch macOS menu bar companion
- `vifi voice list` — List curated voice personas (Edge TTS, Apple Say, ElevenLabs)
- `vifi voice test <name>` — Audition a specific voice
- `vifi panel` — Launch the local web control panel (http://localhost:8765)
- `vifi memo record` — Capture 2-5 min developer voice ramble and synthesize to code plan

## Architecture & Code Conventions

- **Source Code**: Located in `src/voicefi/`
- **Config**: Pydantic models in `src/voicefi/config.py` (saved to `~/.voicefi/config.yaml`)
- **Audio Engines**:
  - TTS: `src/voicefi/tts/` (Apple Say, Edge TTS, ElevenLabs)
  - STT: `src/voicefi/stt/` (Local Faster-Whisper, Groq Cloud, Apple Speech)
  - Audio I/O: `src/voicefi/audio/` (VAD, recorder, player, echo cancellation)
- **UI / HUD**: `src/voicefi/ui/` (PyObjC Cocoa floating dynamic island HUDs, macOS tray companion)
- **Integrations**: `src/voicefi/integrations/` (Antigravity transcript watcher, Claude Code, Cursor focus, Obsidian vault bridge)
