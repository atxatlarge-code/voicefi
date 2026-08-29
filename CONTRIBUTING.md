# Contributing to VoiceFi

Welcome! Thank you for your interest in contributing to **VoiceFi™** — the Universal Voice Layer for AI Agents, MCP, and macOS.

We welcome contributions of all kinds: new voice engines, audio effect packages, agent lifecycle hooks, bug fixes, performance enhancements, and documentation improvements.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Prerequisites](#prerequisites)
- [Local Development Setup](#local-development-setup)
- [Development Workflows & Essential Commands](#development-workflows--essential-commands)
- [Running Tests & Quality Checks](#running-tests--quality-checks)
- [Architecture & Codebase Overview](#architecture--codebase-overview)
- [Branching & Commit Conventions](#branching--commit-conventions)
- [Pull Request Lifecycle](#pull-request-lifecycle)
- [Getting Help](#getting-help)

---

## Code of Conduct

All contributors and maintainers are expected to follow our [Code of Conduct](CODE_OF_CONDUCT.md) (Contributor Covenant v2.1). Please report any unacceptable behavior to [talktome@voicefi.org](mailto:talktome@voicefi.org).

---

## Prerequisites

Before getting started, ensure you have the following installed:

- **Python**: Python 3.10 or higher (Python 3.12 is strongly recommended).
- **Operating System**:
  - **macOS** (macOS 13 Ventura, 14 Sonoma, 15 Sequoia, 16 Tahoe) is recommended for full native capabilities, including the AppKit Dynamic Island HUD, Apple Silicon local neural Ava voice, and hardware audio sensing.
  - **Linux / WSL / Windows** are supported for MCP stdio tools, CLI utilities, REST endpoints, and cloud TTS engines (Edge-TTS, ElevenLabs).
- **Package Manager**: [`uv`](https://github.com/astral-sh/uv) (strongly recommended for fast, reproducible environments) or standard `pip`.
- **System Audio Libraries** (optional for extended local audio processing):
  ```bash
  # On macOS via Homebrew:
  brew install portaudio ffmpeg
  ```

---

## Local Development Setup

Follow these steps to set up your local development environment:

### 1. Clone the Repository

```bash
git clone https://github.com/atxatlarge-code/voicefi.git
cd voicefi
```

### 2. Create and Activate a Virtual Environment

Using `uv` (recommended):
```bash
uv venv --python 3.12
source .venv/bin/activate
```

Or using standard Python `venv`:
```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies in Editable Mode

Install VoiceFi with development and test dependencies:

```bash
# Using uv:
uv pip install -e ".[dev]"

# Or using pip:
pip install -e ".[dev]"
```

### 4. Link Dev Hooks & MCP Server

Point your active Antigravity agent, Claude Code hooks, and MCP servers directly to your local `.venv`:

```bash
vifi setup --dev
```

This verifies that `vifi` CLI points to your editable source checkout.

---

## Development Workflows & Essential Commands

VoiceFi provides a suite of developer commands to facilitate rapid iteration:

| Command | Description |
| :--- | :--- |
| `vifi dev` | **Live Dev Mode**: Takes over background servers, cleans caches, and streams live console logs. |
| `vifi status` | **Server Diagnostic**: Displays running server PID, LaunchAgent state, Port 5141 status, and hook states. |
| `vifi troubleshoot` | **Diagnostic Suite**: Runs comprehensive hardware checks (microphones, speakers, TTS engines, VAD latency). |
| `vifi troubleshoot --json` | **Machine-Readable Diagnostics**: Dumps full audio & platform state in JSON format. |
| `vifi voice test "Viv"` | **Audition Voice**: Synthesizes and speaks a sample phrase using the specified voice persona. |
| `vifi ping --all` | **Voice Latency Benchmark**: Silently tests TTFB latency, throughput (chars/s), and rate limits across all voices. |
| `vifi feedback-loop` | **Acoustic Loopback Test**: Speaks audio and simultaneously monitors mic input for barge-in detection. |
| `vifi hud debug` | **Dynamic Island HUD Studio**: Launches an interactive terminal studio for testing HUD states and animations. |
| `vifi panel` | **Web Control Panel**: Launches the companion UI at `http://localhost:5141`. |
| `vifi mcp` | **MCP Server**: Starts the Stdio JSON-RPC 2.0 MCP server exposing voice tools to AI agents. |
| `vifi clean --all` | **State & Lock Purge**: Safely frees Port 5141, clears stale locks, and cleans `__pycache__`. |

---

## Running Tests & Quality Checks

### Test Suite Execution

VoiceFi uses `pytest` for unit, integration, and protocol conformance testing.

Run all tests:
```bash
pytest
# or with uv:
uv run pytest
```

Run specific test modules:
```bash
# MCP Stdio Server tool conformance
pytest tests/test_mcp_server.py

# Smart Injector & Agent Hooks
pytest tests/test_injector.py

# SFX & Procedural Acoustic Chimes
pytest tests/test_chimes.py
```

### Linting & Formatting

We use [Ruff](https://github.com/astral-sh/ruff) for fast Python linting and code formatting:

```bash
# Check for lint violations
ruff check .

# Automatically fix lint issues where possible
ruff check --fix .

# Check code formatting
ruff format --check .

# Format code
ruff format .
```

---

## Architecture & Codebase Overview

The codebase is organized modularly under `src/voicefi/`:

```
src/voicefi/
├── audio/            # Audio capture, VAD, hardware sensing, sound effects & chimes
│   ├── chimes.py     # Procedural NumPy harmonic waveforms (turn handoffs, errors)
│   ├── device.py     # Hardware device sensing (AirPods vs. built-in speakers)
│   ├── recorder.py   # Streaming audio recorder with energy-based VAD & barge-in
│   └── sfx.py        # Sound effect registry and procedural generators
├── tts/              # Text-to-Speech engines
│   ├── base.py       # BaseTTS abstract engine interface
│   ├── ava.py        # Apple Silicon native neural speech (Ava / Evan / Samantha)
│   ├── edge.py       # Edge-TTS cloud neural synthesis
│   ├── elevenlabs.py # ElevenLabs API streaming synthesis
│   ├── f5tts.py      # F5-TTS zero-shot voice cloning
│   └── kokoro.py     # Kokoro local ONNX neural synthesis
├── stt/              # Speech-to-Text engines
│   ├── apple_stt.py  # Native Apple SpeechKit streaming dictation
│   └── whisper_stt.py# Faster-Whisper local transformer models
├── integrations/     # AI Agent lifecycle hooks & IPC
│   ├── antigravity.py# Native Google Antigravity AgentAPI IPC & Stop hooks
│   ├── claude.py     # Claude Code lifecycle hooks & focus switching
│   └── injector.py   # Smart text injection & prompt submission
├── companion/        # HTTP REST companion server (FastAPI, Port 5141)
├── ui/               # Native macOS AppKit Dynamic Island HUD & menu bar companion
├── mcp_server.py     # Native Model Context Protocol (MCP) Stdio JSON-RPC server
├── cli.py            # Command-line interface subcommands and entrypoints
└── config.py         # Pydantic configuration schema (~/.voicefi/config.yaml)
```

---

## Branching & Commit Conventions

### Branch Naming

Create feature or fix branches from `main` using descriptive prefixes:

- `feat/<short-description>`: New features or voice integrations
- `fix/<short-description>`: Bug fixes or error handling improvements
- `docs/<short-description>`: Documentation changes or tutorials
- `refactor/<short-description>`: Code restructuring without functional changes
- `test/<short-description>`: Adding or improving test coverage
- `chore/<short-description>`: Maintenance, tooling, or dependency updates

### Commit Messages

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<optional-scope>): <description>

[optional body]

[optional footer(s)]
```

**Examples:**
- `feat(tts): add support for Kokoro ONNX offline neural engine`
- `fix(vad): prevent false barge-in trigger during speaker playback`
- `docs(mcp): add copy-paste configuration for Cursor and Zed`
- `test(injector): add tests for Claude Desktop window focus targeting`

---

## Pull Request Lifecycle

1. **Check Existing Issues**: Search [GitHub Issues](https://github.com/atxatlarge-code/voicefi/issues) to avoid duplicate work.
2. **Open an Issue First** (for large changes): Discuss major features or architectural shifts in an issue before writing code.
3. **Keep PRs Scoped**: A pull request should do one thing well. Avoid combining unrelated fixes or large refactors into a single PR.
4. **Verify Locally**:
   - Ensure all tests pass (`pytest`).
   - Ensure linting and formatting pass (`ruff check .` and `ruff format --check .`).
   - Run `vifi troubleshoot` to ensure no audio regressions.
5. **Submit Your PR**:
   - Fill out all sections in the [Pull Request Template](.github/PULL_REQUEST_TEMPLATE.md).
   - Link related issues using keywords (e.g., `Fixes #123`).
6. **Code Review**: Maintainers will review your PR, provide constructive feedback, and run CI workflows.

---

## Getting Help

- **Discussions**: Join our [GitHub Discussions](https://github.com/atxatlarge-code/voicefi/discussions) for architecture questions, ideas, and troubleshooting.
- **Maintainers**: Contact [talktome@voicefi.org](mailto:talktome@voicefi.org) for general inquiries.
