# 🌱 VoiceFi™ Open Source Growth Playbook & Community Initiatives
> **Accelerating Autonomous AI Voice Innovation Through Open Source Collaboration**  
> *Bounties, Community Rituals, Contributor Badges, and Acoustic Leaderboards*

---

## 🏆 1. The VoiceFi Plugin Bounty Program

To incentivize world-class developer tools, low-latency audio backends, and IDE extensions, the VoiceFi team sponsors a cash and recognition bounty program for community contributions.

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 VOICEFI BOUNTY TIERS & REWARDS                                   │
├──────────────────────────┬───────────────────────────────────┬───────────────────────────────────┤
│         TIER 1           │              TIER 2               │              TIER 3               │
│     $200 – $250 USD      │          $100 – $150 USD          │           $50 – $75 USD           │
│   "Acoustic Architect"   │         "Agent Whisperer"         │          "Voice Artisan"          │
├──────────────────────────┼───────────────────────────────────┼───────────────────────────────────┤
│ • Major IDE Extensions   │ • Editor Integrations (Neovim)    │ • Curated Persona YAML Packs      │
│ • Real-time STT/TTS WS   │ • Alternative TTS/STT Engines     │ • Procedural SFX Packs            │
│ • Standalone Edge Daemons│ • Automation & Raycast Extensions │ • Documentation & Tutorial Guides │
└──────────────────────────┴───────────────────────────────────┴───────────────────────────────────┘
```

### 1.1 Active Bounty Wishlist & Opportunities

| Priority | Project / Feature | Target Scope & Key Requirements | Reward | Status |
|---|---|---|---|---|
| 🔥 **High** | **Neovim Lua Plugin (`voicefi.nvim`)** | Native Neovim plugin with statusline audio waveform visualizer, voice command palette, and buffer dictation injection via VoiceFi REST API (`localhost:5141`). | **$200 USD** | Open |
| 🔥 **High** | **VS Code & Cursor Native Extension** | Sidebar audio control panel, real-time waveform canvas, acoustic chime notifications on task completion, and 1-click MCP configuration. | **$250 USD** | Open |
| ⚡ **Medium** | **ElevenLabs WebSocket Streaming TTS** | Ultra-low latency streaming chunked audio synthesizer for ElevenLabs WebSockets protocol in `src/voicefi/tts/elevenlabs_ws.py`. | **$150 USD** | Open |
| ⚡ **Medium** | **Deepgram Nova-2 Streaming STT** | Live streaming STT provider with interim token emission over WebSockets (`/ws/transcribe`) with <120ms latency. | **$150 USD** | Open |
| 💡 **Starter** | **Raycast VoiceFi Extension** | Raycast command palette extension to trigger instant voice notes, toggle mute/unmute, switch agent personas, and run silent speed benchmarks. | **$100 USD** | Open |
| 💡 **Starter** | **Obsidian Community Plugin Submission** | Polish and submit VoiceFi Obsidian companion to the official Obsidian Community Plugin registry with vault auto-syncing. | **$100 USD** | Open |

### 1.2 How to Claim and Complete a Bounty

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ 1. Claim Issue  │ ──► │ 2. RFC & Dev    │ ──► │ 3. PR & CI Test │ ──► │ 4. Review & Pay │
│ Comment on issue│     │ Build feature   │     │ Submit PR with  │     │ 48h SLA review, │
│ to get assigned │     │ with test suite │     │ passing tests   │     │ payout issued   │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
```

