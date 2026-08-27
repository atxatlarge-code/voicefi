# 🚀 VoiceFi™ Developer Workflows: Terminal & MCP Integration Guide
> **Universal Voice Layer for AI Coding Agents, Shell Environments, and MCP Ecosystems**  
> *Target Environments: Antigravity, Claude Code, Cursor, Windsurf, Zed, Terminal / Tmux*  
> *Patent Reference: U.S. Patent Application No. 63/137,300 (LienLogic Data LLC)*

---

## 🧭 Overview

VoiceFi (`vifi`) transforms your software engineering experience from typing in isolated terminal windows to an **ambient, voice-first development loop**. 

This guide details how developers can connect VoiceFi to their daily workflows through two primary integration surfaces:
1. **[Terminal & Shell Workflows](#-part-1-terminal--shell-workflows)**: CLI utilities, agent lifecycle hooks, live dev mode, 3-minute brain dump buffers, ambient meeting co-pilots, and Unix pipelines.
2. **[Model Context Protocol (MCP) Workflows](#-part-2-model-context-protocol-mcp-workflows)**: Exposing native TTS synthesis, vocal confirmation safety gates, ambient memory buffers, and multi-agent personas to any MCP-compliant AI agent (Antigravity, Claude, Cursor, Windsurf) and dispatching spoken voice commands into tools like Slack, Linear, and GitHub.

```
                     ┌─────────────────────────────────────────────────────────────┐
                     │                  DEVELOPER WORKSPACES                       │
                     │  • Terminals: Zsh, Bash, Fish, Tmux, iTerm2, Kitty, Ghostty │
                     │  • AI IDEs & Agents: Antigravity, Claude Code, Cursor, Zed  │
                     └──────────────────────────────┬──────────────────────────────┘
                                                    │
                   ┌────────────────────────────────┴────────────────────────────────┐
                   │                                                                 │
                   ▼ (Option A: CLI & Shell Hooks)                                   ▼ (Option B: Model Context Protocol)
     ┌──────────────────────────────┐                                  ┌──────────────────────────────┐
     │          vifi CLI            │                                  │       voicefi-mcp Server     │
     │ • vifi dev (Live stream)     │                                  │ • voicefi_speak              │
     │ • vifi setup (Hooks)         │                                  │ • voicefi_ask_confirmation   │
     │ • vifi memo (Brain dumps)    │                                  │ • voicefi_get_ambient_context│
     │ • vifi ambient (Standups)    │                                  │ • voicefi_set_agent_persona  │
     │ • Unix Pipes & Scripts       │                                  │ • stdio / SSE Transports     │
     └─────────────┬────────────────┘                                  └──────────────┬───────────────┘
                   │                                                                  │
                   └────────────────────────────────┬─────────────────────────────────┘
                                                    │
                                                    ▼
                     ┌─────────────────────────────────────────────────────────────┐
                     │                  VOICEFI CORE AUDIO DAEMON                  │
                     │  • Streaming STT (Local Whisper / Groq Cloud / Apple Speech)│
                     │  • Neural TTS Personas (Ava, Christopher, Aria, Sonia, Guy) │
                     │  • Silero Energy VAD & Full-Duplex Acoustic Barge-In Safe   │
                     │  • Dynamic Island HUD & macOS Menu Bar Companion            │
                     └─────────────────────────────────────────────────────────────┘
```

---

## 💻 Part 1: Terminal & Shell Workflows

### 1.1 CLI Binaries & Shell Aliases

VoiceFi installs standard shell executables with zero-friction short aliases:

```bash
vifi --version    # Standard binary
vg --version      # 2-letter rapid developer shorthand
voicefi --version # Full canonical name
```

> [!TIP]
> All commands in this guide can use `vifi` or `vg` interchangeably.

---

### 1.2 Automated Agent Lifecycle Hooks & Zero-Touch Audio Handoff

VoiceFi hooks directly into AI coding agents (**Antigravity, Claude Code**) to establish a continuous hands-free dialogue.

#### How It Works
1. **Agent Finishes Working**: When the agent stops (e.g. tests pass, plan drafted, clarification needed), it executes the stop hook.
2. **Punchy Spoken Summary**: VoiceFi cleanses raw Markdown/tables/stack traces and speaks a concise 1–2 sentence soundbite over your speakers or AirPods.
3. **Auto-Opens Mic with VAD**: The microphone immediately opens with Voice Activity Detection.
4. **Hands-Free Injection**: You speak your next command, Whisper transcribes it in real time, and VoiceFi injects the prompt straight back into the active agent.

#### One-Command Setup
```bash
# Auto-configure Antigravity and Claude Code hooks:
vifi setup

# Link hooks directly to your local dev repository virtualenv:
vifi setup --dev
```

#### Auditioning the Lifecycle Hook
To simulate a turn completion event manually in your terminal:
```bash
echo '{"agent": "antigravity", "last_message": "All 18 unit tests passed in 0.42s. Ready to deploy staging migration?"}' | vifi hook
```

---

### 1.3 Live Dev Mode (`vifi dev`) & Server Management

For developers hacking on VoiceFi or wanting full real-time visibility into audio streams, VAD triggers, and hook events:

#### Foreground Dev Mode
```bash
vifi dev
```
- **Auto-Takeover**: Automatically detects and gracefully stops any background server or LaunchAgent to prevent Port 5141 conflicts.
- **Live Stream**: Streams real-time VAD energy levels, acoustic safe-mode calculations, TTS generation timings, and JSON IPC events.
- **Clean Exit**: Press `Ctrl+C` to cleanly exit and restore background services.

#### Server Management & Housekeeping
```bash
# Check server running status, PID, port listeners, and agent hooks:
vifi status
# or:
vifi server status

# Enable persistent background LaunchAgent (runs tray & HUD on login):
vifi autostart
# or:
vifi start

# Unload and disable LaunchAgent:
vifi stop-autostart

# Stop all background servers immediately and free Port 5141:
vifi stop
# or:
vifi server stop (or 'vifi kill')

# Restart background server and reload config:
vifi restart
# or:
vifi server restart

# Purge stale caches, locks, and temporary session files:
vifi clean

# Complete reset (stops servers, frees port, and cleans all caches):
vifi clean --all
```

---

### 1.4 Voice Memo Buffer: Stream-of-Consciousness to Code (`vifi memo`)

When pacing, brainstorming, or thinking through complex architecture, speaking for 2–5 minutes is $10\times$ faster than typing. VoiceFi captures raw developer rambling and synthesizes it directly into structured engineering artifacts.

```bash
# 1. Start a 3-minute countdown recording session:
vifi memo record -d 3m

# 2. Controls during recording:
#    • [Enter] -> Finalize early and synthesize immediately
#    • [Space] -> Pause / Resume recording
#    • At 00:00 -> Soft chime plays; press '1' for +1 min, '2' for +2 min, or 'Enter' to finish
```

#### What It Generates Automatically:
1. **Executive Summary & Key Requirements**
2. **Course Corrections & Architecture Decisions**
3. **Syntax-Valid Mermaid Architecture Diagram**
4. **Implementation Plan & File Diff Proposals**
5. **GitHub-Flavored PR Checklist & Acceptance Criteria**

#### Synthesizing Existing Recordings or Text:
```bash
# Synthesize raw spoken text or transcripts:
vifi memo synth --text "We need a background worker with Redis queues for video processing..."

# Synthesize from an audio file (.wav, .mp3, .m4a):
vifi memo import path/to/recording.m4a

# Export directly to an Antigravity implementation plan:
vifi memo export <memo_id> -o "$HOME/.gemini/antigravity/brain/<conv_id>/implementation_plan.md"

# Copy synthesized plan directly to macOS clipboard:
vifi memo export <memo_id> --clipboard

# View Mermaid diagram only:
vifi memo show <memo_id> --diagram
```

---

### 1.5 Ambient Listener & Proactive Co-Pilot (`vifi ambient`)

Run VoiceFi in the background during Zoom, Google Meet, Slack Huddles, or FaceTime design reviews:

```bash
# Start ambient background listening:
vifi ambient start

# Enable proactive background subagent dispatching:
vifi ambient start --proactive --source loopback

# Inspect rolling transcript & staged background tasks:
vifi ambient status

# Finalize meeting, summarize decisions, and sync action items to Linear:
vifi ambient finalize --sync-linear
```

> [!NOTE]
> Proactive tasks are executed in isolated sandboxes (`Workspace="branch"` or git worktrees) and will never interfere with your working branch without explicit approval.

---

### 1.6 Acoustic Personas & Silent Speed Testing (`vifi voice` & `vifi ping`)

Discover, audition, benchmark, and assign distinct neural acoustic voices across your primary agent and subagents.

```bash
# List all curated neural personas:
vifi voice list

# Audition a voice live over your speakers:
vifi voice test "Viv" -t "Hey! I'm Viv. Ready to build something great today?"
vifi voice test "Christopher" -t "Christopher here. Let's review the system architecture."
vifi voice test "Aria" -t "Aria online. Test suite passed with zero regressions."

# Silent Speed & Latency Benchmark (No sound emitted):
vifi ping "Viv"
vifi ping "Viv" -n 3        # Measure TTFB, jitter, and throughput (chars/sec)
vifi ping --all             # Benchmark all local and neural voices
vifi ping "Viv" --json      # Machine-readable output for scripts

# Assign personas by role:
vifi voice set antigravity Viv           # Main Planner
vifi voice set researcher Sonia         # Deep Research Subagent (British accent)
vifi voice set debugger Aria            # Fast Test & Debugger Subagent
vifi voice set devops Guy               # Build & Deploy Subagent
```

#### Instant 0ms Offline Neural Voice (Apple Silicon)
For zero network latency and 100% offline privacy using Apple's neural voice:
```bash
vifi voice download-ava
# or:
vifi voice set antigravity "Ava (Premium)"
```

---

### 1.7 Acoustic Diagnostics & Room Calibration (`vifi troubleshoot`)

Ensure crystal-clear audio capture, avoid false interruptions, and tune Voice Activity Detection:

```bash
# Run the automated hardware diagnostic suite:
vifi troubleshoot

# Inspect machine-readable hardware profile:
vifi troubleshoot --json

# Calibrate microphone energy threshold to your ambient room noise (1.5s sample):
vifi troubleshoot --fix calibrate

# Test simultaneous Speak + Listen (acoustic loopback & RMS energy):
vifi feedback-loop

# Acoustic Verification (verifies speaker-to-microphone STT accuracy %):
vifi hearing-test

# Live Active Voice Barge-In Test:
vifi barge-in
```

---

### 1.8 Unix Pipelines, Shell Scripts & Custom Functions

VoiceFi integrates into standard Unix shell pipelines, allowing you to give voice to any command-line tool.

#### Piping Output to VoiceFi
```bash
# Announce git branch status:
git status -s | vifi speak

# Announce build / test outcome:
pytest tests/ -q && vifi speak "All test suites passed!" || vifi speak "Tests failed. Check terminal output."

# Long-running background job alert:
docker compose build && vifi speak "Docker build finished."
```

#### Useful Shell Aliases (Add to `~/.zshrc` or `~/.bashrc`):
```bash
# VoiceFi Quick Shortcuts
alias vg-say='vifi speak'
alias vg-listen='vifi listen'
alias vg-memo='vifi memo record -d 3m'
alias vg-standup='vifi memo record -d 2m && vifi memo synth --clipboard'
alias vg-fix='vifi troubleshoot --fix calibrate'

# Voice-notified long commands
vwait() {
    "$@"
    local status=$?
    if [ $status -eq 0 ]; then
        vifi speak "Command succeeded."
    else
        vifi speak "Command failed with exit code $status."
    fi
    return $status
}

# Example usage:
# vwait make deploy
# vwait cargo build --release
```

---

### 1.9 Companion Control Panel & Dynamic Island HUD Studio

```bash
# Launch the interactive Web Control Panel:
vifi panel
# Opens http://localhost:5141 with live transcripts, audio routing, and voice picker.

# Launch the interactive native Dynamic Island HUD Debug Studio:
vifi hud debug
# Press 1-6 to preview morphing HUD states (Idle, Thinking, Working, Speaking, Listening, Review).
```

---

## 🔌 Part 2: Model Context Protocol (MCP) Workflows

The **Model Context Protocol (MCP)** allows any AI coding assistant to communicate with external tools and resources over standardized JSON-RPC protocols.

VoiceFi operates in two distinct MCP capacities:
1. **VoiceFi as an MCP Server (`voicefi-mcp`)**: Exposes speech synthesis, vocal confirmation prompts, ambient memory, and voice configuration to AI agents.
2. **VoiceFi as an MCP Voice Dispatcher**: Translates natural spoken commands into executions against external MCP servers (Slack, Linear, GitHub, Postgres).

---

### 2.1 Connecting VoiceFi MCP Server to IDEs & Agents

Configure VoiceFi in your favorite AI environment by adding the `voicefi-mcp` stdio transport:

#### 1. Google Antigravity
Add to your project or global MCP configuration (`~/.gemini/antigravity/mcp/voicefi.json` or Antigravity Settings):
```json
{
  "mcpServers": {
    "voicefi": {
      "command": "vifi",
      "args": ["mcp"],
      "env": {
        "VOICEFI_TTS_PROVIDER": "edge_tts",
        "VOICEFI_VOICE": "en-US-AvaNeural"
      }
    }
  }
}
```

#### 2. Claude Desktop
Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "voicefi": {
      "command": "vifi",
      "args": ["mcp"]
    }
  }
}
```

#### 3. Claude Code CLI
Register directly via the Claude Code CLI:
```bash
claude mcp add voicefi -- vifi mcp
```
Or define in your project's `.claude/mcp.json`:
```json
{
  "mcpServers": {
    "voicefi": {
      "command": "vifi",
      "args": ["mcp"]
    }
  }
}
```

#### 4. Cursor Composer
Add to `~/.cursor/mcp.json` or `.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "voicefi": {
      "command": "vifi",
      "args": ["mcp"]
    }
  }
}
```

#### 5. Windsurf Cascade
Add to `~/.codeium/windsurf/mcp_config.json`:
```json
{
  "mcpServers": {
    "voicefi": {
      "command": "vifi",
      "args": ["mcp"]
    }
  }
}
```

---

### 2.2 VoiceFi MCP Tool Specification

When connected, VoiceFi exposes the following tools to the AI agent:

#### Tool 1: `voicefi_speak`
Synthesizes and speaks text aloud using the configured voice persona without blocking the agent.

* **Parameters**:
  - `text` (*string*, **required**): The pre-summarized message to speak aloud.
  - `persona` (*string*, optional): Voice persona (`"ava"`, `"viv"`, `"christopher"`, `"aria"`, `"sonia"`, `"guy"`, `"samantha"`). Default: `"ava"`.
  - `priority` (*string*, optional): `"low"`, `"normal"`, or `"urgent"`. Default: `"normal"`.
  - `interrupt_current` (*boolean*, optional): Whether to immediately stop ongoing speech. Default: `false`.

* **Agent Usage Example**:
  ```json
  {
    "name": "voicefi_speak",
    "arguments": {
      "text": "Migration complete. All 42 tables created successfully.",
      "persona": "aria",
      "priority": "normal"
    }
  }
  ```

---

#### Tool 2: `voicefi_ask_confirmation`
**The Vocal Cognitive Safety Gate**: Pauses execution, speaks a question to the developer, activates the microphone with VAD, and returns the verbal response.

* **Parameters**:
  - `question` (*string*, **required**): The spoken question or confirmation prompt.
  - `timeout_seconds` (*integer*, optional): Maximum listening duration in seconds (default: `15`).
  - `expected_responses` (*array of strings*, optional): List of valid affirmative/negative intents (e.g. `["yes", "proceed", "cancel", "skip"]`).

* **Agent Usage Example (Before Destructive Action)**:
  ```json
  {
    "name": "voicefi_ask_confirmation",
    "arguments": {
      "question": "I am about to drop table user_sessions on staging. Should I proceed?",
      "timeout_seconds": 20,
      "expected_responses": ["yes", "proceed", "cancel", "no"]
    }
  }
  ```
* **Tool Return Value**:
  ```json
  {
    "confirmed": true,
    "transcript": "Yes, go ahead and drop it.",
    "matched_intent": "proceed",
    "timed_out": false
  }
  ```

---

#### Tool 3: `voicefi_get_ambient_context`
Retrieves the rolling transcription buffer from recent ambient meetings, standups, or developer pacing thoughts.

* **Parameters**:
  - `since_minutes` (*integer*, optional): Lookback window in minutes (default: `10`, max: `60`).

* **Agent Usage Example**:
  ```json
  {
    "name": "voicefi_get_ambient_context",
    "arguments": {
      "since_minutes": 15
    }
  }
  ```
* **Tool Return Value**:
  ```json
  {
    "timestamp_start": "2026-08-26T08:00:00Z",
    "timestamp_end": "2026-08-26T08:15:00Z",
    "word_count": 420,
    "transcript": "We decided during the call to use SSE instead of WebSockets for the notification service...",
    "detected_topics": ["architecture", "notifications", "sse"]
  }
  ```

---

#### Tool 4: `voicefi_set_agent_persona`
Configures or switches the acoustic persona for a specific agent or subagent role during multi-agent orchestration.

* **Parameters**:
  - `agent_id` (*string*, **required**): Agent identifier (e.g. `"planner"`, `"researcher"`, `"qa"`, `"devops"`).
  - `persona` (*string*, **required**): Desired persona name or neural voice code (e.g. `"Viv"`, `"Sonia"`, `"Aria"`, `"Christopher"`).

* **Agent Usage Example**:
  ```json
  {
    "name": "voicefi_set_agent_persona",
    "arguments": {
      "agent_id": "qa_subagent",
      "persona": "Aria"
    }
  }
  ```

---

### 2.3 End-to-End Multi-MCP Workflows

Combining VoiceFi with external MCP servers transforms spoken voice into structured ecosystem actions:

```
┌─────────────────┐       Spoken Voice       ┌────────────────────────┐
│  Developer Mic  │ ───────────────────────► │   VoiceFi Audio VAD    │
└─────────────────┘                          └───────────┬────────────┘
                                                         │
                                                         ▼
                                             ┌────────────────────────┐
                                             │  Streaming Whisper STT │
                                             └───────────┬────────────┘
                                                         │
                                                         ▼
                                             ┌────────────────────────┐
                                             │ Intent & Entity Parser │
                                             └───────────┬────────────┘
                                                         │
                     ┌───────────────────────────────────┼───────────────────────────────────┐
                     ▼                                   ▼                                   ▼
          ┌─────────────────────┐             ┌─────────────────────┐             ┌─────────────────────┐
          │      Slack MCP      │             │     Linear MCP      │             │    Postgres MCP     │
          │  slack_post_message │             │    create_issue     │             │  execute_sql_query  │
          └─────────────────────┘             └─────────────────────┘             └─────────────────────┘
