# Security & Privacy Policy

VoiceFi takes the security, reliability, and privacy of its users, developers, and AI agent ecosystems seriously.

Because VoiceFi operates with microphone audio capture, text-to-speech synthesis, dynamic UI overlays, and inter-process communication (IPC) with AI coding agents (Antigravity, Claude Code), we adhere to a strict **Local-First, Zero-PII Privacy Architecture**.

---

## Supported Versions

Security updates, vulnerability patches, and bug fixes are actively provided for the following versions:

| Version | Supported | Maintenance Status |
| :--- | :--- | :--- |
| `0.1.x` | :white_check_mark: Yes | Current Active Release / Security Updates |
| `< 0.1.0` | :x: No | Unsupported / Deprecated |

We recommend always running the latest patch release (`vifi update` or `pip install --upgrade voicefi`).

---

## Reporting a Vulnerability

If you discover a security vulnerability or potential privacy flaw in VoiceFi, please report it responsibly. **Do not open a public issue.**

### Preferred Method: GitHub Private Security Advisories

Submit a private advisory directly through GitHub:
👉 **[Open a Private Security Advisory](https://github.com/atxatlarge-code/voicefi/security/advisories/new)**

### Alternative Method: Direct Security Email

You may also email our security team:
📧 **[talktome@voicefi.org](mailto:talktome@voicefi.org)**

### What to Include

To help us quickly triage and address your report, please include:
1. **Description**: A clear overview of the issue and its potential impact.
2. **Impacted Components**: Specific CLI subcommands, MCP tools (`voicefi_*`), REST endpoints (`/api/*`), agent hooks, or audio recorder modules affected.
3. **Environment**: Operating system version (e.g. macOS 15.2 Sequoia), Python version, and VoiceFi version (`vifi --version`).
4. **Proof of Concept / Reproduction Steps**: Minimal reproduction steps, script, or payload demonstrating the issue.
5. **Suggested Fix / Remediation** (if known).

---

## Response SLA & Disclosure Timeline

We are committed to swift and transparent vulnerability management:

- **Acknowledgement SLA**: We will acknowledge receipt of your report within **48 hours**.
- **Initial Triage**: We will complete an initial assessment and verify severity within **7 calendar days**.
- **Remediation & Patching**: Critical and high-severity issues will be patched and verified within **30 days** of confirmation.
- **Coordinated Disclosure**: We collaborate with reporters on mutually agreed disclosure dates following the release of the remediation patch.

---

## Security & Privacy Architecture

VoiceFi is engineered from the ground up to protect user privacy and system security:

### 1. Local-First Audio & Neural Processing
- **Zero Cloud Audio Exposure**: By default, Speech-to-Text (Faster-Whisper / Apple SpeechKit) and neural Text-to-Speech (Apple Silicon Ava Premium / Samantha / Kokoro ONNX) execute **100% locally on your machine**.
- Cloud TTS providers (such as Edge-TTS or ElevenLabs) are only invoked if explicitly configured by the user in `~/.voicefi/config.yaml`.

### 2. Zero-PII Telemetry Guarantee
- VoiceFi **never** records, retains, or transmits your audio recordings, microphone streams, transcribed text, or workspace code snippets.
- Diagnostic and telemetry tools (`vifi troubleshoot --json`, `vifi feedback submit`) automatically sanitize all local file paths, usernames, home directories, and sensitive environment variables before logging.

### 3. Localhost-Bound IPC & Access Controls
- The companion REST API server strictly binds to `127.0.0.1:5141` (localhost only) and rejects remote network connections.
- Native agent IPC hooks (Google Antigravity AgentAPI and Claude Code CLI hooks) communicate over authenticated local stdio pipes and local sockets.

### 4. Lockfile & File System Safety
- All session locks, IPC sockets, and audio scratch buffers are created inside user-owned directories (`~/.voicefi/` and `/tmp/voicefi_*`) with restricted POSIX file permissions (`0700`/`0600`), preventing cross-user eavesdropping on shared systems.
