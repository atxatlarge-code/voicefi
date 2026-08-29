## Description

Please include a concise summary of the changes, motivation, and context.
List any dependencies or architectural impacts required for this change.

---

## Type of Change

Please mark the relevant option(s) with an `x`:

- [ ] 🐛 **Bug fix** (non-breaking change fixing an issue)
- [ ] ✨ **New feature** (non-breaking change adding functionality)
- [ ] 💥 **Breaking change** (fix or feature that alters existing behavior/APIs)
- [ ] 📚 **Documentation update**
- [ ] 🎨 **Refactoring / Style** (no functional code changes)
- [ ] ⚡ **Performance improvement**
- [ ] 🧪 **Tests** (adding missing tests or updating existing tests)
- [ ] 🔧 **CI/CD / Tooling / Maintenance**

---

## Related Issues

Closes #
Fixes #

---

## Impacted Surfaces

- [ ] CLI (`vifi`)
- [ ] MCP Server (`voicefi_*` stdio tools)
- [ ] REST API (`http://localhost:5141`)
- [ ] Audio Engine (Recorder, VAD, Barge-in, SFX)
- [ ] TTS / Voice Personas (Ava, Edge-TTS, ElevenLabs, etc.)
- [ ] STT / Speech Dictation (Whisper, Apple Speech)
- [ ] Agent Integrations (Google Antigravity, Claude Code)
- [ ] Dynamic Island HUD / macOS AppKit Overlay
- [ ] Configuration (`~/.voicefi/config.yaml`)

---

## Testing & Verification Checklist

Please verify your changes before submitting:

- [ ] Running all tests (`pytest` or `uv run pytest`) passes with 0 failures
- [ ] Linting checks (`ruff check .`) pass with 0 errors
- [ ] Code formatting (`ruff format --check .`) passes
- [ ] Audio & hardware diagnostics (`vifi troubleshoot`) pass without unexpected device lockups
- [ ] If changing MCP tools, verified schema compliance and tool execution (`vifi mcp`)
- [ ] Added or updated automated tests covering the new behavior

---

## Contributor Checklist

- [ ] My code follows the code style and guidelines of this project
- [ ] I have performed a self-review of my own code
- [ ] I have commented my code where necessary, particularly in hard-to-understand areas
- [ ] I have made corresponding changes to documentation and command cheat sheets
- [ ] My changes generate no new warnings or unhandled exceptions
- [ ] I have verified that no sensitive credentials, API keys, or PII are committed