```

#### Scenario A: Spoken Standup ➔ Slack MCP
1. **Developer Speaks into Mic**:
   > *"VoiceFi, post standup to engineering: yesterday merged PR 104 and resolved audio buffer latency, today wiring the MCP tool definitions, no blockers."*
2. **VoiceFi Cleans & Structures the Text**:
   Strips conversational pauses (*"um"*, *"like"*), structures Markdown bullet points.
3. **Executes Slack MCP**:
   Calls `slack_post_message(channel="#engineering", text="*Daily Standup — @Developer*\n• *Yesterday:* Merged PR #104 (audio latency fix)\n• *Today:* MCP tool definitions\n• *Blockers:* None")`.
4. **Audio Feedback**:
   Soft confirmation chime + spoken: *"Posted standup to engineering."*

#### Scenario B: Ambient Meeting Bug Capture ➔ Linear MCP
1. **During a Design Call**, a participant mentions:
   > *"The user avatar in the Dynamic Island HUD overflows by 4 pixels on Safari."*
2. **Proactive Ambient Listener** detects the bug pattern.
3. **Executes Linear MCP**:
   Calls `create_issue(team="ENG", title="Fix Dynamic Island HUD avatar 4px overflow on Safari", priority=2)`.
4. **HUD Card Notification**:
   A subtle badge appears on the Dynamic Island HUD: `✓ Staged Linear Issue #ENG-842`.

