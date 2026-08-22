---
name: ambient-listener
description: Enables real-time ambient listening for meetings, standups, and developer brainstorming, automatically producing structured notes and proactively dispatching background subagents.
---

# 🎙️ Ambient Listener & Proactive Co-Pilot Skill

Use this skill when Voicegency is running in ambient background mode during meetings (Zoom, Google Meet, Slack Huddles, FaceTime), standup sessions, or while pacing and brainstorming aloud.

---

## ⚡ Key Capabilities

1. **Granola-Style Meeting Intelligence**: Captures natural multi-speaker conversations and generates:
   - Executive Brief & Key Takeaways
   - Architectural Decisions & Constraints
   - Action Items mapped directly to Linear / GitHub ticket format
2. **Proactive Subagent Dispatch**: While a feature or bug is being discussed, automatically spawns a background subagent in an isolated workspace (`Workspace="branch"`) to pre-fetch docs, draft routes, or scaffold components.
3. **Audio Context Retention**: Links transcription timestamps with project diffs and decision logs.

---

## 🚀 Ambient Commands & Workflow

### 1. Starting Ambient Listening Mode
To start the ambient listener in the background:

```bash
vg ambient start
```
Options:
- `--source mic`: Listen to ambient microphone only.
- `--source loopback`: Listen to system audio (Zoom/Meet/Slack) + microphone.
- `--proactive`: Enable automatic subagent dispatching on detected technical intent.

### 2. Checking Ambient Status & Staged Tasks
```bash
vg ambient status
```
Displays:
- Active listening duration and noise floor.
- Rolling transcript summary.
- Staged proactive tasks waiting for review.

### 3. Finalizing a Meeting & Syncing Action Items
When a meeting or brainstorming session ends:

```bash
vg ambient finalize --sync-linear
```
- Summarizes the conversation.
- Files generated action items directly to Linear/GitHub.
- Prompts whether to merge any proactive branches created during the call.

---

## 🛡️ Proactive Safety Rules

- **Isolated Sandboxing**: All proactive code scaffolds MUST run in `Workspace="branch"` or isolated git worktrees.
- **Never Interfere with Live Audio**: The agent stays completely silent during active speech unless an explicit wake-word is used or a designated prompt is issued.
- **HUD Card Updates**: Subtle, non-intrusive status updates are sent to the macOS Menu Bar and Dictation HUD without stealing keyboard or window focus.