1. **Find & Claim**:
   - Browse open bounty issues labeled `bounty` on [GitHub Issues](https://github.com/atxatlarge-code/voicefi/issues?q=is%3Aissue+is%3Aopen+label%3Abounty).
   - Post a comment: *"I'd like to claim this bounty! Here is my brief technical plan: ..."*
   - A maintainer will assign the issue to you for a 14-day reservation period.
2. **Develop & Test**:
   - Follow development guidelines in [CONTRIBUTING.md](../CONTRIBUTING.md).
   - Ensure your code has unit and integration test coverage (`pytest`).
3. **Submit PR**:
   - Open a Pull Request referencing the issue (e.g. `Resolves #42 - Adds Neovim plugin`).
   - Fill out the PR template with verification instructions and screenshots/recordings.
4. **Review & Payout**:
   - Maintainers provide technical review within **48 hours**.
   - Upon merge, payouts are dispatched via **GitHub Sponsors**, **Open Collective**, or **Wise/PayPal**.

---

## 🎙️ 2. Weekly "Voice Hacker Office Hours"

Community connection and real-time collaboration happen live every week on the official VoiceFi Discord server.

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                             VOICE HACKER OFFICE HOURS (WEEKLY)                                   │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 📅 Every Thursday @ 1:00 PM EST / 10:00 AM PST / 6:00 PM UTC                                     │
│ 📍 Discord Stage: `🎙️ VoiceFi Stage & Audio Lab`                                                  │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Office Hours Agenda
- **00:00 – 00:15 | Ecosystem Changelog & Release Highlights**: Maintainers review new releases, feature demos, and upcoming roadmap milestones.
- **00:15 – 00:40 | Live Acoustic Hacking & PR Reviews**: Live code pairing, architecture discussions for new TTS/STT engines, and PR walkthroughs.
- **00:40 – 00:55 | Community Lightning Demos**: 5-minute showcase slots for contributors displaying new plugins, custom sound packs, and multi-agent setups.
- **00:55 – 01:00 | Bounty Drop & Open Q&A**: Announcing new bounty issues and open floor discussions.

---

## 🎖️ 3. Contributor Showcase & Badges

We celebrate every contributor who shapes VoiceFi. Contributors receive official GitHub badges, Discord roles, and perpetual recognition in our repository root.

```
┌───────────────────────┐  ┌───────────────────────┐  ┌───────────────────────┐
│     VOICE ARTISAN     │  │  ACOUSTIC ARCHITECT   │  │    AGENT WHISPERER    │
│                       │  │                       │  │                       │
│  🎨 Curated 3+ Voice  │  │  ⚙️ Built Core TTS /  │  │  🤖 Built Multi-Agent │
│     Personas / Packs  │  │     STT Audio Engine  │  │     Bridge / IDE Tool │
└───────────────────────┘  └───────────────────────┘  └───────────────────────┘
```

### 3.1 Contributor Badges Catalog

| Badge | Title | Requirement / Achievement | Community Perks |
|---|---|---|---|
| 🎨 | **Voice Artisan** | Created or contributed 3+ high-quality voice personas or custom procedural SFX sound packs. | Profile badge in README, `@Voice Artisan` Discord role, custom persona showcase on `voicefi.org`. |
| ⚙️ | **Acoustic Architect** | Implemented or significantly optimized a TTS engine (e.g. Kokoro, F5-TTS), STT stream, or DSP module. | Featured on Release Notes, `@Acoustic Architect` role, invited to maintainer triage calls. |
| 🤖 | **Agent Whisperer** | Built an editor extension (Cursor, Zed, Neovim), MCP tool, or multi-agent IPC orchestration hook. | Ecosystem directory feature, `@Agent Whisperer` role, priority bounty assignments. |
| 🛡️ | **Acoustic Sentinel** | Identified and fixed critical audio concurrency bugs, VAD feedback issues, or test suite regressions. | Security Hall of Fame, permanent recognition in [`SECURITY.md`](../SECURITY.md). |

---

## ⚡ 4. Local Neural TTS Benchmarking & Latency Leaderboard

To ensure sub-millisecond audio performance, VoiceFi maintains an automated, transparent benchmarking suite.

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                            GLOBAL TTS LATENCY LEADERBOARD (SAMPLE)                               │
├──────────────────────────┬──────────────┬─────────────┬─────────────┬─────────────┬──────────────┤
│ Engine / Persona         │ Provider     │ TTFB (ms)   │ Throughput  │ RTF (x)     │ Privacy Tier │
├──────────────────────────┼──────────────┼─────────────┼─────────────┼─────────────┼──────────────┤
│ 🏆 Apple Ava (Premium)   │ Local macOS  │ 0.8 ms      │ 420 char/s  │ 0.005x      │ 100% Offline │
│ 🥈 Kokoro 82M (ONNX)     │ Local ONNX   │ 112.4 ms    │ 180 char/s  │ 0.045x      │ 100% Offline │
│ 🥉 ElevenLabs Turbo v2.5 │ Cloud WS     │ 145.0 ms    │ 120 char/s  │ 0.080x      │ Cloud API    │
│ 🏅 EdgeTTS (Christopher) │ Cloud HTTPS  │ 220.0 ms    │ 95 char/s   │ 0.110x      │ Cloud Free   │
└──────────────────────────┴──────────────┴─────────────┴─────────────┴─────────────┴──────────────┘
```

### 4.1 Running the Benchmark Suite
Contributors can benchmark their local machine or new TTS provider using VoiceFi's built-in benchmarking tool:

```bash
# Run silent TTFB latency tests across all installed engines
vifi ping --all

# Generate machine-readable JSON benchmark profile
vifi ping --all --json > benchmark_results.json

# Submit benchmark results to the global leaderboard
vifi feedback submit "Benchmark Profile - M3 Max 64GB"
```

### 4.2 Standard Benchmark Metrics
- **TTFB (Time-to-First-Byte)**: Duration from text submission to first playable PCM audio frame.
- **Throughput**: Characters synthesized per second (chars/sec).
- **RTF (Real-Time Factor)**: Audio processing duration divided by audio playback length (<1.0x is faster than real time).
- **Memory Footprint**: Peak RAM consumption during neural inference.

---

## 💬 5. Discord & GitHub Discussions Structure

Our community spaces are organized to foster constructive technical discussions, rapid troubleshooting, and creative acoustic experimentation.

```
📁 VoiceFi Community Discord
├── 📢 #announcements          — Official releases, security updates, and events
├── 💬 #general-chat           — AI coding agents, audio hardware, and pair programming
├── 🛠️ #voice-hackers          — Architecture, engine development, PR coordination
├── 💰 #bounties               — Active bounty announcements, claims, and inquiries
├── 🎙️ #showcase               — Share your custom personas, setups, and agent duels
├── ❓ #help-and-support       — Installation troubleshooting, VAD tuning, hardware assistance
└── 🎧 #acoustic-lab (Voice)   — Live pairing, office hours, and banter testing
```

### 5.1 GitHub Discussions Categories
- **Announcements**: Major version launches and ecosystem roadmaps.
- **Q&A / Troubleshooting**: Technical questions answered by maintainers and community champions.
- **Ideas & Voice Requests**: Request new curated neural personas, sound effects, or IDE integrations.
- **Show and Tell**: Showcase autonomous agent workflows, terminal setups, and custom plugins.
- **Plugin Bounties**: Discussion threads for proposed RFCs and bounty solutions.

---

## 📜 6. Community Values & Code of Conduct

VoiceFi is committed to providing a welcoming, inclusive, and harassment-free environment for all contributors.
- All interactions in Discord, GitHub Discussions, and Pull Requests are governed by our [Code of Conduct](../CODE_OF_CONDUCT.md) (*Contributor Covenant v2.1*).
- For safety or conduct inquiries, please contact our community team at `community@voicefi.org`.