#### Scenario C: Vocal Safety Gate on Database Migrations
1. **Agent Prepares to Execute**:
   `DROP TABLE staging_sessions;`
2. **Agent Calls `voicefi_ask_confirmation`**:
   VoiceFi speaks over AirPods: *"I am ready to drop the staging sessions table. Proceed?"*
3. **Developer Replies Aloud**:
   *"Yes, proceed."*
4. **Execution Continues**:
   Agent safely runs the SQL command knowing explicit spoken authorization was given.

---

## ⚡ Part 3: Developer Cheatsheet & Troubleshooting

### 3.1 Quick Command Reference

| Goal | Command | Description |
| :--- | :--- | :--- |
| **Agent Setup** | `vifi setup` | Auto-configures hooks for Antigravity and Claude Code |
| **Dev Setup** | `vifi setup --dev` | Links hooks directly to local repository virtualenv |
| **Dev Mode** | `vifi dev` | Live foreground logs, auto-server takeover, event stream |
| **Speak Text** | `vifi speak "Hello world"` | Speaks string using active persona |
| **Record Memo** | `vifi memo record -d 3m` | 3-minute voice stream-of-consciousness capture |
| **Synthesize Memo** | `vifi memo synth --text "..."` | Converts spoken thoughts into plan + Mermaid diagram |
| **Ambient Mode** | `vifi ambient start --proactive` | Background listening with proactive subagent staging |
| **Audition Voices** | `vifi voice audition` | Live multi-voice audio showcase |
| **Silent Benchmark**| `vifi ping --all` | Silent TTFB latency and throughput test across voices |
| **Calibrate Mic** | `vifi troubleshoot --fix calibrate` | Dynamically adapts energy threshold to room noise |
| **Test Barge-In** | `vifi barge-in` | Validates full-duplex mid-speech voice interruption |
| **Server Status** | `vifi status` / `vifi server status` | Inspects background server, Port 5141, and agent hooks |
| **Stop Server** | `vifi stop` / `vifi server stop` | Frees Port 5141 and cleanly stops background server |

