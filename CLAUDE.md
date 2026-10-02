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
- `vifi update` — Self-updater: pulls latest build, upgrades venv, and reloads hooks
- `vifi troubleshoot` — Comprehensive audio & voice diagnostic suite
- `vifi feedback-loop` — Simultaneous speak + listen loopback verification
- `vifi hearing-test` — Acoustic reception & STT verification check
- `vifi dev` — Foreground real-time console dev mode with live VAD logging
- `vifi panel` — Launch the local web control panel (http://localhost:5141)
- `vifi implement <file> -i "..."` — Surgical code modifications returning unified diffs (`local-dev`)
- `vifi fix [--clip]` — Self-healing bug fixes from clipboard or test traces (`local-dev`)
- `vifi scout <file|dir> -q "..."` — Pre-digest logs, stack traces, and code on-device (`local-scout`)
- `vifi verify` / `vifi bench` — Run on-device QA regression checks and hardware benchmarks (`local-qa`)
- `vifi speak "..." -p voice_acting -v drill_sergeant` — Voice Acting with prompt-directed emotion (MLX Qwen3-TTS on Metal)
- `vifi speak "..." -p voice_acting --instruct "..."` — Ad-hoc theatrical performance direction
- `vifi speak "..." -v christopher_walken` — Christopher Walken voice acting (SNL Cowbell seed + staccato director)

## 🎙️ Hands-Free Feedback Loop (Conversational Voice Loop)

VoiceFi provides a fully automated, bidirectional hands-free voice loop for Claude Code via the `Stop` event hook in `~/.claude/settings.json`.

### Lifecycle Flow
1. **Turn Completion**: When Claude Code finishes generating a response or running tools, the `Stop` hook triggers `vifi hook --agent claude`.
2. **Crisp Spoken Soundbite**: VoiceFi extracts the key takeaway and speaks it aloud using Claude's voice persona (default: **Guy** / Edge-TTS or Apple Neural).
3. **Hands-Free Mic Handoff**: The microphone automatically opens with VAD energy detection. The Dynamic Island HUD streams real-time audio waveforms (`on_listening_tick`) and live transcription previews (`on_live_transcript`).
4. **Smart Window & Turn Injection**: When speech pauses, Whisper STT transcribes the input and the **Smart Window Injector** delivers the prompt:
   - **Claude Desktop App (`Claude.app`)**: Posts a synthetic focus click to the prompt textarea, pastes (`Cmd+V`), and submits (`Return`).
   - **Terminal CLI (`Ghostty`, `iTerm2`, `Terminal`, `Warp`, `Cursor`)**: Focuses the active terminal window, pastes, and submits.

### Configuration (`~/.voicefi/config.yaml`)
```yaml
claude:
  read_summary_aloud: true
  auto_listen: true
  inject_to_active_window: true
  auto_submit: true
  max_spoken_words: 25

tts:
  provider: local_clone        # or voice_acting
  voice: christopher_walken
  f5_ref_audio: ~/.voicefi/cloned_voices/christopher_walken/samples/sample_cowbell_snl.wav
  f5_ref_text: "Guess what? I got a fever, and the only prescription is more cowbell."
```

## 🎭 Voice Acting & Theatrical Directing

VoiceFi distinguishes between standard TTS (flat), voice cloning (timbre clone), and **Voice Acting** (semantic emotional delivery):
- **MLX Engine (`src/voicefi/tts/voice_acting.py`)**: Runs `mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-4bit` on Apple Silicon Metal GPU at **0.98x RTF**. Supports natural language `--instruct` without reference audio.
- **Theatrical Director (`src/voicefi/tts/director.py`)**: Directs staccato cadence, mid-clause pauses (`...`), and persona archetypes (`TheatricalDirector.direct_walken_cadence`).
- **Antigravity Turn Completion**: All agent turn summaries route through `TheatricalDirector` to produce lively Walken delivery.
- **Speech-to-Speech (STS)**: Zero-render video dubbing by swapping audio tracks with identical syllable envelopes (`ffmpeg -c:v copy`).

## Architecture & Code Conventions

- **Source Code**: Located in `src/voicefi/`
- **Config**: Pydantic models in `src/voicefi/config.py` (saved to `~/.voicefi/config.yaml`)
- **Audio Engines**:
  - TTS & Voice Acting: `src/voicefi/tts/` (MLX Qwen3 Voice Acting, F5-TTS Flow Matching, Apple Say, Edge TTS, ElevenLabs)
  - Theatrical Director: `src/voicefi/tts/director.py` (Cadence directing, emotion matrix routing)
  - STT: `src/voicefi/stt/` (Local Faster-Whisper, Groq Cloud, Apple Speech)
  - Audio I/O: `src/voicefi/audio/` (VAD, recorder, player, echo cancellation)
- **UI / HUD**: `src/voicefi/ui/` (PyObjC Cocoa floating dynamic island HUDs, macOS tray companion)
- **Integrations & Injector**: `src/voicefi/integrations/` (Antigravity IPC, Claude Code hook & Desktop injector, Cursor focus, Obsidian vault bridge)