---

### 3.2 Troubleshooting Matrix

| Issue | Root Cause | Solution |
| :--- | :--- | :--- |
| **Port 5141 in use** | A previous server or orphaned process is bound to the port. | Run `vifi stop` or `vifi clean --all`. |
| **Microphone not triggering** | Noise floor is too high or threshold is too aggressive. | Run `vifi troubleshoot --fix calibrate` in a quiet room. |
| **Agent speech cuts off prematurely** | Barge-in is triggering on speaker bleed. | Set barge-in to `auto`: `vifi troubleshoot --fix auto_barge_in`. |
| **Network latency on TTS** | Cloud EdgeTTS experiencing network jitter. | Switch to 0ms offline neural voice: `vifi voice download-ava`. |
| **MCP server not found in agent** | Stdio command path is not in agent `$PATH`. | Use absolute path to executable (e.g. `/usr/local/bin/vifi` or `~/.voicefi/venv/bin/vifi`). |

---

## 📚 Related Documentation

- [MCP Architecture Specification](file:///Users/jaketrigg/Projects/VoiceFi/docs/MCP_ARCHITECTURE.md)
- [Unified Dynamic Island HUD Design Guide](file:///Users/jaketrigg/Projects/VoiceFi/docs/HUD_DESIGN_GUIDE.md)
- [Active Listening & Cognitive Safety Skill](file:///Users/jaketrigg/Projects/VoiceFi/.agents/skills/active-listening/SKILL.md)
- [Voice Memo Buffer Skill](file:///Users/jaketrigg/Projects/VoiceFi/.agents/skills/voice-memo-buffer/SKILL.md)
- [Ambient Listener Skill](file:///Users/jaketrigg/Projects/VoiceFi/.agents/skills/ambient-listener/SKILL.md)
- [Voice Persona Skill](file:///Users/jaketrigg/Projects/VoiceFi/.agents/skills/voice-persona/SKILL.md)
